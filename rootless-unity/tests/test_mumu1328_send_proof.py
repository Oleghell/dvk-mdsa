"""No screenshot or missing outgoing is proof of a failed send. Synthetic only."""
import copy,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import assistant_guided_chain as guided
import assistant_send_safety as safety
from assistant_error_notify import diagnostic_json
from assistant_store import StateError
from one_chat_send import no_submission_proof
from one_chat_send_device import SubmissionNotStarted
import test_guided_chain as guide
from test_guided_chain import snapshot,WHO,GREETING
from test_inbox_profiles import Base,nav,snap,msg
from conversation_engine import QUESTIONS


def no_attempt(error='frame-budget'):
    return dict(attempted=False,handler_returned=False,native_check=dict(
        root_stage='root-ready',navigation_stage='navigation-stopped',navigation_error=error,
        metadata_checkpoint='ready',read_checkpoint='sample',wait_reason='none',
        scalar_checkpoint='chat-id',scalar_state='positive',identity_checkpoint='recheck',
        message_slot=1,message_kind='text',message_direction='not-own'))


class Proof(unittest.TestCase):
    def test_only_closed_native_no_invocation_proof_is_accepted(self):
        self.assertEqual(no_submission_proof(no_attempt()),'frame-budget')
        for change in (dict(attempted=True),dict(handler_returned=True),dict(attempted=0),dict(native_check=None)):
            self.assertIsNone(no_submission_proof(dict(no_attempt(),**change)))
        for error in ('managed-exception','submission-already-attempted','identity-not-bound','signature-mismatch','send-setup-unavailable'):
            self.assertIsNone(no_submission_proof(no_attempt(error)),error)
        for change in (dict(metadata_checkpoint='base'),dict(root_stage='not-ready'),dict(navigation_error='PRIVATE'),dict(extra='PRIVATE')):
            value=no_attempt();value['native_check'].update(change)
            self.assertIsNone(no_submission_proof(value))
    def test_diagnostic_exports_no_message_or_session(self):
        raw=diagnostic_json(dict(last_chat_diagnostics=dict(send_no_invocation_verified=True,
            send_preflight_retries=2,submission_attempted=False,submission_returned=False,
            last_send_failure='send-setup-unavailable',text='PRIVATE',session='PRIVATE')))
        self.assertNotIn(b'PRIVATE',raw)
        d=json.loads(raw)['diagnostic']['last_chat_diagnostics']
        self.assertTrue(d['send_no_invocation_verified']);self.assertEqual(d['send_preflight_retries'],2)
        self.assertEqual(d['last_send_failure'],'send-setup-unavailable')


class Recovery(unittest.TestCase):
    setUp=guide.WholeChain.setUp
    send=guide.WholeChain.send
    walk=guide.WholeChain.walk
    def bound(self):
        self.chain.bind(snapshot(),(GREETING,),approved=True)
        return snapshot(('Здравствуйте',False))
    def rows(self):
        with self.store.connection() as db:
            return db.execute('SELECT outcome FROM chain_send_attempts ORDER BY id').fetchall()
    def test_two_proven_prechecks_then_one_send_not_three_sends(self):
        before=self.bound();after=snapshot(('Здравствуйте',False),(QUESTIONS[0],True))
        send=MagicMock(side_effect=[no_attempt(),no_attempt(),dict(attempted=True,handler_returned=True)])
        with patch.object(self,'send',send):out=self.walk([before,before,after,after],until_waiting=True)
        self.assertEqual(out['status'],'chain-waiting');self.assertEqual(out['stage'],'wait-mood')
        self.assertEqual(send.call_count,3);self.assertEqual(out['handler_returns'],1)
        self.assertEqual(self.rows(),[('not-invoked',),('not-invoked',),('handler-returned',)])
    def test_three_prechecks_defer_and_keep_hash_draft_and_pending_input(self):
        before=self.bound();send=MagicMock(return_value=no_attempt())
        with patch.object(self,'send',send):out=self.walk([before,before],until_waiting=True)
        self.assertEqual(out['reason'],'send-preflight-deferred');self.assertEqual(send.call_count,3)
        self.assertTrue(out['diagnostics']['send_no_invocation_verified']);self.assertEqual(self.rows(),[('not-invoked',)]*3)
        with self.store.connection() as db:
            row=db.execute('SELECT text_hash,status FROM chain_actions').fetchone()
            self.assertEqual(row[1],'awaiting-approval')
            self.assertEqual(db.execute('SELECT status FROM chain_send_authorizations').fetchone()[0],'not-invoked')
        # Fresh consent/full reads may resume only the proved unsent draft.
        after=snapshot(('Здравствуйте',False),(QUESTIONS[0],True))
        with patch.object(self,'send',return_value=dict(attempted=True,handler_returned=True)) as retry:
            out=self.walk([before,before,after,after],until_waiting=True)
        self.assertEqual(out['stage'],'wait-mood');retry.assert_called_once()
    def test_changed_snapshot_defers_immediately_without_using_stale_draft(self):
        before=self.bound()
        with patch.object(self,'send',return_value=no_attempt('submission-snapshot-changed')) as send:
            out=self.walk([before,before],until_waiting=True)
        self.assertEqual(out['reason'],'send-preflight-deferred');send.assert_called_once()
    def test_entered_handler_unknown_never_retried(self):
        before=self.bound();value=no_attempt();value.update(attempted=True)
        with patch.object(self,'send',return_value=value) as send:out=self.walk([before,before])
        self.assertNotEqual(out['reason'],'send-preflight-deferred');send.assert_called_once()
        self.assertEqual(self.rows(),[('unknown',)])
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'unknown')
    def test_plain_exception_after_one_precheck_stays_unknown_no_third_try(self):
        before=self.bound()
        with patch.object(self,'send',side_effect=[no_attempt(),TimeoutError('PRIVATE')]) as send:
            out=self.walk([before,before])
        self.assertEqual(out['reason'],'send-outcome-unknown');self.assertEqual(send.call_count,2)
        self.assertEqual(self.rows(),[('not-invoked',),('unknown',)])
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'unknown')
        self.assertNotIn('PRIVATE',json.dumps(out))
    def test_fixed_pre_root_transport_proof_retries_but_plain_timeout_does_not(self):
        before=self.bound();after=snapshot(('Здравствуйте',False),(QUESTIONS[0],True))
        with patch.object(self,'send',side_effect=[SubmissionNotStarted('script-create'),dict(attempted=True,handler_returned=True)]) as send:
            out=self.walk([before,before,after,after],until_waiting=True)
        self.assertEqual(send.call_count,2);self.assertEqual(out['stage'],'wait-mood')
        self.assertEqual(self.rows(),[('not-invoked',),('handler-returned',)])
    def test_old_unknown_has_no_new_authorization_and_cannot_be_released(self):
        before=self.bound();_,action=self.chain.proposal(before)
        self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,False)
        with patch.object(self,'send') as send:out=self.walk([before])
        send.assert_not_called();self.assertEqual(out['reason'],'send-outcome-unknown')
        with self.assertRaises(StateError):safety.defer_uninvoked(self.chain,'missing',WHO,action)
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'unknown')
    def test_ledger_never_contains_bodies_and_attempt_record_precedes_sender(self):
        before=self.bound()
        def observe(*args):
            self.assertEqual(self.rows(),[('unknown',)])
            return no_attempt('submission-snapshot-changed')
        with patch.object(self,'send',side_effect=observe):self.walk([before,before])
        raw=self.path.read_bytes()
        for body in (GREETING,'Здравствуйте',QUESTIONS[0]):self.assertNotIn(body.encode(),raw)


class InboxDeferral(Base):
    def test_verified_back_defer_no_review_and_same_input_not_marked_answered(self):
        self.journal();before=snap(msg(1002,'Здравствуйте'));send=MagicMock(return_value=no_attempt())
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[before,before],sender=send)
        self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['history_deferred'],1)
        self.assertEqual(out['isolated_dialogs'],0);self.assertEqual(send.call_count,3)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'awaiting-approval')
            self.assertNotEqual(db.execute('SELECT stage FROM chain_dialogs').fetchone()[0],'manual-review')
    def test_exit_notice_never_suppresses_proved_unsent_incoming(self):
        self.journal();before=snap(msg(1002,'Здравствуйте'))
        with patch('assistant_skip_audit.reported') as reported:
            out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                [before,before],sender=MagicMock(return_value=no_attempt()),exit_notifier=MagicMock(return_value=True))
        self.assertEqual(out['history_deferred'],1)
        self.assertTrue(out['exit_events'])
        self.assertEqual(out['exit_events'][0]['notification'],'accepted')
        reported.assert_not_called()
    def test_unknown_back_still_stops_without_replay(self):
        self.journal();before=snap(msg(1002,'Здравствуйте'));bad=nav('returned',WHO);bad['diagnostic']['destination_verified']=False
        send=MagicMock(return_value=no_attempt())
        out=self.walk([nav('opened',WHO),bad],[before,before],sender=send)
        self.assertEqual(out['status'],'inbox-stopped');self.assertEqual(send.call_count,3)


class SetupTransport(unittest.TestCase):
    def test_only_transient_failure_before_root_has_fixed_no_submission_type(self):
        from test_search_online import OnlineFake
        from test_mumu1315 import error_at
        from one_chat_send_device import inspect_submission
        from smoke_one_chat_send import BEFORE
        for method,stage in (('create_script','script-create'),('load','script-load')):
            f=OnlineFake();error=error_at(stage);setattr(f,method,MagicMock(side_effect=error))
            with self.assertRaises(SubmissionNotStarted) as caught:
                inspect_submission(37149,'PRIVATE',lambda:False,BEFORE,frida_api=f)
            self.assertEqual(caught.exception.stage,stage)
            self.assertTrue(f.detached and f.removed)
        f=OnlineFake();create=f.create_script;error=error_at('script-run')
        def root_unknown(*args,**kwargs):
            script=create(*args,**kwargs);f.exports_sync.root=MagicMock(side_effect=error);return script
        f.create_script=root_unknown
        with self.assertRaises(Exception) as caught:
            inspect_submission(37149,'PRIVATE',lambda:False,BEFORE,frida_api=f)
        self.assertIs(caught.exception,error)
        self.assertNotIsInstance(caught.exception,SubmissionNotStarted)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)


class PortIsolation(unittest.TestCase):
    def test_new_attempt_journals_are_phone_local(self):
        from mumu_store import SharedStore
        with tempfile.TemporaryDirectory() as folder:
            stores=[SharedStore(Path(folder)/'state.db',Path(folder)/'old',device_port=p) for p in (5557,5563)]
            for store in stores:
                with store.connection() as db:safety.tables(db)
            with stores[0].connection() as db:
                db.execute("INSERT INTO chain_send_authorizations VALUES('session','300','mood','hash','active')")
                db.execute("INSERT INTO chain_send_attempts(session,outcome) VALUES('session','unknown')")
            with stores[1].connection() as db:
                self.assertEqual(db.execute('SELECT * FROM chain_send_authorizations').fetchall(),[])
                self.assertEqual(db.execute('SELECT * FROM chain_send_attempts').fetchall(),[])
            with stores[0].connection() as db:
                self.assertEqual(db.execute('SELECT status FROM chain_send_authorizations').fetchall(),[('active',)])
                self.assertEqual(db.execute('SELECT outcome FROM chain_send_attempts').fetchall(),[('unknown',)])
