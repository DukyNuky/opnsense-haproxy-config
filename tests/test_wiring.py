"""Checks for settings -> askable sources -- run them with tests/run.py."""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import opnsense_haproxy as core
from app import wiring
from app.sources import Sources, FAILED

ok = fail = 0
def check(label, got, want):
    global ok, fail
    if got == want: ok += 1
    else:
        fail += 1
        print(f"  FAIL {label}:\n    got  {got!r}\n    want {want!r}")

SYSTEMS = {
    "opnsense": [{"name": "Zuhause", "url": "https://fw.lan", "key": "k",
                  "secret": "s"}],
    "adguard": [{"name": "DNS eins", "url": "https://dns1.lan", "username": "a",
                 "password": "b"},
                {"name": "DNS zwei", "url": "https://dns2.lan"}],
    # the file still calls them portainer entries
    "portainer": [{"name": "Docker haus", "url": "https://p.lan:9443",
                   "api_key": "ptr_x"},
                  {"name": "Docker nas", "url": "https://dh.lan",
                   "manager": "dockhand", "api_key": "dh_x"}],
    "git": [{"name": "GitHub", "url": "https://github.com"}],
}

print("-- entries are found under the key the file uses -----------------")
check("opnsense", [e["name"] for e in wiring.entries_of(SYSTEMS, wiring.OPNSENSE)],
      ["Zuhause"])
check("dns", [e["name"] for e in wiring.entries_of(SYSTEMS, wiring.DNS)],
      ["DNS eins", "DNS zwei"])
check("docker reads the portainer key",
      [e["name"] for e in wiring.entries_of(SYSTEMS, wiring.DOCKER)],
      ["Docker haus", "Docker nas"])

print("-- which manager an entry names ---------------------------------")
check("nothing said means portainer", wiring.manager_of({}), "portainer")
check("said", wiring.manager_of({"manager": "dockhand"}), "dockhand")
check("nonsense falls back", wiring.manager_of({"manager": "dockge"}), "portainer")

print("-- clients are built from the entry -----------------------------")
client = wiring.opnsense_client(SYSTEMS["opnsense"][0])
check("opnsense client", isinstance(client, core.Client), True)
check("dns client", isinstance(wiring.dns_client(SYSTEMS["adguard"][0]),
                               core.AdGuard), True)
engine = wiring.docker_engine("Docker nas", SYSTEMS["portainer"][1])
check("dockhand chosen", engine.kind, "dockhand")
check("portainer chosen",
      wiring.docker_engine("Docker haus", SYSTEMS["portainer"][0]).kind, "portainer")

print("-- an entry that is not usable says what is missing --------------")
for entry, missing in (({"name": "x"}, "url"),
                       ({"name": "x", "url": "u", "key": "k"}, "secret")):
    try:
        wiring.opnsense_client(entry)
        check(f"refused {missing}", False, True)
    except wiring.NotConfigured as exc:
        check(f"names {missing}", missing in str(exc), True)

print("-- and it stays on the shelf as a failing source -----------------")
shelf = wiring.wire(Sources(), {"opnsense": [{"name": "Halbfertig"}]})
shelf.refresh(block=True)
half = shelf.get(wiring.OPNSENSE, "Halbfertig")
check("still listed", half is not None, True)
check("failed", half.status, FAILED)
check("with a reason", "url" in half.error, True)

print("-- the whole shelf ----------------------------------------------")
shelf = wiring.wire(Sources(), SYSTEMS)
check("three kinds", sorted({s.kind for s in shelf.all()}),
      ["adguard", "docker", "opnsense"])
check("git is not a source", shelf.get("git", "GitHub"), None)
check("names", [s.name for s in shelf.of_kind(wiring.DOCKER)],
      ["Docker haus", "Docker nas"])
check("label carries the address", shelf.get(wiring.DNS, "DNS eins").label,
      "DNS eins · https://dns1.lan")

print("-- a source asks a freshly built client every time ---------------")
built = []
entry = {"name": "Zähler", "url": "https://x", "key": "k", "secret": "s"}
def build():
    built.append(1)
    return "client"
read = wiring._reader(build, lambda c: f"gelesen von {c}")
check("nothing built yet", built, [])
check("first read", read(), "gelesen von client")
check("second read", read(), "gelesen von client")
check("built twice", len(built), 2)

print("-- editing the settings keeps answers and drops what went --------")
shelf = Sources()
wiring.wire(shelf, SYSTEMS)
shelf.get(wiring.DNS, "DNS eins").data = ["alte antwort"]
shelf.get(wiring.DNS, "DNS eins").read_at = 1.0
fewer = dict(SYSTEMS, adguard=[SYSTEMS["adguard"][0]])
wiring.wire(shelf, fewer)
check("removed one is gone", [s.name for s in shelf.of_kind(wiring.DNS)],
      ["DNS eins"])
check("the other kept its answer",
      shelf.get(wiring.DNS, "DNS eins").data, ["alte antwort"])

print("-- a docker source is pointed at the chosen host -----------------")
asked = {}
shelf = Sources()
wiring.wire(shelf, SYSTEMS, places={"Docker haus": "5"})
src = shelf.get(wiring.DOCKER, "Docker haus")
engine = wiring.docker_engine("Docker haus", SYSTEMS["portainer"][0])
engine.read = lambda place=None: asked.setdefault("place", place)
src._read = lambda: engine.read("5")
src.refresh()
check("place handed through", asked["place"], "5")

print("-- each manager is asked for its own environment -----------------")
# the preference is a mapping of manager name -> environment. Handing the
# whole mapping to every manager asked each of them for an environment named
# after a dictionary; each said it had no such thing, and every Docker host
# in the program reported "keine Antwort".
kept = {"Docker haus": "5", "Docker nas": "2"}
check("one environment each", wiring.places_for(SYSTEMS, kept),
      {"Docker haus": "5", "Docker nas": "2"})
check("a manager nobody chose for gets none",
      wiring.places_for({"portainer": [{"name": "Neu", "url": "https://n.lan"}]},
                        kept), {"Neu": ""})
check("no preference yet", wiring.places_for(SYSTEMS, None),
      {"Docker haus": "", "Docker nas": ""})
check("and a preference of the wrong shape is not passed on",
      wiring.places_for(SYSTEMS, "5"), {"Docker haus": "", "Docker nas": ""})
check("named the way the shelf names them",
      sorted(wiring.places_for({"portainer": [{"url": "https://only.lan"}]},
                               {})), ["https://only.lan"])

print("-- nothing configured at all ------------------------------------")
empty = wiring.wire(Sources(), {})
check("empty shelf", len(empty), 0)
check("summary is honest", empty.summary()["total"], 0)

print(f"\n{ok} ok, {fail} fail")
sys.exit(1 if fail else 0)
