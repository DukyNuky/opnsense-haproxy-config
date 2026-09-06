"""Checks for the updater -- run them with tests/run.py."""

import sys, os, io, json, zipfile, shutil, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import opnsense_haproxy as core

ok = fail = 0
def check(label, got, want):
    global ok, fail
    if got == want:
        ok += 1
    else:
        fail += 1
        print(f"  FAIL {label}: got {got!r}, want {want!r}")

print("-- updatable ---------------------------------------------------")
for name, want in [
    ("opnsense_haproxy.py", True), ("ui/status.py", True),
    ("ui/parts/card.py", True), ("a/b/c/d.py", True),   # depth 4
    ("a/b/c/d/e.py", False),                            # depth 5
    ("../evil.py", False), ("ui/../../evil.py", False),
    ("/etc/passwd.py", False), ("C:/x.py", False),
    (".hidden.py", False), ("ui/.hidden.py", False),
    ("config.json", False), ("ui/config.json", False),
    ("gui.json", False), ("channel.json", False),
    ("__pycache__/x.py", False), ("x.txt", False), ("", False),
    ("__init__.py", True), ("ui/__init__.py", True), ("_private.py", True),
    ("releases/opnsense-haproxy-1.1.0.zip", False),
]:
    check(name, core.updatable(name), want)

print("-- unpack_release: a restructured archive ----------------------")
blob = io.BytesIO()
with zipfile.ZipFile(blob, "w") as z:
    z.writestr("DukyNuky-repo-abc123/opnsense_haproxy.py", 'VERSION = "3.0.0"\n')
    z.writestr("DukyNuky-repo-abc123/haproxy_gui.py", "x = 1\n")
    z.writestr("DukyNuky-repo-abc123/ui/__init__.py", "")
    z.writestr("DukyNuky-repo-abc123/ui/status.py", "y = 2\n")
    z.writestr("DukyNuky-repo-abc123/ui/parts/card.py", "z = 3\n")
    z.writestr("DukyNuky-repo-abc123/.github/workflows/ci.yml", "no")
    z.writestr("DukyNuky-repo-abc123/../escape.py", "no")
files = core.unpack_release(blob.getvalue())
check("names", sorted(files), ["haproxy_gui.py", "opnsense_haproxy.py",
                               "ui/__init__.py", "ui/parts/card.py", "ui/status.py"])
core.verify_download(files)   # must not raise

print("-- install_update: flat 2.10 folder -> tree --------------------")
d = tempfile.mkdtemp()
for name in core.LEGACY_FILES:
    open(os.path.join(d, name), "w").write("old\n")
open(os.path.join(d, "opnsense_haproxy.py"), "w").write('VERSION = "2.11.0"\n')
open(os.path.join(d, "config.json"), "w").write('{"secret": "keep me"}')
open(os.path.join(d, "meine-notizen.md"), "w").write("nicht anfassen\n")

core._download = lambda url, timeout=60, report=None: blob.getvalue()
res = core.install_update({"zip": "x", "version": "3.0.0", "channel": "stable",
                           "current": "2.11.0"}, folder=d, report=lambda t: None)

here = sorted(os.path.relpath(os.path.join(r, n), d).replace(os.sep, "/")
              for r, _, ns in os.walk(d) for n in ns
              if not os.path.relpath(os.path.join(r, n), d).startswith("backup-"))
check("new tree", here, ["channel.json", "config.json", "haproxy_gui.py",
                         "meine-notizen.md", "opnsense_haproxy.py",
                         "ui/__init__.py", "ui/parts/card.py", "ui/status.py"])
check("config kept", open(os.path.join(d, "config.json")).read(), '{"secret": "keep me"}')
check("user file kept", os.path.exists(os.path.join(d, "meine-notizen.md")), True)
check("removed count", len(res["removed"]), 11)
check("catalog.py gone", os.path.exists(os.path.join(d, "catalog.py")), False)
check("backup has it", os.path.exists(os.path.join(d, "backup-2.11.0", "catalog.py")), True)
check("record", core.channel_state(d)["installed"]["files"],
      ["haproxy_gui.py", "opnsense_haproxy.py", "ui/__init__.py",
       "ui/parts/card.py", "ui/status.py"])

print("-- a second update, now from the record ------------------------")
blob2 = io.BytesIO()
with zipfile.ZipFile(blob2, "w") as z:
    z.writestr("r-def/opnsense_haproxy.py", 'VERSION = "3.1.0"\n')
    z.writestr("r-def/haproxy_gui.py", "x = 2\n")
    z.writestr("r-def/ui/__init__.py", "")
    z.writestr("r-def/ui/status.py", "y = 9\n")     # ui/parts/card.py is gone
core._download = lambda url, timeout=60, report=None: blob2.getvalue()
res2 = core.install_update({"zip": "x", "version": "3.1.0", "channel": "stable",
                            "current": "3.0.0"}, folder=d, report=lambda t: None)
check("removed", res2["removed"], ["ui/parts/card.py"])
check("empty dir pruned", os.path.isdir(os.path.join(d, "ui", "parts")), False)
check("ui kept", os.path.isdir(os.path.join(d, "ui")), True)

print("-- a poisoned channel.json cannot delete anything --------------")
state = core.channel_state(d)
state["installed"]["files"] = ["../../../etc/passwd", "/etc/hosts", "config.json"]
core.write_channel_state(state, d)
check("filtered out", core.channel_state(d)["installed"]["files"], [])

print("-- copy_program walks the tree ---------------------------------")
t = tempfile.mkdtemp()
copied = core.copy_program(d, t, report=lambda _t: None)
# a stray file in the source comes along, as it always has -- it was put into
# the target by us, so the record may later take it back out again
check("copied", sorted(copied), ["haproxy_gui.py", "meine-notizen.md",
                                 "opnsense_haproxy.py", "ui/__init__.py",
                                 "ui/status.py"])
check("subdir there", os.path.exists(os.path.join(t, "ui", "status.py")), True)

shutil.rmtree(d); shutil.rmtree(t)
print(f"\n{ok} ok, {fail} fail")
sys.exit(1 if fail else 0)
