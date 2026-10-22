"""Read-only recovery: no handler replay, no weakening of identity/return gates."""
import unittest
from unittest.mock import MagicMock, patch
import test_guided_chain as guide
import test_inbox_profiles as ih
from test_1210_context_loading import Clock, InboxLoading
import assistant_guided_chain as guided
import assistant_inbox as inbox
import assistant_history_wait as wait
from one_chat_device import ReadStopped, safe_read_failure

WHO=guide.WHO

def budget(**changes):
    diagnostic=dict(stage='navigation-stopped',metadata_checkpoint='ready',read_checkpoint='last-message',
        identity_checkpoint='recheck',scalar_checkpoint='message-chat-id',scalar_state='positive',
        wait_reason='none',frames=1,managed_calls=118,message_slot=3,message_kind='text',message_direction='not-own')
    diagnostic.update(changes)
    return ReadStopped('frame-budget',diagnostic)

class ReadRecovery(guide.WholeChain):
    def test_recovers_before_send(self):
        c=Clock();out=self.walk([budget(),budget()]+guide.sequence(),pause=c.pause,read_clock=c)
        self.assertEqual(out['status'],'chain-completed');self.assertEqual(out['submission_calls'],2)
        self.assertEqual(out['diagnostics']['read_retries'],2);self.assertEqual(c.delays[:2],[.5,.5])

    def test_recovers_after_handler_without_replaying(self):
        values=guide.sequence();values.insert(3,budget());values.insert(3,budget())
        out=self.walk(values)
        self.assertEqual(out['status'],'chain-completed');self.assertEqual(out['submission_calls'],2)
        self.assertEqual(len(self.sent),2)

    def test_persistent_after_handler_preserves_reservation(self):
        out=self.walk(guide.sequence()[:3]+[budget()]*4)
        self.assertEqual(out['reason'],'history-read-budget-timeout');self.assertEqual(out['status'],'chain-waiting')
        self.assertEqual(out['submission_calls'],1);self.assertEqual(out['handler_returns'],1)
        self.assertTrue(out['diagnostics']['history_budget_exhausted'])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'handler-returned-unconfirmed')
        # A later verified snapshot confirms the existing send instead of sending again.
        out=self.walk(guide.sequence()[3:]);self.assertEqual(out['status'],'chain-completed')
        self.assertEqual(out['submission_calls'],1);self.assertEqual(len(self.sent),2)

    def test_persistent_initial_read_has_no_journal_side_effects(self):
        reader=MagicMock(side_effect=lambda who: (_ for _ in ()).throw(budget()))
        out=guided.walk(self.chain,WHO,self.stop,self.approve,reader,self.send,approved=True,pause=lambda _:False)
        self.assertEqual(reader.call_count,4);self.assertEqual(out['reason'],'history-read-budget-timeout')
        self.assertFalse(self.sent)
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_dialogs').fetchone()[0],0)

    def test_identity_error_after_retry_remains_global(self):
        out=self.walk([budget(),ReadStopped('identity-changed')])
        self.assertEqual(out['reason'],'bound-chat-read-failed');self.assertFalse(self.sent)

    def test_wrong_snapshot_after_retry_never_sends(self):
        wrong=guide.snapshot();wrong['identity']['peer']='999'
        out=self.walk([budget(),wrong]);self.assertNotEqual(out['reason'],'history-read-budget-timeout');self.assertFalse(self.sent)

    def test_incomplete_evidence_does_not_retry(self):
        for key,value in [('scalar_state','zero'),('metadata_checkpoint','none'),('read_checkpoint','identity'),('wait_reason','history-loading')]:
            self.assertFalse(wait.verified_read_budget(safe_read_failure(budget(**{key:value}))))
        out=self.walk([budget(scalar_state='zero')]);self.assertEqual(out['reason'],'bound-chat-read-failed')
        self.assertEqual(out['diagnostics']['read_retries'],0)

    def test_cancel_during_retry(self):
        def pause(_):self.stop.set();return True
        out=self.walk([budget()],pause=pause);self.assertEqual(out['status'],'chain-cancelled');self.assertFalse(self.sent)

for name in dir(guide.WholeChain):
    if name.startswith('test_') and name not in ReadRecovery.__dict__:setattr(ReadRecovery,name,None)

class InboxRecovery(InboxLoading):
    def deferred(self):
        out=guided.report();out.update(status='chain-waiting',reason='history-read-budget-timeout')
        out['diagnostics'].update(history_budget_exhausted=True,last_read_failure=safe_read_failure(budget()))
        return out

    def test_missing_evidence_stops_without_back(self):
        self.journal();bad=self.deferred();bad['diagnostics']['history_budget_exhausted']=False
        with patch.object(inbox,'walk_chat',return_value=bad):
            out=self.walk([ih.nav('opened',WHO)],[],chain=self.chain())
        self.assertEqual(out['status'],'inbox-stopped');self.assertEqual(self.nav.call_count,1)

class Rules(unittest.TestCase):
    def test_honest_owner_style(self):
        from pathlib import Path
        text=(Path(__file__).resolve().parents[2]/'config/groq-rules.txt').read_text(encoding='utf-8')
        self.assertIn('отвечай честно',text);self.assertIn('не здоровайся снова',text)
        self.assertNotIn('а реальный человек',text);self.assertIn('взрослыми женщинами',text)
