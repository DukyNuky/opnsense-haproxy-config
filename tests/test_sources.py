"""Checks for the source shelf -- run them with tests/run.py."""

import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.sources import Source, Sources, describe_age, IDLE, LOADING, OK, FAILED

ok = fail = 0
def check(label, got, want):
    global ok, fail
    if got == want: ok += 1
    else:
        fail += 1
        print(f"  FAIL {label}: got {got!r}, want {want!r}")

print("-- one source --------------------------------------------------")
s = Source("adguard", "haus", lambda: ["a", "b"])
check("starts idle", s.status, IDLE)
check("nothing yet", s.ready, False)
check("no age", s.age(), None)
s.refresh()
check("ok", s.status, OK)
check("data", s.data, ["a", "b"])
check("ready", s.ready, True)
check("reads", s.reads, 1)

print("-- a failure keeps the last good answer -------------------------")
boom = {"n": 0}
def flaky():
    boom["n"] += 1
    if boom["n"] > 1:
        raise ConnectionError("host is off")
    return ["first"]
f = Source("adguard", "keller", flaky)
f.refresh()
check("first ok", f.data, ["first"])
f.refresh()
check("now failed", f.status, FAILED)
check("message", f.error, "host is off")
check("old data kept", f.data, ["first"])
check("still ready", f.ready, True)

print("-- an exception with no message still says something ------------")
class Silent(Exception): pass
q = Source("x", "y", lambda: (_ for _ in ()).throw(Silent()))
q.refresh()
check("class name", q.error, "Silent")

print("-- three slow hosts are asked at once ---------------------------")
def slow(seconds, value):
    def read():
        time.sleep(seconds)
        return value
    return read
shelf = Sources(workers=6)
for n in ("a", "b", "c"):
    shelf.put(Source("adguard", n, slow(0.30, n)))
seen = []
lock = threading.Lock()
def note(src):
    with lock:
        seen.append((src.name, src.status))
started = time.time()
shelf.refresh(kinds=["adguard"], notify=note, block=True)
took = time.time() - started
check("parallel, not serial", took < 0.60, True)
check("all ok", sorted(s.data for s in shelf.of_kind("adguard")), ["a", "b", "c"])
check("loading was announced", sorted(n for n, st in seen if st == LOADING), ["a","b","c"])
check("and the answers", sorted(n for n, st in seen if st == OK), ["a","b","c"])

print("-- one host down does not hold up the others --------------------")
def dies():
    time.sleep(0.05)
    raise TimeoutError("no route to host")
shelf.put(Source("adguard", "b", dies))
shelf.refresh(kinds=["adguard"], block=True)
check("b failed", shelf.get("adguard", "b").status, FAILED)
check("a still fine", shelf.get("adguard", "a").status, OK)
check("summary", shelf.summary(["adguard"]),
      {"total": 3, "loading": 0, "ok": 2, "failed": 1, "idle": 0, "ready": 3})

print("-- pressing refresh twice does not ask twice --------------------")
calls = {"n": 0}
def counted():
    calls["n"] += 1
    time.sleep(0.25)
    return "x"
sh2 = Sources()
sh2.put(Source("k", "one", counted))
sh2.refresh(block=False)
time.sleep(0.05)
second = sh2.refresh(block=False)      # still loading -> taken on nothing
check("skipped", second, None)
time.sleep(0.35)
check("asked once", calls["n"], 1)

print("-- editing settings keeps the answer ----------------------------")
sh3 = Sources()
sh3.put(Source("adguard", "haus", lambda: ["alt"]))
sh3.refresh(block=True)
same = sh3.put(Source("adguard", "haus", lambda: ["neu"]))    # new password, say
check("same object", same is sh3.get("adguard", "haus"), True)
check("answer survives", same.data, ["alt"])
check("not asked twice over", len(sh3), 1)
sh3.refresh(block=True)
check("new reader used", same.data, ["neu"])

print("-- a system that was removed from the settings ------------------")
sh3.put(Source("adguard", "keller", lambda: []))
check("two", len(sh3.of_kind("adguard")), 2)
sh3.keep_only("adguard", ["haus"])
check("one left", [s.name for s in sh3.of_kind("adguard")], ["haus"])

print("-- kinds do not mix ---------------------------------------------")
sh4 = Sources()
sh4.put(Source("adguard", "a", lambda: 1))
sh4.put(Source("docker", "a", lambda: 2))       # same name, other kind
sh4.refresh(kinds=["docker"], block=True)
check("only docker read", sh4.get("adguard", "a").status, IDLE)
check("docker read", sh4.get("docker", "a").data, 2)

print("-- ages in words -------------------------------------------------")
for seconds, want in [(None, "noch nicht gelesen"), (3, "gerade eben"),
                      (44, "gerade eben"), (60, "vor 1 Minute"),
                      (200, "vor 3 Minuten"), (3600, "vor 1 Stunde"),
                      (7200, "vor 2 Stunden"), (90000, "vor 1 Tag"),
                      (200000, "vor 2 Tagen")]:
    check(f"age {seconds}", describe_age(seconds), want)

now = time.time()
sh5 = Sources()
a = sh5.put(Source("k", "a", lambda: 1)); a.read_at = now - 100
b = sh5.put(Source("k", "b", lambda: 1)); b.read_at = now - 900
check("oldest", int(sh5.oldest(["k"], now)), 900)

print("-- a round counts how far it has come ---------------------------")
ok2 = fail2 = 0
def check2(label, got, want):
    global ok2, fail2
    if got == want: ok2 += 1
    else:
        fail2 += 1
        print(f"  FAIL {label}: got {got!r}, want {want!r}")

import threading as _t
gate = _t.Event()
def waits(value):
    def read():
        gate.wait(2.0)
        return value
    return read

shelf = Sources(workers=4)
for name in ("a", "b", "c", "d"):
    shelf.put(Source("adguard", name, waits(name), label=f"{name} · https://{name}"))
here = shelf.refresh(kinds=["adguard"])
check2("a round comes back", here is not None, True)
check2("total", here.total, 4)
check2("none done yet", here.done, 0)
check2("nothing counted", here.fraction, 0.0)
check2("running by label", sorted(here.running),
       ["a · https://a", "b · https://b", "c · https://c", "d · https://d"])
check2("active", here.active, True)
gate.set()
for _ in range(200):
    if not here.active:
        break
    time.sleep(0.01)
check2("all done", here.done, 4)
check2("full", here.fraction, 1.0)
check2("nothing left running", here.running, [])
check2("no longer active", here.active, False)
check2("the shelf keeps it", shelf.round is here, True)

print("-- a round that takes nothing on is no round --------------------")
# a gate of its own: the one above is open by now, and a source that answers
# instantly is not still loading when the second refresh looks
held = _t.Event()
def held_read():
    held.wait(2.0)
    return "x"
busy = Sources()
busy.put(Source("k", "one", held_read))
first = busy.refresh()
check2("first is a round", first is not None, True)
check2("second is none while it runs", busy.refresh(), None)
check2("and did not replace it", busy.round is first, True)
held.set()
for _ in range(200):
    if not first.active:
        break
    time.sleep(0.01)
check2("then it may be asked again", busy.refresh() is not None, True)
held.set()

print("-- an empty shelf ------------------------------------------------")
check2("nothing to do", Sources().refresh(), None)

print(f"\n{ok + ok2} ok, {fail + fail2} fail  (alles)")
sys.exit(1 if (fail or fail2) else 0)
