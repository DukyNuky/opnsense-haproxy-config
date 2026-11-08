import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

import mock_services
from pforte import config
from pforte.net import PforteError
from pforte.server import App, make_server


class Setup(unittest.TestCase):
    def setUp(self):
        self.mock, self.state = mock_services.start()
        self.url = f"http://127.0.0.1:{self.mock.server_address[1]}"
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "config.json")
        self.app = App(self.path)

    def tearDown(self):
        self.mock.shutdown()
        self.dir.cleanup()

    def full(self, **extra):
        body = {"opnsense": {"url": self.url, "key": "k", "secret": "s", "verify": False},
                "adguard": {"url": self.url, "username": "admin", "password": "pw",
                            "target": "192.168.0.1", "verify": False},
                "portainer": {"url": self.url, "api_key": "tok", "verify": False}}
        body.update(extra)
        return body

    def wait(self, job):
        for _ in range(100):
            state = self.app.jobs.get(job)
            if state["done"]:
                return state
            time.sleep(0.05)
        self.fail("Auftrag wurde nicht fertig")


class Wizard(Setup):
    def test_each_service_is_tested(self):
        for kind, section in (("opnsense", self.full()["opnsense"]),
                              ("adguard", self.full()["adguard"]),
                              ("portainer", self.full()["portainer"])):
            self.assertTrue(self.app.test({"kind": kind, "settings": section}), kind)

    def test_wrong_credentials_are_reported(self):
        bad = self.full()["opnsense"] | {"secret": "x"}
        with self.assertRaises(PforteError):
            self.app.test({"kind": "opnsense", "settings": bad})
        with self.assertRaises(PforteError):
            self.app.test({"kind": "adguard", "settings": self.full()["adguard"] | {"password": "x"}})
        with self.assertRaises(PforteError):
            self.app.test({"kind": "portainer", "settings": self.full()["portainer"] | {"api_key": "x"}})

    def test_save_names_profile_after_host_and_hides_secrets(self):
        state = self.app.save_profile(self.full())
        self.assertEqual(state["active"], "127.0.0.1")
        shown = json.dumps(state)
        for secret in ('"k"', '"s"', '"pw"', '"tok"'):
            self.assertNotIn(secret, shown)
        self.assertTrue(state["profiles"][0]["opnsense"]["has_secret"])
        saved = config.load(self.path)["profiles"][0]
        self.assertEqual(saved["opnsense"]["secret"], "s")
        self.assertNotIn("has_secret", saved["opnsense"])

    def test_config_file_is_private(self):
        self.app.save_profile(self.full())
        if os.name != "nt":
            self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_editing_keeps_blank_secrets(self):
        self.app.save_profile(self.full())
        edit = self.full()
        edit["opnsense"] = {"url": self.url, "key": "", "secret": "", "verify": False}
        edit["adguard"] = None
        edit["previous"] = "127.0.0.1"
        state = self.app.save_profile(edit)
        saved = config.load(self.path)["profiles"][0]
        self.assertEqual((saved["opnsense"]["key"], saved["opnsense"]["secret"]), ("k", "s"))
        self.assertIsNone(saved["adguard"])
        self.assertEqual(len(state["profiles"]), 1)

    def test_blank_secret_test_uses_stored_one(self):
        self.app.save_profile(self.full())
        section = {"url": self.url, "key": "", "secret": "", "verify": False}
        self.assertTrue(self.app.test({"kind": "opnsense", "settings": section,
                                       "profile": "127.0.0.1"}))

    def test_opnsense_only_is_enough(self):
        self.app.save_profile({"opnsense": self.full()["opnsense"]})
        overview = self.app.overview()
        self.assertFalse(overview["dns"]["enabled"])
        self.assertFalse(overview["docker"])

    def test_missing_credentials(self):
        with self.assertRaises(PforteError):
            self.app.save_profile({"opnsense": {"url": self.url}})

    def test_second_profile_and_switch_and_delete(self):
        self.app.save_profile(self.full())
        self.app.save_profile(self.full(name="Zweit"))
        state = self.app.state()
        self.assertEqual((state["active"], len(state["profiles"])), ("Zweit", 2))
        self.assertEqual(self.app.set_active("127.0.0.1")["active"], "127.0.0.1")
        with self.assertRaises(PforteError):
            self.app.set_active("gibt es nicht")
        self.assertEqual(self.app.delete_profile("127.0.0.1")["active"], "Zweit")

    def test_import_from_old_version(self):
        old = os.path.join(self.dir.name, "alt.json")
        with open(old, "w") as handle:
            json.dump({"opnsense": [{"name": "Zuhause", "url": self.url, "key": "k",
                                     "secret": "s", "verify_ssl": False, "adguard": "G",
                                     "portainer": "P", "haproxy_ip": "10.0.0.1"}],
                       "adguard": [{"name": "G", "url": self.url, "username": "admin",
                                    "password": "pw", "target": ""}],
                       "portainer": [{"name": "P", "url": self.url, "api_key": "tok"}]}, handle)
        found = config.importable(old)
        self.assertEqual(found[0]["name"], "Zuhause")
        self.assertFalse(found[0]["opnsense"]["verify"])
        self.assertEqual(found[0]["adguard"]["target"], "10.0.0.1")
        self.assertEqual(found[0]["portainer"]["api_key"], "tok")
        # ohne eigene Verknüpfung gelten die zuletzt benutzten Dienste
        with open(old, "w") as handle:
            json.dump({"active": {"opnsense": "Zuhause", "adguard": "G", "portainer": "P"},
                       "opnsense": [{"name": "Zuhause", "url": self.url, "key": "k", "secret": "s"},
                                    {"name": "Anderswo", "url": self.url, "key": "k", "secret": "s"}],
                       "adguard": [{"name": "G", "url": self.url, "username": "a", "password": "p"}],
                       "portainer": []}, handle)
        named = {p["name"]: p for p in config.importable(old)}
        self.assertEqual(named["Zuhause"]["adguard"]["url"], self.url)
        self.assertIsNone(named["Anderswo"]["adguard"])


class Working(Setup):
    def setUp(self):
        super().setUp()
        self.app.save_profile(self.full())

    def test_overview(self):
        ov = self.app.overview()
        self.assertEqual(ov["listeners"][0]["name"], "https_frontend")
        self.assertEqual([d["domain"] for d in ov["domains"]],
                         ["home.example.com", "lab.example.org"])
        self.assertEqual(len(ov["hosts"]), 2)
        self.assertEqual(ov["dns"], {"enabled": True, "target": "192.168.0.1"})
        names = {s["name"] for s in ov["suggestions"]}
        self.assertEqual(names, {"grafana", "vaultwarden", "portainer"})
        grafana = next(s for s in ov["suggestions"] if s["name"] == "grafana")
        self.assertEqual((grafana["host"], grafana["port"]), ("127.0.0.1", 3001))
        portainer = next(s for s in ov["suggestions"] if s["name"] == "portainer")
        self.assertTrue(portainer["tls"])
        self.assertTrue(portainer["target"].startswith("https://"))

    def test_create_and_remove_through_jobs(self):
        job = self.wait(self.app.create({
            "label": "neu", "domain": "home.example.com", "target": "192.168.0.50:8080",
            "listener": self.app.overview()["listeners"][0]["uuid"]}))
        self.assertTrue(job["ok"], job["error"])
        self.assertEqual(job["result"]["host"], "neu.home.example.com")
        self.assertGreaterEqual(len(job["steps"]), 5)
        ov = self.app.overview()
        mine = next(h for h in ov["hosts"] if h["host"] == "neu.home.example.com")
        self.assertEqual(mine["target"], "192.168.0.50:8080")
        gone = self.wait(self.app.remove({"uuid": mine["uuid"]}))
        self.assertTrue(gone["ok"], gone["error"])
        self.assertEqual(len(self.app.overview()["hosts"]), 2)

    def test_edit_through_a_job(self):
        ov = self.app.overview()
        wiki = next(h for h in ov["hosts"] if h["host"] == "wiki.home.example.com")
        self.assertTrue(wiki["editable"])
        job = self.wait(self.app.edit({
            "uuid": wiki["uuid"], "label": "wiki2", "domain": "home.example.com",
            "target": "192.168.0.77:9000", "listener": wiki["listener_uuid"]}))
        self.assertTrue(job["ok"], job["error"])
        self.assertTrue(job["result"]["changed"])
        moved = next(h for h in self.app.overview()["hosts"] if h["host"] == "wiki2.home.example.com")
        self.assertEqual(moved["target"], "192.168.0.77:9000")

    def test_edit_needs_a_listener(self):
        with self.assertRaises(PforteError):
            self.app.edit({"uuid": "x", "label": "a", "domain": "b.de", "target": "1.2.3.4"})

    def test_overview_is_cached_but_forgotten_after_changes(self):
        first = self.app.overview()
        self.assertIs(self.app.overview(), first)
        self.assertIsNot(self.app.overview(fresh=True), first)
        job = self.wait(self.app.create({
            "label": "neu", "domain": "home.example.com", "target": "192.168.0.50:8080",
            "listener": first["listeners"][0]["uuid"]}))
        self.assertTrue(job["ok"], job["error"])
        self.assertIn("neu.home.example.com", [h["host"] for h in self.app.overview()["hosts"]])

    def test_create_error_is_in_the_job(self):
        job = self.wait(self.app.create({
            "label": "wiki", "domain": "home.example.com", "target": "192.168.0.50",
            "listener": self.app.overview()["listeners"][0]["uuid"]}))
        self.assertFalse(job["ok"])
        self.assertIn("gibt es schon", job["error"])

    def test_listener_is_required(self):
        with self.assertRaises(PforteError):
            self.app.create({"label": "x", "domain": "a.de", "target": "1.2.3.4"})

    def test_dns_target_falls_back_to_listener_or_host(self):
        data = config.load(self.path)
        data["profiles"][0]["adguard"]["target"] = ""
        config.save(data, self.path)
        self.assertEqual(self.app.overview()["dns"]["target"], "127.0.0.1")


class Http(Setup):
    def setUp(self):
        super().setUp()
        self.server = make_server(self.app, 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=lambda: self.server.serve_forever(0.05), daemon=True).start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.shutdown()
        super().tearDown()

    def get(self, path, cookie=True, host=None):
        headers = {}
        if cookie:
            headers["Cookie"] = f"pforte={self.app.token}"
        if host:
            headers["Host"] = host
        req = urllib.request.Request(self.base + path, headers=headers)
        try:
            with urllib.request.urlopen(req) as reply:
                return reply.status, reply.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_needs_the_cookie(self):
        self.assertEqual(self.get("/api/state", cookie=False)[0], 401)
        self.assertEqual(self.get("/", cookie=False)[0], 401)
        self.assertEqual(self.get("/api/state")[0], 200)

    def test_rejects_foreign_host_header(self):
        self.assertEqual(self.get("/api/state", host="evil.example:80")[0], 403)

    def test_page_and_assets_are_served(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Pforte", body)
        for asset in ("/app.js", "/style.css", "/logo.svg"):
            self.assertEqual(self.get(asset)[0], 200, asset)

    def test_no_path_traversal(self):
        self.assertEqual(self.get("/..%2Fserver.py")[0], 404)
        self.assertEqual(self.get("/../server.py")[0], 404)

    def test_token_link_sets_cookie(self):
        class NoFollow(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoFollow)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            opener.open(f"{self.base}/?t={self.app.token}")
        self.assertEqual(caught.exception.code, 302)
        self.assertIn("pforte=", caught.exception.headers["Set-Cookie"])
        with self.assertRaises(urllib.error.HTTPError) as wrong:
            opener.open(f"{self.base}/?t=falsch")
        self.assertEqual(wrong.exception.code, 401)

    def test_errors_come_as_json_with_code(self):
        status, body = self.get("/api/overview")
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))


if __name__ == "__main__":
    unittest.main()
