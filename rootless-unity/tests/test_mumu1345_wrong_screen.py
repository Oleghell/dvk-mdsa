"""Report 168: early wrong-screen after pacing; fresh reads never prove sending."""
import copy,unittest
from unittest.mock import MagicMock
from one_chat_device import ReadStopped,safe_read_failure,transient_read_failure,verified_early_wrong_screen
import assistant_guided_chain as guided
import test_guided_chain as g
from mumu_recovery import recoverable


def wrong(**changes):
    value=dict(stage='navigation-stopped',metadata_checkpoint='ready',read_checkpoint='not-checked',
        wait_reason='not-checked',frames=6,managed_calls=95,message_slot=-1,message_kind='not-read',
        message_direction='not-read',scalar_state='not-read',identity_checkpoint='not-checked',scalar_checkpoint='not-read')
    value.update(changes)
    return ReadStopped('wrong-screen',value)


class Reads(unittest.TestCase):
    setUp=g.WholeChain.setUp
    send=g.WholeChain.send
    def walk(self,items):
        self.reader=MagicMock(side_effect=items)
        return guided.walk(self.chain,g.WHO,self.stop,self.approve,self.reader,self.send,
            approved=True,greetings=(g.GREETING,),notifier=self.notifier,pause=lambda _:False,max_polls=12)
    def test_report_after_pacing_gets_fresh_bound_read_not_second_send(self):
        sequence=g.sequence();sequence.insert(2,wrong())
        out=self.walk(sequence)
        self.assertEqual(out['status'],'chain-completed')
        self.assertEqual(out['diagnostics']['read_retries'],1)
        self.assertEqual(len(self.sent),2)
        self.assertEqual(out['submission_calls'],2)
        self.assertTrue(all(call.args==(g.WHO,) for call in self.reader.call_args_list))
    def test_persistent_wrong_screen_retries_once_with_no_send_or_ui(self):
        out=self.walk([wrong(),wrong()])
        self.assertEqual(self.reader.call_count,2);self.assertEqual(out['reason'],'bound-chat-read-failed')
        self.assertEqual(out['diagnostics']['read_retries'],1)
        self.assertEqual(out['submission_calls'],0);self.assertFalse(self.sent)
        self.approve.assert_not_called()
    def test_fresh_wrong_identity_still_blocks_after_retry(self):
        different=copy.deepcopy(g.snapshot());different['identity']['peer']='999'
        out=self.walk([wrong(),different])
        self.assertEqual(out['reason'],'guided-binding-changed')
        self.assertFalse(self.sent);self.approve.assert_not_called()
    def test_post_send_wrong_screen_never_replays_returned_unconfirmed_send(self):
        sequence=g.sequence()
        out=self.walk(sequence[:3]+[wrong(),wrong()])
        self.assertEqual(out['reason'],'bound-chat-read-failed')
        self.assertEqual(len(self.sent),1)
        with self.store.connection() as db:
            before=db.execute('SELECT COUNT(*) FROM chain_send_attempts').fetchone()[0]
        self.walk([copy.deepcopy(sequence[1]) for _ in range(8)])
        self.assertEqual(len(self.sent),1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_send_attempts').fetchone()[0],before)

    def test_unverified_and_identity_read_failures_are_not_transient(self):
        self.assertTrue(transient_read_failure(wrong()))
        for error in [ReadStopped('wrong-screen'),wrong(identity_checkpoint='recheck'),wrong(scalar_state='positive'),ReadStopped('identity-not-bound',wrong().diagnostic)]:
            self.assertFalse(transient_read_failure(error))
        out=self.walk([ReadStopped('wrong-screen')])
        self.assertEqual(self.reader.call_count,1);self.assertEqual(out['diagnostics']['read_retries'],0)


class Supervisor(unittest.TestCase):
    def report(self):
        diagnostics=dict(failure_point='bound-chat-read-failed',host_failure='internal-error',host_checkpoint='chat-read',
            error_type='ReadStopped',last_read_failure=safe_read_failure(wrong()),
            last_navigation_failure=dict(stage='device-inspection',error='startup-device-inspection-failed',error_type='OtherError'))
        return dict(status='stopped',reason='initial-pass-stopped',initial_run=dict(status='stopped',reason='inbox-not-finished',
            inbox=dict(status='inbox-stopped',reason='chat-bound-chat-read-failed',last_chat_diagnostics=diagnostics)))
    def test_report168_enters_safe_repair_not_a_final_stop(self):
        self.assertTrue(recoverable(self.report()))
    def test_supervisor_continues_only_after_repair_verifies_screen(self):
        from assistant_settings import Settings
        from assistant_monitor import REPORT
        import mumu_recovery,threading
        monitor=MagicMock(side_effect=[self.report(),dict(status='completed')])
        repair=MagicMock(return_value=True)
        out=mumu_recovery.run(Settings(errors_enabled=False),threading.Event(),MagicMock(),
            monitor=monitor,repair=repair,write=lambda _:REPORT)
        self.assertEqual(out['status'],'completed')
        self.assertEqual(monitor.call_count,2);repair.assert_called_once()

    def test_stale_wrong_screen_cannot_hide_other_failures(self):
        for changes in [dict(host_checkpoint='chat-proposal'),dict(error_type='ValueError'),dict(failure_point='snapshot-validation-failed')]:
            report=self.report();report['initial_run']['inbox']['last_chat_diagnostics'].update(changes)
            self.assertFalse(recoverable(report))
        report=self.report();report['initial_run']['inbox']['last_chat_diagnostics']['last_read_failure']['error']='identity-changed'
        self.assertFalse(recoverable(report))
