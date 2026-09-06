"""Checks for the dependency overview -- run them with tests/run.py.

One arrangement with a deliberate hole at every station, so that each gap is
named at the right link rather than as a general "something is wrong".
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import overview as ov
from app import wiring
from app.docker.model import Container, Inventory, Place, Port, Stack
from app.sources import Source, Sources

ok = fail = 0
def check(label, got, want):
    global ok, fail
    if got == want: ok += 1
    else:
        fail += 1
        print(f"  FAIL {label}:\n    got  {got!r}\n    want {want!r}")


def rule(name, host, backend_name="be", servers=(("192.168.1.40", "8096"),),
         path=""):
    return {"uuid": "r", "name": name, "type": "use_backend", "host": host,
            "path": path, "conditions": [],
            "backend": None if backend_name is None else {
                "name": backend_name, "mode": "http",
                "servers": [{"name": "srv", "address": a, "port": p,
                             "ssl": False} for a, p in servers]}}


def service(name="https_443", rules=(), mode="http", enabled=True, bind="0.0.0.0:443",
            default=None, dns=""):
    return {"uuid": "f", "name": name, "mode": mode, "tls": True,
            "default": default, "managed": True, "dns": dns, "bind": bind,
            "enabled": enabled, "rules": list(rules)}


DOMAINS = [{"domain": "example.com", "wildcard": True,
            "certificate": "wildcard-example",
            "covers": ["*.example.com", "example.com"]}]

FIREWALL = {
    "domains": DOMAINS, "domains_error": "",
    "services": [service(rules=[
        rule("acl_media", "media.example.com"),
        rule("acl_buch", "buch.example.com", servers=(("192.168.1.40", "8000"),)),
        rule("acl_leer", "leer.example.com", backend_name=None),
        rule("acl_fremd", "fremd.anders.de", servers=(("192.168.1.99", "9999"),)),
    ])],
}


def docker_inventory():
    place = Place(id="2", name="lokal")
    jelly = Container(id="a", name="jellyfin", state="running", stack="media",
                      service="web",
                      ports=[Port(host=8096, inside=8096, everywhere=True,
                                  container="jellyfin", service="web")])
    books = Container(id="b", name="buchhalter", state="exited", stack="buch",
                      service="web",
                      ports=[Port(host=8000, inside=8000, everywhere=True,
                                  container="buchhalter", service="web")])
    return Inventory(place=place, places=[place], stacks=[
        Stack(name="media", ref="1", place="2", state="running",
              containers=[jelly], ports=list(jelly.ports)),
        Stack(name="buch", ref="2", place="2", state="stopped",
              containers=[books], ports=list(books.ports)),
    ], loose=[])


def shelf_with(dns=True, docker=True, firewall=True, dns_answer="192.168.1.1"):
    shelf = Sources()
    if firewall:
        s = Source(wiring.OPNSENSE, "Zuhause", lambda: FIREWALL,
                   settings={"haproxy_ip": "192.168.1.1"})
        s.data, s.status, s.read_at = FIREWALL, "ok", 1.0
        shelf.put(s)
    if dns:
        d = Source(wiring.DNS, "DNS eins", lambda: [], settings={})
        d.data = [{"domain": "media.example.com", "answer": dns_answer},
                  {"domain": "leer.example.com", "answer": dns_answer},
                  {"domain": "fremd.anders.de", "answer": dns_answer}]
        d.status, d.read_at = "ok", 1.0
        shelf.put(d)
    if docker:
        k = Source(wiring.DOCKER, "Docker haus", lambda: None,
                   settings={"host_ip": "192.168.1.40"})
        k.data, k.status, k.read_at = docker_inventory(), "ok", 1.0
        shelf.put(k)
    return shelf


print("-- the whole arrangement ----------------------------------------")
picture = ov.build(shelf_with())
check("four chains", [c.name for c in picture.chains],
      ["buch.example.com", "fremd.anders.de", "leer.example.com",
       "media.example.com"])
check("seven stations each", sorted({len(c.stations) for c in picture.chains}), [7])
check("in order", [s.key for s in picture.chains[0].stations],
      ["certificate", "dns", "frontend", "rule", "backend", "server", "container"])

print("-- the one that is completely fine ------------------------------")
good = next(c for c in picture.chains if c.name == "media.example.com")
check("all through", good.state, ov.OK)
check("no gaps", good.gaps, [])
check("certificate named", good.station("certificate").detail,
      "wildcard-example gilt für media.example.com")
check("container found", good.station("container").detail, "jellyfin")

print("-- a missing DNS entry is named at the DNS station ---------------")
books = next(c for c in picture.chains if c.name == "buch.example.com")
check("chain is broken", books.state, ov.MISSING)
check("at DNS", [s.key for s in books.gaps if s.state == ov.MISSING], ["dns"])
check("says what", books.station("dns").detail,
      "Keine Umschreibung für buch.example.com")
check("and what it costs", "nicht zu erreichen" in books.station("dns").hint, True)
check("the way in", books.station("dns").tab, "adguard")

print("-- a container that is not running is a warning, not a hole -----")
check("container warned", books.station("container").state, ov.WARN)
check("named anyway", "buchhalter" in books.station("container").detail, True)

print("-- a rule pointing at no pool -----------------------------------")
empty = next(c for c in picture.chains if c.name == "leer.example.com")
check("pool missing", empty.station("backend").state, ov.MISSING)
check("server too", empty.station("server").state, ov.MISSING)
check("but DNS is fine", empty.station("dns").state, ov.OK)
check("and the certificate", empty.station("certificate").state, ov.OK)

print("-- a name no certificate covers ---------------------------------")
foreign = next(c for c in picture.chains if c.name == "fremd.anders.de")
check("certificate warns", foreign.station("certificate").state, ov.WARN)
check("says which exist", "example.com" in foreign.station("certificate").hint, True)
check("nothing listening", foreign.station("container").state, ov.UNKNOWN)
check("names the address", "192.168.1.99:9999" in foreign.station("container").detail,
      True)

print("-- DNS pointing somewhere other than HAProxy --------------------")
astray = ov.build(shelf_with(dns_answer="192.168.1.250"))
one = next(c for c in astray.chains if c.name == "media.example.com")
check("warned", one.station("dns").state, ov.WARN)
check("says where HAProxy is", "192.168.1.1" in one.station("dns").hint, True)

print("-- two DNS servers disagreeing ----------------------------------")
shelf = shelf_with()
second = Source(wiring.DNS, "DNS zwei", lambda: [], settings={})
second.data = [{"domain": "media.example.com", "answer": "192.168.1.250"}]
second.status, second.read_at = "ok", 1.0
shelf.put(second)
split = ov.build(shelf)
check("noticed", next(c for c in split.chains
                      if c.name == "media.example.com").station("dns").state, ov.WARN)

print("-- nothing configured is not the same as broken -----------------")
bare = ov.build(shelf_with(dns=False, docker=False))
one = next(c for c in bare.chains if c.name == "media.example.com")
check("DNS skipped", one.station("dns").state, ov.SKIPPED)
check("container skipped", one.station("container").state, ov.SKIPPED)
check("so the chain is not broken", one.state, ov.OK)

print("-- a system that was never read ---------------------------------")
shelf = shelf_with()
shelf.get(wiring.DOCKER, "Docker haus").data = None
shelf.get(wiring.DOCKER, "Docker haus").status = "idle"
unread = ov.build(shelf)
check("card unknown", next(c for c in unread.cards if c.kind == wiring.DOCKER).state,
      ov.UNKNOWN)
check("and says so", "noch nicht gelesen" in
      " ".join(next(c for c in unread.cards if c.kind == wiring.DOCKER).lines), True)

print("-- an unreachable firewall means no chains, not wrong ones ------")
shelf = shelf_with()
shelf.get(wiring.OPNSENSE, "Zuhause").data = None
shelf.get(wiring.OPNSENSE, "Zuhause").status = "failed"
down = ov.build(shelf)
check("no chains invented", down.chains, [])
check("card warns", next(c for c in down.cards if c.kind == wiring.OPNSENSE).state,
      ov.WARN)

print("-- a firewall without the ACME plugin ---------------------------")
shelf = shelf_with()
src = shelf.get(wiring.OPNSENSE, "Zuhause")
src.data = dict(FIREWALL, domains=[], domains_error="cannot read ACME certificates")
noacme = ov.build(shelf)
one = next(c for c in noacme.chains if c.name == "media.example.com")
check("cannot tell", one.station("certificate").state, ov.UNKNOWN)
# "cannot tell" is not "fine": the chain says unknown rather than ok, because
# claiming a certificate covers the name when nobody could look would be
# exactly the kind of confident wrong answer this overview exists to replace
check("chain says unknown", one.state, ov.UNKNOWN)
check("but nothing is called missing",
      [st.key for st in one.stations if st.state == ov.MISSING], [])

print("-- a listener with a port of its own ----------------------------")
shelf = shelf_with()
shelf.get(wiring.OPNSENSE, "Zuhause").data = {
    "domains": DOMAINS, "domains_error": "",
    "services": [service(name="turn_tls", mode="tcp", bind="0.0.0.0:5349",
                         dns="turn.example.com",
                         default={"name": "be_turn", "mode": "tcp",
                                  "servers": [{"name": "s", "address": "192.168.1.50",
                                               "port": "5349", "ssl": False}]})]}
listen = ov.build(shelf)
check("one chain", [c.name for c in listen.chains], ["turn.example.com"])
chain = listen.chains[0]
check("it is a listener", chain.kind, "listener")
check("no rule to speak of", chain.station("rule").state, ov.SKIPPED)
check("pool is the default", chain.station("backend").detail, "be_turn")
check("DNS still checked", chain.station("dns").state, ov.MISSING)

print("-- a public service that is switched off ------------------------")
shelf = shelf_with()
shelf.get(wiring.OPNSENSE, "Zuhause").data = dict(
    FIREWALL, services=[service(enabled=False,
                                rules=[rule("acl_media", "media.example.com")])])
off = ov.build(shelf)
check("warned", off.chains[0].station("frontend").state, ov.WARN)
check("says the consequence",
      "nichts dahinter" in off.chains[0].station("frontend").hint.lower()
      or "nichts dahinter" in off.chains[0].station("frontend").hint, True)

print("-- the map above ------------------------------------------------")
picture = ov.build(shelf_with())
check("three cards", [c.kind for c in picture.cards],
      [wiring.DNS, wiring.OPNSENSE, wiring.DOCKER])
check("dns counted", picture.cards[0].lines, ["3 Umschreibungen auf 1 Server"])
check("proxy counted", picture.cards[1].lines, ["1 öffentliche Dienste, 4 Regeln"])
check("docker counted", picture.cards[2].lines, ["2 Stacks, 1 Container laufen"])

print("-- what is worth saying out loud --------------------------------")
check("trouble listed", sorted(c.name for c in picture.trouble),
      ["buch.example.com", "fremd.anders.de", "leer.example.com"])
check("notes name the station", any("buch.example.com: DNS-Name" in n
                                    for n in picture.notes), True)


# --------------------------------------------------------------------------
# noting what sits behind an address
# --------------------------------------------------------------------------

import opnsense_haproxy as core

print("-- the note is read out of the server description ---------------")
for text, want in (("managed: media.example.com", ""),
                   ("managed: x behind=vm", "vm"),
                   ("eigene Notiz behind=docker", "docker"),
                   ("behind=quatsch", ""),      # not one of ours
                   ("BEHIND=VM", "vm"),
                   ("", "")):
    check(f"behind_of {text!r}", core.behind_of(text), want)

print("-- setting it keeps whatever else the description says ----------")
check("added", core.with_behind("managed: media", "vm"), "managed: media behind=vm")
check("replaced", core.with_behind("managed: media behind=vm", "geraet"),
      "managed: media behind=geraet")
check("cleared", core.with_behind("managed: media behind=vm", ""), "managed: media")
check("own words kept", core.with_behind("meine Notiz", "extern"),
      "meine Notiz behind=extern")
check("nothing there", core.with_behind("", "vm"), "behind=vm")
try:
    core.with_behind("x", "quatsch")
    check("refuses nonsense", False, True)
except core.UsageError as exc:
    check("refuses nonsense", "quatsch" in str(exc), True)

print("-- a VM behind the address makes the chain complete -------------")
def with_note(note):
    services = [service(rules=[rule("acl_vm", "vm.example.com",
                                    servers=(("192.168.1.60", "8006"),))])]
    for s in services:
        for r in s["rules"]:
            for srv in r["backend"]["servers"]:
                srv["uuid"] = "srv-1"
                srv["behind"] = note
    shelf = shelf_with()
    shelf.get(wiring.OPNSENSE, "Zuhause").data = dict(FIREWALL, services=services)
    d = shelf.get(wiring.DNS, "DNS eins")
    d.data = [{"domain": "vm.example.com", "answer": "192.168.1.1"}]
    return ov.build(shelf).chains[0]

unmarked = with_note("")
check("unknown without a note", unmarked.station("container").state, ov.UNKNOWN)
check("chain not complete", unmarked.state, ov.UNKNOWN)
check("offers to note it", unmarked.station("container").fix, "behind")
check("with a label", unmarked.station("container").fix_label,
      "Vermerken, was dort läuft")
check("and hands over the server", 
      [s["uuid"] for s in unmarked.station("container").data["servers"]], ["srv-1"])

noted = with_note("vm")
check("green once noted", noted.station("container").state, ov.OK)
check("says why", noted.station("container").detail,
      "eigene VM — vermerkt, es wird kein Container erwartet")
check("whole chain complete", noted.state, ov.OK)
check("still changeable", noted.station("container").fix_label, "Vermerk ändern")

print("-- a device or something external counts the same ---------------")
for kind in ("geraet", "extern"):
    check(f"{kind} is complete", with_note(kind).state, ov.OK)

print("-- noted as a container, but none is there ----------------------")
claimed = with_note("docker")
check("that is a real gap", claimed.station("container").state, ov.WARN)
check("says both halves", "Als Docker-Container vermerkt" in
      claimed.station("container").detail, True)

print("-- the station is called what it now answers --------------------")
check("title", noted.station("container").title, "Dahinter")

print("-- the missing DNS entry carries what to write ------------------")
books = next(c for c in ov.build(shelf_with()).chains
             if c.name == "buch.example.com")
check("fix named", books.station("dns").fix, "dns")
check("with the name", books.station("dns").data["host"], "buch.example.com")
check("and where it points", books.station("dns").data["answer"], "192.168.1.1")
check("button says what it does", books.station("dns").fix_label,
      "Eintrag anlegen")

astray = ov.build(shelf_with(dns_answer="192.168.1.250"))
one = next(c for c in astray.chains if c.name == "media.example.com")
check("a wrong entry is changed, not added", one.station("dns").fix_label,
      "Eintrag ändern")



# --------------------------------------------------------------------------
# unknown is not the same as complete, and not the same as missing
# --------------------------------------------------------------------------

print("-- a chain with an open question is not 'alles vorhanden' -------")
ok4 = fail4 = 0
def check4(label, got, want):
    global ok4, fail4
    if got == want: ok4 += 1
    else:
        fail4 += 1
        print(f"  FAIL {label}: got {got!r}, want {want!r}")

unclear_chain = with_note("")          # nothing noted, no container found
check4("mark is a question", unclear_chain.state, ov.UNKNOWN)
check4("no gaps", unclear_chain.gaps, [])
check4("but something unclear", [s.key for s in unclear_chain.unclear],
       ["container"])
check4("so the row has something to say",
       bool(unclear_chain.gaps + unclear_chain.unclear), True)

complete = with_note("vm")
check4("a settled chain has neither", complete.gaps + complete.unclear, [])

print("-- no Docker host answered: say that, not 'no container' --------")
shelf = shelf_with()
broken = shelf.get(wiring.DOCKER, "Docker haus")
broken.data, broken.status, broken.error = None, "failed", "connection refused"
blind = ov.build(shelf)
one = next(c for c in blind.chains if c.name == "media.example.com")
station = one.station("container")
check4("unknown", station.state, ov.UNKNOWN)
check4("says why", station.detail, "Kein Docker-Host hat geantwortet")
check4("does not claim the port is free",
       "veröffentlicht" in station.detail, False)
check4("still offers the note", station.fix, "behind")

print("-- a noted VM stays green even with Docker unreachable ----------")
services = [service(rules=[rule("acl_vm", "vm.example.com",
                                servers=(("192.168.1.60", "8006"),))])]
for srv in services[0]["rules"][0]["backend"]["servers"]:
    srv["uuid"], srv["behind"] = "srv-1", "vm"
shelf = shelf_with()
shelf.get(wiring.OPNSENSE, "Zuhause").data = dict(FIREWALL, services=services)
d = shelf.get(wiring.DOCKER, "Docker haus")
d.data, d.status = None, "failed"
noted_blind = ov.build(shelf).chains[0]
check4("the note settles it", noted_blind.station("container").state, ov.OK)

print("-- with a Docker host that did answer, the old wording stands ---")
present = ov.build(shelf_with())
gone = next(c for c in present.chains if c.name == "fremd.anders.de")
check4("names the address", "192.168.1.99:9999" in
       gone.station("container").detail, True)

print(f"\n{ok + ok4} ok, {fail + fail4} fail  (alles)")
sys.exit(1 if (fail or fail4) else 0)
