"""Only synthetic ADB responses; working MuMu may be absent or powered off."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import diagnose_device as d
import target_only as p
from test_device import TARGET, WORKING, BOOT_ID, PACKAGE, TestError
from test_reply_contract import ready

BOOT = '12345678-1234-1234-1234-123456789abc'
OTHER_BOOT = 'abcdefab-1234-1234-1234-123456789abc'


class TargetOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / 'test-apks'; self.folder.mkdir()
        self.adb = object.__new__(p.TargetOnlyAdb)
        self.adb.folder = self.folder
        self.adb.forward_port = None
        self.adb.adb_events = []
        self.calls = []
        self.identities = iter((BOOT, BOOT, BOOT))
        self.fail_connect = False
        self.present = True
        self.booted = True
        self.state = 'device'

    def adb_run(self, adb, args, timeout=30):
        adb.validate(args)
        self.calls.append(args)
        if WORKING in args:
            raise AssertionError('Working instance must never be contacted')
        if args == ['connect', TARGET]:
            if self.fail_connect:
                raise TestError('Тестовое устройство недоступно.')
            text = ''
        elif args == ['-s', TARGET, 'get-state']:
            text = self.state
        elif args == ['-s', TARGET, 'shell', 'cat', BOOT_ID]:
            text = next(self.identities)
        elif args == ['-s', TARGET, 'shell', 'getprop', 'sys.boot_completed']:
            text = '1' if self.booted else '0'
        elif args == ['-s', TARGET, 'shell', 'pm', 'list', 'packages', PACKAGE]:
            text = 'package:' + PACKAGE if self.present else ''
        elif args[-2:] == ['tcp:0', 'tcp:27042']:
            text = '37149'
        elif args == ['-s', TARGET, 'shell', 'pidof', PACKAGE]:
            text = '42'
        else:
            text = ''
        adb.observe_result(args, 0, text)
        return text

    def patched(self):
        return patch.object(p.TargetOnlyAdb, 'run', lambda adb, args, timeout=30: self.adb_run(adb, args, timeout))

    def test_preflight_works_without_working_instance(self):
        with self.patched():
            identity = p.preflight(self.adb)
            p.recheck(self.adb, identity)
        self.assertEqual(identity, BOOT)
        self.assertFalse(any(WORKING in a for a in self.calls))
        self.assertEqual(self.calls[1], ['connect', TARGET])

    def test_working_commands_and_implicit_targets_rejected(self):
        for args in (['connect', WORKING], ['-s', WORKING, 'get-state'],
                     ['-s', WORKING, 'shell', 'cat', BOOT_ID], ['devices'],
                     ['shell', 'id'], ['-d', 'shell', 'id'], ['connect', '127.0.0.1:5565']):
            with self.assertRaises(TestError, msg=args):
                self.adb.validate(args)

    def test_install_launch_root_and_input_are_still_blocked(self):
        for op in (['install-multiple', str(self.folder/'base.apk'), str(self.folder/'split-001.apk')],
                   ['shell', 'am', 'start', '-n', 'drug.vokrug/drug.vokrug.activity.Launcher'],
                   ['shell', 'input', 'tap', '1', '2'], ['root'], ['shell', 'su']):
            with self.assertRaises(TestError, msg=op):
                self.adb.validate(['-s', TARGET] + op)

    def test_no_fallback_when_test_endpoint_unavailable(self):
        self.fail_connect = True
        with self.patched(), self.assertRaises(TestError):
            p.preflight(self.adb)
        self.assertEqual(self.calls, [['version'], ['connect', TARGET]])

    def test_boot_identity_change_rejected(self):
        self.identities = iter((BOOT, OTHER_BOOT))
        with self.patched():
            identity = p.preflight(self.adb)
            with self.assertRaises(TestError):
                p.recheck(self.adb, identity)

    def test_not_booted_missing_package_and_unauthorized_fail_closed(self):
        for field, value in (('booted', False), ('present', False), ('state', 'unauthorized')):
            setattr(self, field, value); self.identities = iter((BOOT, BOOT, BOOT))
            with self.patched(), self.assertRaises(TestError):
                p.preflight(self.adb)
            setattr(self, field, 'device' if field == 'state' else True)

    def test_full_report_uses_only_target_and_never_exports_boot_id(self):
        with self.patched(), patch.object(d, 'bundle_token', return_value='a'*64), \
             patch.object(d, 'preflight') as old_preflight, patch.object(d, 'recheck') as old_recheck:
            report, path = d.diagnose(self.adb, self.folder, reply_contract_probe=True, test_only=True,
                inspector=lambda *args: dict(stage='contract-ready', native_metadata=ready()))
        old_preflight.assert_not_called(); old_recheck.assert_not_called()
        self.assertEqual(report['status'], 'contract-ready')
        self.assertEqual(report['device_scope'], 'test-only')
        self.assertIs(report['working_device_contacted'], False)
        self.assertIs(report['instances_verified_distinct'], False)
        self.assertIs(report['test_session_identity_rechecked'], True)
        self.assertNotIn('working_instance', report)
        raw = path.read_text()
        self.assertNotIn(BOOT, raw); self.assertNotIn('a'*64, raw)
        self.assertNotIn(WORKING, raw)
        self.assertFalse(any(WORKING in a for a in self.calls))
        self.assertEqual(sum(a == ['-s', TARGET, 'shell', 'cat', BOOT_ID] for a in self.calls), 3)
        self.assertIn(['-s', TARGET, 'forward', '--remove', 'tcp:37149'], self.calls)

    def test_identity_rechecked_after_gadget_and_cleanup_still_runs(self):
        self.identities = iter((BOOT, BOOT, OTHER_BOOT))
        with self.patched(), patch.object(d, 'bundle_token', return_value='a'*64):
            report, path = d.diagnose(self.adb, self.folder, reply_contract_probe=True, test_only=True,
                inspector=lambda *args: dict(stage='contract-ready', native_metadata=ready()))
        self.assertEqual(report['status'], 'stopped')
        self.assertIs(report['test_session_identity_rechecked'], False)
        self.assertIn(['-s', TARGET, 'forward', '--remove', 'tcp:37149'], self.calls)
        self.assertNotIn(OTHER_BOOT, path.read_text())

    def test_auth_failure_never_falls_back_and_does_not_export_exception(self):
        def failed(*args):
            raise RuntimeError('PRIVATE TOKEN')
        with self.patched(), patch.object(d, 'bundle_token', return_value='a'*64):
            report, path = d.diagnose(self.adb, self.folder, reply_contract_probe=True, test_only=True,
                                     inspector=failed)
        self.assertEqual(report['status'], 'stopped')
        self.assertNotIn('PRIVATE TOKEN', path.read_text())
        self.assertFalse(any(WORKING in a for a in self.calls))
        self.assertIn(['-s', TARGET, 'forward', '--remove', 'tcp:37149'], self.calls)

    def test_scope_cannot_be_enabled_in_sending_or_installer_modes(self):
        for flags in ({}, {'automatic_probe': True}, {'chat_send_probe': True}, {'profile_probe': True},
                      {'reply_contract_probe': True, 'test_only': 'yes'}):
            args = dict(test_only=True); args.update(flags)
            with self.assertRaises(TestError):
                d.diagnose(self.adb, self.folder, **args)
        self.assertEqual(self.calls, [])
        with self.assertRaises(TestError):
            d.diagnose(object(), self.folder, reply_contract_probe=True, test_only=True)

    def test_unrestricted_adb_not_accepted(self):
        with self.assertRaises(TestError):
            p.preflight(object())


if __name__ == '__main__':
    unittest.main()
