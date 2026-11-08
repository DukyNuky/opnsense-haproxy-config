"""Kommt Version 4 über die *echten* alten Updater an?

Die alten Installationen werden aus den Git-Tags gebaut (v2.12.0, v3.0.0-beta.1),
ihr eigener Updater holt Version 4 von einem lokalen GitHub-Ersatz, und danach
holt Version 4 mit ihrem eigenen Updater eine 4.0.1. Ohne Git oder ohne die
Tags wird übersprungen.
"""

import http.cookiejar
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.request

from fake_github import Fake, make_zip
from pforte import VERSION

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args, binary=False):
    out = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, check=True).stdout
    return out if binary else out.decode()


def have_tag(tag):
    try:
        git("rev-parse", "--verify", "-q", f"refs/tags/{tag}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def tree_files(version=None, web_note=None):
    """Der Arbeitsstand, wie ihn ein Tag-Archiv enthielte."""
    names = git("ls-files", "-co", "--exclude-standard").splitlines()
    files = {}
    for name in names:
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as handle:
            files[name] = handle.read()
    if version:
        for name in ("pforte/__init__.py", "opnsense_haproxy.py"):
            files[name] = re.sub(rb'VERSION = "[^"]+"', f'VERSION = "{version}"'.encode(), files[name])
        if web_note:
            files["pforte/web/app.js"] += f"\n// {web_note}\n".encode()
    return files


def load_old(folder):
    spec = importlib.util.spec_from_file_location("old_core", os.path.join(folder, "opnsense_haproxy.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["old_core"] = module
    spec.loader.exec_module(module)
    return module


def extract_tag(tag, folder):
    data = git("archive", tag, binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(folder, filter="data")


class Smoke:
    """Das Programm aus einem Ordner starten und seine Seiten holen."""

    def __init__(self, folder):
        self.folder = folder

    def __enter__(self):
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(self.folder, "haproxy_gui.py"), "--no-window"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=self.folder)
        url = None
        for line in self.proc.stdout:
            found = re.search(r"(http://127\.0\.0\.1:\d+/\?t=\S+)", line)
            if found:
                url = found.group(1)
                break
        if not url:
            self.proc.kill()
            raise AssertionError("Das Programm hat keine Adresse genannt")
        self.base = url.split("/?t=")[0]
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.opener.open(url).read()          # setzt das Cookie
        return self

    def get(self, path):
        return self.opener.open(self.base + path).read()

    def __exit__(self, *exc):
        self.proc.kill()
        self.proc.wait()


class Migration(unittest.TestCase):
    def setUp(self):
        try:
            git("rev-parse", "--git-dir")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.skipTest("kein Git")
        self.fake = Fake().start()
        self.dir = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.dir.name, "install")
        os.makedirs(self.folder)

    def tearDown(self):
        self.fake.stop()
        self.dir.cleanup()

    def settings(self):
        for name, text in (("config.json", '{"opnsense": []}'), ("gui.json", '{"x": 1}')):
            with open(os.path.join(self.folder, name), "w") as handle:
                handle.write(text)

    def assert_settings_survived(self):
        with open(os.path.join(self.folder, "config.json")) as handle:
            self.assertEqual(handle.read(), '{"opnsense": []}')
        with open(os.path.join(self.folder, "gui.json")) as handle:
            self.assertEqual(handle.read(), '{"x": 1}')

    def assert_is_version_4(self, tidy=True):
        for name in ("pforte/__init__.py", "pforte/_web.py", "pforte/server.py",
                     "haproxy_gui.py", "opnsense_haproxy.py", "HAProxy-Starter.bat", "pforte/update.py"):
            self.assertTrue(os.path.isfile(os.path.join(self.folder, name)), name)
        gone = ["portainer.py", "portainer_gui.py", "adguard_gui.py", "catalog.py",
                "catalog.json", "config.example.json"]
        if tidy:      # nur mit Aufzeichnung kennt der alte Updater auch den Ordner app/
            gone.append("app")
        for name in gone:
            self.assertFalse(os.path.exists(os.path.join(self.folder, name)), f"{name} liegt noch da")
        # was Version 4 nur für die Entwicklung hat, wird nie ausgeliefert
        self.assertFalse(os.path.exists(os.path.join(self.folder, "tests", "fake_github.py")))

    def assert_runs(self):
        with Smoke(self.folder) as running:
            page = running.get("/").decode()
            self.assertIn("Pforte", page)
            # ohne web/-Ordner kommt die Oberfläche aus dem eingebetteten Modul
            self.assertEqual(running.get("/app.js").decode(), tree_files()["pforte/web/app.js"].decode())
            self.assertIn("version", json.loads(running.get("/api/state")))

    def then_update_itself(self):
        """Der zweite Schritt: Version 4 holt mit eigenem Updater die 4.0.1."""
        self.fake.releases.insert(0, {"tag": "v4.0.1", "notes": "Kleinigkeiten",
                                      "zip": make_zip(tree_files("4.0.1", "neu in 4.0.1"))})
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from pforte import update; update.API = sys.argv[2];"
            "r = update.check(); print('FOUND', r and r['version']);"
            "print('DONE', update.install(r, sys.argv[1])['version'])")
        out = subprocess.run([sys.executable, "-c", code, self.folder, self.fake.url],
                             capture_output=True, text=True, cwd=self.dir.name)
        self.assertIn("FOUND 4.0.1", out.stdout, out.stderr)
        self.assertIn("DONE 4.0.1", out.stdout, out.stderr)
        with open(os.path.join(self.folder, "pforte", "web", "app.js")) as handle:
            self.assertIn("neu in 4.0.1", handle.read())       # .js kommt jetzt als Datei an
        self.assert_settings_survived()
        with Smoke(self.folder) as running:
            self.assertIn("neu in 4.0.1", running.get("/app.js").decode())   # Datei geht vor Einbettung

    # ------------------------------------------------------------------

    def test_from_2_12_stable(self):
        if not have_tag("v2.12.0"):
            self.skipTest("Tag v2.12.0 fehlt")
        extract_tag("v2.12.0", self.folder)
        self.settings()
        old = load_old(self.folder)
        old.GITHUB_API = self.fake.url
        # so schreibt eine 2.x ihre Aufzeichnung
        old.write_channel_state({"channel": "stable", "installed": {
            "channel": "stable", "ref": "", "version": old.VERSION,
            "files": old.program_files(self.folder)}}, self.folder)
        self.fake.releases.insert(0, {"tag": "v4.0.0", "notes": "Version 4",
                                      "zip": make_zip(tree_files())})
        release = old.check_for_update(current=old.VERSION, folder=self.folder)
        self.assertEqual(release["version"], "4.0.0")
        old.install_update(release, self.folder)
        self.assert_is_version_4()
        self.assert_settings_survived()
        self.assert_runs()
        self.then_update_itself()

    def test_from_2_12_without_a_record(self):
        if not have_tag("v2.12.0"):
            self.skipTest("Tag v2.12.0 fehlt")
        extract_tag("v2.12.0", self.folder)      # frisch entpackt, nie aktualisiert
        old = load_old(self.folder)
        old.GITHUB_API = self.fake.url
        self.fake.releases.insert(0, {"tag": "v4.0.0", "zip": make_zip(tree_files())})
        old.install_update(old.check_for_update(current=old.VERSION, folder=self.folder), self.folder)
        self.assert_is_version_4(tidy=False)
        self.assert_runs()

    def test_from_3_beta_on_the_beta_channel(self):
        if not have_tag("v3.0.0-beta.1"):
            self.skipTest("Tag v3.0.0-beta.1 fehlt")
        extract_tag("v3.0.0-beta.1", self.folder)
        self.settings()
        old = load_old(self.folder)
        old.GITHUB_API = self.fake.url
        old.GITHUB_RAW = self.fake.url
        old.set_channel("beta", self.folder)
        state = old.channel_state(self.folder)
        state["installed"].update(version=old.VERSION, files=old.program_files(self.folder))
        old.write_channel_state(state, self.folder)       # so schreibt es der Updater selbst
        files = tree_files()
        self.fake.branch = {"sha": "f" * 40, "zip": make_zip(files),
                            "shim": files["opnsense_haproxy.py"]}
        release = old.check_for_update(current=old.VERSION, folder=self.folder)
        self.assertIsNotNone(release, "die Beta-Schiene sieht das neue Beta nicht")
        self.assertEqual(release["version"], VERSION)   # steht in der Versionszeile der Einstiegsdatei
        old.install_update(release, self.folder)
        self.assert_is_version_4()
        self.assert_settings_survived()
        self.assert_runs()
        self.then_update_itself()


if __name__ == "__main__":
    unittest.main()
