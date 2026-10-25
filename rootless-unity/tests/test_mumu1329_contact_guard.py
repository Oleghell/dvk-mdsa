"""Deny-only cross-port regression tests. No real send, accounts or network."""
from pathlib import Path
import tempfile,threading,unittest
from unittest.mock import MagicMock,patch
import assistant_guided_chain as guided
import assistant_send_safety as safety
from mumu_store import SharedStore
from mumu_peer_policy import ensure_communication_allowed,PeerCommunicationBlocked
from assistant_error_notify import diagnostic_json
from assistant_exit_notify import REASONS
from test_guided_chain import WHO,GREETING,snapshot,stable_snapshots
from test_mumu1328_send_proof import no_attempt
import test_inbox_profiles as fixture


class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.db';self.old=Path(self.tmp.name)/'old'
        self.a=SharedStore(self.path,self.old,device_port=5557)
        self.b=SharedStore(self.path,self.old,device_port=5563)
        self.chain=guided.GuidedChain(self.a,choose=lambda:0,seal=lambda b:b,unseal=lambda b:b)
        self.chain.bind(snapshot(),(GREETING,),approved=True)
        with self.a.connection() as db:safety.tables(db)
        self.stop=threading.Event()
    def block(self,reason='contact-refused',who=WHO):
        with self.b.connection() as db:self.b.record_peer_outcome(db,who,reason)
    def action(self):
        return self.chain.proposal(snapshot(('Привет',False)))[1]
    def walk(self,*,approve=None,reader=None,sender=None):
        self.sender=sender or MagicMock(side_effect=AssertionError('A blocked peer must never be messaged'))
        self.approve=approve or MagicMock(return_value=True)
        return guided.walk(self.chain,WHO,self.stop,self.approve,
            reader or MagicMock(side_effect=stable_snapshots([snapshot(('Привет',False))])),self.sender,
            approved=True,greetings=(GREETING,),pause=lambda _:False,until_waiting=True,max_polls=3)
    def test_terminal_block_prevents_reply_preparation_approval_and_send(self):
        self.block()
        with patch.object(self.chain,'proposal',side_effect=AssertionError('No draft for blocked peer')) as proposal:
            out=self.walk()
        self.assertEqual(out['reason'],'peer-contact-blocked')
        self.assertEqual(out['status'],'chain-waiting')
        proposal.assert_not_called();self.approve.assert_not_called();self.sender.assert_not_called()
    def test_contact_received_has_same_no_send_guard(self):
        self.block('contact-received');out=self.walk()
        self.assertEqual(out['reason'],'peer-contact-blocked');self.sender.assert_not_called()
    def test_reservation_checks_block_in_same_transaction(self):
        action=self.action();self.block()
        with self.assertRaises(PeerCommunicationBlocked):self.chain.reserve_confirmed(WHO,action)
        with self.a.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('awaiting-approval',)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_send_authorizations').fetchone()[0],0)
    def test_refusal_during_approval_prevents_reservation_and_sender(self):
        def approve(*args):self.block();return True
        out=self.walk(approve=approve)
        self.assertEqual(out['reason'],'peer-contact-blocked');self.sender.assert_not_called()
        self.assertEqual(out['submission_calls'],0)
    def test_block_after_reservation_prevents_adapter_entry(self):
        action=self.action();session=self.chain.reserve_confirmed(WHO,action);self.block()
        sender=MagicMock(side_effect=AssertionError('Must not enter adapter'))
        with self.assertRaises(PeerCommunicationBlocked):
            safety.submit_checked(self.chain,session,WHO,action,snapshot(),sender,self.stop,lambda _:None,{})
        sender.assert_not_called()
        with self.a.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('reserved-unknown',)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_send_attempts').fetchone()[0],0)
    def test_each_preflight_retry_rechecks_new_global_block(self):
        def no_send(*args):self.block();return no_attempt()
        sender=MagicMock(side_effect=no_send);out=self.walk(sender=sender)
        self.assertEqual(out['reason'],'peer-contact-blocked');sender.assert_called_once()
        with self.a.connection() as db:
            self.assertEqual(db.execute('SELECT outcome FROM chain_send_attempts').fetchall(),[('not-invoked',)])
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('reserved-unknown',)])
    def test_other_accounts_chat_ids_and_future_ports_still_blocked(self):
        self.block()
        for port in (5559,5561,5563,5565,16790):
            store=SharedStore(self.path,self.old,device_port=port)
            with self.assertRaises(PeerCommunicationBlocked):
                ensure_communication_allowed(store,dict(account='999',peer=WHO['peer'],chat='9999'))
    def test_greeting_and_other_peer_do_not_create_a_terminal_block(self):
        ensure_communication_allowed(self.a,WHO)
        self.block(who=dict(WHO,peer='201'))
        ensure_communication_allowed(self.a,WHO)
    def test_profile_search_excludes_exact_blocked_user_id_before_chat(self):
        import assistant_pass
        self.block()
        visited=self.a.visited_peers()
        self.assertIn(WHO['peer'],visited)
        source=assistant_pass.build('Synthetic greeting',visited)
        self.assertIn('batchSeen=new Set(["200"])',source)
        self.assertIn("s.batchId=checked(s.user,'get_Id',10)",source)
        self.assertIn('if(batchSeen.has(identityKey))return null;',source)
        self.assertLess(source.index('if(batchSeen.has(identityKey))return null;'),source.index('state.targetUser=own(selected.user)'))
        self.assertIn("if(identity.compare(0)<=0)fail('selection-changed')",source)
        self.assertIn('identityKey!==batchCandidateKey',source)
    def test_existing_unknowns_and_global_rows_survive_restart(self):
        action=self.action();session=self.chain.reserve_confirmed(WHO,action)
        safety.begin(self.chain,session,WHO,action);self.block()
        other=SharedStore(self.path,self.old,device_port=5557)
        with self.assertRaises(PeerCommunicationBlocked):ensure_communication_allowed(other,WHO)
        with other.connection() as db:
            self.assertEqual(db.execute('SELECT outcome FROM chain_send_attempts').fetchall(),[('unknown',)])
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('reserved-unknown',)])
            self.assertEqual(db.execute('SELECT reason FROM mumu_peer_blocks').fetchall(),[('contact-refused',)])
    def test_diagnostic_code_is_public_but_not_peer_data(self):
        data=diagnostic_json(dict(reason='peer-contact-blocked',peer='PRIVATE',last_chat_diagnostics=dict(failure_point='peer-contact-blocked')))
        self.assertIn(b'peer-contact-blocked',data);self.assertNotIn(b'PRIVATE',data)
        self.assertIn('peer-contact-blocked',REASONS)
        self.assertNotIn('отправленный ответ',REASONS['history-read-budget-timeout'])


class Inbox(unittest.TestCase):
    setUp=fixture.Base.setUp
    journal=fixture.Base.journal
    chain=fixture.Base.chain
    sender=fixture.Base.sender
    walk=fixture.Base.walk
    def test_blocked_open_chat_leaves_via_verified_back_without_unknown_send(self):
        self.store=SharedStore(self.store.path,Path(self.tmp.name)/'old',device_port=5557)
        self.journal()
        other=SharedStore(self.store.path,Path(self.tmp.name)/'old',device_port=5563)
        with other.connection() as db:other.record_peer_outcome(db,WHO,'contact-refused')
        sender=MagicMock(side_effect=AssertionError('No send to blocked peer'))
        out=self.walk([fixture.nav('opened',WHO),fixture.nav('returned',WHO),fixture.nav('search-ready')],
            [fixture.snap(fixture.msg(1002,'Привет'))],sender=sender)
        self.assertEqual(out['status'],'inbox-completed');sender.assert_not_called()
        self.assertEqual(out['isolated_dialogs'],0)
        self.assertEqual(out['outcomes'],{'chain-waiting:peer-contact-blocked':1})


class DiagnosticEvidence(unittest.TestCase):
    def test_known_input_disabled_read_failure_survives_private_filter(self):
        import json
        from assistant_store import Store
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'state.db',Path(tmp)/'old')
            chain=guided.GuidedChain(store,choose=lambda:0,seal=lambda b:b,unseal=lambda b:b)
            chain.bind(snapshot(),(GREETING,),approved=True)
            value=snapshot(('Привет',False));value['input_enabled']=False
            send=MagicMock(side_effect=AssertionError('Input is disabled'))
            result=guided.walk(chain,WHO,threading.Event(),lambda *a:True,lambda *a:value,send,
                approved=True,greetings=(GREETING,),pause=lambda _:False)
            self.assertEqual(result['reason'],'chat-input-disabled');send.assert_not_called()
            sanitized=json.loads(diagnostic_json(dict(status='stopped',last_pass=dict(
                status='inbox-stopped',reason='chat-chat-input-disabled',last_chat_diagnostics=result['diagnostics']))))['diagnostic']
            self.assertEqual(sanitized['last_pass']['reason'],'chat-chat-input-disabled')
            diag=sanitized['last_pass']['last_chat_diagnostics']
            self.assertEqual(diag['failure_point'],'chat-input-disabled')
            self.assertTrue(diag['input_disabled_verified'])
    def test_absent_evidence_and_masked_old_code_are_not_invented(self):
        import json
        value=dict(status='inbox-stopped',reason='unrecognized-diagnostic-code',last_chat_diagnostics=dict(
            failure_point='unrecognized-diagnostic-code',host_failure='state-check-failed',host_checkpoint='chat-read',error_type='StateError'))
        result=json.loads(diagnostic_json(value))['diagnostic']
        self.assertEqual(result,value)
        self.assertNotIn('input_disabled_verified',result['last_chat_diagnostics'])
    def test_only_exact_bounded_boolean_evidence_is_exported(self):
        import json
        data=json.loads(diagnostic_json(dict(last_chat_diagnostics=dict(history_budget_exhausted=True,
            history_wait_exhausted=False,history_snapshot_oversized=True,post_send_checked=False,
            input_disabled_verified='PRIVATE',text='PRIVATE',exception='PRIVATE'))))['diagnostic']['last_chat_diagnostics']
        self.assertEqual(data,dict(history_budget_exhausted=True,history_wait_exhausted=False,
            history_snapshot_oversized=True,post_send_checked=False))
