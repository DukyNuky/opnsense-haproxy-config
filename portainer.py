#!/usr/bin/env python3
"""Portainer side of the program: stacks, containers and their published ports.

Same house rules as opnsense_haproxy: standard library only, every call goes
through one small client, and everything a window needs to show is prepared
here rather than in the widgets.

Two things make this module worth its own file. Portainer answers with the
raw Docker API underneath (``/endpoints/<id>/docker/...``), which needs its own
reading; and a stack deployed from git is redeployed through a different call
than one deployed from a file, which the caller should not have to know.
"""

import json
import posixpath
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

import opnsense_haproxy as core

DEFAULT_COMPOSE_FILE = "docker-compose.yml"
DEFAULT_INTERVAL = "5m"

# Creating a stack is the one call that has real work behind it: Portainer
# clones the repository, pulls the images and waits for `compose up` -- and a
# service that waits for another one to become healthy waits again. The usual
# half minute would cut that off in the middle, which is the worst moment to
# stop listening: the answer never arrives, and the stack is created anyway.
DEPLOY_TIMEOUT = 900

# Where an environment file tends to sit, most telling name first. Every miss
# costs Portainer a fresh clone of the repository, so the list is short and the
# search stops at the first hit.
ENV_CANDIDATES = (".env.example", ".env", "example.env", ".env.sample",
                  ".env.template", "stack.env")
MAX_ENV_PROBES = 7

# Portainer's own numbers for the stack kinds. Only compose stacks are handled
# here; a swarm stack publishes its ports through services instead of
# containers and would need a second reading of everything below.
SWARM_STACK, COMPOSE_STACK, KUBERNETES_STACK = 1, 2, 3

# The names Docker Hub answers to. An image may spell one of them out, and it
# still means the registry everybody reaches without a login.
DOCKER_HUB_HOSTS = ("docker.io", "index.docker.io", "registry-1.docker.io",
                    "registry.hub.docker.com")

# GitHub's own registry, and the mark of the token it will not take. GitHub
# hands out two kinds: a fine-grained one, which begins like this and is the
# better token for everything else, and a classic one. The container registry
# accepts only the classic kind, no matter what the fine-grained one is
# allowed to do -- and it says no in the same words it uses for a missing
# right, which is what makes the mistake so hard to see from the message.
GITHUB_REGISTRY_HOSTS = ("ghcr.io", "docker.pkg.github.com")
FINE_GRAINED_MARK = "github_pat_"


def github_refuses_token(host, token):
    """Whether that token cannot work at that registry, prefix aside."""
    return (str(host or "").lower() in GITHUB_REGISTRY_HOSTS
            and str(token or "").startswith(FINE_GRAINED_MARK))


# Portainer's own number for a registry that is nothing but a host with a
# login. The other kinds it knows (GitLab, ECR, Quay and their like) only add
# fields for their own conveniences; the plain one reaches every registry that
# speaks the usual protocol, and means the same on every Portainer version.
CUSTOM_REGISTRY = 3

STACK_KIND = {SWARM_STACK: "Swarm", COMPOSE_STACK: "Compose",
              KUBERNETES_STACK: "Kubernetes"}

# What Docker puts in front of a published port when it is reachable on every
# address of the host -- as opposed to 127.0.0.1, which stays on the machine.
ANY_ADDRESS = ("0.0.0.0", "::", "")


class PortainerError(core.ApiError):
    """An API error that remembers its HTTP status.

    Deploying has to tell "this Portainer is too old for that call" apart from
    "that did not work", and only the status says which it is.
    """

    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class DeployFailed(PortainerError):
    """A stack that did not come up, and what was taken away afterwards.

    ``cleanup`` is what :func:`rollback_deploy` reports, so the window can say
    what is gone as well as what went wrong -- the two halves of the same
    message.
    """

    def __init__(self, message, cleanup=None, status=0):
        super().__init__(message, status)
        self.cleanup = cleanup or {}


class Portainer:
    """The handful of Portainer calls this program makes.

    Either an access token (``X-API-Key``) or a user name with a password; the
    password is traded for a token on the first call and again whenever the one
    in hand is refused, so a session that outlives its token keeps working.
    """

    def __init__(self, url, api_key="", username="", password="", verify=True,
                 timeout=30):
        self.base = core.base_url(url, "Portainer address", keep_path=True)
        self.timeout = timeout
        self.api_key = (api_key or "").strip()
        self.username = username or ""
        self.password = password or ""
        self._jwt = ""
        if not self.api_key and not (self.username and self.password):
            raise core.UsageError(
                "Portainer needs either an access token or user and password")
        self._ctx = None
        if not verify:
            self._ctx = ssl.create_default_context()
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE

    # -- plumbing ----------------------------------------------------------

    def login(self):
        """Trade user and password for a token."""
        reply = self._send("auth", {"Username": self.username,
                                    "Password": self.password}, "POST",
                           authenticated=False)
        token = reply.get("jwt", "")
        if not token:
            raise PortainerError("Portainer returned no token for that login")
        self._jwt = token
        return token

    def call(self, path, payload=None, method=None, timeout=None):
        """Call an API endpoint; ``path`` starts after ``/api/``.

        ``timeout`` is for the few calls that are allowed to take their time --
        creating a stack waits for the whole ``compose up``.
        """
        if not self.api_key and not self._jwt:
            self.login()
        try:
            return self._send(path, payload, method, timeout=timeout)
        except PortainerError as exc:
            # A token that has run out is the one error worth a second try.
            if exc.status != 401 or self.api_key:
                raise
            self.login()
            return self._send(path, payload, method, timeout=timeout)

    def _send(self, path, payload=None, method=None, authenticated=True,
              timeout=None):
        url = f"{self.base}/api/{path}"
        headers = {"Accept": "application/json"}
        if authenticated:
            if self.api_key:
                headers["X-API-Key"] = self.api_key
            else:
                headers["Authorization"] = f"Bearer {self._jwt}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if method is None:
            method = "POST" if data is not None else "GET"
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout,
                                        context=self._ctx) as resp:
                body = resp.read().decode(errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            detail = _message_of(raw)
            if exc.code in (401, 403):
                raise PortainerError(
                    f"Portainer refused the login ({exc.code}) -- check the "
                    f"access token or the password: {detail}", exc.code) from None
            where = path.split("?", 1)[0]
            raise PortainerError(f"Portainer {exc.code} on {where}: {detail}",
                                 exc.code) from None
        except urllib.error.URLError as exc:
            raise PortainerError(
                f"cannot reach Portainer at {self.base}: {exc.reason}") from None
        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise PortainerError(
                f"non-JSON reply from {path}: {body[:200]}") from None

    def _fetch(self, path):
        """A GET whose answer is not JSON -- a container's log, notably.

        Docker hands that one out as a byte stream, so it goes past ``_send``
        and its json.loads. The login is the same, and so is the token that
        may have run out in the meantime.
        """
        if not self.api_key and not self._jwt:
            self.login()
        headers = {"Accept": "*/*"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self._jwt}"
        req = urllib.request.Request(f"{self.base}/api/{path}", headers=headers,
                                     method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout,
                                        context=self._ctx) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            where = path.split("?", 1)[0]
            raise PortainerError(
                f"Portainer {exc.code} on {where}: "
                f"{_message_of(exc.read().decode(errors='replace'))}",
                exc.code) from None
        except urllib.error.URLError as exc:
            raise PortainerError(
                f"cannot reach Portainer at {self.base}: {exc.reason}") from None

    # -- reading -----------------------------------------------------------

    def version(self):
        """The server's own version -- also the cheapest proof of a login."""
        return str(self._send("status").get("Version", ""))

    def endpoints(self):
        """The environments (Portainer's word for a Docker host)."""
        reply = self.call("endpoints")
        return reply if isinstance(reply, list) else []

    def stacks(self):
        reply = self.call("stacks")
        return reply if isinstance(reply, list) else []

    def stack_file(self, stack_id):
        """The compose file Portainer keeps for this stack."""
        reply = self.call(f"stacks/{stack_id}/file")
        return reply.get("StackFileContent", "")

    def containers(self, endpoint_id):
        """Every container on that environment, stopped ones included.

        This is the Docker API itself, handed through by Portainer, so the
        field names are Docker's: Names, Ports, State, Labels.
        """
        reply = self.call(f"endpoints/{endpoint_id}/docker/containers/json"
                          f"?all=1")
        return reply if isinstance(reply, list) else []

    def networks(self, endpoint_id):
        """The docker networks on that environment, with their labels.

        A compose file makes one per stack and nothing removes it by itself,
        so a deploy that has to be taken back has to look here too.
        """
        reply = self.call(f"endpoints/{endpoint_id}/docker/networks")
        return reply if isinstance(reply, list) else []

    def container_logs(self, endpoint_id, container_id, tail=40):
        """The last lines a container wrote, stdout and stderr together.

        Raw bytes: without a terminal Docker frames every chunk, which
        ``docker_log_text`` unpicks.
        """
        return self._fetch(
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/logs"
            f"?stdout=1&stderr=1&tail={int(tail)}")

    def registries(self):
        """The registries Portainer keeps a login for.

        This is where an image pull gets its credentials from -- the ones on a
        stack are for the git clone alone. Reading the list needs no special
        right; changing it does.
        """
        reply = self.call("registries")
        return reply if isinstance(reply, list) else []

    def repo_file(self, repository, target_file, reference="", username="",
                  password="", skip_tls_verify=False):
        """Read one file out of a git repository -- Portainer does the cloning.

        This is what its own "load from repository" preview uses, so GitHub and
        GitLab need no telling apart and a private repository works with the
        credentials that were typed into the form.
        """
        body = {
            "repository": repository,
            "reference": reference or "",
            "targetFile": target_file,
            "username": username or "",
            "password": password or "",
            "tlsSkipVerify": bool(skip_tls_verify),
        }
        try:
            reply = self.call("gitops/repo/file/preview", body, method="POST")
        except PortainerError as exc:
            if exc.status not in (404, 405):
                raise
            # before Portainer 2.15 the same job sat with the app templates,
            # and knew nothing about credentials
            reply = self.call("templates/file",
                              {"repositoryUrl": repository,
                               "composeFilePathInRepository": target_file},
                              method="POST")
        return reply.get("FileContent", "")

    # -- writing -----------------------------------------------------------

    def create_registry(self, url, username, password, name=""):
        """Store a login for one registry, so image pulls can use it."""
        return self.call("registries", {
            "Name": name or url,
            "Type": CUSTOM_REGISTRY,
            "URL": url,
            "BaseURL": "",
            "Authentication": True,
            "Username": username,
            "Password": password,
        }, method="POST")

    def update_registry(self, registry_id, url, username, password, name=""):
        """Put a new login into a registry that is already there."""
        return self.call(f"registries/{registry_id}", {
            "Name": name or url,
            "URL": url,
            "Authentication": True,
            "Username": username,
            "Password": password,
        }, method="PUT")

    def deploy_repository(self, endpoint_id, name, repository, reference="",
                          compose_file="", env=None, username="", password="",
                          auto_update=None, skip_tls_verify=False):
        """Create a compose stack from a git repository.

        The call moved to ``/stacks/create/standalone/repository`` in Portainer
        2.14; older servers only know the query-string form, so a 404 or 400
        from the new path is answered by trying the old one.
        """
        body = {
            "Name": name,
            "RepositoryURL": repository,
            "RepositoryReferenceName": reference or "",
            "ComposeFile": compose_file or DEFAULT_COMPOSE_FILE,
            "RepositoryAuthentication": bool(username or password),
            "RepositoryUsername": username or "",
            "RepositoryPassword": password or "",
            "Env": list(env or []),
            "TLSSkipVerify": bool(skip_tls_verify),
            "FromAppTemplate": False,
        }
        if auto_update:
            body["AutoUpdate"] = auto_update
        try:
            return self.call(
                f"stacks/create/standalone/repository?endpointId={endpoint_id}",
                body, method="POST", timeout=DEPLOY_TIMEOUT)
        except PortainerError as exc:
            if exc.status not in (400, 404, 405):
                raise
            return self.call(
                f"stacks?type={COMPOSE_STACK}&method=repository"
                f"&endpointId={endpoint_id}", body, method="POST",
                timeout=DEPLOY_TIMEOUT)

    def redeploy(self, stack, pull_image=True, prune=False, env=None,
                 username="", password=""):
        """Deploy this stack again, optionally pulling the images first.

        ``env`` defaults to what the stack already has: Portainer replaces the
        whole environment with what it is given, so leaving it out of the call
        would quietly empty it.
        """
        stack_id = stack.get("Id")
        endpoint_id = stack.get("EndpointId")
        variables = list(env if env is not None else (stack.get("Env") or []))
        if git_config(stack):
            body = {
                "RepositoryReferenceName": (git_config(stack) or {}).get(
                    "ReferenceName", ""),
                "RepositoryAuthentication": bool(username or password),
                "RepositoryUsername": username or "",
                "RepositoryPassword": password or "",
                "Env": variables,
                "Prune": bool(prune),
                # PullImage is the older name for the same wish; both go out so
                # the call means the same thing on either side of Portainer 2.36
                "PullImage": bool(pull_image),
                "RepullImageAndRedeploy": bool(pull_image),
                "StackName": stack.get("Name", ""),
            }
            return self.call(f"stacks/{stack_id}/git/redeploy"
                             f"?endpointId={endpoint_id}", body, method="PUT")
        # A stack that was deployed from a file has nothing to pull from, so
        # its own file goes back in unchanged.
        body = {
            "StackFileContent": self.stack_file(stack_id),
            "Env": variables,
            "Prune": bool(prune),
            "PullImage": bool(pull_image),
        }
        return self.call(f"stacks/{stack_id}?endpointId={endpoint_id}", body,
                         method="PUT")

    def remove_container(self, endpoint_id, container_id):
        """Take one container away, running or not.

        ``v=true`` is what ``docker compose down`` does with the volumes: the
        nameless ones this container was given go with it, a named one stays --
        that is somebody's data.
        """
        return self.call(f"endpoints/{endpoint_id}/docker/containers/"
                         f"{container_id}?force=true&v=true", method="DELETE")

    def remove_network(self, endpoint_id, network_id):
        """Take one docker network away -- the one a stack made for itself."""
        return self.call(
            f"endpoints/{endpoint_id}/docker/networks/{network_id}",
            method="DELETE")

    def delete_stack(self, stack_id, endpoint_id, external=False):
        """Take the stack down and remove it: containers, networks, the lot.

        Portainer wants the environment in the query string even though the
        stack knows its own -- without it the call is refused as belonging to
        no environment.
        """
        return self.call(f"stacks/{stack_id}?endpointId={endpoint_id}"
                         f"&external={'true' if external else 'false'}",
                         method="DELETE")


# What the Docker daemon says when a name or a host port is already taken. Its
# words arrive verbatim inside Portainer's 500, so they are matched rather than
# guessed at.
NAME_IN_USE = re.compile(
    r'container name\s+"?/?(?P<name>[^"\s]+)"?\s+is already in use', re.I)
PORT_TAKEN = re.compile(
    r"(?P<before>.*?)(?:port is already allocated|address already in use)",
    re.I | re.S)
# The daemon has two ways of naming the port it could not have, and they are
# not read the same: "Bind for 0.0.0.0:8088 failed" ends with the host port,
# "bind host port for 0.0.0.0:8088:172.18.0.2:8080" carries the container side
# behind it.
BIND_FOR = re.compile(r"bind for\s+\S*?:(?P<port>\d+)", re.I)
HOST_PORT_FOR = re.compile(r"host port for\s+\S*?:(?P<port>\d+):", re.I)


def conflict_in(message):
    """What a failed deploy collided with, read out of the error text.

    Returns ``{"kind": "name"|"port", "value": ...}`` or None. Both kinds mean
    the same thing: something in the compose file belongs to the whole Docker
    host, not to one stack, and a second stack out of the same repository asked
    for it again.
    """
    text = str(message or "")
    found = NAME_IN_USE.search(text)
    if found:
        return {"kind": "name", "value": found.group("name").lstrip("/")}
    taken = PORT_TAKEN.search(text)
    if not taken:
        return None
    before = taken.group("before")
    found = HOST_PORT_FOR.search(before) or BIND_FOR.search(before)
    if found:
        return {"kind": "port", "value": int(found.group("port"))}
    # some other wording for the same thing: the last port named before the
    # complaint is the best guess left
    numbers = re.findall(r":(\d+)", before)
    return {"kind": "port", "value": int(numbers[-1])} if numbers else None


# What the daemon says when the image, not the repository, was refused. The
# two are easy to mix up: both end in a deploy that failed over a login.
REGISTRY_DENIED = re.compile(
    r"from registry:\s*(unauthorized|denied)|pull access denied|"
    r"unauthorized:\s*authentication required|no basic auth credentials|"
    r"denied:\s*requested access to the resource is denied", re.I)


def registry_refused(message):
    """Whether a deploy failed at the image pull rather than at the clone.

    Worth telling apart: the credentials on the stack are the repository's,
    and a message about the registry means they did their job and something
    else is missing.
    """
    return bool(REGISTRY_DENIED.search(str(message or "")))


# What compose says when it waited for one service before starting the next.
# Both wordings name the container, which is the one thing worth having: it is
# what a message should point at and what a log should be read from.
UNHEALTHY = re.compile(
    r'container\s+"?(?P<name>[^"\s,]+)"?\s+is unhealthy', re.I)
EXITED_EARLY = re.compile(
    r'container\s+"?(?P<name>[^"\s,]+)"?\s+exited\s*\((?P<code>\d+)\)', re.I)


def start_failure_in(message):
    """Which container kept the stack from coming up, out of the error text.

    ``depends_on`` with a condition makes compose wait, and when the wait ends
    badly it gives up on the whole stack -- the containers it had already
    started keep running. Returns ``{"container", "kind", "code"}`` or None.
    """
    text = str(message or "")
    found = UNHEALTHY.search(text)
    if found:
        return {"container": found.group("name").lstrip("/"),
                "kind": "unhealthy", "code": None}
    found = EXITED_EARLY.search(text)
    if found:
        return {"container": found.group("name").lstrip("/"),
                "kind": "exited", "code": int(found.group("code"))}
    return None


def docker_log_text(raw, limit=40):
    """A container's log as plain lines, however Docker framed it.

    Without a terminal the daemon puts eight bytes in front of every chunk:
    one for the stream it came from, three zeros, four for the length. With
    one, the bytes are the text itself. The header is what tells them apart,
    and a stream that stops making sense halfway is kept as far as it went --
    this is being read to show somebody, not to parse.
    """
    text = raw if isinstance(raw, str) else _unframe(raw or b"")
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return [line for line in lines if line.strip()][-limit:]


def _unframe(raw):
    chunks, pos = [], 0
    while pos + 8 <= len(raw):
        if raw[pos] not in (0, 1, 2) or raw[pos + 1:pos + 4] != b"\x00\x00\x00":
            if not chunks:
                return raw.decode("utf-8", "replace")  # a terminal: plain text
            break
        size = int.from_bytes(raw[pos + 4:pos + 8], "big")
        chunks.append(raw[pos + 8:pos + 8 + size])
        pos += 8 + size
    return b"".join(chunks).decode("utf-8", "replace")


def _message_of(raw):
    """The readable part of an error body -- Portainer answers in JSON."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw.strip()[:300]
    if isinstance(parsed, dict):
        text = str(parsed.get("message") or parsed.get("details") or "").strip()
        detail = str(parsed.get("details") or "").strip()
        if detail and detail not in text:
            text = f"{text} ({detail})" if text else detail
        return text[:300] or raw.strip()[:300]
    return raw.strip()[:300]


# --------------------------------------------------------------------------
# reading what came back
# --------------------------------------------------------------------------


def git_config(stack):
    """The stack's git settings, or None when it was not deployed from one."""
    config = stack.get("GitConfig")
    return config if isinstance(config, dict) and config.get("URL") else None


def auto_update_of(stack):
    """How this stack updates itself: a schedule, a webhook, or nothing."""
    settings = stack.get("AutoUpdate")
    if not isinstance(settings, dict):
        return None
    interval = str(settings.get("Interval") or "").strip()
    webhook = str(settings.get("Webhook") or "").strip()
    if not interval and not webhook:
        return None
    return {"interval": interval, "webhook": webhook,
            "force_pull": bool(settings.get("ForcePullImage"))}


def container_name(container):
    """Docker hands out names with a leading slash; nobody wants to see it."""
    names = container.get("Names") or []
    first = str(names[0]) if names else str(container.get("Id", ""))[:12]
    return first.lstrip("/")


def stack_of(container):
    """The compose project a container belongs to, from its labels."""
    labels = container.get("Labels") or {}
    return str(labels.get("com.docker.compose.project", "")).strip()


def service_of(container):
    labels = container.get("Labels") or {}
    return str(labels.get("com.docker.compose.service", "")).strip()


def published_ports(container):
    """The host ports this container is reachable on, one entry per port.

    Docker reports a binding once per address family, so 8080 published on
    every address arrives twice -- as 0.0.0.0 and as ::. They are folded into
    one entry here, because they are one port on one host.

    ``everywhere`` is what matters for a reverse proxy: a port bound to
    127.0.0.1 cannot be reached from another machine, so HAProxy on the
    firewall could not use it.
    """
    found = {}
    for entry in container.get("Ports") or []:
        host_port = entry.get("PublicPort")
        if not host_port:
            continue  # only exposed inside Docker, nothing to reach from outside
        address = str(entry.get("IP", ""))
        key = (host_port, str(entry.get("Type", "tcp")))
        port = found.setdefault(key, {
            "host_port": int(host_port),
            "container_port": int(entry.get("PrivatePort") or 0),
            "proto": str(entry.get("Type", "tcp")),
            "addresses": [],
            "everywhere": False,
        })
        if address not in port["addresses"]:
            port["addresses"].append(address)
        if address in ANY_ADDRESS:
            port["everywhere"] = True
    return sorted(found.values(), key=lambda port: port["host_port"])


def read_container(container):
    """One container, reduced to what a window shows."""
    return {
        "id": str(container.get("Id", ""))[:12],
        "name": container_name(container),
        "service": service_of(container),
        "stack": stack_of(container),
        "image": str(container.get("Image", "")),
        "state": str(container.get("State", "")),
        "status": str(container.get("Status", "")),
        "ports": published_ports(container),
    }


def read_stack(stack, containers):
    """One stack with the containers that carry its compose project label."""
    name = str(stack.get("Name", ""))
    mine = [c for c in containers if c["stack"] == name]
    ports = []
    for container in mine:
        for port in container["ports"]:
            ports.append({**port, "container": container["name"],
                          "service": container["service"] or container["name"]})
    git = git_config(stack) or {}
    return {
        "id": stack.get("Id"),
        "name": name,
        "endpoint_id": stack.get("EndpointId"),
        "type": int(stack.get("Type") or 0),
        "kind": STACK_KIND.get(int(stack.get("Type") or 0), "?"),
        "git": {
            "url": str(git.get("URL", "")),
            "reference": str(git.get("ReferenceName", "")),
            "compose_file": str(git.get("ConfigFilePath", "")),
            "authenticated": bool(git.get("Authentication")),
        } if git else None,
        "auto_update": auto_update_of(stack),
        "env": list(stack.get("Env") or []),
        "containers": mine,
        "ports": sorted(ports, key=lambda port: port["host_port"]),
        "running": sum(1 for c in mine if c["state"] == "running"),
        "raw": stack,
    }


def inventory(client, endpoint_id=None):
    """Everything one environment is running, stacks first.

    Containers started outside a stack are kept as well: they publish ports on
    the same host, and a port that is already taken is worth seeing whichever
    way it got there.
    """
    endpoints = client.endpoints()
    chosen = None
    for entry in endpoints:
        if endpoint_id in (None, "") or str(entry.get("Id")) == str(endpoint_id):
            chosen = entry
            break
    if chosen is None:
        known = ", ".join(f"{e.get('Id')}: {e.get('Name')}" for e in endpoints)
        raise PortainerError(
            f"no environment with id {endpoint_id} in Portainer"
            + (f" (have: {known})" if known else " -- there is none configured"))
    eid = chosen.get("Id")

    containers = [read_container(entry) for entry in client.containers(eid)]
    stacks = [read_stack(stack, containers) for stack in client.stacks()
              if str(stack.get("EndpointId")) == str(eid)]
    stacks.sort(key=lambda stack: stack["name"].lower())
    named = {stack["name"] for stack in stacks}
    loose = sorted((c for c in containers if c["stack"] not in named),
                   key=lambda container: container["name"].lower())
    return {
        "endpoint": {"id": eid, "name": str(chosen.get("Name", "")),
                     "url": str(chosen.get("URL", "")),
                     "status": int(chosen.get("Status") or 0)},
        "endpoints": [{"id": e.get("Id"), "name": str(e.get("Name", ""))}
                      for e in endpoints],
        "stacks": stacks,
        "loose": loose,
    }


def all_ports(state):
    """Every published host port in one list, for spotting a collision."""
    ports = []
    for stack in state["stacks"]:
        for port in stack["ports"]:
            ports.append({**port, "stack": stack["name"]})
    for container in state["loose"]:
        for port in container["ports"]:
            ports.append({**port, "stack": "", "container": container["name"],
                          "service": container["name"]})
    return sorted(ports, key=lambda port: port["host_port"])


# --------------------------------------------------------------------------
# what goes in
# --------------------------------------------------------------------------


def parse_env(text):
    """Turn Portainer's free-text environment block into what the API wants.

    One ``KEY=value`` per line, blank lines and ``#`` comments ignored -- the
    same thing Portainer's own "advanced mode" box accepts.
    """
    variables = []
    for number, line in enumerate(str(text or "").splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.lower().startswith("export "):
            entry = entry[7:].lstrip()
        if "=" not in entry:
            raise core.UsageError(
                f"line {number} of the environment has no '=': {line.strip()}")
        name, value = entry.split("=", 1)
        name = name.strip()
        if not name:
            raise core.UsageError(f"line {number} of the environment has no name")
        value = value.strip()
        # a quoted value is written the same way in a .env file; the quotes
        # belong to the notation, not to the value
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        variables.append({"name": name, "value": value})
    return variables


def env_text(variables):
    """The other direction, for showing what a stack has now."""
    return "\n".join(f"{entry.get('name', '')}={entry.get('value', '')}"
                     for entry in variables or [])


def put_env(text, values, note=""):
    """Write these variables into an environment block, keeping the rest of it.

    A name already in there is changed where it stands: a second line for the
    same name would leave the block saying two things, and only one of them
    would reach Docker. What is not in there yet is appended under ``note``, so
    the block still says where each part came from.
    """
    lines = str(text or "").splitlines()
    left = dict(values or {})
    for index, line in enumerate(lines):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.lower().startswith("export "):
            entry = entry[7:].lstrip()
        name = entry.split("=", 1)[0].strip()
        if name in left:
            lines[index] = f"{name}={left.pop(name)}"
    if left:
        if any(line.strip() for line in lines):
            lines.append("")
        if note:
            lines.append(f"# {note}")
        lines.extend(f"{name}={value}" for name, value in left.items())
    return "\n".join(lines).strip("\n") + "\n"


def read_env_file(text):
    """Read a ``.env`` found in a repository, forgiving what it finds.

    Unlike the box in the window, this text was not typed by anyone here: an
    example file may carry a stray heading or a commented-out block. A line
    that cannot be a variable is counted and skipped rather than refused --
    the point is to offer a starting position, not to grade the repository.
    """
    entries, skipped = [], 0
    for line in str(text or "").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.lower().startswith("export "):
            raw = raw[7:].lstrip()
        name, sign, value = raw.partition("=")
        name = name.strip()
        if not sign or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            skipped += 1
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        entries.append({"name": name, "value": value})
    return entries, skipped


# ``$$`` is how a compose file writes a literal dollar sign, so those are
# blanked out before the search rather than read as a variable.
VARIABLE = re.compile(r"""
    \$ (?:
        \{ (?P<braced>[A-Za-z_][A-Za-z0-9_]*)
           (?P<how>:?[-?+=])? (?P<default>[^}]*) \}
      | (?P<plain>[A-Za-z_][A-Za-z0-9_]*)
    )""", re.VERBOSE)


def compose_variables(text):
    """Every ``${VAR}`` a compose file reads, with its default where it has one.

    ``${VAR:-eins}`` and ``${VAR-eins}`` name a fallback and that is worth
    offering. ``${VAR:?...}`` and ``${VAR:+...}`` do not: the first is an error
    message, the second the value used when VAR *is* set.
    """
    found = {}
    for match in VARIABLE.finditer(str(text or "").replace("$$", "\0\0")):
        name = match.group("braced") or match.group("plain")
        default = ""
        if match.group("braced") and match.group("how") in (":-", "-"):
            default = (match.group("default") or "").strip()
        # first mention wins, but a later one may be the one carrying a default
        if name not in found or (default and not found[name]):
            found[name] = default
    return found


def _scalar(text):
    """One YAML value: without its quotes and without a trailing comment."""
    value = str(text).split(" #", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def _scalars(text):
    entry = str(text).strip()
    if entry.startswith("[") and entry.endswith("]"):
        return [_scalar(part) for part in entry[1:-1].split(",")]
    return [_scalar(entry)]


def compose_env_files(text):
    """The files a compose file names under ``env_file:``.

    This reads lines rather than YAML -- there is no parser in the standard
    library and one file name is not worth carrying a dependency for. It knows
    the three ways the key is written: one name, a list of names, and the
    longer form with ``path:``. Anything it does not recognise is passed over,
    which costs at most a suggestion.
    """
    names, lines, index = [], str(text or "").splitlines(), 0
    while index < len(lines):
        line = lines[index]
        index += 1
        stripped = line.strip()
        if not stripped.startswith("env_file:"):
            continue
        inline = stripped[len("env_file:"):].strip()
        if inline and not inline.startswith("#"):
            names.extend(_scalars(inline))
            continue
        indent = len(line) - len(line.lstrip())
        while index < len(lines):
            following = lines[index]
            if not following.strip():
                index += 1
                continue
            if len(following) - len(following.lstrip()) <= indent:
                break
            item = following.strip()
            index += 1
            if item.startswith("-"):
                item = item[1:].strip()
            if item.startswith("path:"):
                item = item[5:].strip()
            elif ":" in item:
                continue  # "required: false" and its kind, not a file name
            names.extend(_scalars(item))
    # several services usually name the same file; it is one file to read
    return list(dict.fromkeys(name for name in names if name))


def expand(text, variables=None):
    """Fill in ``${VAR}`` the way compose will, from what this deploy sets.

    Only the two cases that have an answer here: a variable the deploy gives a
    value, and one that carries its own fallback. Anything else is left as it
    stands -- unknown reads better further up than wrongly resolved.
    """
    values = {entry.get("name"): entry.get("value", "")
              for entry in (variables or []) if entry.get("name")}

    def swap(match):
        name = match.group("braced") or match.group("plain")
        if values.get(name):
            return values[name]
        if match.group("braced") and match.group("how") in (":-", "-"):
            return (match.group("default") or "").strip()
        return match.group(0)

    return VARIABLE.sub(swap, str(text or ""))


def variable_in(text):
    """The first ``${VAR}`` in a value, so a clash can name what to set."""
    found = VARIABLE.search(str(text or ""))
    return (found.group("braced") or found.group("plain")) if found else ""


def compose_names(text):
    """The container names a compose file pins with ``container_name:``.

    Such a name is not the stack's to vary: Docker hands out container names
    once per host, so two stacks from one repository ask for the same one and
    the second is refused. Read by line, for the reason given at env_file.
    """
    names = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("container_name:"):
            continue
        value = _scalar(stripped[len("container_name:"):])
        if value:
            names.append(value)
    return list(dict.fromkeys(names))


def compose_services(text):
    """Every service, with the image it names and whether it builds its own.

    Read by line, for the reason given at env_file, and only as deep as the
    question needs: ``services:`` at the top, one step in each service, one
    more its keys. That is enough to tell an image that has to be fetched from
    one the host builds itself out of the repository.
    """
    services, current, service_indent = [], None, None
    in_services = False
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if not in_services:
            in_services = indent == 0 and stripped.startswith("services:")
            continue
        if indent == 0:
            break  # the next key at the top ends the services block
        if service_indent is None:
            service_indent = indent
        if indent <= service_indent:
            current = {"name": stripped.split(":", 1)[0].strip(),
                       "image": "", "build": False}
            services.append(current)
            continue
        if current is None:
            continue
        if stripped.startswith("image:"):
            current["image"] = _scalar(stripped[len("image:"):])
        elif stripped.startswith("build:"):
            current["build"] = True
    return services


def registry_host_of(image):
    """The registry an image is fetched from, or "" when Docker Hub serves it.

    Docker reads the part before the first slash as a host only when it looks
    like one: it carries a dot or a port, or it is localhost. Anything else is
    a name on Docker Hub, and a name without a slash at all is one of Docker's
    own. A reference still holding a ``${VAR}`` is left alone -- half a host
    name is worse than none.
    """
    ref = str(image or "").strip()
    if not ref or "/" not in ref:
        return ""
    head = ref.split("/", 1)[0]
    if VARIABLE.search(head):
        return ""
    if head == "localhost" or "." in head or ":" in head:
        return head.lower()
    return ""


def images_to_pull(text, variables=None):
    """The images this compose file fetches from a registry of its own.

    A service that builds its image needs no registry at all: the Dockerfile
    comes with the repository and the host builds it right there, which is why
    a private repository alone gets by with the credentials on the stack. Only
    a prebuilt image from a host of its own is a second login, and Portainer
    takes that one from its registry list rather than from the stack.

    Docker Hub is left out on purpose, whether an image names it or leaves it
    out. Nearly everything served from there is public, and a warning on every
    ``postgres:16-alpine`` would bury the one that matters. A private image on
    Docker Hub is the one case this misses, and it is answered afterwards by
    what the failed deploy says.
    """
    found = []
    for service in compose_services(text):
        if service["build"] or not service["image"]:
            continue
        host = registry_host_of(expand(service["image"], variables))
        if host and host not in DOCKER_HUB_HOSTS:
            found.append({"service": service["name"], "host": host,
                          "image": expand(service["image"], variables)})
    return found


def same_registry(url, host):
    """Whether a registry entry points at that host -- scheme and path aside.

    Portainer stores what was typed, which may carry an ``https://`` or a
    trailing slash; an image reference never does.
    """
    def bare(value):
        text = str(value or "").strip().rstrip("/").lower()
        if "//" in text:
            text = text.split("//", 1)[1]
        return text.split("/", 1)[0]

    return bool(bare(url)) and bare(url) == bare(host)


def registry_for(registries, host):
    """The entry that already covers that host, if there is one."""
    for entry in registries or []:
        if same_registry(entry.get("URL", ""), host):
            return entry
    return None


def compose_port_entries(text):
    """Every line under a ``ports:`` key, still as written.

    Unresolved on purpose: which variable a port comes from is what makes the
    difference between a clash somebody can answer in the form and one that
    needs a change in the repository.
    """
    entries, lines, index = [], str(text or "").splitlines(), 0
    while index < len(lines):
        line = lines[index]
        index += 1
        stripped = line.strip()
        if not stripped.startswith("ports:"):
            continue
        inline = stripped[len("ports:"):].strip()
        if inline and not inline.startswith("#"):
            entries.extend(_scalars(inline))
            continue
        indent = len(line) - len(line.lstrip())
        while index < len(lines):
            following = lines[index]
            if not following.strip():
                index += 1
                continue
            if len(following) - len(following.lstrip()) <= indent:
                break
            item = following.strip()
            index += 1
            if item.startswith("-"):
                item = item[1:].strip()
            if item and not item.startswith("#"):
                entries.append(item)
    return list(dict.fromkeys(entries))


def host_port_of(entry):
    """The host port one ``ports:`` entry publishes, or 0 when it has none.

    ``8088:8080`` and ``127.0.0.1:8088:8080`` both name their host port second
    from the end; the long form spells it out under ``published:``. A container
    port on its own gets a free host port from Docker and can never collide, and
    a range is left alone -- a wrong warning is worse here than none.
    """
    value = str(entry or "").strip()
    if value.startswith("published:"):
        value = _scalar(value[len("published:"):])
        return int(value) if value.isdigit() else 0
    value = _scalar(value)
    if "/" in value:
        value = value.rsplit("/", 1)[0]
    parts = value.split(":")
    if len(parts) < 2:
        return 0
    host = parts[-2].strip()
    return int(host) if host.isdigit() else 0


def env_paths(compose_file, named=()):
    """Where to look for an environment file, most likely first.

    What the compose file points at comes first and is read relative to that
    file, as Docker Compose reads it. Then the usual names beside it, and only
    then the top of the repository.
    """
    folder = posixpath.dirname(str(compose_file or DEFAULT_COMPOSE_FILE).strip("/"))
    paths, seen = [], set()

    def add(path):
        clean = posixpath.normpath(path)
        if clean and clean not in seen and not clean.startswith(".."):
            seen.add(clean)
            paths.append(clean)

    for name in named:
        add(name.lstrip("/") if name.startswith("/")
            else posixpath.join(folder, name))
    for name in ENV_CANDIDATES:
        add(posixpath.join(folder, name))
    if folder:
        for name in ENV_CANDIDATES:
            add(name)
    return paths


def auto_update_settings(mode, interval=DEFAULT_INTERVAL, force_pull=True,
                         webhook=""):
    """Portainer's GitOps block: poll on a schedule, or wait for a webhook."""
    if mode == "interval":
        return {"Interval": (interval or DEFAULT_INTERVAL).strip(),
                "ForcePullImage": bool(force_pull), "Webhook": ""}
    if mode == "webhook":
        return {"Interval": "", "ForcePullImage": bool(force_pull),
                "Webhook": webhook or str(uuid.uuid4())}
    return None


def webhook_url(client, webhook_id):
    return f"{client.base}/api/stacks/webhooks/{webhook_id}"


def stack_name_taken(state, name):
    return any(stack["name"].lower() == name.lower() for stack in state["stacks"])


def port_owner(state, host_port):
    """Who is already on that host port, if anybody."""
    for port in all_ports(state):
        if port["host_port"] == int(host_port):
            return port
    return None


def containers_of(state):
    """Every container the last reading found, in a stack or beside one."""
    listed = [container for stack in state["stacks"]
              for container in stack["containers"]]
    listed.extend(state["loose"])
    return listed


def name_owner(state, name):
    """Which container already answers to that name, if any."""
    wanted = str(name or "").lstrip("/")
    for container in containers_of(state):
        if container["name"] == wanted:
            return container
    return None


def free_name(state, wanted):
    """``wanted`` if it is free, otherwise the same with a number behind it."""
    base = str(wanted or "").strip("-") or "stack"
    if not name_owner(state, base):
        return base
    for number in range(2, 100):
        candidate = f"{base}-{number}"
        if not name_owner(state, candidate):
            return candidate
    return base


def free_port(state, wanted):
    """The first free host port from ``wanted`` upwards."""
    port = int(wanted or 0)
    while port and port < 65536 and port_owner(state, port):
        port += 1
    return port


def taken_ports(state):
    """Every host port something on this environment already answers on."""
    if not state:
        return []
    return sorted({port["host_port"] for port in all_ports(state)})


def free_ports(state, start, count=8):
    """The next ``count`` host ports from ``start`` upwards that nobody holds.

    Measured against the last reading of the environment, so it says what is
    free among the containers Portainer knows. A port held by something outside
    Docker, or by a container that is currently stopped, cannot be seen from
    here -- this is a shortlist worth trying, not a guarantee.
    """
    taken = set(taken_ports(state))
    found = []
    port = max(int(start or 0), 1)
    while port < 65536 and len(found) < count:
        if port not in taken:
            found.append(port)
        port += 1
    return found


# --------------------------------------------------------------------------
# the steps a window runs
# --------------------------------------------------------------------------


def check_deploy(client, opts, state, out=print):
    """Ask what this stack wants for itself and whether the host still has it.

    Container names and published ports belong to the Docker host, not to the
    stack that asks for them. Portainer notices that only while deploying, and
    answers with the daemon's own words -- "the container name is already in
    use" -- after the stack has been created and left half standing.

    Reading the compose file first costs one clone and says the same thing
    while it can still be answered. Every clash carries the variable its value
    came from: one written into the compose file cannot be helped from here,
    one out of a ``${VAR}`` is a line in the environment box.
    """
    compose_path = (getattr(opts, "compose_file", "") or "").strip() \
        or DEFAULT_COMPOSE_FILE
    compose = client.repo_file(
        opts.repository, compose_path,
        reference=getattr(opts, "reference", ""),
        username=getattr(opts, "username", ""),
        password=getattr(opts, "password", ""),
        skip_tls_verify=bool(getattr(opts, "skip_tls_verify", False)))
    variables = parse_env(getattr(opts, "env_text", ""))
    # the stack's own name is the obvious way out of a name clash: it is unique
    # on this Portainer already, and it says which of the two this container is
    wanted = getattr(opts, "name", "")
    wanted = core.slug(wanted, allow_dots=False).lower() if wanted else ""

    clashes = []
    for raw in compose_names(compose):
        name = expand(raw, variables)
        if VARIABLE.search(name):
            continue  # a variable nobody filled in; Portainer will say so
        holder = name_owner(state, name)
        out(f"container name {name}"
            + (f" -- taken by {holder['stack'] or 'a loose container'}"
               if holder else " is free"))
        if holder:
            clashes.append({
                "kind": "name", "value": name, "variable": variable_in(raw),
                "suggest": free_name(state, wanted or name),
                "container": holder["name"], "stack": holder["stack"]})

    for raw in compose_port_entries(compose):
        port = host_port_of(expand(raw, variables))
        if not port:
            continue
        owner = port_owner(state, port)
        out(f"host port {port}"
            + (f" -- taken by {owner.get('container', '?')}"
               if owner else " is free"))
        if owner:
            clashes.append({
                "kind": "port", "value": port, "variable": variable_in(raw),
                "suggest": free_port(state, port),
                "container": owner.get("container", ""),
                "stack": owner.get("stack", "")})

    if clashes:
        out(f"= {len(clashes)} of them already in use on this environment")
    return {"compose": compose_path, "clashes": clashes,
            "registry": check_registries(client, compose, variables, out)}


def check_registries(client, compose, variables, out=print):
    """Whether the images in this compose file can be fetched at all.

    The credentials on a stack open the git repository; the image pull is a
    second login that Portainer looks up in its own registry list, by host.
    A service that builds its image asks for neither, which is why a private
    repository on its own gets along without any of this.

    Returns one entry per registry host that would be asked for a login,
    saying whether Portainer already knows it. Nothing here changes anything.
    """
    wanted = images_to_pull(compose, variables)
    if not wanted:
        return []
    try:
        known = client.registries()
    except PortainerError as exc:
        out(f"= cannot read the registries of this Portainer: {exc}")
        return []

    hosts, seen = [], set()
    for entry in wanted:
        if entry["host"] in seen:
            continue
        seen.add(entry["host"])
        holder = registry_for(known, entry["host"])
        out(f"{entry['service']} pulls {entry['image']}"
            + (f" -- {entry['host']} is a registry Portainer knows"
               if holder else f" -- no login stored for {entry['host']}"))
        hosts.append({"host": entry["host"], "service": entry["service"],
                      "image": entry["image"],
                      "id": holder.get("Id") if holder else 0,
                      "name": (holder or {}).get("Name", "")})
    return hosts


def ensure_registry(client, host, username, password, registry_id=0, name="",
                    out=print):
    """Store the login an image pull will need, under that host.

    One entry per host is the point. Portainer hands every registry it holds
    to the deploy and lets Docker match them by host, so a second entry for a
    host that already has one is a coin toss over which token gets used.
    """
    try:
        if registry_id:
            client.update_registry(registry_id, host, username, password,
                                   name=name)
            out(f"+ {host}: the stored login was replaced with this token")
        else:
            client.create_registry(host, username, password)
            out(f"+ {host} added to the registries, with this user and token")
        return True
    except PortainerError as exc:
        out(f"= {host} could not be stored as a registry: {exc}")
        if exc.status in (401, 403):
            out("= adding a registry needs a Portainer administrator")
        return False


def last_words(client, endpoint_id, name, blame=None, keep=(), out=print):
    """Read the log of the container that failed, while there still is one.

    Removing a container removes its log with it, and for a health check that
    never went green that log is the whole answer -- the error only says the
    check failed, never why. So it is read out first and written into the same
    report the failure is being told in.

    ``blame`` is what :func:`start_failure_in` found; without it every
    container of the stack that is not running gets a look.
    """
    kept = {str(entry) for entry in keep}
    try:
        containers = [entry for entry in client.containers(endpoint_id)
                      if stack_of(entry) == name
                      and str(entry.get("Id")) not in kept]
    except core.ApiError:
        return
    wanted = (blame or {}).get("container", "")
    if wanted:
        containers = [entry for entry in containers
                      if container_name(entry) == wanted] or containers
    else:
        containers = [entry for entry in containers
                      if str(entry.get("State", "")) != "running"] or containers
    for entry in containers[:2]:
        label = container_name(entry)
        try:
            lines = docker_log_text(
                client.container_logs(endpoint_id, entry.get("Id")), limit=20)
        except core.ApiError as exc:
            out(f"= {label} kept its log to itself: {exc}")
            continue
        if not lines:
            out(f"= {label} wrote nothing at all")
            continue
        out(f"= what {label} said last:")
        for line in lines:
            out(f"    {line}")


def rollback_deploy(client, endpoint_id, name, keep=(), out=print):
    """Take away what a failed deploy left standing.

    Portainer creates the stack first and starts the containers afterwards, so
    a compose file that comes up badly leaves both behind: a stack that never
    ran, and the containers that did start before compose gave up. Deleting the
    stack takes its containers with it; whatever is still there afterwards is
    found by the compose project label, and the network the stack made for
    itself goes last -- Docker refuses it while anything is still attached.

    ``keep`` are the container ids that were there before the deploy: a
    container carrying the label but not the moment belongs to somebody else,
    and nothing here may touch it. Named volumes stay, the same way
    ``docker compose down`` leaves them.

    Undoing must not hide what went wrong, so a removal that fails is a line
    in the log rather than an exception. Returns what went and what would not.
    """
    gone = {"stack": "", "containers": [], "networks": [], "failed": []}
    kept = {str(entry) for entry in keep}

    def failed(what, exc):
        gone["failed"].append(f"{what}: {exc}")
        out(f"! could not remove {what}: {exc}", file=sys.stderr)

    try:
        mine = [stack for stack in client.stacks()
                if str(stack.get("Name", "")) == name
                and str(stack.get("EndpointId")) == str(endpoint_id)]
    except core.ApiError as exc:
        mine = []
        failed(f"stack {name}", exc)
    for stack in mine:
        try:
            client.delete_stack(stack.get("Id"), endpoint_id)
            gone["stack"] = name
            out(f"- stack {name} removed again", file=sys.stderr)
        except core.ApiError as exc:
            failed(f"stack {name}", exc)

    try:
        left = [entry for entry in client.containers(endpoint_id)
                if stack_of(entry) == name and str(entry.get("Id")) not in kept]
    except core.ApiError as exc:
        left = []
        failed(f"the containers of {name}", exc)
    for entry in left:
        label = container_name(entry)
        try:
            client.remove_container(endpoint_id, entry.get("Id"))
            gone["containers"].append(label)
            out(f"- container {label} removed", file=sys.stderr)
        except core.ApiError as exc:
            failed(f"container {label}", exc)

    try:
        nets = [net for net in client.networks(endpoint_id)
                if str((net.get("Labels") or {}).get(
                    "com.docker.compose.project", "")) == name]
    except core.ApiError as exc:
        nets = []
        failed(f"the networks of {name}", exc)
    for net in nets:
        label = str(net.get("Name") or net.get("Id", ""))
        try:
            client.remove_network(endpoint_id, net.get("Id"))
            gone["networks"].append(label)
            out(f"- network {label} removed", file=sys.stderr)
        except core.ApiError as exc:
            failed(f"network {label}", exc)
    return gone


def deploy(client, opts, out=print):
    """Create a stack from a repository and say what happened while doing it.

    ``opts`` carries the same names the dialog uses: endpoint_id, name,
    repository, reference, compose_file, env_text, username, password,
    auto_update, skip_tls_verify.
    """
    # Portainer lowercases the name itself before it becomes the compose
    # project; doing it here means the log says the name that will exist.
    name = core.slug(opts.name, allow_dots=False).lower() if opts.name else ""
    if not name:
        raise core.UsageError("the stack needs a name")
    if not opts.repository:
        raise core.UsageError("the stack needs a repository URL")
    variables = parse_env(getattr(opts, "env_text", ""))

    out(f"deploying stack {name}")
    out(f"repository {opts.repository}"
        + (f" ({opts.reference})" if opts.reference else ""))
    out(f"compose file {opts.compose_file or DEFAULT_COMPOSE_FILE}")
    if variables:
        out(f"environment {len(variables)} variables")
    if getattr(opts, "username", "") or getattr(opts, "password", ""):
        out("repository credentials go to Portainer, not into the config file")
    # The same token, a second time and in the other place: what the stack
    # carries is read by the git clone, what the images need is read from the
    # registry list. Only what was agreed to in the form lands here.
    for entry in getattr(opts, "registry", None) or []:
        ensure_registry(client, entry["host"],
                        getattr(opts, "username", ""),
                        getattr(opts, "password", ""),
                        registry_id=entry.get("id") or 0,
                        name=entry.get("name", ""), out=out)
    auto = getattr(opts, "auto_update", None)
    if auto:
        if auto.get("Interval"):
            out(f"auto update every {auto['Interval']}"
                + (", pulling images" if auto.get("ForcePullImage") else ""))
        else:
            out(f"auto update on webhook {auto.get('Webhook')}")

    # Who was already there, so that undoing this can tell the containers it
    # started apart from the ones it found. Not knowing is no reason to stop:
    # the list is only needed if something goes wrong, and an empty one merely
    # means the label has to speak for itself.
    try:
        before = [str(entry.get("Id")) for entry in
                  client.containers(opts.endpoint_id)]
    except core.ApiError:
        before = []

    try:
        reply = client.deploy_repository(
            opts.endpoint_id, name, opts.repository,
            reference=getattr(opts, "reference", ""),
            compose_file=getattr(opts, "compose_file", ""),
            env=variables,
            username=getattr(opts, "username", ""),
            password=getattr(opts, "password", ""),
            auto_update=auto,
            skip_tls_verify=bool(getattr(opts, "skip_tls_verify", False)))
    except core.ApiError as exc:
        out(f"! {exc}", file=sys.stderr)
        # An answer is what makes this a failure. Without one -- a timeout, a
        # connection that broke -- Portainer may well be pulling images this
        # very moment, and tearing down a deploy that is still running would be
        # the one truly destructive thing this program could do.
        if not getattr(exc, "status", 0):
            out(f"= no answer from Portainer, so what became of {name} is not "
                f"known here -- nothing was taken away. Reload in a minute and "
                f"look before trying again.", file=sys.stderr)
            raise
        # This is a stack being made, not one being changed: nothing here was
        # running a minute ago, so there is nothing to preserve and no reason
        # to leave half of it standing.
        out(f"{name} did not come up -- taking back what was created",
            file=sys.stderr)
        blame = start_failure_in(str(exc))
        last_words(client, opts.endpoint_id, name, blame=blame, keep=before,
                   out=out)
        gone = rollback_deploy(client, opts.endpoint_id, name, keep=before,
                               out=out)
        gone["blame"] = blame
        gone["name"] = name
        raise DeployFailed(str(exc), cleanup=gone,
                           status=getattr(exc, "status", 0)) from None
    stack_id = reply.get("Id")
    out(f"+ stack {name} created (id {stack_id})")
    return {"id": stack_id, "name": name, "stack": reply}


def discover_env(client, opts, out=print):
    """Find out what this stack expects, before anything is deployed.

    Reads the compose file, notes every variable it uses, and then looks for
    an environment file to fill them in from. Coming back with the compose
    file at all is already an answer: the repository, the branch, the path and
    the credentials must all have been right.
    """
    if not getattr(opts, "repository", ""):
        raise core.UsageError("no repository to read from")
    compose_path = (getattr(opts, "compose_file", "") or "").strip() \
        or DEFAULT_COMPOSE_FILE
    reference = getattr(opts, "reference", "")
    username = getattr(opts, "username", "")
    password = getattr(opts, "password", "")
    skip = bool(getattr(opts, "skip_tls_verify", False))

    def read(path):
        return client.repo_file(opts.repository, path, reference=reference,
                                username=username, password=password,
                                skip_tls_verify=skip)

    out(f"reading {compose_path} from {opts.repository}"
        + (f" ({reference})" if reference else ""))
    compose = read(compose_path)
    variables = compose_variables(compose)
    out(f"the compose file reads {len(variables)} variable"
        f"{'' if len(variables) == 1 else 's'}")

    named = compose_env_files(compose)
    if named:
        out("it points at " + ", ".join(named))

    entries, source, skipped = [], "", 0
    for path in env_paths(compose_path, named)[:MAX_ENV_PROBES]:
        out(f"looking for {path}")
        try:
            text = read(path)
        except (PortainerError, core.UsageError):
            continue  # not there is the normal answer, and not an error
        if not text.strip():
            continue
        entries, skipped = read_env_file(text)
        if not entries:
            continue
        source = path
        out(f"+ {path} holds {len(entries)} variable"
            f"{'' if len(entries) == 1 else 's'}")
        break
    if not source:
        out("= no environment file in the repository")

    known = {entry["name"] for entry in entries}
    missing = [{"name": name, "value": variables[name]}
               for name in sorted(variables) if name not in known]
    if missing:
        out(f"= {len(missing)} more used by the compose file")
    return {"compose": compose_path, "source": source, "entries": entries,
            "missing": missing, "skipped": skipped,
            "variables": sorted(variables)}


def redeploy(client, stack, pull_image=True, prune=False, username="",
             password="", out=print):
    """Deploy an existing stack again."""
    name = stack.get("name") or stack.get("Name") or "?"
    raw = stack.get("raw", stack)
    out(f"redeploying stack {name}")
    if git_config(raw):
        out(f"from {git_config(raw).get('URL')}"
            + (f" ({git_config(raw).get('ReferenceName')})"
               if git_config(raw).get("ReferenceName") else ""))
    else:
        out("from the compose file Portainer keeps for it")
    out("pulling images first" if pull_image else "keeping the images as they are")
    if prune:
        out("removing services that are no longer in the file")
    client.redeploy(raw, pull_image=pull_image, prune=prune,
                    username=username, password=password)
    out(f"+ stack {name} redeployed")
    return {"name": name}


def remove_stack(client, stack, out=print):
    """Delete one stack, and say what goes with it before it is gone.

    The containers are named in the log on purpose: a stack is deleted by its
    name, but what actually stops are these, and afterwards there is nothing
    left to look at and check against.
    """
    name = stack.get("name") or "?"
    stack_id = stack.get("id")
    endpoint_id = stack.get("endpoint_id")
    if stack_id is None:
        raise core.UsageError(f"{name} has no id -- reload and try again")
    out(f"removing stack {name}")
    for container in stack.get("containers") or []:
        out(f"- container {container['name']} ({container['image']})")
    for port in stack.get("ports") or []:
        out(f"- host port {port['host_port']} is given back")
    client.delete_stack(stack_id, endpoint_id)
    out(f"+ stack {name} removed")
    return {"name": name, "containers": len(stack.get("containers") or []),
            "ports": [port["host_port"] for port in stack.get("ports") or []]}


def run_step(operation, client, *args, log=None, **kwargs):
    """Run one step and collect its log, the way the OPNsense side does.

    Returns ``{"ok", "log", "error", "result", "cleanup"}`` so a window can
    show the same thing whether the step worked or not. ``cleanup`` is set
    when the step undid itself -- see :class:`DeployFailed`.
    """
    recorder = log or core.LogRecorder()
    try:
        result = operation(client, *args, out=recorder, **kwargs)
    except (core.ApiError, core.UsageError) as exc:
        return {"ok": False, "log": recorder.lines, "error": str(exc),
                "result": None, "cleanup": getattr(exc, "cleanup", None)}
    return {"ok": True, "log": recorder.lines, "error": "", "result": result,
            "cleanup": None}


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


def settings_of(profile):
    """The Portainer section of a connection profile."""
    return dict((profile or {}).get("portainer") or {})


def host_ip_of(profile):
    """The address HAProxy should send traffic to for containers on this host.

    The Portainer section may name one; otherwise the host out of the Portainer
    URL is the best guess, since that is the machine Docker runs on in the
    common case of Portainer sitting on its own host.
    """
    settings = settings_of(profile)
    named = str(settings.get("host_ip", "")).strip()
    if named:
        return named
    url = str(settings.get("url", "")).strip()
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(core.base_url(url, "Portainer address"))
    except core.UsageError:
        return ""
    return parsed.hostname or ""


def client_from_config(profile, insecure=False):
    """Build a Portainer client from a profile, or None when unconfigured.

    Returns ``(client, settings)``; an unusable address lands in
    ``settings["error"]`` instead of raising, so the window can say so and
    carry on with the OPNsense side.
    """
    settings = settings_of(profile)
    if not settings.get("url"):
        return None, settings
    verify = settings.get("verify_ssl", True)
    if insecure:
        verify = False
    try:
        client = Portainer(settings["url"],
                           api_key=settings.get("api_key", ""),
                           username=settings.get("username", ""),
                           password=settings.get("password", ""),
                           verify=verify)
    except (core.UsageError, PortainerError) as exc:
        settings["error"] = str(exc)
        return None, settings
    return client, settings
