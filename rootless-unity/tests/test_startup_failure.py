"""Synthetic startup fault injection. No accounts, credentials or device access."""
import copy
import json
import unittest
from unittest.mock import MagicMock, patch

import startup_failure as failure
import assistant_monitor as monitor
import assistant_error_notify as notify
import search_online as online
import dialog_browser as browser
from one_chat_device import ReadStopped
from test_search_online import OnlineFake
import test_assistant_monitor as harness
from test_assistant_monitor import list_result
from test_dialog_browser import raw_open, TARGET

PRIVATE = 'PRIVATE TOKEN PHONE CHAT PATH'

class Evidence(unittest.TestCase):
    def test_no_raw_exception_data_for_every_stage(self):
        for stage in failure.STAGES:
            error=RuntimeError(PRIVATE)
            value=failure.record(error,stage)
            self.assertEqual(failure.clean(value),value)
            self.assertNotIn(PRIVATE,json.dumps(value))
            self.assertIsNotNone(failure.message(value))
    def test_keep_innermost_stage(self):
        error=ValueError(PRIVATE)
        first=failure.record(error,'result-validation')
        self.assertEqual(failure.record(error,'device-inspection'),first)
    def test_reject_forged_evidence(self):
        for value in (None,{},dict(stage=PRIVATE,error=PRIVATE,error_type=PRIVATE),
                      dict(stage='script-run',error='startup-script-run-failed',error_type='RPCException',body=PRIVATE),
                      dict(stage=[],error=[],error_type=[])):
            self.assertIsNone(failure.clean(value))
        e=RuntimeError(PRIVATE);e._dvk_failure={'body':PRIVATE}
        self.assertNotIn(PRIVATE,json.dumps(failure.record(e,'script-run')))
    def test_only_authored_fixed_read_codes(self):
        for cls in (ReadStopped,RuntimeError):
            for code in ('client-version',PRIVATE):
                v=failure.record(cls(code),'runtime-check')
                self.assertEqual(v['error'],'client-version' if cls is ReadStopped and code=='client-version' else 'startup-runtime-check-failed')
    def test_checkpoint_preserves_exception_identity(self):
        e=ValueError(PRIVATE)
        with self.assertRaises(ValueError) as raised:
            with failure.checkpoint('result-validation'):raise e
        self.assertIs(raised.exception,e)
        self.assertEqual(e._dvk_failure['stage'],'result-validation')

class InspectStages(unittest.TestCase):
    def invoke(self,f,**kw):
        return online.inspect(37149,PRIVATE,lambda:False,frida_api=f,**kw)
    def test_each_stage_is_reported_and_never_retried(self):
        for method,stage in [('get_device_manager','gadget-manager'),('add_remote_device','gadget-connect'),
                 ('enumerate_processes','gadget-process'),('attach','gadget-attach'),
                 ('create_script','script-create'),('load','script-load')]:
            f=OnlineFake();bad=MagicMock(side_effect=RuntimeError(PRIVATE));setattr(f,method,bad)
            with self.assertRaises(RuntimeError) as raised:self.invoke(f)
            self.assertEqual(raised.exception._dvk_failure['stage'],stage)
            bad.assert_called_once()
            self.assertNotIn(PRIVATE,json.dumps(raised.exception._dvk_failure))
            if stage in ('script-create','script-load'):self.assertTrue(f.detached and f.removed)
    def test_rpc_and_validation_are_distinct(self):
        for phase in ('runtime-check','script-run','result-validation'):
            f=OnlineFake();original=f.create_script
            rpc=MagicMock(side_effect=RuntimeError(PRIVATE))
            def create(*a,**kw):
                result=original(*a,**kw)
                if phase=='runtime-check':f.exports_sync.runtime=rpc
                if phase=='script-run':f.exports_sync.root=rpc
                return result
            f.create_script=create
            kw={'validator':rpc} if phase=='result-validation' else {}
            with self.assertRaises(RuntimeError) as raised:self.invoke(f,**kw)
            self.assertEqual(raised.exception._dvk_failure['stage'],phase)
            rpc.assert_called_once()
            self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_wrong_client_has_authored_reason(self):
        f=OnlineFake();f.__version__='0'
        with self.assertRaises(ReadStopped) as raised:self.invoke(f)
        self.assertEqual(raised.exception._dvk_failure['error'],'client-version')

class StartupMonitor(unittest.TestCase):
    setUp=harness.Monitor.setUp
    lock=harness.Monitor.lock
    write=harness.Monitor.write
    wait_stop=harness.Monitor.wait_stop
    run_monitor=harness.Monitor.run_monitor
    def test_startup_transport_failure_saved_no_initial_or_inbox_send(self):
        e=RuntimeError(PRIVATE);failure.record(e,'gadget-connect')
        self.navigator.side_effect=e
        out=self.run_monitor()
        self.initial.assert_not_called();self.inbox.assert_not_called()
        self.navigator.assert_called_once()
        self.assertEqual(out['last_navigation_failure']['stage'],'gadget-connect')
        self.assertEqual(out['last_navigation_failure']['operation'],'list')
        self.assertEqual(out['reason'],'dialog-list-not-verified')
        self.assertTrue(out['ui_may_remain_open'])
        self.assertIn('startup-gadget-connect-failed',notify.reasons(out))
        self.assertIn('компоненту внутри приложения',monitor.summary(out))
        self.assertNotIn(PRIVATE,json.dumps(self.reports))
    def test_return_failure_not_confused_with_list_and_no_initial(self):
        e=ValueError(PRIVATE);failure.record(e,'script-run')
        self.navigator.side_effect=[list_result(),e]
        out=self.run_monitor()
        self.assertIsNone(out['last_navigation'])
        self.assertEqual(out['last_navigation_failure']['operation'],'return')
        self.assertEqual(out['reason'],'search-screen-not-verified')
        self.initial.assert_not_called()
    def test_malformed_result_and_diagnostic_not_confused(self):
        for value,stage in [({'body':PRIVATE},'navigation-result'),
                     (dict(list_result(),diagnostic={'body':PRIVATE}),'navigation-diagnostic'),
                     (dict(list_result(),state='stopped'),'navigation-destination')]:
            self.navigator.side_effect=None;self.navigator.return_value=value
            out=self.run_monitor()
            self.assertEqual(out['last_navigation_failure']['stage'],stage)
            self.initial.assert_not_called()
            self.assertNotIn(PRIVATE,json.dumps(out))
    def test_preserve_safe_native_diagnostic_without_raw_rpc(self):
        e=ValueError(PRIVATE);e._dvk_navigation=list_result()['diagnostic']
        self.navigator.side_effect=e
        out=self.run_monitor()
        self.assertEqual(out['last_navigation'],list_result()['diagnostic'])
        self.assertNotIn(PRIVATE,json.dumps(out))
    def test_notify_closed_reason_and_plain_explanation_only(self):
        e=ValueError(PRIVATE);failure.record(e,'result-validation');self.navigator.side_effect=e
        out=self.run_monitor();send=MagicMock(return_value=True)
        self.assertEqual(notify.notify(out,loader=lambda:('secret','private-id'),sender=send),'accepted')
        text=send.call_args.args[2]
        self.assertIn('неподтверждённый результат',text)
        self.assertNotIn(PRIVATE,text)

class RejectedNativeResult(unittest.TestCase):
    def run_result(self,result):
        def fake_capture(*a,inspector,**kw):
            return inspector(37149,PRIVATE,lambda:False,None)
        def fake_inspect(*a,validator,**kw):
            return validator(result)
        with patch('one_chat_device.capture',side_effect=fake_capture),patch('search_online.inspect',side_effect=fake_inspect):
            return browser.perform('open','ADB','APK',allowed=[TARGET])
    def test_rejected_extra_rpc_keeps_only_closed_diagnostic(self):
        value=raw_open();value['navigation']['body']=PRIVATE
        with self.assertRaises(ValueError) as raised:self.run_result(value)
        self.assertEqual(raised.exception._dvk_navigation['metadata_checkpoint'],'ready')
        self.assertNotIn(PRIVATE,json.dumps(raised.exception._dvk_navigation))
        self.assertNotIn('private_identity',raised.exception._dvk_navigation)
    def test_bad_native_category_is_not_exported(self):
        value=raw_open();value['navigation']['metadata_checkpoint']=PRIVATE
        with self.assertRaises(ValueError) as raised:self.run_result(value)
        self.assertFalse(hasattr(raised.exception,'_dvk_navigation'))
    def test_valid_result_unchanged(self):
        self.assertEqual(self.run_result(raw_open())['state'],'opened')

class AdbEvidence(unittest.TestCase):
    def test_only_failed_authored_adb_check_is_preserved(self):
        from types import SimpleNamespace
        adb=SimpleNamespace(adb_events=[dict(check='test-connect',status='failed',reason='connection-refused',raw=PRIVATE)])
        with self.assertRaises(RuntimeError) as raised:
            with failure.checkpoint('adb-preflight',adb=adb):raise RuntimeError(PRIVATE)
        v=raised.exception._dvk_failure
        self.assertEqual(v['adb_reason'],'connection-refused')
        self.assertEqual(failure.clean(v),v)
        self.assertIn('отклонил',failure.message(dict(v,operation='list')))
        self.assertNotIn(PRIVATE,json.dumps(v))
    def test_unrecognized_or_private_adb_fields_never_leave_memory(self):
        from types import SimpleNamespace
        for event in (dict(check=PRIVATE,status='failed',reason='connection-refused'),
                      dict(check='test-connect',status='failed',reason=PRIVATE),
                      dict(check='working-state',status='failed',reason='device-offline'),
                      dict(check='test-connect',status='passed',reason='none'),
                      dict(check=[],status='failed',reason=[])):
            with self.assertRaises(RuntimeError) as raised:
                with failure.checkpoint('adb-preflight',adb=SimpleNamespace(adb_events=[event])):
                    raise RuntimeError(PRIVATE)
            self.assertNotIn('adb_reason',raised.exception._dvk_failure)
            self.assertNotIn(PRIVATE,json.dumps(raised.exception._dvk_failure))
    def test_reject_partial_adb_evidence(self):
        v=dict(stage='adb-preflight',error='startup-adb-preflight-failed',error_type='TestError')
        self.assertIsNone(failure.clean(dict(v,adb_reason='connection-refused')))
        self.assertIsNone(failure.clean(dict(v,adb_check='test-connect',adb_reason=PRIVATE)))
