"""Turning what stands in the settings into things that can be asked.

One place decides how a saved entry becomes a client, so that the window, the
status overview and the command line cannot drift apart about it. Everything
here is free of tkinter and takes the settings as a plain dictionary, which is
what makes it checkable without a display.

An entry that is not usable does not vanish. It becomes a source that fails
with a sentence saying what is missing -- a name in the list with "keine
Adresse hinterlegt" beside it is something to act on, an entry silently left
out is not.
"""

import opnsense_haproxy as core

from . import docker as docker_layer
from .sources import Source

# What the tabs are about, and what a source's kind is.
OPNSENSE = "opnsense"
DNS = "adguard"
DOCKER = "docker"
KINDS = (OPNSENSE, DNS, DOCKER)

# The settings file still calls a Docker host a portainer entry. Renaming the
# key would make a file written in the beta unreadable to the stable version,
# and stepping back out of the beta has to keep working. What the window says
# is "Docker"; what the key is called is between the file and us.
DOCKER_KEY = "portainer"

TITLES = {OPNSENSE: "OPNsense", DNS: "DNS", DOCKER: "Docker"}


class NotConfigured(core.UsageError):
    """The entry is there but cannot be used yet, and says what is missing."""


def _need(entry, *fields):
    missing = [name for name in fields if not str(entry.get(name, "")).strip()]
    if missing:
        raise NotConfigured("es fehlt noch: " + ", ".join(missing))


def opnsense_client(entry):
    _need(entry, "url", "key", "secret")
    return core.Client(entry["url"], entry["key"], entry["secret"],
                       verify=entry.get("verify_ssl", True) is not False)


def dns_client(entry):
    _need(entry, "url")
    return core.AdGuard(entry["url"],
                        username=entry.get("username", ""),
                        password=entry.get("password", ""),
                        verify=entry.get("verify_ssl", True) is not False)


def docker_engine(name, entry):
    _need(entry, "url")
    return docker_layer.engine_for(name, entry)


def read_opnsense(client):
    """What the overview needs from one firewall, in one reading.

    The certificates are a second call into a second plugin. A firewall
    without os-acme-client answers everything else perfectly well, so a
    missing ACME list is written down rather than raised: the overview then
    says "kann ich nicht sagen" at that one station instead of losing the
    whole firewall over it.
    """
    reading = {"services": core.inventory(client), "domains": [],
               "domains_error": ""}
    try:
        reading["domains"] = core.base_domains(client)
    except core.ApiError as exc:
        reading["domains_error"] = str(exc)
    return reading


def entries_of(systems, kind):
    """The saved entries for one kind, under whatever key the file uses."""
    key = DOCKER_KEY if kind == DOCKER else kind
    return [entry for entry in (systems.get(key) or []) if isinstance(entry, dict)]


def _reader(build, ask):
    """A source's read: build the client, then ask it.

    Built on every read rather than once, so that a host which was down when
    the window opened is not stuck behind a client that failed to come up --
    and so that a token corrected in the settings takes effect on the next
    refresh rather than on the next start.
    """
    def read():
        return ask(build())
    return read


def source_for(kind, entry, place=None):
    """One configured system, ready to be asked."""
    name = str(entry.get("name") or entry.get("url") or "?")
    label = f"{name} · {entry.get('url', '')}".rstrip(" ·")
    if kind == OPNSENSE:
        read = _reader(lambda: opnsense_client(entry), read_opnsense)
    elif kind == DNS:
        read = _reader(lambda: dns_client(entry), lambda client: client.rewrites())
    elif kind == DOCKER:
        read = _reader(lambda: docker_engine(name, entry),
                       lambda engine: engine.read(place))
    else:
        raise LookupError(f"{kind!r} ist keine Art von System")
    return Source(kind, name, read, label=label, settings=entry)


def wire(shelf, systems, places=None):
    """Put a source on the shelf for every configured system, and only those.

    Called again whenever the settings were edited. Entries that are still
    there keep the answer they already gave -- see ``Sources.put`` -- and ones
    that were removed are dropped, so a tab never shows a host that is no
    longer configured.
    """
    places = places or {}
    for kind in KINDS:
        entries = entries_of(systems, kind)
        for entry in entries:
            name = str(entry.get("name") or entry.get("url") or "?")
            shelf.put(source_for(kind, entry,
                                 place=places.get(name) if kind == DOCKER
                                 else None))
        shelf.keep_only(kind, [str(e.get("name") or e.get("url") or "?")
                               for e in entries])
    return shelf


def manager_of(entry):
    """Which program manages this Docker host, defaulting to Portainer.

    Every entry written before there was a choice is a Portainer, and saying
    so is better than asking again.
    """
    kind = str((entry or {}).get("manager") or "").lower()
    return kind if kind in docker_layer.KINDS else docker_layer.DEFAULT_KIND
