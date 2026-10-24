"""Uploaded stop shapes reconstructed with fixed synthetic evidence only."""
import json,sqlite3,threading,unittest
from unittest.mock import MagicMock
import startup_failure as failure
from assistant_failure import category
from assistant_error_notify import diagnostic_json
from mumu_recovery import recoverable,run
from assistant_monitor import REPORT
from assistant_settings import Settings
from test_guided_chain import WHO,GREETING
import test_guided_chain as fixture
import assistant_guided_chain as guided


def adb(stage,reason):
    return dict(stage=stage,error='startup-'+stage+'-failed',error_type='TestError',
                adb_check='test-'+stage,adb_reason=reason)
class Recovery(unittest.TestCase):
    def report(self,stage,reason):
        return dict(status='stopped',reason='inbox-pass-stopped',last_pass=dict(status='inbox-stopped',
                    reason='navigation-check-stopped',host_failure='internal-error',last_navigation_failure=adb(stage,reason)))
    def test_forward_disconnect_and_failed_forward_are_recoverable(self):
        for stage,reason in [('forward-close','device-not-found'),('forward-open','command-failed'),('forward-open','command-timeout')]:
            value=adb(stage,reason);self.assertTrue(failure.recoverable_adb(value))
            error=type('TestError',(Exception,),{})('PRIVATE raw output');error._dvk_failure=value
            self.assertEqual(category(error),'native-transport-error')
            self.assertTrue(recoverable(self.report(stage,reason)))
        profile=dict(status='stopped',reason='initial-pass-stopped',initial_run=dict(status='stopped',reason='profiles-not-finished',
                     inbox=dict(status='inbox-completed'),profiles=dict(status='profiles-stopped',host_failure='internal-error',last_preparation_failure=adb('forward-open','command-failed'))))
        self.assertTrue(recoverable(profile))
    def test_unproved_or_security_failures_and_generic_binding_error_stay_blocked(self):
        for reason in ('permission-denied','device-unauthorized','ambiguous-device','unsupported-command','oversized-output','unexpected-response'):
            self.assertFalse(recoverable(self.report('forward-open',reason)),reason)
        for code in ('identity-changed','journal-corrupt','message-not-approved'):
            r=self.report('forward-close','device-not-found');r['last_pass']['reason']=code
            self.assertFalse(recoverable(r))
        self.assertFalse(recoverable(dict(status='stopped',reason='inbox-pass-stopped',last_pass=dict(status='inbox-stopped',reason='chat-binding-or-history-check-stopped'))))
        wrong=adb('forward-open','command-failed');wrong['adb_check']='test-forward-close';self.assertFalse(failure.recoverable_adb(wrong))
    def test_supervisor_restarts_after_transport_repair_without_reset_or_send(self):
        m=MagicMock(side_effect=[self.report('forward-close','device-not-found'),dict(status='cancelled')])
        repair=MagicMock(return_value=True);alerts=MagicMock();states=[]
        out=run(Settings(errors_enabled=True),threading.Event(),None,monitor=m,repair=repair,
                json_alert=alerts,write=lambda value:states.append(value) or REPORT)
        self.assertEqual(out['status'],'cancelled');self.assertEqual(m.call_count,2)
        self.assertFalse(m.call_args.kwargs['fresh_session']);repair.assert_called_once()
        self.assertEqual(alerts.call_args.args[0]['status'],'recovering')
    def test_historical_read_budget_does_not_hide_current_binding_or_journal_fault(self):
        for host in ('internal-error','state-check-failed','journal-corrupt'):
            r=dict(status='stopped',reason='inbox-pass-stopped',last_pass=dict(status='inbox-stopped',reason='chat-binding-or-history-check-stopped',
                   last_chat_diagnostics=dict(host_failure=host,last_read_failure=dict(error='frame-budget',stage='navigation-stopped'))))
            self.assertFalse(recoverable(r),host)
    def test_current_chat_nested_transport_is_detected_but_journal_blocks(self):
        r=dict(status='stopped',reason='inbox-pass-stopped',last_pass=dict(status='inbox-stopped',reason='chat-binding-or-history-check-stopped',
               last_chat_diagnostics=dict(host_failure='native-transport-error',last_navigation_failure=adb('forward-close','device-not-found'))))
        self.assertTrue(recoverable(r));r['last_pass']['last_chat_diagnostics']['host_failure']='journal-corrupt'
        self.assertFalse(recoverable(r))

class Diagnostics(unittest.TestCase):
    def test_hidden_binding_errors_keep_closed_class_without_private_body(self):
        for error,expected in [(sqlite3.IntegrityError('PRIVATE SQL TEXT'),'journal-error'),
                               (RuntimeError('PRIVATE API TOKEN'),'internal-error')]:
            p=fixture.WholeChain('test_all_stages_in_one_run_both_question_variants');p.setUp();self.addCleanup(p.doCleanups)
            out=guided.walk(p.chain,WHO,p.stop,p.approve,MagicMock(side_effect=error),p.send,approved=True)
            self.assertEqual(out['diagnostics']['host_failure'],expected)
            value=json.loads(diagnostic_json(dict(status='stopped',last_chat_diagnostics=out['diagnostics'])))['diagnostic']['last_chat_diagnostics']
            self.assertEqual(value['host_failure'],expected);self.assertNotIn('PRIVATE',json.dumps(value))
            self.assertEqual(value['error_type'],type(error).__name__)
