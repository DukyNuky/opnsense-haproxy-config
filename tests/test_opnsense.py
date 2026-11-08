import unittest

import mock_services
from pforte import opnsense
from pforte.adguard import AdGuard
from pforte.net import ApiError, PforteError


class Base(unittest.TestCase):
    def setUp(self):
        self.server, self.state = mock_services.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.client = opnsense.Client(self.url, "k", "s")
        self.guard = AdGuard(self.url, "admin", "pw")
        self.log = []

    def tearDown(self):
        self.server.shutdown()

    def say(self, text, level="info"):
        self.log.append((level, text))

    def counts(self):
        return {k: len(v) for k, v in self.state.objects.items()}

    def frontend(self, name):
        return next(l for l in opnsense.listeners(self.client) if l["name"] == name)

    def create(self, label="neu", target="192.168.0.50:8080", listener="https_frontend",
               domain="home.example.com", guard=True):
        return opnsense.create_host(
            self.client, label=label, domain=domain, target=target,
            listener_uuid=self.frontend(listener)["uuid"],
            adguard=self.guard if guard else None, dns_target="192.168.0.1",
            say=self.say)


class Reading(Base):
    def test_check(self):
        self.assertEqual(opnsense.check(self.client)["listeners"], 3)

    def test_wrong_secret_is_explained(self):
        bad = opnsense.Client(self.url, "k", "falsch")
        with self.assertRaises(ApiError) as caught:
            opnsense.check(bad)
        self.assertIn("abgelehnt", str(caught.exception))

    def test_unreachable(self):
        gone = opnsense.Client("http://127.0.0.1:9", "k", "s", timeout=2)
        with self.assertRaises(ApiError):
            opnsense.check(gone)

    def test_https_listener_with_most_rules_is_recommended(self):
        found = opnsense.listeners(self.client)
        self.assertEqual(found[0]["name"], "https_frontend")
        self.assertTrue(found[0]["recommended"])
        self.assertEqual(found[0]["rule_count"], 2)
        self.assertEqual(found[0]["ports"], [443])

    def test_busiest_443_listener_wins(self):
        self.state.add("frontend", name="https_zwei", mode="http", bind="0.0.0.0:443",
                       linkedActions=["a", "b", "c"], enabled="1")
        self.assertEqual(opnsense.listeners(self.client)[0]["name"], "https_zwei")

    def test_disabled_listener_is_never_first(self):
        for obj in self.state.objects["frontend"].values():
            if obj["name"] == "https_frontend":
                obj["enabled"] = "0"
        self.assertNotEqual(opnsense.listeners(self.client)[0]["name"], "https_frontend")

    def test_domains_from_enabled_certificates(self):
        names = [d["domain"] for d in opnsense.domains(self.client)]
        self.assertEqual(names, ["home.example.com", "lab.example.org"])

    def test_domains_fall_back_to_existing_hosts(self):
        self.state.acme = False
        found = opnsense.domains(self.client, ["wiki.home.example.com"])
        self.assertEqual([d["domain"] for d in found], ["home.example.com"])

    def test_existing_hosts(self):
        found = opnsense.hosts(self.client)
        self.assertEqual([h["host"] for h in found],
                         ["cloud.home.example.com", "wiki.home.example.com"])
        wiki = found[1]
        self.assertEqual(wiki["target"], "192.168.0.20:8080")
        self.assertEqual(wiki["listener"], "https_frontend")
        self.assertTrue(wiki["managed"])

    def test_manual_rules_are_listed_but_not_managed(self):
        acl = self.state.add("acl", name="acl_hand", description="", expression="hdr",
                             hdr="hand.home.example.com")
        action = self.state.add("action", name="rule_hand", description="", type="use_backend",
                                linkedAcls=[acl], use_backend="")
        found = {h["host"]: h for h in opnsense.hosts(self.client)}
        self.assertFalse(found["hand.home.example.com"]["managed"])
        self.assertTrue(found["wiki.home.example.com"]["managed"])
        with self.assertRaises(PforteError):
            opnsense.remove_host(self.client, action, say=self.say)


class Parsing(unittest.TestCase):
    def test_targets(self):
        p = opnsense.parse_target
        self.assertEqual(p("192.168.0.5"), ("192.168.0.5", 80, False))
        self.assertEqual(p("nas:8080"), ("nas", 8080, False))
        self.assertEqual(p("https://nas"), ("nas", 443, True))
        self.assertEqual(p("https://10.0.0.1:8443/pfad"), ("10.0.0.1", 8443, True))
        self.assertEqual(p(" http://x:81 "), ("x", 81, False))

    def test_bad_targets(self):
        for bad in ("", "ftp://x", "a b", "host:abc", "host:70000"):
            with self.assertRaises(PforteError, msg=bad):
                opnsense.parse_target(bad)

    def test_labels(self):
        self.assertEqual(opnsense.check_label(" Wiki "), "wiki")
        for bad in ("", "-x", "a_b", "x y"):
            with self.assertRaises(PforteError, msg=bad):
                opnsense.check_label(bad)

    def test_fqdn(self):
        self.assertEqual(opnsense.build_fqdn("wiki", "a.de"), "wiki.a.de")
        self.assertEqual(opnsense.build_fqdn("wiki.a.de", "a.de"), "wiki.a.de")
        self.assertEqual(opnsense.build_fqdn("@", "a.de"), "a.de")


class Creating(Base):
    def test_creates_everything_and_applies(self):
        before = self.counts()
        result = self.create()
        self.assertEqual(result["host"], "neu.home.example.com")
        after = self.counts()
        for kind in ("server", "backend", "acl", "action"):
            self.assertEqual(after[kind], before[kind] + 1, kind)
        self.assertEqual(self.state.reconfigured, 1)
        self.assertEqual(self.frontend("https_frontend")["rule_count"], 3)
        self.assertIn({"domain": "neu.home.example.com", "answer": "192.168.0.1"},
                      self.state.rewrites)
        server = next(o for o in self.state.objects["server"].values()
                      if o["name"] == "srv_neu.home.example.com")
        self.assertEqual((server["address"], server["port"], server["ssl"]),
                         ("192.168.0.50", "8080", "0"))

    def test_https_target_sets_ssl(self):
        self.create(target="https://192.168.0.50")
        server = next(o for o in self.state.objects["server"].values()
                      if o["name"] == "srv_neu.home.example.com")
        self.assertEqual((server["port"], server["ssl"], server["sslVerify"]),
                         ("443", "1", "0"))

    def test_sni_listener_uses_tcp_and_ssl_sni(self):
        self.create(listener="mqtt_tcp")
        acl = next(o for o in self.state.objects["acl"].values()
                   if o["name"] == "acl_neu_home_example_com")
        self.assertEqual((acl["expression"], acl["ssl_sni"]),
                         ("ssl_sni", "neu.home.example.com"))
        backend = next(o for o in self.state.objects["backend"].values()
                       if o["name"] == "be_neu.home.example.com")
        self.assertEqual(backend["mode"], "tcp")

    def test_without_adguard_says_so(self):
        result = self.create(guard=False)
        self.assertTrue(any("AdGuard" in w for w in result["warnings"]))
        self.assertEqual(self.state.rewrites, [])

    def test_existing_foreign_rewrite_is_left_alone(self):
        self.state.rewrites.append({"domain": "neu.home.example.com", "answer": "1.2.3.4"})
        result = self.create()
        self.assertEqual(self.state.rewrites,
                         [{"domain": "neu.home.example.com", "answer": "1.2.3.4"}])
        self.assertTrue(any("1.2.3.4" in w for w in result["warnings"]))

    def test_duplicate_is_refused_without_changes(self):
        before = self.counts()
        with self.assertRaises(PforteError) as caught:
            self.create(label="wiki")
        self.assertIn("gibt es schon", str(caught.exception))
        self.assertEqual(self.counts(), before)

    def test_failure_rolls_everything_back(self):
        for step in ("server", "backend", "acl", "action"):
            with self.subTest(step=step):
                self.state.fail_on = ("add", step)
                before = self.counts()
                links = self.frontend("https_frontend")["rule_count"]
                with self.assertRaises(PforteError):
                    self.create()
                self.assertEqual(self.counts(), before)
                self.assertEqual(self.frontend("https_frontend")["rule_count"], links)
        self.state.fail_on = None

    def test_refused_config_rolls_back_and_does_not_reload(self):
        self.state.config_ok = False
        before = self.counts()
        with self.assertRaises(PforteError) as caught:
            self.create()
        self.assertIn("lehnt", str(caught.exception))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.state.reconfigured, 0)
        self.assertEqual(self.state.rewrites, [])

    def test_certificate_warning(self):
        entry = next(d for d in opnsense.domains(self.client) if d["domain"] == "lab.example.org")
        # Platzhalter deckt genau eine Ebene ab
        self.assertTrue(opnsense.covered(entry, "a.lab.example.org"))
        self.assertFalse(opnsense.covered(entry, "a.b.lab.example.org"))

    def test_progress_is_reported(self):
        self.create()
        texts = [t for _, t in self.log]
        self.assertEqual(texts[0], "Server anlegen")
        self.assertIn("HAProxy neu laden", texts)


class Removing(Base):
    def test_remove_cleans_up_including_dns(self):
        self.create()
        mine = next(h for h in opnsense.hosts(self.client) if h["host"] == "neu.home.example.com")
        before = self.counts()
        opnsense.remove_host(self.client, mine["uuid"], adguard=self.guard, say=self.say)
        after = self.counts()
        for kind in ("server", "backend", "acl", "action"):
            self.assertEqual(after[kind], before[kind] - 1, kind)
        self.assertEqual(self.state.rewrites, [])
        self.assertNotIn("neu.home.example.com", [h["host"] for h in opnsense.hosts(self.client)])
        self.assertEqual(self.frontend("https_frontend")["rule_count"], 2)

    def test_foreign_rules_are_not_touched(self):
        foreign = self.state.add("action", name="rule_fremd", description="von Hand",
                                 type="use_backend", linkedAcls=[], use_backend="")
        with self.assertRaises(PforteError):
            opnsense.remove_host(self.client, foreign, say=self.say)
        self.assertIn(foreign, self.state.objects["action"])



class Editing(Base):
    def entry(self, host):
        return next(h for h in opnsense.hosts(self.client) if h["host"] == host)

    def edit(self, host="wiki.home.example.com", **kw):
        current = self.entry(host)
        args = dict(label=host.split(".")[0], domain=host.split(".", 1)[1],
                    target=current["target"], listener_uuid=current["listener_uuid"],
                    adguard=self.guard, dns_target="192.168.0.1", say=self.say)
        args.update(kw)
        return opnsense.update_host(self.client, current["uuid"], **args)

    def snapshot(self):
        import copy
        return copy.deepcopy((self.state.objects, self.state.rewrites))

    def test_hosts_report_what_is_needed_for_editing(self):
        wiki = self.entry("wiki.home.example.com")
        self.assertTrue(wiki["editable"])
        for key in ("acl_uuid", "backend_uuid", "server_uuid", "listener_uuid"):
            self.assertTrue(wiki[key], key)

    def test_change_the_target(self):
        result = self.edit(target="https://192.168.0.99:8443")
        self.assertTrue(result["changed"])
        wiki = self.entry("wiki.home.example.com")
        self.assertEqual((wiki["target"], wiki["ssl"]), ("192.168.0.99:8443", True))
        self.assertEqual(self.state.reconfigured, 1)

    def test_rename_moves_names_conditions_and_dns(self):
        self.state.rewrites.append({"domain": "wiki.home.example.com", "answer": "192.168.0.1"})
        result = self.edit(label="wiki2")
        self.assertEqual(result["host"], "wiki2.home.example.com")
        self.assertEqual(self.state.rewrites,
                         [{"domain": "wiki2.home.example.com", "answer": "192.168.0.1"}])
        moved = self.entry("wiki2.home.example.com")
        self.assertEqual(moved["name"], "rule_wiki2_home_example_com")
        names = {o["name"] for o in self.state.objects["server"].values()}
        self.assertIn("srv_wiki2.home.example.com", names)
        self.assertNotIn("srv_wiki.home.example.com", names)
        self.assertEqual(self.counts()["action"], 2)
        # umbenannt heißt auch: dieselben Namen lassen sich wieder anlegen
        self.create(label="wiki")

    def test_foreign_dns_answer_is_not_touched(self):
        self.state.rewrites.append({"domain": "wiki.home.example.com", "answer": "9.9.9.9"})
        self.edit(label="wiki2")
        self.assertIn({"domain": "wiki.home.example.com", "answer": "9.9.9.9"}, self.state.rewrites)

    def test_change_the_listener(self):
        other = self.frontend("http_redirect")["uuid"]
        self.edit(listener_uuid=other)
        self.assertEqual(self.entry("wiki.home.example.com")["listener"], "http_redirect")
        self.assertEqual(self.frontend("https_frontend")["rule_count"], 1)
        self.assertEqual(self.frontend("http_redirect")["rule_count"], 1)

    def test_listener_of_another_kind_is_refused(self):
        before = self.snapshot()
        with self.assertRaises(PforteError):
            self.edit(listener_uuid=self.frontend("mqtt_tcp")["uuid"])
        self.assertEqual(self.snapshot(), before)

    def test_nothing_changed_does_nothing(self):
        result = self.edit()
        self.assertFalse(result["changed"])
        self.assertEqual(self.state.reconfigured, 0)

    def test_name_taken_by_another_host(self):
        before = self.snapshot()
        with self.assertRaises(PforteError) as caught:
            self.edit(label="cloud")
        self.assertIn("gibt es schon", str(caught.exception))
        self.assertEqual(self.snapshot(), before)

    def test_every_failure_restores_everything(self):
        for verb, kind in (("set", "server"), ("set", "backend"), ("set", "acl"),
                           ("set", "action"), ("set", "frontend")):
            with self.subTest(step=kind):
                self.state.fail_on = (verb, kind)
                before = self.snapshot()
                other = self.frontend("http_redirect")["uuid"]
                with self.assertRaises(PforteError):
                    self.edit(label="wiki3", target="10.0.0.9:81", listener_uuid=other)
                self.state.fail_on = None
                self.assertEqual(self.snapshot(), before)

    def test_refused_config_restores_everything_and_does_not_reload(self):
        before = self.snapshot()
        self.state.config_ok = False
        with self.assertRaises(PforteError):
            self.edit(label="wiki3", target="10.0.0.9:81")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.state.reconfigured, 0)

    def test_manual_rules_can_be_edited_but_keep_their_names(self):
        server = self.state.add("server", name="mein_server", description="", address="1.1.1.1",
                                port="80", ssl="0")
        backend = self.state.add("backend", name="mein_pool", description="", mode="http",
                                 linkedServers=[server])
        acl = self.state.add("acl", name="meine_bed", description="", expression="hdr",
                             hdr="hand.home.example.com")
        action = self.state.add("action", name="meine_regel", description="", type="use_backend",
                                linkedAcls=[acl], use_backend=backend)
        https = next(k for k, o in self.state.objects["frontend"].items() if o["name"] == "https_frontend")
        self.state.objects["frontend"][https]["linkedActions"].append(action)
        self.edit(host="hand.home.example.com", label="hand2", target="2.2.2.2:8080")
        self.assertEqual(self.state.objects["server"][server]["name"], "mein_server")
        self.assertEqual(self.state.objects["server"][server]["description"], "")
        self.assertEqual(self.state.objects["acl"][acl]["hdr"], "hand2.home.example.com")
        self.assertEqual(self.state.objects["server"][server]["address"], "2.2.2.2")

    def test_shared_parts_block_editing(self):
        wiki = self.entry("wiki.home.example.com")
        twin = self.state.add("action", name="rule_zwilling", description="", type="use_backend",
                              linkedAcls=[], use_backend=wiki["backend_uuid"])
        self.assertIn(twin, self.state.objects["action"])
        entry = self.entry("wiki.home.example.com")
        self.assertFalse(entry["editable"])
        with self.assertRaises(PforteError) as caught:
            self.edit(label="wiki9")
        self.assertIn("mitbenutzt", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
