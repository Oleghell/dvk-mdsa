"""Reported 1.3.8 stops: synthetic only; no emulator, network or send replay."""
import copy
import unittest
from unittest.mock import MagicMock, patch, call
import test_guided_chain as g
import test_inbox_profiles as ih
from test_1214_read_budget import budget
from one_chat_device import ReadStopped, safe_read_failure
import assistant_history_wait as wait
import assistant_guided_chain as guided
import assistant_inbox as inbox
from assistant_contact_photo import capture_profile
from assistant_store import StateError
from test_extensions126 import png


def timeout(**changes):
    failure=budget(**changes)
    return ReadStopped('transition-timeout',failure.diagnostic)


class Reads(g.WholeChain):
    def test_timeout_has_only_one_fresh_retry(self):
        reader=MagicMock(side_effect=lambda who: (_ for _ in ()).throw(timeout()))
        out=guided.walk(self.chain,g.WHO,self.stop,self.approve,reader,self.send,approved=True,pause=lambda _:False)
        self.assertEqual(reader.call_count,2)
        self.assertEqual(out['reason'],'history-read-budget-timeout')
        self.assertTrue(out['diagnostics']['history_budget_exhausted'])
        self.assertFalse(self.sent)

    def test_timeout_can_recover_without_send_replay(self):
        history=g.sequence();history.insert(3,timeout())
        out=self.walk(history)
        self.assertEqual(out['status'],'chain-completed')
        self.assertEqual(len(self.sent),2)

    def test_wrong_timeout_evidence_remains_global(self):
        for changes in ({'metadata_checkpoint':'none'},{'identity_checkpoint':'initial-ids'},
                        {'scalar_state':'negative'},{'read_checkpoint':'not-read'}):
            self.assertFalse(wait.verified_read_budget(safe_read_failure(timeout(**changes))))
        out=self.walk([timeout(scalar_state='negative')])
        self.assertEqual(out['reason'],'bound-chat-read-failed')
        self.assertEqual(out['diagnostics']['read_retries'],0)

    def test_disabled_before_ai_approval_and_reservation(self):
        out=self.walk([dict(g.snapshot(('Привет',False)),input_enabled=False)])
        self.assertEqual(out['reason'],'chat-input-disabled')
        self.assertTrue(out['diagnostics']['input_disabled_verified'])
        self.approve.assert_not_called();self.assertFalse(self.sent)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_actions').fetchone()[0],0)

    def test_disabled_during_approval_never_sends(self):
        sample=g.snapshot(('Привет',False))
        out=self.walk([dict(g.snapshot(),input_enabled=True),dict(sample,input_enabled=True),dict(sample,input_enabled=False)])
        self.assertEqual(out['reason'],'chat-input-disabled');self.assertFalse(self.sent)
        with self.store.connection() as db:
            # The approved draft remains durable, but send was never reserved.
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('awaiting-approval',)])

    def test_final_disabled_keeps_reservation_and_never_replays(self):
        with patch.object(self,'send',return_value=FinalSendGate().proof()) as sender:
            out=self.walk(g.sequence()[:3])
        self.assertEqual(out['reason'],'chat-input-disabled');self.assertEqual(sender.call_count,1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'unknown')
        out=self.walk(g.sequence()[:3]);self.assertFalse(self.sent)

    def test_false_input_does_not_override_wrong_identity(self):
        value=dict(g.snapshot(),input_enabled=False);value['identity']['peer']='999'
        out=self.walk([value])
        self.assertEqual(out['reason'],'guided-binding-changed');self.assertFalse(self.sent)
        self.assertNotIn('input_disabled_verified',out['diagnostics'])

    def test_bad_input_type_is_not_skip_proof(self):
        out=self.walk([dict(g.snapshot(),input_enabled=0)])
        self.assertEqual(out['reason'],'snapshot-validation-failed');self.assertFalse(self.sent)

for name in dir(g.WholeChain):
    if name.startswith('test_') and name not in Reads.__dict__:setattr(Reads,name,None)


class Profiles(unittest.TestCase):
    def device(self):
        dev=MagicMock();dev.screen.return_value=png();return dev

    def test_wrong_profile_and_failed_chat_read_never_back(self):
        dev=self.device();chat=MagicMock(side_effect=[g.snapshot(),RuntimeError(),RuntimeError()])
        with self.assertRaisesRegex(StateError,'profile-return-not-verified'):
            capture_profile('adb','folder',g.WHO,device_factory=lambda *a:dev,chat_reader=chat,
                profile_reader=MagicMock(side_effect=StateError('profile-not-verified')))
        self.assertNotIn(call(['shell','input','keyevent','4']),dev.run.call_args_list)

    def test_noop_tap_transient_read_failure_never_back(self):
        dev=self.device();chat=MagicMock(side_effect=[g.snapshot(),RuntimeError(),g.snapshot()])
        with self.assertRaisesRegex(StateError,'profile-photo-unavailable'):
            capture_profile('adb','folder',g.WHO,device_factory=lambda *a:dev,chat_reader=chat,
                profile_reader=MagicMock(side_effect=StateError('profile-not-verified')))
        self.assertNotIn(call(['shell','input','keyevent','4']),dev.run.call_args_list)

    def test_wrong_chat_after_single_verified_back_stops(self):
        dev=self.device();wrong=copy.deepcopy(g.snapshot());wrong['identity']['peer']='999'
        with self.assertRaisesRegex(StateError,'profile-return-not-verified'):
            capture_profile('adb','folder',g.WHO,device_factory=lambda *a:dev,
                chat_reader=MagicMock(side_effect=[g.snapshot(),wrong]),profile_reader=lambda *a:True)
        self.assertEqual(dev.run.call_args_list.count(call(['shell','input','keyevent','4'])),1)

    def test_default_check_is_identity_only(self):
        dev=self.device()
        with patch('one_chat_device.capture',return_value={'identity':g.WHO,'messages':None}) as reader:
            with self.assertRaisesRegex(StateError,'profile-photo-unavailable'):
                capture_profile('adb','folder',g.WHO,device_factory=lambda *a:dev,
                    profile_reader=MagicMock(side_effect=StateError('profile-not-verified')))
        self.assertTrue(reader.call_args_list)
        for args in reader.call_args_list:
            self.assertEqual(len(args.args),3);self.assertFalse(args.kwargs)


class Inbox(ih.Base):
    def test_disabled_is_durable_local_skip(self):
        self.journal();sample=dict(ih.snap(),input_enabled=False)
        out=self.walk([ih.nav('opened',ih.WHO),ih.nav('returned',ih.WHO),ih.nav('search-ready')],
                      [sample],chain=self.chain())
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['isolated_reasons'].get('chat-input-disabled'),1)
        self.assertFalse(self.sent)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs').fetchone()[0],'manual-review')
        self.assertFalse(inbox.inbox_targets(self.chain())[1])

    def test_read_timeout_defers_only_after_verified_back(self):
        self.journal();chain=self.chain()
        out=guided.report();out.update(status='chain-waiting',reason='history-read-budget-timeout')
        out['diagnostics'].update(history_budget_exhausted=True,last_read_failure=safe_read_failure(timeout()))
        with patch.object(inbox,'walk_chat',return_value=out):
            result=self.walk([ih.nav('opened',ih.WHO),ih.nav('returned',ih.WHO),ih.nav('search-ready')],[],chain=chain)
        self.assertEqual(result['status'],'inbox-completed');self.assertEqual(result['history_deferred'],1)
        attention,unread,skipped=wait.eligible(self.store,[ih.WHO],[ih.WHO])
        self.assertEqual((attention,unread,skipped),([],[],1))

    def test_wrong_back_never_becomes_local_timeout(self):
        self.journal();chain=self.chain()
        out=guided.report();out.update(status='chain-waiting',reason='history-read-budget-timeout')
        out['diagnostics'].update(history_budget_exhausted=True,last_read_failure=safe_read_failure(timeout()))
        with patch.object(inbox,'walk_chat',return_value=out):
            result=self.walk([ih.nav('opened',ih.WHO),ih.nav('returned',ih.OTHER)],[],chain=chain)
        self.assertEqual(result['status'],'inbox-stopped');self.assertEqual(result['history_deferred'],0)
        self.assertEqual(wait.eligible(self.store,[ih.WHO],[])[2],0)

    def test_skip_proof_is_required(self):
        out=guided.report();out.update(reason='chat-input-disabled',status='chain-needs-review')
        self.assertIsNone(inbox.isolation_reason(out))

class FinalSendGate(unittest.TestCase):
    def proof(self):
        return dict(attempted=False,handler_returned=False,native_check=dict(
            root_stage='root-ready',navigation_stage='navigation-stopped',navigation_error='input-disabled',
            metadata_checkpoint='ready',read_checkpoint='sample',wait_reason='none',
            scalar_checkpoint='chat-id',scalar_state='positive',identity_checkpoint='recheck',
            message_slot=1,message_kind='text',message_direction='not-own'))

    def test_only_complete_native_no_attempt_proof(self):
        from one_chat_send import input_disabled_before_submission as check
        self.assertTrue(check(self.proof()))
        for field in self.proof()['native_check']:
            value=self.proof();del value['native_check'][field];self.assertFalse(check(value))
        for key,value in [('attempted',True),('attempted',0),('handler_returned',True)]:
            proof=self.proof();proof[key]=value;self.assertFalse(check(proof))
        proof=self.proof();proof['native_check']['navigation_error']='managed-exception'
        self.assertFalse(check(proof))
