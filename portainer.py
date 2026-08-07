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
import urllib.error
import urllib.parse
import urllib.request
import uuid

import opnsense_haproxy as core

DEFAULT_COMPOSE_FILE = "docker-compose.yml"
DEFAULT_INTERVAL = "5m"

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

    def call(self, path, payload=None, method=None):
        """Call an API endpoint; ``path`` starts after ``/api/``."""
        if not self.api_key and not self._jwt:
            self.login()
        try:
            return self._send(path, payload, method)
        except PortainerError as exc:
            # A token that has run out is the one error worth a second try.
            if exc.status != 401 or self.api_key:
                raise
            self.login()
            return self._send(path, payload, method)

    def _send(self, path, payload=None, method=None, authenticated=True):
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
            with urllib.request.urlopen(req, timeout=self.timeout,
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
                body, method="POST")
        except PortainerError as exc:
            if exc.status not in (400, 404, 405):
                raise
            return self.call(
                f"stacks?type={COMPOSE_STACK}&method=repository"
                f"&endpointId={endpoint_id}", body, method="POST")

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
    return {"compose": compose_path, "clashes": clashes}


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
    auto = getattr(opts, "auto_update", None)
    if auto:
        if auto.get("Interval"):
            out(f"auto update every {auto['Interval']}"
                + (", pulling images" if auto.get("ForcePullImage") else ""))
        else:
            out(f"auto update on webhook {auto.get('Webhook')}")

    reply = client.deploy_repository(
        opts.endpoint_id, name, opts.repository,
        reference=getattr(opts, "reference", ""),
        compose_file=getattr(opts, "compose_file", ""),
        env=variables,
        username=getattr(opts, "username", ""),
        password=getattr(opts, "password", ""),
        auto_update=auto,
        skip_tls_verify=bool(getattr(opts, "skip_tls_verify", False)))
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


def run_step(operation, client, *args, log=None, **kwargs):
    """Run one step and collect its log, the way the OPNsense side does.

    Returns ``{"ok", "log", "error", "result"}`` so a window can show the same
    thing whether the step worked or not.
    """
    recorder = log or core.LogRecorder()
    try:
        result = operation(client, *args, out=recorder, **kwargs)
    except (core.ApiError, core.UsageError) as exc:
        return {"ok": False, "log": recorder.lines, "error": str(exc),
                "result": None}
    return {"ok": True, "log": recorder.lines, "error": "", "result": result}


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
