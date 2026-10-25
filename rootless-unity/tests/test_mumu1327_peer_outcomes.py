"""Cross-port availability follows contacts/refusals, not greeting claims."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from mumu_store import SharedStore,SharedPeerClaimed
from assistant_guided_chain import GuidedChain
from assistant_profiles import clear_history
from assistant_contact_policy import enable as contact_only
from assistant_chain import text_hash
from mumu_peer_policy import explicit_refusal
from test_guided_chain import WHO,GREETING,snapshot,sequence
from test_assistant import pending


class Availability(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'db';self.old=Path(self.temp.name)/'legacy'
        self.a=self.store(5557);self.b=self.store(5559)
    def store(self,port):return SharedStore(self.path,self.old,device_port=port)
    def reserve(self,store):return store.reserve(pending(),'Hi',approved=True)
    def outcome(self,store,reason='contact-refused',who=WHO):
        with store.connection() as db:store.record_peer_outcome(db,who,reason)
    def chain(self,store):
        c=GuidedChain(store,choose=lambda:0,seal=lambda b:b,unseal=lambda b:b)
        c.bind(snapshot(),(GREETING,),approved=True)
        return c
    def through_contact_request(self,c):
        h=[('Привет',False)]
        for _ in range(2):
            stage,a=c.proposal(snapshot(*h));c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
            h.append((a['text'],True));c.proposal(snapshot(*h))
            if a['kind']=='question':h.append(('Хорошо',False))
        return h
    def test_greeting_without_conversation_does_not_block_other_ports(self):
        self.reserve(self.a)
        self.assertTrue(self.a.peer_claimed(pending()))
        self.assertFalse(self.b.peer_claimed(pending()))
        self.assertNotIn('200',self.b.visited_peers())
        self.reserve(self.b)
        self.assertEqual(self.a.summary()['reserved'],1);self.assertEqual(self.b.summary()['reserved'],1)
    def test_all_local_send_statuses_stay_local_across_restart_and_clear(self):
        for attempted,returned in ((False,False),(True,False),(True,True)):
            with self.subTest(status=(attempted,returned)):
                peer=str(1000+10*int(attempted)+int(returned));p=pending(peer=peer)
                action=self.a.reserve(p,'Hi',approved=True)
                self.a.finish(action,dict(send_attempted=attempted,send_handler_returned=returned))
                clear_history(self.a)
                self.assertTrue(self.store(5557).peer_claimed(p))
                self.assertFalse(self.store(5559).peer_claimed(p))
                with self.assertRaises(SharedPeerClaimed):self.a.reserve(p,'Hi',approved=True)
    def test_profile_visit_and_recovery_skip_are_phone_local(self):
        self.a.record_visit('201',dict(profile_verified=True,friends_count=10,history_status='empty'))
        self.a.skip_recovery_peer(dict(WHO,peer='202'))
        self.assertIn('201',self.a.visited_peers());self.assertIn('202',self.a.visited_peers())
        self.assertNotIn('201',self.b.visited_peers());self.assertNotIn('202',self.b.visited_peers())
        self.assertFalse(self.b.peer_claimed(pending(peer='202')))
    def test_old_global_greeting_visit_and_recovery_rows_kept_but_not_bans(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("INSERT INTO mumu_peer_claims(peer,device,account) VALUES('210','5557','100')")
            db.execute("INSERT INTO mumu_profile_visits(peer) VALUES('211')")
            db.execute("INSERT INTO mumu_recovery_skips VALUES('212')")
        b=self.store(5559)
        for peer in ('210','211','212'):
            self.assertNotIn(peer,b.visited_peers());self.assertFalse(b.peer_claimed(pending(peer=peer)))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT peer FROM mumu_peer_claims').fetchall(),[('210',)])
            self.assertEqual(db.execute('SELECT peer FROM mumu_profile_visits').fetchall(),[('211',)])
            self.assertEqual(db.execute('SELECT peer FROM mumu_recovery_skips').fetchall(),[('212',)])
    def test_contact_or_refusal_blocks_all_other_accounts_and_future_ports(self):
        for reason,peer in (('contact-received','220'),('contact-refused','221')):
            self.outcome(self.a,reason,dict(WHO,peer=peer))
            for port in (5559,5561,5563,5565,16790):
                s=self.store(port);p=pending(peer=peer,account='999')
                self.assertTrue(s.peer_claimed(p));self.assertIn(peer,s.visited_peers())
                with self.assertRaises(SharedPeerClaimed):s.reserve(p,'Hi',approved=True)
    def test_refusal_is_written_by_verified_chain(self):
        c=self.chain(self.a);h=self.through_contact_request(c)
        self.assertFalse(self.b.peer_claimed(pending()))
        self.assertEqual(c.proposal(snapshot(*h,('Номер не дам',False))),('declined',None))
        self.assertTrue(self.b.peer_claimed(pending()))
        with self.b.connection() as db:self.assertEqual(db.execute('SELECT reason FROM mumu_peer_blocks').fetchone()[0],'contact-refused')
    def test_do_not_contact_is_also_global_before_contact_request(self):
        c=self.chain(self.a)
        self.assertEqual(c.proposal(snapshot(('Не пиши мне',False))),('declined',None))
        self.assertTrue(self.b.peer_claimed(pending()))
    def test_contact_received_even_telegram_disabled_blocks_others(self):
        c=self.chain(self.a);c.contact_notifications=False
        self.assertEqual(c.proposal(snapshot(('Мой номер +79991234567',False))),('done',None))
        self.assertTrue(self.b.peer_claimed(pending()))
        with self.a.connection() as db:
            self.assertEqual(db.execute('SELECT reason FROM mumu_peer_blocks').fetchone()[0],'contact-received')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_contact_outbox').fetchone()[0],0)
    def test_policy_decline_is_not_a_contact_refusal(self):
        c=self.chain(self.a);h=self.through_contact_request(c);contact_only(self.a)
        self.assertEqual(c.proposal(snapshot(*h,('Ты откуда?',False))),('declined',None))
        self.assertFalse(self.b.peer_claimed(pending()))
        self.assertFalse(self.store(5561).peer_claimed(pending()))
    def test_app_unavailability_is_not_global_refusal(self):
        c=self.chain(self.a);h=self.through_contact_request(c)
        self.assertEqual(c.proposal(snapshot(*h,('Нет ни того ни другого',False))),('declined',None))
        self.assertFalse(self.b.peer_claimed(pending()))
    def test_expired_or_unverified_reply_window_does_not_block_others(self):
        self.reserve(self.a)
        from assistant_reply_window import enable,reason
        enable(self.a)
        with self.a.connection() as db:db.execute("UPDATE manual_actions SET created_at=datetime('now','-4000 seconds')")
        self.assertIsNone(reason(self.a,WHO))
        self.assertFalse(self.b.peer_claimed(pending()))
    def test_contact_backfill_includes_original_and_future_namespaces_not_declined(self):
        for port,peer,stage in ((5563,'230','done'),(16790,'231','done'),(5561,'232','declined'),(5565,'233','manual-review')):
            s=self.store(port);GuidedChain(s)
            with s.connection() as db:db.execute('INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)',('100',peer,'3'+peer,'1001',stage,'a'*64))
        fresh=self.store(5559)
        for peer,blocked in (('230',True),('231',True),('232',False),('233',False)):
            self.assertEqual(fresh.peer_claimed(pending(peer=peer)),blocked)
    def test_encrypted_contact_receipt_backfills_even_without_done(self):
        c=self.chain(self.a)
        with self.a.connection() as db:
            db.execute("UPDATE chain_dialogs SET stage='manual-review'")
            db.execute("INSERT INTO chain_contact_outbox VALUES('300','1002',?,'pending')",(b'protected',))
        self.assertTrue(self.store(5559).peer_claimed(pending()))
    def test_rolled_back_outcome_does_not_block_or_authorize(self):
        with self.assertRaises(RuntimeError):
            with self.a.connection() as db:
                self.a.record_peer_outcome(db,WHO,'contact-received');raise RuntimeError('rollback')
        self.assertFalse(self.b.peer_claimed(pending()))
    def test_reservation_rechecks_outcome_after_precheck(self):
        self.assertFalse(self.b.peer_claimed(pending()))
        self.outcome(self.a)
        with self.assertRaises(SharedPeerClaimed):self.reserve(self.b)
        self.assertEqual(self.b.summary()['reserved'],0)
    def test_outcome_after_reserve_before_ack_uses_no_send_back_path(self):
        from unittest.mock import MagicMock,patch
        import assistant_pass
        script=MagicMock();script.exports_sync.cohortpending.return_value=pending()
        script.exports_sync.cohortack.return_value=True
        done=MagicMock();done.wait.return_value=False;done.is_set.return_value=False
        reserve=self.a.reserve
        def then_refuse(*args,**kwargs):
            action=reserve(*args,**kwargs);self.outcome(self.b);return action
        state={}
        with patch.object(self.a,'reserve',side_effect=then_refuse):
            assistant_pass.monitor(script,self.a,'Hi',lambda *a:True,done,lambda:False,state)
        self.assertTrue(state['shared_peer_skipped']);self.assertIn('action_id',state)
        script.exports_sync.cohortack.assert_called_once_with(dict(pending(),skip=True))
        self.assertEqual(self.a.summary()['statuses'],{'reserved-unknown':1})

    def test_nonterminal_reason_cannot_create_global_ban(self):
        for reason in ('greeting','manual-review','declined','timeout','wait-contact'):
            with self.assertRaises(ValueError):self.outcome(self.a,reason)
        self.assertFalse(self.b.peer_claimed(pending()))
    def test_refusal_classifier_does_not_use_silence_quotes_or_questions(self):
        for text in ('Привет','Хорошо','Давай','Ты откуда?','> Номер не дам','Телеграм не работает','Мой номер +79991234567'):
            self.assertFalse(explicit_refusal([dict(text=text)],requested=True),text)
        for text in ('Номер не дам','Общаюсь только тут','Нет','Не пиши мне'):
            self.assertTrue(explicit_refusal([dict(text=text)],requested=True),text)
