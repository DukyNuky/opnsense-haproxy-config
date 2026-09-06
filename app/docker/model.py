"""What a Docker host looks like from here, whoever manages it.

Two things were asked of this layer at once: that it make no difference to the
person using the program whether Portainer or Dockhand is behind it, and that
it stay plain what was made how. The first is the shape of these objects --
one vocabulary, filled in by either adapter. The second is ``Origin``, which
is carried through rather than flattened away, because "this came from a
repository and updates itself" and "this was already running when we first
looked" are not the same thing to anyone deciding what to touch.
"""

from dataclasses import dataclass, field

# How a stack came to be.
GIT = "git"          # cloned from a repository, and follows it
COMPOSE = "compose"  # a compose file handed over once, kept by the manager
FOUND = "found"      # already running when the manager first looked
UNKNOWN = "unknown"

# What Docker puts in front of a published port when it is reachable on every
# address of the host -- as opposed to 127.0.0.1, which stays on the machine.
# The difference decides whether a reverse proxy on another machine can use it.
ANY_ADDRESS = ("0.0.0.0", "::", "")


@dataclass(frozen=True)
class Port:
    """One published port, folded across address families.

    Docker reports a binding once per family, so 8080 on every address arrives
    twice -- as 0.0.0.0 and as ::. That is one port on one host, and counting
    it twice makes a collision check lie.
    """

    host: int
    inside: int = 0
    proto: str = "tcp"
    addresses: tuple = ()
    everywhere: bool = False
    container: str = ""
    service: str = ""

    def __str__(self):
        where = "" if self.everywhere else f" ({', '.join(self.addresses) or '?'})"
        return f"{self.host}->{self.inside}/{self.proto}{where}"


@dataclass
class Container:
    id: str
    name: str
    image: str = ""
    state: str = ""
    status: str = ""
    service: str = ""
    stack: str = ""
    ports: list = field(default_factory=list)

    @property
    def running(self):
        return self.state == "running"


@dataclass
class Origin:
    """Where a stack came from, in as much detail as the manager knows."""

    kind: str = UNKNOWN
    repository: str = ""
    reference: str = ""
    compose_file: str = ""
    authenticated: bool = False
    # "" when it does not update itself, otherwise an interval like "5m" or
    # the word "webhook"
    auto_update: str = ""


@dataclass
class Stack:
    name: str
    # Whatever the manager needs to be handed to find this stack again:
    # Portainer wants its numeric id, Dockhand the name. Nobody outside the
    # adapter reads it -- it is passed back in, not interpreted.
    ref: str = ""
    place: str = ""
    state: str = "unknown"          # running | partial | stopped | created
    origin: Origin = field(default_factory=Origin)
    containers: list = field(default_factory=list)
    ports: list = field(default_factory=list)
    env: list = field(default_factory=list)

    @property
    def running(self):
        return sum(1 for c in self.containers if c.running)


@dataclass
class Place:
    """One Docker host behind a manager. Portainer calls it an environment."""

    id: str
    name: str
    url: str = ""
    reachable: bool = True


@dataclass
class Inventory:
    """Everything one place is running, as one answer."""

    place: Place
    places: list = field(default_factory=list)
    stacks: list = field(default_factory=list)
    # Containers that belong to no stack. Kept, because they hold host ports
    # too, and a port that is taken is worth seeing however it got that way.
    loose: list = field(default_factory=list)

    def ports(self):
        """Every published host port here, for spotting a collision."""
        found = []
        for stack in self.stacks:
            found.extend(stack.ports)
        for container in self.loose:
            found.extend(container.ports)
        return sorted(found, key=lambda port: port.host)

    def stack_named(self, name):
        return next((s for s in self.stacks if s.name == name), None)


ORIGIN_TEXT = {
    GIT: "aus einem Repository",
    COMPOSE: "aus einer Compose-Datei",
    FOUND: "war schon da",
    UNKNOWN: "Herkunft unbekannt",
}


def describe_origin(origin):
    """One line saying how this stack came about, for a window to print."""
    if origin.kind == GIT:
        where = origin.repository
        if origin.reference:
            where += f" ({origin.reference})"
        text = f"aus {where}" if where else ORIGIN_TEXT[GIT]
        if origin.compose_file:
            text += f", {origin.compose_file}"
        if origin.auto_update:
            text += ("; erneuert sich per Webhook"
                     if origin.auto_update == "webhook"
                     else f"; erneuert sich alle {origin.auto_update}")
        return text
    return ORIGIN_TEXT.get(origin.kind, ORIGIN_TEXT[UNKNOWN])
