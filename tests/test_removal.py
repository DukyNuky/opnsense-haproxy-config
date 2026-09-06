"""Checks for taking an entry out again -- run them with tests/run.py."""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import opnsense_haproxy as core
from app import overview as ov
from app import removal, wiring
from app.sources import Source, Sources

ok = fail = 0
def check(label, got, want):
    global ok, fail
    if got == want: ok += 1
    else:
        fail += 1
        print(f"  FAIL {label}:\n    got  {got!r}\n    want {want!r}")


def adguard(name, entries, ready=True):
    source = Source(wiring.DNS, name, lambda: entries,
                    settings={"url": f"https://{name}.lan"})
    if ready:
        source.data = entries
        source.read_at = 1.0
    return source


print("-- the prefix a rule was made with is read back off the rule -----")
check("with prefix", core.prefix_of("haus_rule_media_example_com"), "haus_")
check("without", core.prefix_of("rule_media_example_com"), "")
check("not a rule at all", core.prefix_of("be_media.example.com"), "")
check("nothing", core.prefix_of(""), "")
# a name whose prefix itself contains the marker: the first one wins, which
# is the one the front of the name was built with
check("first marker wins", core.prefix_of("a_rule_b_rule_c"), "a_")

print("-- a host chain is addressed the way it was created --------------")
host = ov.Chain(name="media.example.com", where="Zuhause", path="/tv",
                kind="host",
                data={"target": "media.example.com/tv", "prefix": "haus_",
                      "host": "media.example.com", "service": "https"})
opts = removal.options_for(host, dry_run=True)
check("the removal for a host", removal.operation_for(host), core.deprovision)
check("target", opts.target, "media.example.com/tv")
check("prefix carried over", opts.prefix, "haus_")
check("a trial run changes nothing", opts.dry_run, True)
check("and does not stop to ask", opts.yes, True)

print("-- a listener is addressed by its public service -----------------")
listen = ov.Chain(name="jellyfin", where="Zuhause", kind="listener",
                  data={"service": "srv_jellyfin", "host": "tv.example.com"})
check("the other removal", removal.operation_for(listen),
      core.deprovision_listener)
check("by name", removal.options_for(listen).name, "srv_jellyfin")
check("with its dns name", removal.options_for(listen).host, "tv.example.com")

print("-- a chain with nothing written down still says something -------")
bare = ov.Chain(name="alt.example.com", where="Zuhause", path="/x")
check("falls back to the name it shows",
      removal.options_for(bare).target, "alt.example.com/x")

print("-- every AdGuard that answers for the name, not just one --------")
one = adguard("DNS eins", [{"domain": "media.example.com", "answer": "10.0.0.1"},
                           {"domain": "other.example.com", "answer": "10.0.0.1"}])
two = adguard("DNS zwei", [{"domain": "MEDIA.example.com", "answer": "10.0.0.9"}])
cold = adguard("DNS drei", [], ready=False)
sources = [one, two, cold]
check("both are found, case and all",
      [(s.name, a) for s, a in removal.dns_holders(sources, "media.example.com")],
      [("DNS eins", "10.0.0.1"), ("DNS zwei", "10.0.0.9")])
check("a name nobody has", removal.dns_holders(sources, "nope.example.com"), [])
check("no name at all", removal.dns_holders(sources, ""), [])
check("what was never read is named separately",
      removal.unread_dns(sources), ["DNS drei"])
check("the plan says which server", removal.dns_plan(sources, "media.example.com"),
      ["DNS-Eintrag media.example.com → 10.0.0.1 auf DNS eins",
       "DNS-Eintrag media.example.com → 10.0.0.9 auf DNS zwei"])

print("-- removing from DNS tries every server, failure or not ----------")
tried = []
class Fussy:
    def __init__(self, name): self.name = name
    def delete_rewrite(self, domain, answer):
        tried.append((self.name, domain, answer))
        if self.name == "DNS eins":
            raise core.ApiError("AdGuard sagt nein")

kept = wiring.dns_client
try:
    # stand-ins named after the servers, so the failure lands on the first
    wiring.dns_client = lambda entry: Fussy(
        "DNS eins" if "eins" in entry["url"] else "DNS zwei")
    done, failed = removal.remove_dns(sources, "media.example.com")
finally:
    wiring.dns_client = kept
check("the second was tried after the first failed", len(tried), 2)
check("and it worked", done, ["DNS zwei"])
check("the failure is kept with its reason",
      [name for name, _why in failed], ["DNS eins"])
check("with what the server said",
      "sagt nein" in failed[0][1], True)

print("-- the report is read back in German ----------------------------")
check("a rule", removal.german("will delete rule           rule_media"),
      "Regel rule_media")
check("a condition", removal.german("will delete condition      acl_media"),
      "Bedingung acl_media")
check("a pool", removal.german("will delete backend pool   be_media"),
      "Backend-Pool be_media")
check("a server", removal.german("will delete real server    srv_media"),
      "Real Server srv_media")
check("a rewrite",
      removal.german("will delete dns rewrite    media.example.com -> 10.0.0.1"),
      "DNS-Eintrag media.example.com -> 10.0.0.1")
check("what stays", removal.german("keeping        : backend pool 'x' (used)"),
      "bleibt stehen: backend pool 'x' (used)")
check("the header", removal.german("public service : https on 0.0.0.0:443"),
      "Öffentlicher Dienst: https on 0.0.0.0:443")
check("nothing there",
      removal.german("nothing found for media.example.com"),
      "Auf der OPNsense ist dazu nichts (mehr) zu finden: media.example.com")
check("what was done", removal.german("- deleted rule rule_media"),
      "Regel rule_media entfernt")
# a line nobody planned for is shown as it is rather than mangled
check("an unknown line survives", removal.german("something else entirely"),
      "something else entirely")

print("-- the plan is what the firewall said, minus the noise -----------")
log = [{"text": "will delete rule           rule_media", "level": "info"},
       {"text": "will delete real server    srv_media", "level": "info"},
       {"text": "", "level": "info"},
       {"text": "dry run -- nothing was changed", "level": "info"}]
check("two lines, both in German", removal.plan_lines(log),
      ["Regel rule_media", "Real Server srv_media"])
check("an empty log", removal.plan_lines([]), [])

print("-- the firewall to write to is the one it was read from ----------")
shelf = Sources()
shelf.put(Source(wiring.OPNSENSE, "Zuhause", lambda: None))
check("found", removal.firewall_of(shelf, host).name, "Zuhause")
check("gone from the settings",
      removal.firewall_of(shelf, ov.Chain(name="x", where="Weg")), None)

print(f"\n{ok} ok, {fail} fail")
sys.exit(1 if fail else 0)
