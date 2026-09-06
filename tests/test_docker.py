"""Checks for the Docker layer -- run them with tests/run.py.

The point of the layer is that Portainer and Dockhand come out the same. So
the same situation is fed to both in their own wire format, and the two
answers are compared to each other.
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.docker as dk
from app.docker.engine import read_container, read_ports, stack_state
from app.docker.model import COMPOSE, FOUND, GIT, describe_origin

ok = fail = 0
def check(label, got, want):
    global ok, fail
    if got == want: ok += 1
    else:
        fail += 1
        print(f"  FAIL {label}:\n    got  {got!r}\n    want {want!r}")

# --------------------------------------------------------------------------
# the same two stacks, on both managers
# --------------------------------------------------------------------------
#
# jellyfin: two containers, one port on every address, from a git repository
# paperless: one container, a port on 127.0.0.1 only, from a compose file
# watchtower: a loose container nobody's stack claims

LABELS = lambda project, service: {"com.docker.compose.project": project,
                                   "com.docker.compose.service": service}

PORTAINER_CONTAINERS = [
    {"Id": "aaaaaaaaaaaabbbb", "Names": ["/jellyfin"], "Image": "jellyfin:10",
     "State": "running", "Status": "Up 2 days", "Labels": LABELS("jellyfin", "web"),
     "Ports": [{"IP": "0.0.0.0", "PrivatePort": 8096, "PublicPort": 8096, "Type": "tcp"},
               {"IP": "::", "PrivatePort": 8096, "PublicPort": 8096, "Type": "tcp"}]},
    {"Id": "ccccccccccccdddd", "Names": ["/jellyfin-redis"], "Image": "redis:7",
     "State": "running", "Status": "Up 2 days", "Labels": LABELS("jellyfin", "cache"),
     "Ports": []},
    {"Id": "eeeeeeeeeeeeffff", "Names": ["/paperless"], "Image": "paperless:2",
     "State": "exited", "Status": "Exited (0)", "Labels": LABELS("paperless", "web"),
     "Ports": [{"IP": "127.0.0.1", "PrivatePort": 8000, "PublicPort": 8010, "Type": "tcp"}]},
    {"Id": "1111111111112222", "Names": ["/watchtower"], "Image": "watchtower",
     "State": "running", "Status": "Up 9 days", "Labels": {}, "Ports": []},
]
PORTAINER_STACKS = [
    {"Id": 7, "Name": "jellyfin", "EndpointId": 2, "Type": 2, "Env": [],
     "GitConfig": {"URL": "https://github.com/x/media", "ReferenceName": "refs/heads/main",
                   "ConfigFilePath": "docker-compose.yml"},
     "AutoUpdate": {"Interval": "5m", "ForcePullImage": True}},
    {"Id": 8, "Name": "paperless", "EndpointId": 2, "Type": 2,
     "Env": [{"name": "TZ", "value": "Europe/Berlin"}]},
    {"Id": 9, "Name": "woanders", "EndpointId": 5, "Type": 2},   # other place
]

DOCKHAND_CONTAINERS = [
    {"id": "aaaaaaaaaaaabbbb", "name": "jellyfin", "image": "jellyfin:10",
     "state": "running", "status": "Up 2 days", "labels": LABELS("jellyfin", "web"),
     "ports": [{"IP": "0.0.0.0", "PrivatePort": 8096, "PublicPort": 8096, "Type": "tcp"},
               {"IP": "::", "PrivatePort": 8096, "PublicPort": 8096, "Type": "tcp"}]},
    {"id": "ccccccccccccdddd", "name": "jellyfin-redis", "image": "redis:7",
     "state": "running", "status": "Up 2 days", "labels": LABELS("jellyfin", "cache"),
     "ports": []},
    {"id": "eeeeeeeeeeeeffff", "name": "paperless", "image": "paperless:2",
     "state": "exited", "status": "Exited (0)", "labels": LABELS("paperless", "web"),
     "ports": [{"IP": "127.0.0.1", "PrivatePort": 8000, "PublicPort": 8010, "Type": "tcp"}]},
    {"id": "1111111111112222", "name": "watchtower", "image": "watchtower",
     "state": "running", "status": "Up 9 days", "labels": {}, "ports": []},
]
DOCKHAND_STACKS = [
    {"name": "jellyfin", "sourceType": "git", "status": "running",
     "repository": {"url": "https://github.com/x/media", "branch": "main",
                    "composePath": "docker-compose.yml"}},
    {"name": "paperless", "sourceType": "internal", "status": "stopped"},
]


def portainer():
    engine = dk.engine_for("haus", {"url": "https://p.example:9443",
                                    "api_key": "ptr_x"})
    engine.client.endpoints = lambda: [
        {"Id": 2, "Name": "lokal", "URL": "unix:///var/run/docker.sock", "Status": 1},
        {"Id": 5, "Name": "nas", "URL": "tcp://nas:2375", "Status": 2}]
    engine.client.containers = lambda place: PORTAINER_CONTAINERS
    engine.client.stacks = lambda: PORTAINER_STACKS
    return engine


def dockhand():
    engine = dk.engine_for("haus", {"url": "https://dh.example",
                                    "manager": "dockhand", "api_key": "dh_x"})
    def call(path, query=None, payload=None, method=None, timeout=30):
        if path == "environments":
            return [{"id": 2, "name": "lokal", "connectionType": "socket"},
                    {"id": 5, "name": "nas", "host": "nas", "port": 2375,
                     "protocol": "tcp", "connectionType": "tcp"}]
        if path == "containers":
            return DOCKHAND_CONTAINERS
        if path == "stacks":
            return DOCKHAND_STACKS
        raise AssertionError(f"unexpected call {path}")
    engine.call = call
    return engine


print("-- ports fold across address families ---------------------------")
ports = read_ports(PORTAINER_CONTAINERS[0]["Ports"])
check("one entry", len(ports), 1)
check("reachable from outside", ports[0].everywhere, True)
check("both families kept", ports[0].addresses, ("0.0.0.0", "::"))
local = read_ports(PORTAINER_CONTAINERS[2]["Ports"])
check("localhost only", local[0].everywhere, False)

print("-- a container reads the same from either manager ---------------")
check("same container", read_container(PORTAINER_CONTAINERS[0]),
      read_container(DOCKHAND_CONTAINERS[0]))
check("no name, no crash", read_container({"Id": "abcdef012345678"}).name,
      "abcdef012345")

print("-- stack states -------------------------------------------------")
cs = [read_container(c) for c in PORTAINER_CONTAINERS]
check("all up", stack_state([c for c in cs if c.stack == "jellyfin"]), "running")
check("none up", stack_state([c for c in cs if c.stack == "paperless"]), "stopped")
check("some up", stack_state([cs[0], cs[2]]), "partial")
check("nothing at all", stack_state([]), "created")

print("-- the two managers give the same answer ------------------------")
p = portainer().read()
h = dockhand().read()

check("same place chosen", (p.place.id, p.place.name), (h.place.id, h.place.name))
check("both know two places", ([x.name for x in p.places], [x.name for x in h.places]),
      (["lokal", "nas"], ["lokal", "nas"]))
check("same stacks", [s.name for s in p.stacks], [s.name for s in h.stacks])
check("stacks are jellyfin, paperless", [s.name for s in p.stacks],
      ["jellyfin", "paperless"])
check("other place's stack left out", "woanders" in [s.name for s in p.stacks], False)
check("same loose containers", [c.name for c in p.loose], [c.name for c in h.loose])
check("watchtower is loose", [c.name for c in p.loose], ["watchtower"])

for a, b in zip(p.stacks, h.stacks):
    check(f"{a.name}: same containers", [c.name for c in a.containers],
          [c.name for c in b.containers])
    check(f"{a.name}: same ports", a.ports, b.ports)
    check(f"{a.name}: same state", a.state, b.state)
    check(f"{a.name}: same origin kind", a.origin.kind, b.origin.kind)

check("same published ports", p.ports(), h.ports())
check("two ports on this host", [str(x) for x in p.ports()],
      ["8010->8000/tcp (127.0.0.1)", "8096->8096/tcp"])

print("-- how it was made stays visible --------------------------------")
pj, hj = p.stack_named("jellyfin"), h.stack_named("jellyfin")
check("portainer: git", pj.origin.kind, GIT)
check("dockhand: git", hj.origin.kind, GIT)
check("same repository", pj.origin.repository, hj.origin.repository)
check("portainer says the auto update", pj.origin.auto_update, "5m")
check("dockhand has none to say", hj.origin.auto_update, "")
check("paperless from a file", p.stack_named("paperless").origin.kind, COMPOSE)
check("dockhand agrees", h.stack_named("paperless").origin.kind, COMPOSE)
check("in words", describe_origin(pj.origin),
      "aus https://github.com/x/media (refs/heads/main), docker-compose.yml; "
      "erneuert sich alle 5m")

print("-- a stack written but never started ----------------------------")
e = dockhand()
e.call = lambda path, query=None, payload=None, method=None, timeout=30: (
    [{"id": 2, "name": "lokal", "connectionType": "socket"}] if path == "environments"
    else [] if path == "containers"
    else [{"name": "neu", "sourceType": "internal", "status": "created"}])
only = e.read()
check("kept", [s.name for s in only.stacks], ["neu"])
check("said to be created", only.stacks[0].state, "created")

print("-- a stack Dockhand only noticed --------------------------------")
check("no sourceType means found", dockhand()._origin({"name": "x"}).kind, FOUND)

print("-- picking a place ----------------------------------------------")
p2 = portainer()
check("by id", p2.read(place="5").place.name, "nas")
check("by name", p2.read(place="nas").place.name, "nas")
check("none given takes the first", p2.read().place.name, "lokal")
try:
    p2.read(place="gibtsnicht")
    check("unknown place refused", False, True)
except LookupError as exc:
    check("unknown place refused", "gibtsnicht" in str(exc), True)
    check("and says what it knows", "lokal" in str(exc) and "nas" in str(exc), True)

print(f"\n{ok} ok, {fail} fail")
sys.exit(1 if fail else 0)
