"""Dockhand, said in the same words as Portainer.

Dockhand answers on /api and takes a bearer token that starts with ``dh_``.
Where Portainer numbers its stacks, Dockhand names them; where Portainer keeps
a GitConfig on the stack, Dockhand keeps a sourceType beside it. Underneath
both, Docker reports the same containers with the same labels -- which is why
the stacks here are built by the shared join rather than from Dockhand's own
stack listing, whose container entries carry no bind address and so cannot say
whether a port is reachable from another machine.
"""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

import opnsense_haproxy as core

from .engine import Engine, build_inventory, build_stack, read_container
from .model import COMPOSE, FOUND, GIT, Origin, Place

# Dockhand's own words for where a stack came from.
SOURCE_KIND = {"git": GIT, "internal": COMPOSE, "external": FOUND}

TIMEOUT = 30


class Dockhand(Engine):
    kind = "dockhand"
    title = "Dockhand"

    def __init__(self, name, settings):
        super().__init__(name, settings)
        self.token = str(self.settings.get("api_key", "")).strip()
        self.verify = self.settings.get("verify_ssl", True) is not False

    # -- talking to it -----------------------------------------------------

    def call(self, path, query=None, payload=None, method=None, timeout=TIMEOUT):
        url = f"{self.url}/api/{path.lstrip('/')}"
        if query:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in query.items() if v not in (None, "")})
        headers = {"Accept": "application/json",
                   "User-Agent": f"opnsense-haproxy/{core.VERSION}"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers,
                                         method=method or ("POST" if body
                                                           else "GET"))
        context = None if self.verify else ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(request, timeout=timeout,
                                        context=context) as reply:
                raw = reply.read()
        except urllib.error.HTTPError as exc:
            raise core.ApiError(self._complaint(exc)) from None
        except urllib.error.URLError as exc:
            raise core.ApiError(f"Dockhand {self.url} ist nicht erreichbar "
                                f"({exc.reason})") from None
        if not raw:
            return {}
        try:
            return json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise core.ApiError(f"Dockhand {self.url} hat auf {path} keine "
                                "JSON-Antwort gegeben") from None

    def _complaint(self, exc):
        """Dockhand puts its reason in the body; say that rather than the code."""
        reason = ""
        try:
            reason = str((json.loads(exc.read().decode()) or {}).get("error", ""))
        except Exception:  # noqa: BLE001 - a body we cannot read is no reason to hide the code
            pass
        if exc.code in (401, 403):
            return (f"Dockhand {self.url} weist die Anmeldung ab "
                    f"({reason or 'kein Zugriff'}) -- ist der Token noch gültig?")
        return f"Dockhand {self.url} antwortet {exc.code}" + (f": {reason}"
                                                             if reason else "")

    # -- reading -----------------------------------------------------------

    def check(self):
        # There is no version endpoint that a token alone may read on every
        # build; the environment list is the smallest thing that proves both
        # that it answers and that the token is good for something.
        found = self.places()
        return {"manager": self.title, "version": "",
                "places": len(found)}

    def places(self):
        entries = self.call("environments")
        if not isinstance(entries, list):
            return []
        return [Place(id=str(entry.get("id")),
                      name=str(entry.get("name", "")),
                      url=self._where(entry),
                      reachable=True)
                for entry in entries]

    @staticmethod
    def _where(entry):
        """Something to show for "which machine is this", best effort.

        A local environment has no host at all -- it is the socket next to
        Dockhand itself -- and printing an empty string there is better than
        printing "None".
        """
        host = str(entry.get("host", "") or "")
        if not host:
            return str(entry.get("connectionType", "") or "")
        port = entry.get("port")
        protocol = str(entry.get("protocol", "") or "")
        where = f"{host}:{port}" if port else host
        return f"{protocol}://{where}" if protocol else where

    def read(self, place=None):
        places = self.places()
        chosen = self.pick_place(places, place)
        raw_containers = self.call("containers", {"env": chosen.id})
        containers = [read_container(entry)
                      for entry in (raw_containers if isinstance(raw_containers,
                                                                 list) else [])]
        listed = self.call("stacks", {"env": chosen.id})
        stacks = []
        for raw in (listed if isinstance(listed, list) else []):
            name = str(raw.get("name", ""))
            if not name:
                continue
            stacks.append(build_stack(
                name=name,
                containers=containers,
                ref=name,          # Dockhand addresses a stack by its name
                place=chosen.id,
                origin=self._origin(raw),
                # a stack Dockhand knows but Docker does not is one that was
                # written and never started; it has no containers to judge by
                state="" if any(c.stack == name for c in containers)
                      else str(raw.get("status") or "created")))
        return build_inventory(chosen, places, stacks, containers)

    def _origin(self, raw):
        kind = SOURCE_KIND.get(str(raw.get("sourceType") or ""), None)
        if kind is None:
            # Dockhand only fills sourceType for stacks it has a record of;
            # one it merely sees running is one it did not make.
            return Origin(kind=FOUND)
        if kind != GIT:
            return Origin(kind=kind)
        repository = raw.get("repository")
        if not isinstance(repository, dict):
            repository = {}
        return Origin(kind=GIT,
                      repository=str(repository.get("url", "")),
                      reference=str(repository.get("branch", "")
                                    or repository.get("reference", "")),
                      compose_file=str(repository.get("composePath", "")
                                       or raw.get("composePath", "")),
                      authenticated=bool(repository.get("credentialId")))
