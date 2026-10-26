"""Report 237: a wrong-screen between samples permits fresh reads, never replay."""
import copy,unittest
from unittest.mock import MagicMock
import assistant_guided_chain as guided
import test_guided_chain as g
import test_mumu1345_wrong_screen as previous
from one_chat_device import ReadStopped,safe_read_failure,transient_read_failure,verified_sample_wrong_screen
from mumu_recovery import recoverable


def wrong(**changes):
    value=dict(stage='navigation-stopped',metadata_checkpoint='ready',read_checkpoint='sample',
        wait_reason='none',frames=4,managed_calls=341,message_slot=3,identity_checkpoint='recheck',
        message_kind='text',scalar_checkpoint='chat-id',message_direction='not-own',scalar_state='positive')
    value.update(changes);return ReadStopped('wrong-screen',value)


class Reads(unittest.TestCase):
    setUp=g.WholeChain.setUp
    send=g.WholeChain.send
    walk=previous.Reads.walk
    def test_reproduced237_shape_allows_one_fresh_same_bound_read(self):
        self.assertTrue(transient_read_failure(wrong()))
        self.assertTrue(verified_sample_wrong_screen(safe_read_failure(wrong())))
        sequence=g.sequence();sequence.insert(0,wrong());out=self.walk(sequence)
        self.assertEqual(out['status'],'chain-completed');self.assertEqual(out['diagnostics']['read_retries'],1)
        self.assertEqual(len(self.sent),2)
        self.assertTrue(all(call.args==(g.WHO,) for call in self.reader.call_args_list))
    def test_persistent_sample_failure_no_approval_or_send(self):
        out=self.walk([wrong(),wrong()])
        self.assertEqual(out['reason'],'bound-chat-read-failed');self.assertEqual(self.reader.call_count,2)
        self.assertEqual(out['submission_calls'],0);self.approve.assert_not_called();self.assertFalse(self.sent)
    def test_different_identity_on_fresh_read_stops(self):
        value=copy.deepcopy(g.snapshot());value['identity']['peer']='999'
        out=self.walk([wrong(),value]);self.assertEqual(out['reason'],'guided-binding-changed')
        self.assertFalse(self.sent);self.approve.assert_not_called()
    def test_identity_and_schema_failures_never_enter_retry(self):
        for error in [ReadStopped('identity-changed',wrong().diagnostic),ReadStopped('signature-mismatch',wrong().diagnostic),
                      wrong(identity_checkpoint='saved-binding'),wrong(scalar_state='zero'),wrong(message_slot=-1),
                      wrong(message_slot=True),wrong(read_checkpoint='last-message')]:
            self.assertFalse(transient_read_failure(error))
    def test_after_send_unknown_never_replayed(self):
        sequence=g.sequence();out=self.walk(sequence[:3]+[wrong(),wrong()])
        self.assertEqual(out['reason'],'bound-chat-read-failed');self.assertEqual(len(self.sent),1)
        self.walk([copy.deepcopy(sequence[1]) for _ in range(8)])
        self.assertEqual(len(self.sent),1)
    def test_supervisor_uses_current_read_failure_only(self):
        report=previous.Supervisor().report();d=report['initial_run']['inbox']['last_chat_diagnostics']
        d['last_read_failure']=safe_read_failure(wrong())
        self.assertTrue(recoverable(report))
        for key,value in [('host_checkpoint','chat-proposal'),('error_type','ValueError'),('failure_point','snapshot-validation-failed')]:
            changed=copy.deepcopy(report);changed['initial_run']['inbox']['last_chat_diagnostics'][key]=value
            self.assertFalse(recoverable(changed))
