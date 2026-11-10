"""Geführte Einrichtung: Prüfung Punkt für Punkt, Kommandozeile, Installer."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

import mock_services
from pforte import VERSION, cli, config, opnsense
from pforte.net import ApiError
from pforte.server import App

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Base(unittest.TestCase):
    def setUp(self):
        self.mock, self.state = mock_services.start()
        self.url = f"http://127.0.0.1:{self.mock.server_address[1]}"
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "config.json")
        self.app = App(self.path)

    def tearDown(self):
        self.mock.shutdown()
        self.dir.cleanup()

    def report(self, **change):
        settings = {"url": self.url, "key": "k", "secret": "s"} | change
        return self.app.diagnose({"settings": settings})

    def states(self, report):
        return {c["id"]: c["state"] for c in report["checks"]}


class Diagnose(Base):
    def test_everything_ready(self):
        report = self.report()
        self.assertTrue(report["ready"])
        self.assertEqual(set(self.states(report).values()), {"ok"})
        self.assertEqual(report["url"], self.url)

    def test_wrong_key_says_where_to_get_one(self):
        report = self.report(secret="falsch")
        self.assertFalse(report["ready"])
        first = report["checks"][0]
        self.assertEqual((first["id"], first["state"]), ("login", "fail"))
        self.assertTrue(first["steps"])

    def test_missing_acme_is_only_a_warning(self):
        self.state.acme = False
        report = self.report()
        self.assertTrue(report["ready"])
        self.assertEqual(self.states(report)["acme"], "warn")
        acme = next(c for c in report["checks"] if c["id"] == "acme")
        self.assertIn("os-acme-client", " ".join(acme["steps"]))

    def test_no_listener_on_443_explains_how_to_create_one(self):
        for obj in self.state.objects["frontend"].values():
            obj["bind"] = "0.0.0.0:8443"
        report = self.report()
        listener = next(c for c in report["checks"] if c["id"] == "listener")
        self.assertEqual(listener["state"], "warn")
        self.assertIn("Public Services", " ".join(listener["steps"]))
        self.assertEqual(listener["page"], opnsense.PAGE_HAPROXY)

    def test_key_is_required(self):
        with self.assertRaises(Exception):
            self.app.diagnose({"settings": {"url": self.url}})

    def test_probe_accepts_any_answer_and_rejects_silence(self):
        self.assertEqual(self.app.probe({"settings": {"url": self.url}})["url"], self.url)
        with self.assertRaises(ApiError):
            self.app.probe({"settings": {"url": "http://127.0.0.1:9"}})


class CommandLine(Base):
    def run_cli(self, argv, env=None):
        out = io.StringIO()
        previous = os.environ.get("PFORTE_CONFIG")
        os.environ["PFORTE_CONFIG"] = self.path
        try:
            code = cli.main(argv, env=env or {}, out=out)
        finally:
            if previous is None:
                os.environ.pop("PFORTE_CONFIG", None)
            else:
                os.environ["PFORTE_CONFIG"] = previous
        return code, out.getvalue()

    def env(self, **more):
        keyfile = os.path.join(self.dir.name, "apikey.txt")
        with open(keyfile, "w", encoding="utf-8") as handle:
            handle.write("key=k\nsecret=s\n")
        return {"OPNSENSE_URL": self.url, "OPNSENSE_KEYFILE": keyfile} | more

    def test_check_without_config(self):
        code, text = self.run_cli(["--check"])
        self.assertEqual(code, 2)
        self.assertIn("Noch nichts eingerichtet", text)

    def test_configure_then_check(self):
        code, text = self.run_cli(["--configure"], self.env(
            ADGUARD_URL=self.url, ADGUARD_USER="admin", ADGUARD_PASSWORD="pw",
            PORTAINER_URL=self.url, PORTAINER_TOKEN="tok"))
        self.assertEqual(code, 0, text)
        saved = config.load(self.path)["profiles"][0]
        self.assertEqual(saved["opnsense"]["key"], "k")
        self.assertTrue(saved["adguard"]["target"])
        code, text = self.run_cli(["--check"])
        self.assertEqual(code, 0, text)
        self.assertIn("AdGuard Home", text)

    def test_configure_refuses_a_wrong_key(self):
        code, text = self.run_cli(["--configure"], {
            "OPNSENSE_URL": self.url, "OPNSENSE_KEY": "k", "OPNSENSE_SECRET": "x"})
        self.assertEqual(code, 1)
        self.assertIn("1. ", text)                      # die Abhilfe steht dabei
        self.assertEqual(config.load(self.path)["profiles"], [])

    def test_configure_refuses_a_broken_optional_service(self):
        code, _ = self.run_cli(["--configure"], self.env(
            ADGUARD_URL=self.url, ADGUARD_USER="admin", ADGUARD_PASSWORD="falsch"))
        self.assertEqual(code, 1)
        self.assertEqual(config.load(self.path)["profiles"], [])

    def test_check_reports_a_revoked_key(self):
        self.run_cli(["--configure"], self.env())
        data = config.load(self.path)
        data["profiles"][0]["opnsense"]["secret"] = "alt"
        config.save(data, self.path)
        code, text = self.run_cli(["--check"])
        self.assertEqual(code, 1)
        self.assertIn("[FEHLT]", text)

    def test_version(self):
        self.assertEqual(self.run_cli(["--version"]), (0, VERSION + "\n"))


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "braucht bash")
class Installer(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.env = {"HOME": self.home.name, "PATH": os.environ["PATH"]}
        self.target = os.path.join(self.home.name, ".local/share/opnsense-haproxy")

    def tearDown(self):
        self.home.cleanup()

    def install(self, *args):
        return subprocess.run(["bash", os.path.join(HERE, "install.sh"), *args],
                              env=self.env, capture_output=True, text=True)

    def test_install_update_uninstall(self):
        done = self.install()
        self.assertEqual(done.returncode, 0, done.stderr)
        for name in ("haproxy_gui.py", "pforte/server.py", "pforte/web/app.js",
                     "pforte/cli.py", "CLAUDE.md", "icon.png"):
            self.assertTrue(os.path.isfile(os.path.join(self.target, name)), name)
        self.assertFalse(os.path.exists(os.path.join(self.target, "tests")))
        with open(os.path.join(self.target, "channel.json"), encoding="utf-8") as handle:
            record = json.load(handle)["installed"]
        self.assertEqual(record["version"], VERSION)
        self.assertIn("pforte/web/app.js", record["files"])
        starter = os.path.join(self.home.name, ".local/bin/pforte")
        got = subprocess.run([starter, "--version"], env=self.env,
                             capture_output=True, text=True)
        self.assertEqual(got.stdout.strip(), VERSION)
        desktop = os.path.join(self.home.name,
                               ".local/share/applications/opnsense-haproxy.desktop")
        with open(desktop, encoding="utf-8") as handle:
            self.assertIn("StartupWMClass=opnsense-haproxy", handle.read())

        # ein zweiter Lauf räumt weg, was nicht mehr zum Programm gehört
        stale = os.path.join(self.target, "pforte", "alt.py")
        with open(stale, "w", encoding="utf-8") as handle:
            handle.write("")
        record["files"].append("pforte/alt.py")
        with open(os.path.join(self.target, "channel.json"), "w", encoding="utf-8") as handle:
            json.dump({"channel": "stable", "installed": record}, handle)
        self.assertEqual(self.install("--no-menu").returncode, 0)
        self.assertFalse(os.path.exists(stale))

        os.makedirs(os.path.join(self.home.name, ".config/pforte"))
        gone = self.install("--uninstall")
        self.assertEqual(gone.returncode, 0, gone.stderr)
        self.assertFalse(os.path.exists(self.target))
        self.assertFalse(os.path.exists(starter))
        self.assertTrue(os.path.isdir(os.path.join(self.home.name, ".config/pforte")))

    def test_refuses_a_git_checkout(self):
        os.makedirs(os.path.join(self.target, ".git"))
        self.assertNotEqual(self.install().returncode, 0)
        self.assertNotEqual(self.install("--uninstall").returncode, 0)
        self.assertTrue(os.path.isdir(self.target))
