"""User-authorized one-retry reply recovery; synthetic DB and snapshots only."""
import copy,threading,unittest,tempfile
from pathlib import Path
from unittest.mock import MagicMock,patch
import assistant_unknown_reply as retry
import assistant_guided_chain as guide
from assistant_store import Store
from assistant_chain import text_hash
from conversation_engine import QUESTIONS
import test_guided_chain as fixtures

class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db',Path(self.tmp.name)/'old')
        self.chain=guide.GuidedChain(self.store,choose=lambda:0,seal=lambda v:v,unseal=lambda v:v)
        self.chain.bind(fixtures.snapshot(),(fixtures.GREETING,),approved=True)
        self.snapshot=fixtures.snapshot(('Привет',False))
        stage,self.action=self.chain.proposal(self.snapshot)
        self.assertEqual(stage,'pending-question')
        self.session=self.chain.reserve_confirmed(fixtures.WHO,self.action)
        self.chain.finish(fixtures.WHO,self.action,False)
        retry.enable(self.chain)
    def row(self):
        with self.store.read_connection() as db:return db.execute('SELECT status FROM chain_actions WHERE kind=\'question\'').fetchone()[0]
    def recover(self,current=None):return retry.recover(self.chain,self.snapshot,current or self.snapshot)
    def test_unknown_is_archived_and_only_one_new_authorization_can_be_made(self):
        from assistant_send_safety import begin
        self.assertEqual(self.recover(),'prepared');self.assertEqual(self.row(),'awaiting-approval')
        stage,action=self.chain.proposal(self.snapshot);self.assertEqual(action,self.action)
        new=self.chain.reserve_confirmed(fixtures.WHO,action);self.assertNotEqual(new,self.session)
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT original_status,state FROM chain_unknown_reply_retries').fetchone(),('unknown','reserved'))
            self.assertEqual(db.execute('SELECT status FROM chain_send_authorizations WHERE session=?',(self.session,)).fetchone()[0],'superseded-unknown')
        self.chain.finish(fixtures.WHO,action,False)
        self.assertEqual(self.recover(),'retry-used');self.assertEqual(self.row(),'unknown')
        self.assertEqual(self.chain.proposal(self.snapshot),('submission-unknown',None))
        self.assertEqual(retry.targets(self.chain),set())
        # A stale original authorization cannot become live again.
        with self.assertRaises(Exception):begin(self.chain,self.session,fixtures.WHO,self.action)
    def test_original_actual_attempt_is_never_deleted_or_marked_successful(self):
        with self.store.connection() as db:
            from assistant_send_safety import tables
            tables(db)
            db.execute("INSERT INTO chain_send_attempts(session,outcome) VALUES(?,'unknown')",(self.session,))
            db.execute("UPDATE chain_send_authorizations SET status='unknown' WHERE session=?",(self.session,))
        self.assertEqual(self.recover(),'prepared')
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT session,outcome FROM chain_send_attempts').fetchall(),[(self.session,'unknown')])
            self.assertEqual(db.execute('SELECT status FROM chain_send_authorizations WHERE session=?',(self.session,)).fetchone(),('unknown',))

    def test_hard_kill_reserved_unknown_is_eligible_once(self):
        with self.store.connection() as db:db.execute("UPDATE chain_actions SET status='reserved-unknown'")
        self.assertEqual(self.recover(),'prepared')
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT original_status FROM chain_unknown_reply_retries').fetchone()[0],'reserved-unknown')
    def test_prepared_retry_survives_restart_but_spent_retry_does_not_reset(self):
        self.assertEqual(self.recover(),'prepared')
        fresh=guide.GuidedChain(self.store,choose=lambda:0,seal=lambda v:v,unseal=lambda v:v);retry.enable(fresh)
        self.assertIn(tuple(fixtures.WHO[k] for k in ('account','peer','chat')),retry.targets(fresh))
        self.assertEqual(fresh.proposal(self.snapshot)[1],self.action)
        fresh.reserve_confirmed(fixtures.WHO,self.action) # crash before actual adapter
        self.assertEqual(retry.recover(fresh,self.snapshot,self.snapshot),'retry-used')
    def test_exact_visible_outgoing_is_observed_without_retry_or_fake_return(self):
        current=fixtures.snapshot(('Привет',False),(self.action['text'],True))
        self.assertEqual(retry.recover(self.chain,current,current),'observed');self.assertEqual(self.row(),'outgoing-observed')
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs').fetchone()[0],'wait-mood')
            self.assertEqual(db.execute('SELECT original_status,state FROM chain_unknown_reply_retries').fetchone(),('unknown','observed'))
            self.assertEqual(db.execute('SELECT status FROM chain_send_authorizations WHERE session=?',(self.session,)).fetchone()[0],'active')
    def test_different_outgoing_is_never_retried(self):
        current=fixtures.snapshot(('Привет',False),('Другой ответ',True))
        self.assertEqual(retry.recover(self.chain,current,current),'outgoing-conflict');self.assertEqual(self.row(),'unknown')
    def test_current_refusal_prevents_retry(self):
        current=fixtures.snapshot(('Привет',False),('Не пиши мне',False))
        self.assertEqual(retry.recover(self.chain,current,current),'blocked');self.assertEqual(self.row(),'unknown')
    def test_different_reads_and_edited_history_do_not_prepare_retry(self):
        changed=fixtures.snapshot(('Привет',False),('Другое сообщение',False))
        self.assertEqual(self.recover(changed),'changing-history')
        edited=copy.deepcopy(self.snapshot);edited['messages'][0]['text']='Изменено'
        self.assertEqual(retry.recover(self.chain,edited,edited),'history-changed');self.assertEqual(self.row(),'unknown')
    def test_terminal_stage_never_reopened(self):
        for stage in ('declined','done','manual-review'):
            with self.store.connection() as db:db.execute('UPDATE chain_dialogs SET stage=?',(stage,))
            self.assertFalse(retry.candidate(self.chain,fixtures.WHO));self.assertEqual(self.recover(),'not-pending')
    def test_missing_encrypted_draft_is_not_replaced_by_generated_reply(self):
        with self.store.connection() as db:db.execute('UPDATE chain_actions SET text_hash=?',(text_hash('Неизвестный черновик'),))
        self.chain.responder=MagicMock(side_effect=AssertionError('No AI in recovery'))
        self.assertEqual(self.recover(),'draft-unavailable');self.chain.responder.assert_not_called()
    def test_disabled_policy_retains_original_behavior(self):
        self.chain.retry_unknown_once=False
        self.assertFalse(retry.candidate(self.chain,fixtures.WHO));self.assertEqual(self.recover(),'disabled')
        self.assertEqual(self.chain.proposal(self.snapshot),('submission-unknown',None))
    def test_walk_rechecks_and_sends_only_once_with_existing_approval_and_native_guard(self):
        after=fixtures.snapshot(('Привет',False),(self.action['text'],True));reads=iter([self.snapshot,self.snapshot,self.snapshot,self.snapshot,after]);sent=[]
        def sender(snapshot,text):sent.append(text);return dict(attempted=True,handler_returned=True)
        out=guide.walk(self.chain,fixtures.WHO,threading.Event(),lambda *a:True,lambda _:next(reads),sender,
            approved=True,greetings=(fixtures.GREETING,),until_waiting=True,pause=lambda _:False)
        self.assertEqual(out['reason'],'wait-mood',out['diagnostics']);self.assertEqual(sent,[self.action['text']])
        self.assertEqual(out['submission_calls'],1);self.assertTrue(out['diagnostics']['post_send_checked'])
    def test_reported_seen_input_hint_is_bypassed_only_for_unspent_recovery(self):
        from assistant_inbox import with_seen_ids
        self.assertEqual(with_seen_ids(self.chain,[fixtures.WHO])[0]['seen_ids'],[])
        self.assertEqual(self.recover(),'prepared');self.chain.reserve_confirmed(fixtures.WHO,self.action);self.chain.finish(fixtures.WHO,self.action,False)
        self.assertEqual(retry.targets(self.chain),set())

class ContactRecovery(Recovery):
    def setUp(self):
        super().setUp()
        # Complete the original question synthetically, then interrupt contact.
        self.assertEqual(self.recover(),'prepared')
        self.chain.reserve_confirmed(fixtures.WHO,self.action);self.chain.finish(fixtures.WHO,self.action,True)
        question=(self.action['text'],True)
        self.chain.proposal(fixtures.snapshot(('Привет',False),question))
        self.snapshot=fixtures.snapshot(('Привет',False),question,('Сам как? / Супер',False))
        stage,self.action=self.chain.proposal(self.snapshot)
        self.assertEqual(stage,'pending-contact')
        self.session=self.chain.reserve_confirmed(fixtures.WHO,self.action);self.chain.finish(fixtures.WHO,self.action,False)
    def test_contact_unknown_restores_exact_same_proposal_without_new_ai(self):
        self.assertEqual(self.recover(),'prepared')
        self.assertEqual(self.chain.proposal(self.snapshot),('pending-contact',self.action))
        self.chain.reserve_confirmed(fixtures.WHO,self.action);self.chain.finish(fixtures.WHO,self.action,False)
        self.assertEqual(self.recover(),'retry-used')
    def test_uncertain_returned_handler_also_has_only_one_retry(self):
        with self.store.connection() as db:db.execute("UPDATE chain_actions SET status='handler-returned-unconfirmed' WHERE kind='contact'")
        self.assertEqual(self.recover(),'prepared')
    def test_user_notification_describes_retry_not_permanent_skip(self):
        from assistant_exit_notify import notify_exit
        sent=[]
        result=dict(reason='send-outcome-unknown')
        notify_exit(self.chain,fixtures.WHO,result,sender=lambda text:sent.append(text) or True)
        self.assertIn('одна повторная попытка',sent[0]);self.assertNotIn('Повторной отправки не будет',sent[0])
for name in dir(Recovery):
    if name.startswith('test_') and name not in ContactRecovery.__dict__:setattr(ContactRecovery,name,None)
