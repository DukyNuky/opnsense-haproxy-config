import os
import re
import unittest

import build_web
from pforte import VERSION, _web

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Embedding(unittest.TestCase):
    def test_embedded_web_files_match_the_real_ones(self):
        self.assertEqual(_web.FILES, build_web.collect(),
                         "Weboberfläche geändert? Bitte `python3 tests/build_web.py` ausführen.")

    def test_generated_file_is_current(self):
        with open(os.path.join(ROOT, "pforte", "_web.py"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), build_web.render(build_web.collect()))

    def test_old_updaters_find_the_version_in_the_legacy_entry_file(self):
        with open(os.path.join(ROOT, "opnsense_haproxy.py"), encoding="utf-8") as handle:
            head = handle.read(4096)
        found = re.search(r'^VERSION = "([^"]+)"', head, re.M)   # genau das liest ein 3.x
        self.assertIsNotNone(found)
        self.assertEqual(found.group(1), VERSION)

    def test_legacy_entry_points_exist(self):
        for name in ("haproxy_gui.py", "opnsense_haproxy.py", "HAProxy-Starter.bat"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, name)), name)

    def test_only_old_updater_friendly_names_outside_tests(self):
        from pforte import update
        for name in update.program_files(ROOT):
            self.assertTrue(update.updatable(name), name)


if __name__ == "__main__":
    unittest.main()
