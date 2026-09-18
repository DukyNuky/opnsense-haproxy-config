"""Regression checks for protocol changes and listener selection, without a GUI."""
import ast
import copy
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import opnsense_haproxy as core


def options(**changes):
    values = dict(target='web.example.com', prefix='', frontend='web',
                  backend_mode=None, port=8080, ssl=False, ssl_verify=False,
                  healthcheck=None, forward_for=True, ip='192.0.2.10',
                  dry_run=False, no_apply=True)
    values.update(changes)
    return SimpleNamespace(**values)


class Firewall:
    def __init__(self):
        self.records = {('frontend', 'web'): dict(name='web', mode='http',
                                                bind='0.0.0.0:443')}
        self.counter = 0
        self.wrong_mode = None
        self.corrupt_acl = {}

    def search(self, kind):
        return [dict(record, uuid=uuid) for (k, uuid), record in self.records.items()
                if k == kind]

    def find(self, kind, name):
        return next((r for r in self.search(kind) if r['name'] == name), None)

    def get(self, kind, uuid):
        record = copy.deepcopy(self.records[kind, uuid])
        if kind == 'backend':
            mode = record['mode']
            record['mode'] = {m: {'selected': int(m == mode), 'value': m}
                              for m in ('tcp', 'http')}
        return record

    def add(self, kind, body):
        self.counter += 1
        uuid = str(self.counter)
        self.records[kind, uuid] = dict(body)
        if kind == 'backend' and self.wrong_mode:
            self.records[kind, uuid]['mode'] = self.wrong_mode
        if kind == "acl":
            self.records[kind, uuid].update(self.corrupt_acl)
        return uuid

    def update(self, kind, uuid, body):
        self.records[kind, uuid].update(body)

    def delete(self, kind, uuid):
        del self.records[kind, uuid]


def quiet(*args, **kwargs):
    pass


class ProvisionTests(unittest.TestCase):
    def test_tcp_listener_then_http_host(self):
        api = Firewall()
        core.provision_listener(api, options(name='stream', mode='tcp', port=5349), quiet)
        core.provision(api, options(), quiet)
        self.assertEqual(api.find('backend', 'be_stream')['mode'], 'tcp')
        self.assertEqual(api.find('backend', 'be_web.example.com')['mode'], 'http')
        self.assertEqual(api.search('acl')[0]['expression'], 'hdr')

    def test_current_frontend_mode_is_read_for_each_host(self):
        api = Firewall()
        api.records['frontend', 'web']['mode'] = 'tcp'
        core.provision(api, options(target='tcp.example.com'), quiet)
        api.records['frontend', 'web']['mode'] = 'http'
        core.provision(api, options(), quiet)
        self.assertEqual([r['mode'] for r in api.search('backend')], ['tcp', 'http'])
        self.assertEqual([r['expression'] for r in api.search('acl')], ['ssl_sni', 'hdr'])

    def test_wrong_stored_mode_rolls_back_hosts_and_listeners(self):
        for create, opts in ((core.provision, options()),
                             (core.provision_listener,
                              options(name='other', mode='http', port=8443))):
            with self.subTest(create=create.__name__):
                api = Firewall()
                before = copy.deepcopy(api.records)
                api.wrong_mode = 'tcp'
                with self.assertRaisesRegex(core.ApiError, 'mode is tcp, not http'):
                    create(api, opts, quiet)
                self.assertEqual(api.records, before)

    def test_wrong_condition_type_or_value_rolls_back_everything(self):
        for corruption in ({'expression': 'ssl_sni'}, {'hdr': 'old.example.com'},
                           {'path_beg': '/old'}):
            with self.subTest(corruption=corruption):
                api = Firewall()
                before = copy.deepcopy(api.records)
                api.corrupt_acl = corruption
                with self.assertRaisesRegex(core.ApiError, 'condition was not stored'):
                    core.provision(api, options(target='web.example.com/api'), quiet)
                self.assertEqual(api.records, before)

    def test_http_path_conditions_are_read_back(self):
        api = Firewall()
        core.provision(api, options(target='web.example.com/api'), quiet)
        self.assertEqual([r['expression'] for r in api.search('acl')], ['hdr', 'path_beg'])
        self.assertEqual(api.search('acl')[1]['path_beg'], '/api')

    def test_unknown_frontend_mode_does_not_create_objects(self):
        for mode in ('', 'unknown', {}):
            api = Firewall()
            api.records['frontend', 'web']['mode'] = mode
            with self.assertRaises(core.UsageError):
                core.provision(api, options(), quiet)
            self.assertEqual(api.counter, 0)

    def test_dry_run_never_writes(self):
        api = Firewall()
        core.provision(api, options(dry_run=True), quiet)
        self.assertEqual(api.counter, 0)


# Load only these UI methods so their behavior can be checked on machines
# without tkinter or a display. Widget doubles supply the same get/set API.
def ui_method(class_name, method_name, **globals_):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'haproxy_gui.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    namespace = dict(core=core, **globals_)
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'haproxy_gui.py', 'exec'), namespace)
    return namespace[method_name]


class SelectionTests(unittest.TestCase):
    def test_all_ports_are_offered_and_existing_selection_survives(self):
        services = [dict(name=name, bind=f'0.0.0.0:{port}') for name, port in
                    [('custom', 8443), ('web', 443), ('stream', 5349), ('plain', 80)]]
        for chosen in ('', 'custom'):
            app = SimpleNamespace(services=services, profile={},
                                  var_frontend=Mock(get=lambda: chosen))
            dialog = SimpleNamespace(app=app, frontend_box=Mock(), frontend_hint=Mock())
            ui_method('HostDialog', 'fill_frontends')(dialog)
            names = dialog.frontend_box.configure.call_args.kwargs['values']
            self.assertEqual([n.split(' · ')[0] for n in names],
                             ['web', 'custom', 'plain', 'stream'])
            self.assertIn('0.0.0.0:8443', names[1])
            dialog.frontend_box.current.assert_called_once_with(1 if chosen else 0)
            if chosen:
                app.var_frontend.set.assert_not_called()
            else:
                app.var_frontend.set.assert_called_once_with('web')

    def test_selection_passes_only_the_api_name(self):
        dialog = SimpleNamespace(
            frontend_names=['web', 'custom'],
            frontend_box=Mock(current=lambda: 1), frontend_hint=Mock(),
            app=SimpleNamespace(var_frontend=Mock()))
        ui_method('HostDialog', 'frontend_selected')(dialog)
        dialog.app.var_frontend.set.assert_called_once_with('custom')

    def test_new_form_resets_override_but_open_form_keeps_edits(self):
        constructor = Mock()
        app = SimpleNamespace(host_dialog=None, var_backend_mode=Mock())
        open_host = ui_method('App', 'open_host', HostDialog=constructor)
        open_host(app)
        app.var_backend_mode.set.assert_called_once_with('automatisch')
        app.var_backend_mode.reset_mock()
        open_host(app)
        app.var_backend_mode.set.assert_not_called()
        self.assertEqual(constructor.call_count, 1)


if __name__ == '__main__':
    unittest.main()
