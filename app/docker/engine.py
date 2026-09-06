"""The part of a Docker host that is the same whoever manages it.

Portainer and Dockhand disagree about stacks -- one addresses them by number
and calls a repository a GitConfig, the other addresses them by name and calls
it a sourceType. They do not disagree about containers: both hand back what
Docker itself reports, labels and all. That is the seam this module sits on.

Everything below reads containers and joins them into stacks by the compose
labels Docker writes. An adapter is then only what is genuinely different:
how to fetch, and what the manager knows about a stack beyond its containers.
"""

from .model import (ANY_ADDRESS, Container, Inventory, Origin, Place, Port,
                    Stack, UNKNOWN)


def read_ports(entries):
    """Fold Docker's port list into one entry per host port.

    Entries without a public port are dropped: they are reachable inside
    Docker only, and nothing outside can be pointed at them. Field names are
    asked for twice throughout -- Portainer passes Docker's own capitals
    through, Dockhand lowercases them.
    """
    found = {}
    for entry in entries or []:
        host = entry.get("PublicPort") or entry.get("publicPort")
        if not host:
            continue
        proto = str(entry.get("Type") or entry.get("type") or "tcp")
        address = str(entry.get("IP") or entry.get("ip") or "")
        inside = int(entry.get("PrivatePort") or entry.get("privatePort") or 0)
        port = found.setdefault((int(host), proto),
                                {"inside": inside, "addresses": [],
                                 "everywhere": False})
        if address not in port["addresses"]:
            port["addresses"].append(address)
        if address in ANY_ADDRESS:
            port["everywhere"] = True
        # the same host port can map inside twice only in a broken setup; the
        # first answer is kept rather than silently averaged into nonsense
        port["inside"] = port["inside"] or inside
    return sorted(
        (Port(host=host, inside=port["inside"], proto=proto,
              addresses=tuple(port["addresses"]), everywhere=port["everywhere"])
         for (host, proto), port in found.items()),
        key=lambda port: (port.host, port.proto))


def read_container(entry):
    """One container out of what Docker reports, whoever passed it on.

    Both managers hand this through nearly untouched; the only real difference
    is capitalisation, which is why every field is asked for twice.
    """
    names = entry.get("Names") or entry.get("names") or []
    name = str(entry.get("name") or (names[0] if names else "")).lstrip("/")
    identifier = str(entry.get("Id") or entry.get("id") or "")
    labels = entry.get("Labels") or entry.get("labels") or {}
    if not name:
        name = identifier[:12]
    return Container(
        id=identifier[:12],
        name=name,
        image=str(entry.get("Image") or entry.get("image") or ""),
        state=str(entry.get("State") or entry.get("state") or ""),
        status=str(entry.get("Status") or entry.get("status") or ""),
        service=str(labels.get("com.docker.compose.service", "")).strip(),
        stack=str(labels.get("com.docker.compose.project", "")).strip(),
        ports=read_ports(entry.get("Ports") or entry.get("ports")),
    )


def stack_state(containers, fallback="created"):
    """running, partial, stopped -- or whatever a manager already said."""
    if not containers:
        return fallback
    running = sum(1 for c in containers if c.running)
    if running == len(containers):
        return "running"
    return "partial" if running else "stopped"


def build_stack(name, containers, ref="", place="", origin=None, env=(),
                state=""):
    """One stack and the containers carrying its compose project label."""
    mine = [c for c in containers if c.stack == name]
    ports = []
    for container in mine:
        for port in container.ports:
            ports.append(Port(host=port.host, inside=port.inside,
                              proto=port.proto, addresses=port.addresses,
                              everywhere=port.everywhere,
                              container=container.name,
                              service=container.service or container.name))
    return Stack(
        name=name,
        ref=ref or name,
        place=place,
        state=state or stack_state(mine),
        origin=origin or Origin(kind=UNKNOWN),
        containers=sorted(mine, key=lambda c: c.name.lower()),
        ports=sorted(ports, key=lambda port: port.host),
        env=list(env),
    )


def build_inventory(place, places, stacks, containers):
    """Stacks first, then what belongs to none of them."""
    named = {stack.name for stack in stacks}
    loose = sorted((c for c in containers if c.stack not in named),
                   key=lambda c: c.name.lower())
    return Inventory(place=place, places=list(places),
                     stacks=sorted(stacks, key=lambda s: s.name.lower()),
                     loose=loose)


class Engine:
    """One Docker manager, as the rest of the program sees it.

    An adapter fills in the three reading methods. Writing -- deploying and
    removing -- is not declared here yet: a method that only raises would
    claim a shape before there is one behind it, and this layer exists to stop
    exactly that kind of pretending.
    """

    #: what this is, for the settings and for saying how a stack was made
    kind = ""
    #: what it is called in the window
    title = ""

    def __init__(self, name, settings):
        self.name = name
        self.settings = dict(settings or {})
        self.url = str(self.settings.get("url", "")).rstrip("/")

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name} {self.url}>"

    def check(self):
        """Reach the manager and say what it is. Raises when it cannot."""
        raise NotImplementedError

    def places(self):
        """The Docker hosts this manager knows about."""
        raise NotImplementedError

    def read(self, place=None):
        """Everything one place is running, as an Inventory."""
        raise NotImplementedError

    # -- shared -----------------------------------------------------------

    def pick_place(self, places, wanted=None):
        """The place asked for, or the only one, or the first.

        A manager with one host is the normal case, and asking which one every
        time would be a question with a single answer.
        """
        if not places:
            raise LookupError(f"{self.title} {self.name} verwaltet keinen "
                              "Docker-Host")
        if wanted in (None, ""):
            return places[0]
        for place in places:
            if str(place.id) == str(wanted) or place.name == wanted:
                return place
        known = ", ".join(f"{p.id}: {p.name}" for p in places)
        raise LookupError(f"{self.title} {self.name} kennt keinen Docker-Host "
                          f"{wanted!r} (bekannt: {known})")
