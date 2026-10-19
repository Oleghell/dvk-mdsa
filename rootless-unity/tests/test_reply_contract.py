import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import reply_contract as p
import diagnose_device as d
import diagnose_reply_contract as gui
from test_chat_runtime_metadata import RuntimeFake


def ready():
    roots = [dict(zip(('key', 'image', 'namespace', 'type'), r), found=True) for r in p.ROOTS]
    identities = {r['key']: {k: r[k] for k in ('image', 'namespace', 'type')} for r in roots}
    identities.update(list=dict(image='Core.dll', namespace='DataKit', type='BaseDataList`1'),
                      content=dict(image='DV.dll', namespace='DV.CMs', type='ContentDataList`1'),
                      loaded=dict(image='Core.dll', namespace='DataKit', type='DataField`1'))
    primitives = {2: 'Boolean', 8: 'Int32', 10: 'Int64', 14: 'String'}
    def desc(kind, target=None):
        return dict(kind=kind, byref=False,
                    target=copy.deepcopy(identities[target]) if target else
                    dict(image='mscorlib.dll', namespace='System', type=primitives[kind]))
    checks = [dict(label=label, status='ready', owner=copy.deepcopy(identities[owner]),
                   return_type=desc(kind, target), arity=len(params), static=False, abstract=False,
                   parameters=[desc(k) for k in params])
              for label, owner, method, kind, target, params in p.SPECS]
    return dict(schema_version=1, tool_version=p.VERSION, mode='targeted-reply-contract-definitions',
                stage='contract-ready', reason='none', api_available=True,
                current_thread_initially_attached=False, thread_attach_performed=True,
                thread_detach_confirmed=True, cleanup_failed=False, native_calls=505,
                assemblies_scanned=4, limited=False, all_required_signatures_verified=True,
                method_values_read=False, history_read=False, ui_actions_attempted=False,
                messages_sent=0, chronological_order_verified=False, live_replies_available=False,
                roots=roots, checks=checks)


class Contract(unittest.TestCase):
    def test_ready_proves_definitions_not_live_replies(self):
        self.assertEqual(p.validate(ready()), ready())
        self.assertFalse(ready()['live_replies_available'])
        self.assertFalse(ready()['chronological_order_verified'])

    def test_bounded_fixed_lookup_source_has_no_application_value_apis(self):
        for forbidden in ('runtime_invoke', 'object_get', 'field_get', 'gchandle', 'Interceptor',
                          'NativeCallback', 'class_get_methods', 'class_get_fields', 'image_get_class',
                          'readUtf16String', 'Memory.scan', 'OnSendText', 'sendMessage', 'OnMessageButton'):
            self.assertNotIn(forbidden, p.FUNCTION)
        self.assertIn('r.native_calls>=12000', p.FUNCTION)
        self.assertIn('deadline=Date.now()+5000', p.FUNCTION)
        self.assertIn('i<10&&!k.isNull()', p.FUNCTION)
        self.assertNotIn('__ROOTS__', p.FUNCTION)
        self.assertEqual(len(p.ROOTS), 7)
        self.assertEqual(len(p.SPECS), 23)

    def test_unknown_or_private_fields_rejected(self):
        for key, val in (('message_text', 'PRIVATE'), ('native_calls', True), ('messages_sent', False),
                         ('method_values_read', True), ('history_read', True), ('ui_actions_attempted', True),
                         ('chronological_order_verified', True), ('live_replies_available', True),
                         ('reason', 'PRIVATE'), ('native_calls', 12001)):
            r = ready(); r[key] = val
            with self.assertRaises(ValueError, msg=key):
                p.validate(r)

    def test_return_and_parameter_kind_byref_and_flags_verified(self):
        mutations = [
            lambda r: r['checks'][17]['return_type'].update(kind=21),
            lambda r: r['checks'][17]['return_type'].update(byref=True),
            lambda r: r['checks'][19]['parameters'][0].update(kind=2),
            lambda r: r['checks'][19]['parameters'][0].update(byref=True),
            lambda r: r['checks'][0]['return_type']['target'].update(type='User'),
            lambda r: r['checks'][0].update(static=True),
            lambda r: r['checks'][0].update(abstract=True),
            lambda r: r['checks'][0].update(arity=1),
            lambda r: r['checks'][0].update(owner=None),
            lambda r: r['checks'][0].update(address='0x1234'),
            lambda r: r['checks'][0]['owner'].update(type='BAD\nPRIVATE'),
        ]
        for mutate in mutations:
            r = ready(); mutate(r)
            with self.assertRaises(ValueError):
                p.validate(r)

    def test_incomplete_is_explicit_and_not_marked_ready(self):
        r = ready(); check = r['checks'][17]
        check.update(status='return-type-mismatch')
        check['return_type']['kind'] = 21
        r.update(stage='contract-incomplete', all_required_signatures_verified=False)
        p.validate(r)
        r['all_required_signatures_verified'] = True
        with self.assertRaises(ValueError):
            p.validate(r)

    def test_missing_root_or_incomplete_check_cannot_be_ready(self):
        for modify in (lambda r: r['roots'][4].update(found=False),
                       lambda r: r['checks'][17].update(status='method-missing'),
                       lambda r: r['checks'][0].update(status='not-checked')):
            r = ready(); modify(r)
            with self.assertRaises(ValueError):
                p.validate(r)

    def test_partial_stopped_report_and_cleanup(self):
        r = ready()
        r.update(stage='contract-stopped', reason='cleanup-failed', cleanup_failed=True,
                 thread_detach_confirmed=False, all_required_signatures_verified=False)
        p.validate(r)
        r['reason'] = 'none'
        with self.assertRaises(ValueError):
            p.validate(r)
        for changes in (dict(current_thread_initially_attached=True),
                        dict(thread_detach_confirmed=False), dict(thread_attach_performed=False)):
            r = ready(); r.update(changes)
            with self.assertRaises(ValueError):
                p.validate(r)

    def test_transport_is_native_metadata_only_and_releases_resources(self):
        class Fake(RuntimeFake):
            def create_script(self, *args, **kwargs):
                super().create_script(*args, **kwargs)
                self.exports_sync.native = ready
                return self
        fake = Fake()
        report = d.inspect_gadget(37149, 'a'*64, lambda: False, frida_api=fake, reply_contract_probe=True)
        self.assertEqual(report['stage'], 'contract-ready')
        self.assertEqual(fake.script_name, 'dvk-reply-contract-0.3.28')
        self.assertNotIn('rpc.exports.root', fake.script_source)
        self.assertNotIn('rpc.exports.cancel', fake.script_source)
        self.assertNotIn('Interceptor', fake.script_source)
        self.assertTrue(fake.script_unloaded and fake.detached and fake.removed)

    def test_all_conflicting_modes_fail_closed(self):
        for key in ('uikit_root_probe', 'uikit_tree_probe', 'navigation_probe', 'profile_probe',
                    'profile_metadata_probe', 'batch_probe', 'chat_runtime_probe', 'chat_state_probe',
                    'chat_send_probe', 'automatic_probe', 'replies_probe'):
            with self.assertRaises(d.TestError, msg=key):
                d.inspect_gadget(37149, 'a'*64, lambda: False, frida_api=RuntimeFake(),
                                 reply_contract_probe=True, **{key: True})
            with self.assertRaises(d.TestError, msg=key):
                d.diagnose(None, None, reply_contract_probe=True, **{key: True})
        with self.assertRaises(d.TestError):
            d.inspect_gadget(37149, 'a'*64, lambda: False, frida_api=RuntimeFake(),
                             reply_contract_probe=True, cohort_store=object())

    def test_report_name_flags_and_no_token_leak(self):
        class Adb:
            forward_port = None
            def run(self, args, timeout=30):
                return '37149' if args[-2:] == ['tcp:0', 'tcp:27042'] else ''
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'test-apks'; folder.mkdir()
            with patch.object(d, 'bundle_token', return_value='a'*64), \
                 patch.object(d, 'preflight', return_value=('PRIVATE1', 'PRIVATE2')), patch.object(d, 'recheck'):
                report, path = d.diagnose(Adb(), folder, reply_contract_probe=True,
                    inspector=lambda *args: dict(stage='contract-ready', native_metadata=ready()))
            self.assertEqual(path.name, 'rootless-reply-contract-0.3.28.json')
            self.assertEqual(report['tool_version'], '0.3.28')
            self.assertEqual(report['mode'], 'targeted-reply-contract-definitions')
            for k in ('method_values_read', 'history_read', 'chat_opened', 'ui_actions_attempted',
                      'ui_actions_performed', 'app_installation_modified', 'working_device_modified'):
                self.assertIs(report[k], False)
            self.assertNotIn('PRIVATE', path.read_text())
            self.assertNotIn('a'*64, path.read_text())

    def test_default_inspector_forwards_no_broad_inventory_flag(self):
        class Adb:
            forward_port = None
            def run(self, args, timeout=30):
                return '37149' if args[-2:] == ['tcp:0', 'tcp:27042'] else ''
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'test-apks'; folder.mkdir()
            with patch.object(d, 'bundle_token', return_value='a'*64), \
                 patch.object(d, 'preflight', return_value=('A', 'B')), patch.object(d, 'recheck'), \
                 patch.object(d, 'inspect_gadget', return_value=dict(stage='contract-ready', native_metadata=ready())) as inspect:
                d.diagnose(Adb(), folder, inspector=inspect, reply_contract_probe=True)
            self.assertIs(inspect.call_args.kwargs['reply_contract_probe'], True)
            self.assertIs(inspect.call_args.kwargs['chat_runtime_probe'], False)
            self.assertIs(inspect.call_args.kwargs['replies_probe'], False)

    def test_gui_is_button_started_with_no_sending_or_enrollment_controls(self):
        tk = MagicMock(); ttk = MagicMock(); tk.ttk = ttk
        tk.Tk.return_value.winfo_height.return_value = 350
        ttk.Frame.return_value.winfo_reqheight.return_value = 300
        with patch.dict(sys.modules, {'tkinter': tk, 'tkinter.ttk': ttk,
                        'tkinter.filedialog': tk.filedialog, 'tkinter.messagebox': tk.messagebox}), \
             patch.object(gui.threading, 'Thread') as thread:
            gui.launch_gui()
            thread.assert_not_called()
            commands = {c.kwargs['text']: c.kwargs['command'] for c in ttk.Button.call_args_list}
            self.assertNotIn('Новая десятка · сохранить привязки', commands)
            self.assertNotIn('Подготовить ответы · без отправки', commands)
            commands['Проверить сигнатуры · без сообщений']()
            commands['Проверить сигнатуры · без сообщений']()
            thread.return_value.start.assert_called_once()
        ttk.Checkbutton.assert_not_called()

    def test_gui_worker_only_passes_targeted_mode(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(gui, 'DiagnosticAdb') as adb, \
             patch.object(gui, 'diagnose', return_value=('result', 'path')) as run:
            self.assertEqual(gui.start('adb.exe', temp), ('result', 'path'))
            self.assertEqual(run.call_args.kwargs, {'reply_contract_probe': True})


if __name__ == '__main__':
    unittest.main()
