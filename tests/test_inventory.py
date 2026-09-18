"""Inventory equivalence, request counts, failures and bounded concurrency."""
import copy
import os
import sys
import threading
import time
import unittest
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import opnsense_haproxy as core


class Firewall:
    def __init__(self, delay=0):
        self.delay = delay
        self.lock = threading.Lock()
        self.calls = Counter()
        self.active = self.peak = 0
        self.broken = set()
        self.records = {}
        for i in range(3):
            self.records['frontend', f'f{i}'] = dict(
                name=f'listener{i}', mode='http', bind=f'0.0.0.0:{443+i}',
                enabled='1', ssl_enabled='1', defaultBackend='b0',
                linkedActions=','.join(f'a{j}' for j in range(12)))
        for i in range(12):
            self.records['action', f'a{i}'] = dict(
                name=f'rule{i}', type='use_backend', use_backend=f'b{i % 2}',
                linkedAcls={f'c{i % 4}': {'selected': 1},
                            'unused': {'selected': 0}})
        for i in range(4):
            self.records['acl', f'c{i}'] = dict(expression='hdr', hdr=f'web{i}.example.com')
        for i in range(2):
            self.records['backend', f'b{i}'] = dict(name=f'pool{i}', mode='http',
                                                   linkedServers='s0,s1')
            self.records['server', f's{i}'] = dict(name=f'server{i}', address='192.0.2.1',
                                                  port=str(8000+i), ssl='0')

    def search(self, kind):
        return [dict(uuid=uuid, name=record.get('name', ''))
                for (k, uuid), record in self.records.items() if k == kind]

    def get(self, kind, uuid):
        key = kind, uuid
        with self.lock:
            self.calls[key] += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            if key in self.broken:
                raise core.ApiError(f'unreadable {kind} {uuid}')
            return copy.deepcopy(self.records[key])
        finally:
            with self.lock:
                self.active -= 1


class InventoryTests(unittest.TestCase):
    def test_same_content_and_order_with_one_read_per_object(self):
        api = Firewall()
        expected = core._inventory_from_records(api, api.search('frontend'))
        old_count = sum(api.calls.values())
        api.calls.clear()
        self.assertEqual(core.inventory(api), expected)
        self.assertEqual(set(api.calls), set(api.records))
        self.assertTrue(all(count == 1 for count in api.calls.values()))
        self.assertLess(sum(api.calls.values()), old_count)

    def test_reads_overlap_but_never_exceed_four(self):
        api = Firewall(delay=0.005)
        core.inventory(api)
        self.assertGreater(api.peak, 1)
        self.assertLessEqual(api.peak, 4)
        self.assertEqual(api.active, 0)

    def test_each_refresh_reads_changes(self):
        api = Firewall()
        before = core.inventory(api)
        api.records['server', 's0']['address'] = '192.0.2.99'
        after = core.inventory(api)
        self.assertNotEqual(before, after)
        self.assertEqual(after[0]['default']['servers'][0]['address'], '192.0.2.99')
        self.assertTrue(all(count == 2 for count in api.calls.values()))

    def test_unreadable_shared_references_keep_existing_behavior(self):
        for key in [('action', 'a0'), ('acl', 'c0'), ('backend', 'b0'), ('server', 's0')]:
            with self.subTest(key=key):
                api = Firewall()
                api.broken.add(key)
                expected = core._inventory_from_records(api, api.search('frontend'))
                api.calls.clear()
                self.assertEqual(core.inventory(api), expected)
                self.assertEqual(api.calls[key], 1)

    def test_frontend_failure_still_fails_refresh(self):
        api = Firewall()
        api.broken.add(('frontend', 'f0'))
        with self.assertRaises(core.ApiError):
            core.inventory(api)

    def test_empty_firewall(self):
        api = Firewall()
        api.records.clear()
        self.assertEqual(core.inventory(api), [])
        self.assertFalse(api.calls)


if __name__ == '__main__':
    unittest.main()
