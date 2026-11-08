import io
import os
import tempfile
import unittest
import zipfile

from fake_github import Fake, make_zip
from pforte import update
from pforte.net import ApiError, PforteError

APP = "VERSION = 'x'\nprint('app')\n"


def release_files(version="9.9.9", extra=None, drop=()):
    files = {
        "opnsense_haproxy.py": f'VERSION = "{version}"\n',
        "haproxy_gui.py": APP,
        "pforte/__init__.py": f'VERSION = "{version}"\n',
        "pforte/web/app.js": f"// {version}\n",
        "pforte/web/style.css": "body{}\n",
        "pforte/_web.py": "FILES = {}\n",
        "README.md": "# x\n",
        "icon.png": "png",
        "config.json": '{"von": "GitHub"}',          # darf nie ankommen
        "tests/test_x.py": "raise SystemExit(1)\n",   # darf nie ankommen
        ".gitignore": "x\n",
    }
    files.update(extra or {})
    for name in drop:
        files.pop(name, None)
    return files


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = Fake().start()
        self.saved = update.API
        update.API = self.fake.url
        self.dir = tempfile.TemporaryDirectory()
        self.folder = self.dir.name

    def tearDown(self):
        update.API = self.saved
        self.fake.stop()
        self.dir.cleanup()

    def publish(self, tag, **kw):
        self.fake.releases.insert(0, {"tag": tag, "notes": kw.pop("notes", ""),
                                      "zip": make_zip(release_files(tag.lstrip("v"), **kw))})

    def read(self, name):
        with open(os.path.join(self.folder, name)) as handle:
            return handle.read()

    def put(self, name, text="alt"):
        path = os.path.join(self.folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)


class Rules(unittest.TestCase):
    def test_what_belongs_to_the_program(self):
        ok = ("haproxy_gui.py", "pforte/web/app.js", "pforte/web/style.css",
              "pforte/web/logo.svg", "pforte/web/index.html", "icon.png")
        for name in ok:
            self.assertTrue(update.updatable(name), name)
        no = ("config.json", "gui.json", "channel.json", "tests/test_x.py",
              "../x.py", "/etc/x.py", "a/../b.py", ".hidden.py", "C:/x.py",
              "a\\..\\b.py", "x.exe", "pforte/__pycache__/x.py", "a/b/c/d/e.py", "")
        for name in no:
            self.assertFalse(update.updatable(name), name)

    def test_versions(self):
        p = update.parse_version
        self.assertGreater(p("4.0.0"), p("3.0.0-beta.1"))
        self.assertGreater(p("v4.0.1"), p("4.0.0"))
        self.assertGreater(p("3.0.0-beta.1"), p("3.0.0-beta"))
        self.assertEqual(p("v1.2"), (1, 2, 0, 0))
        self.assertEqual(p("nichts"), (0, 0, 0, 0))


class Checking(Base):
    def test_newer_release_is_offered(self):
        self.publish("v5.0.0", notes="Neuigkeiten")
        found = update.check("4.0.0")
        self.assertEqual((found["version"], found["notes"]), ("5.0.0", "Neuigkeiten"))

    def test_same_or_older_is_not(self):
        self.publish("v4.0.0")
        self.assertIsNone(update.check("4.0.0"))
        self.assertIsNone(update.check("4.1.0"))

    def test_repair_offers_the_current_version(self):
        self.publish("v4.0.0")
        found = update.check("4.0.0", repair=True)
        self.assertTrue(found["repair"])

    def test_tags_are_the_fallback_for_missing_releases(self):
        self.fake.tags_only = True
        self.publish("v2.0.0")
        self.publish("v10.0.0")
        self.publish("v3.0.0")
        self.assertEqual(update.check("1.0.0")["version"], "10.0.0")

    def test_nothing_published(self):
        self.fake.tags_only = True
        with self.assertRaises(ApiError):
            update.check("1.0.0")

    def test_rate_limit_is_explained(self):
        self.fake.rate_limited = True
        with self.assertRaises(ApiError) as caught:
            update.check("1.0.0")
        self.assertIn("bremst", str(caught.exception))

    def test_unreachable(self):
        update.API = "http://127.0.0.1:9"
        with self.assertRaises(ApiError):
            update.check("1.0.0")


class Installing(Base):
    def run_install(self, tag="v9.9.9", **kw):
        self.publish(tag, **kw)
        release = update.check("1.0.0")
        steps = []
        result = update.install(release, self.folder, say=steps.append)
        return result, steps

    def test_installs_every_kind_of_file_including_the_web_ones(self):
        result, steps = self.run_install()
        for name in ("haproxy_gui.py", "opnsense_haproxy.py", "pforte/__init__.py",
                     "pforte/web/app.js", "pforte/web/style.css", "pforte/_web.py", "icon.png"):
            self.assertTrue(os.path.isfile(os.path.join(self.folder, name)), name)
        self.assertIn("Lade die neue Version", steps)
        self.assertEqual(result["version"], "9.9.9")

    def test_user_files_and_foreign_files_are_untouched(self):
        self.put("config.json", "MEINE ZUGANGSDATEN")
        self.put("gui.json", "MEINE FENSTER")
        self.put("notizen.txt", "meine notizen")
        self.run_install()
        self.assertEqual(self.read("config.json"), "MEINE ZUGANGSDATEN")
        self.assertEqual(self.read("gui.json"), "MEINE FENSTER")
        self.assertEqual(self.read("notizen.txt"), "meine notizen")
        self.assertFalse(os.path.exists(os.path.join(self.folder, "tests")))
        self.assertFalse(os.path.exists(os.path.join(self.folder, ".gitignore")))

    def test_record_is_written_in_the_old_format(self):
        import json
        self.run_install()
        data = json.loads(self.read("channel.json"))
        self.assertEqual(data["installed"]["version"], "9.9.9")
        self.assertIn("pforte/web/app.js", data["installed"]["files"])
        self.assertNotIn("config.json", data["installed"]["files"])

    def test_files_the_new_version_lacks_are_removed_by_record(self):
        import json
        self.put("alt.py", "x")
        self.put("modul/innen.py", "x")
        self.put("fremd.py", "gehört mir")
        self.put("channel.json", json.dumps({"installed": {"files": ["alt.py", "modul/innen.py"]}}))
        result, _ = self.run_install()
        self.assertFalse(os.path.exists(os.path.join(self.folder, "alt.py")))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "modul")))   # leerer Ordner weg
        self.assertEqual(self.read("fremd.py"), "gehört mir")                  # nicht in der Aufzeichnung
        self.assertEqual(sorted(result["removed"]), ["alt.py", "modul/innen.py"])

    def test_without_a_record_only_known_old_files_go(self):
        for name in ("portainer.py", "catalog.py", "adguard_gui.py"):
            self.put(name)
        self.put("fremd.py", "gehört mir")
        self.run_install()
        for name in ("portainer.py", "catalog.py", "adguard_gui.py"):
            self.assertFalse(os.path.exists(os.path.join(self.folder, name)), name)
        self.assertEqual(self.read("fremd.py"), "gehört mir")

    def test_backup_keeps_what_was_replaced_and_removed(self):
        self.put("haproxy_gui.py", "ALT")
        self.put("portainer.py", "ALT2")
        self.run_install()
        backup = os.path.join(self.folder, "backup-1.0.0")
        with open(os.path.join(backup, "haproxy_gui.py")) as handle:
            self.assertEqual(handle.read(), "ALT")
        with open(os.path.join(backup, "portainer.py")) as handle:
            self.assertEqual(handle.read(), "ALT2")

    def test_only_the_newest_backups_stay(self):
        for index in range(6):
            path = os.path.join(self.folder, f"backup-0.{index}")
            os.makedirs(path)
            os.utime(path, (1000 + index, 1000 + index))
        self.run_install()
        left = sorted(n for n in os.listdir(self.folder) if n.startswith("backup-"))
        self.assertEqual(len(left), update.KEEP_BACKUPS)
        self.assertNotIn("backup-0.0", left)

    def test_executable_bit_survives(self):
        if os.name == "nt":
            self.skipTest("kein Ausführrecht")
        self.put("haproxy_gui.py", "ALT")
        os.chmod(os.path.join(self.folder, "haproxy_gui.py"), 0o755)
        self.run_install()
        self.assertTrue(os.access(os.path.join(self.folder, "haproxy_gui.py"), os.X_OK))

    def test_incomplete_download_is_refused_before_anything_changes(self):
        self.put("haproxy_gui.py", "ALT")
        self.publish("v9.9.9", drop=("opnsense_haproxy.py",))
        with self.assertRaises(ApiError) as caught:
            update.install(update.check("1.0.0"), self.folder)
        self.assertIn("opnsense_haproxy.py", str(caught.exception))
        self.assertEqual(self.read("haproxy_gui.py"), "ALT")

    def test_broken_python_is_refused(self):
        self.put("haproxy_gui.py", "ALT")
        self.publish("v9.9.9", extra={"pforte/kaputt.py": "def ("})
        with self.assertRaises(ApiError):
            update.install(update.check("1.0.0"), self.folder)
        self.assertEqual(self.read("haproxy_gui.py"), "ALT")
        self.assertFalse(os.path.exists(os.path.join(self.folder, "pforte")))

    def test_hostile_archive_names_never_leave_the_folder(self):
        evil = make_zip(release_files("9.9.9", extra={"../ausbruch.py": "x"}))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name in release_files("9.9.9"):
                archive.writestr(f"root/{name}", "VERSION = '1'\n")
            archive.writestr("root/../../ausbruch.py", "x")
            archive.writestr("/abs/ausbruch.py", "x")
            archive.writestr("root/..\\ausbruch.py", "x")
        files = update.unpack(buffer.getvalue())
        self.assertTrue(all(update.updatable(n) for n in files))
        # „/abs/…“ verliert wie jeder Wurzelordner sein erstes Element und bleibt
        # damit ein Pfad *innerhalb* des Ordners; nichts führt hinaus
        for name in files:
            self.assertFalse(name.startswith(("/", "..")) or ".." in name.split("/"), name)
        self.assertNotIn("ausbruch.py", files)
        self.assertIsNotNone(evil)

    def test_git_folder_is_not_updated(self):
        os.makedirs(os.path.join(self.folder, ".git"))
        self.publish("v9.9.9")
        with self.assertRaises(PforteError) as caught:
            update.install(update.check("1.0.0"), self.folder)
        self.assertIn("Git", str(caught.exception))
        self.assertEqual(update.blocked(self.folder), "git")

    def test_corrupt_archive(self):
        self.fake.releases.insert(0, {"tag": "v9.9.9", "zip": b"das ist kein zip"})
        with self.assertRaises(ApiError):
            update.install(update.check("1.0.0"), self.folder)


if __name__ == "__main__":
    unittest.main()
