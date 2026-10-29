"""Synthetic contact receipts and old ambiguity reconciliation; no network/PII."""
import copy,json,itertools,threading,unittest
from unittest.mock import MagicMock,patch
from test_mumu1311_context import Refusals as Seed
from test_guided_chain import snapshot,WHO,GREETING
from assistant_contact_receipt import candidates,reserve_probe,reconcile
from assistant_inbox import inbox_targets,with_seen_ids
import assistant_guided_chain as guided
from shared_contact import self_shared

PHONE='89991234567'
HANDLE='@synthetic_person'
class Receipts(unittest.TestCase):
    chain=Seed.chain
    def ledger(self,store):
        with store.connection() as db:
            return db.execute('SELECT * FROM chain_actions ORDER BY kind').fetchall()
    def test_phone_in_mixed_packet_and_extra_own_messages_is_receipt_not_send_proof(self):
        for reverse in (False,True):
            c,store,h=self.chain();before=self.ledger(store)
            c.responder=MagicMock(side_effect=AssertionError('No AI'))
            rows=[('Сохраняю контакт',True),('По какому номеру найти в Максе?',True),
                  ('Давай',False),('> > У меня только Макс\nОпределись или здесь или там 😆',False),
                  ('Так не мучай себя, спать ложись',False),('Думаю что наверно',False),(PHONE,False)]
            s=snapshot(*h,*rows)
            if reverse:s['messages'].reverse()
            self.assertEqual(c.proposal(s),('done',None));c.responder.assert_not_called()
            self.assertEqual(self.ledger(store),before)
            notice=MagicMock(return_value=True)
            self.assertEqual(c.notify(WHO,notice),'accepted')
            self.assertEqual(c.proposal(s),('done',None));self.assertEqual(c.notify(WHO,notice),'nothing-pending')
            notice.assert_called_once()
    def test_telegram_contact_and_one_unavailable_app_finish_without_reply(self):
        for absent in ('Ват сапом не пользуюсь','Нет ватсапа','У меня нет телеграма','Не пользуюсь ватсап'):
            c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
            self.assertEqual(c.proposal(snapshot(*h,(HANDLE+' тг',False),(absent,False))),('done',None),absent)
            c.responder.assert_not_called()
    def test_returned_contact_proposal_and_contact_burst_observed_together(self):
        c,store,h=self.chain();sample=snapshot(*h)
        outgoing=sample['messages'][-1]
        with store.connection() as db:
            db.execute("UPDATE chain_dialogs SET stage='pending-contact'")
            db.execute("UPDATE chain_actions SET status='handler-returned-unconfirmed' WHERE kind='contact'")
            db.execute('DELETE FROM chain_seen WHERE chat=? AND message=?',(WHO['chat'],outgoing['id']))
        self.assertEqual(c.proposal(snapshot(*h,(HANDLE+' тг',False),('Не пользуюсь ватсап',False))),('done',None))
        with store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='contact'").fetchone()[0],'outgoing-observed')
    def test_historical_contact_request_edit_blocks_even_new_valid_contact(self):
        c,store,h=self.chain();sample=snapshot(*h,(PHONE,False))
        sample['messages'][-2]['text']='Changed contact request'
        self.assertEqual(c.proposal(sample),('manual-review',None))
        with store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM chain_contact_outbox').fetchone()[0],0)
    def test_blanket_refusal_is_not_overridden_by_contact(self):
        for refusal in ('Нет ни того ни другого','Не хочу','Пиши тут','Не передавай никому'):
            c,store,h=self.chain();s=snapshot(*h,(HANDLE,False),(refusal,False))
            self.assertNotEqual(c.proposal(s)[0],'done',refusal)
            with store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM chain_contact_outbox').fetchone()[0],0)
    def test_other_person_contact_and_quote_never_forwarded(self):
        for values in ((PHONE,'Это номер моей подруги'),('> '+PHONE,),('Не мой '+PHONE,)):
            c,store,h=self.chain();c.proposal(snapshot(*h,*[(x,False) for x in values]))
            with store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM chain_contact_outbox').fetchone()[0],0)
    def test_unknown_followup_is_preserved_when_contact_arrives(self):
        c,store,h=self.chain()
        with store.connection() as db:
            db.execute("UPDATE chain_dialogs SET stage='pending-followup'")
            db.execute("INSERT INTO chain_actions VALUES(?,'followup','777','digest','reserved-unknown')",(WHO['chat'],))
        old=self.ledger(store)
        self.assertEqual(c.proposal(snapshot(*h,(PHONE,False))),('done',None))
        self.assertEqual(self.ledger(store),old)
    def test_no_request_anchor_does_not_bypass_unknown_send(self):
        c,store,h=self.chain()
        with store.connection() as db:
            db.execute("UPDATE chain_actions SET status='reserved-unknown' WHERE kind='contact'")
            db.execute("UPDATE chain_dialogs SET stage='pending-contact'")
        old=self.ledger(store)
        self.assertNotEqual(c.proposal(snapshot(*h,('Стороннее сообщение',True),(PHONE,False)))[0],'done')
        self.assertEqual(self.ledger(store),old)
    def test_max_phone_label_is_supported_only_after_request(self):
        self.assertEqual(self_shared('В Максе '+PHONE,requested=True),['+79991234567'])
        self.assertEqual(self_shared('В Максе '+PHONE,requested=False),[])

class OldReview(unittest.TestCase):
    chain=Seed.chain
    def old(self):
        c,store,h=self.chain()
        c.responder=MagicMock(side_effect=AssertionError('No AI'))
        # v1.3.84: consume no longer CREATES this review - a manually typed
        # request beside the peer's number saves the contact directly (see the
        # regression test below). A database written by an older version can
        # still hold the terminal contact-batch-ambiguous review, and the
        # receipt-only reconciliation keeps working for exactly those rows.
        sample=snapshot(*h,('По какому номеру найти в Максе?',True),(PHONE,False))
        with store.connection() as db:
            db.execute("INSERT OR REPLACE INTO chain_review_reasons VALUES(?,'contact-batch-ambiguous')",(WHO['chat'],))
            db.execute("UPDATE chain_dialogs SET stage='manual-review'")
        self.assertEqual(c.proposal(sample),('manual-review',None))
        sample['latest_message_id']=sample['messages'][-1]['id']
        return c,store,sample
    def test_operator_request_beside_number_now_saves_directly(self):
        # v1.3.84 regression: the old ambiguity on a manual outgoing is gone.
        c,store,h=self.chain()
        c.responder=MagicMock(side_effect=AssertionError('No AI'))
        sample=snapshot(*h,('По какому номеру найти в Максе?',True),(PHONE,False))
        self.assertEqual(c.proposal(sample),('done',None))
        with store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM chain_contact_outbox").fetchone()[0],1)
            self.assertIsNone(db.execute("SELECT reason FROM chain_review_reasons WHERE reason='contact-batch-ambiguous'").fetchone())
        c.responder.assert_not_called()
    def test_one_reconciliation_preserves_every_action_and_review_reason(self):
        c,store,s=self.old()
        with store.connection() as db:old=db.execute('SELECT * FROM chain_actions').fetchall()
        self.assertIn(tuple(WHO[k] for k in ('account','peer','chat')),candidates(store))
        self.assertIn(WHO,inbox_targets(c)[1]);self.assertEqual(with_seen_ids(c,[WHO])[0]['seen_ids'],[])
        self.assertTrue(reserve_probe(c,WHO));self.assertFalse(reserve_probe(c,WHO));self.assertFalse(candidates(store))
        other=copy.deepcopy(s);other['messages'].reverse()
        self.assertTrue(reconcile(c,s,other));self.assertFalse(reconcile(c,s,other))
        with store.connection() as db:
            self.assertEqual(db.execute('SELECT * FROM chain_actions').fetchall(),old)
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs').fetchone()[0],'done')
            self.assertEqual(db.execute('SELECT reason FROM chain_review_reasons').fetchone()[0],'contact-batch-ambiguous')
        self.assertEqual(c.proposal({k:v for k,v in s.items() if k!='latest_message_id'}),('done',None))
    def test_no_reconciliation_of_changed_or_unproven_history(self):
        for mode in ('missing-latest','wrong-latest','own-latest','edit','truncated','other-chat','other-review','declined'):
            c,store,s=self.old();other=copy.deepcopy(s)
            if mode=='missing-latest':other.pop('latest_message_id')
            elif mode=='wrong-latest':other['latest_message_id']='999999'
            elif mode=='own-latest':s['latest_message_id']=other['latest_message_id']=s['messages'][-2]['id']
            elif mode=='edit':other['messages'][1]['text']='Changed'
            elif mode=='truncated':other['messages'].pop(0)
            elif mode=='other-chat':other['identity']['chat']='301'
            else:
                with store.connection() as db:
                    if mode=='other-review':db.execute("UPDATE chain_review_reasons SET reason='history-edited'")
                    else:db.execute("UPDATE chain_dialogs SET stage='declined'")
            self.assertFalse(reconcile(c,s,other),mode)
            with store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM chain_contact_outbox').fetchone()[0],0)
    def test_walk_finishes_old_contact_without_any_sender_or_ai(self):
        c,store,s=self.old();c.responder=MagicMock(side_effect=AssertionError('No AI'))
        sender=MagicMock(side_effect=AssertionError('No send'));notice=MagicMock(return_value=True)
        out=guided.walk(c,WHO,threading.Event(),MagicMock(),lambda who:copy.deepcopy(s),sender,
                        approved=True,notifier=notice,greetings=(GREETING,),until_waiting=True,max_polls=2,pause=lambda _:False)
        self.assertEqual(out['reason'],'contact-forwarded');self.assertTrue(out['stages']['peer_contact'])
        sender.assert_not_called();c.responder.assert_not_called();notice.assert_called_once()
