"""Accurate read-only ban/send notices, never reset protections from screenshots."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock
from mumu_store import SharedStore
from mumu_peer_policy import record, ensure_communication_allowed, PeerCommunicationBlocked
from assistant_guided_chain import GuidedChain
from assistant_exit_notify import notify_exit, blocked_explanation, unknown_send_explanation
from test_guided_chain import WHO, GREETING, snapshot
import test_mumu1323_alternatives_statistics as alternatives


class Notices(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=SharedStore(Path(self.temp.name)/'db',Path(self.temp.name)/'old',device_port=5565)
        self.chain=GuidedChain(self.store,choose=lambda:0,seal=lambda b:b,unseal=lambda b:b)
        self.chain.bind(snapshot(),(GREETING,),approved=True)

    def test_each_global_ban_has_real_reason_and_safe_source_without_changing_it(self):
        for reason,source,expected in (
            ('contact-received','5559','полученный контакт'),
            ('contact-refused','5561','явный отказ'),
            ('manual-block','telegram','ручной запрет /num')):
            with self.subTest(reason=reason):
                with self.store.connection() as db:
                    db.execute('DELETE FROM mumu_peer_blocks')
                    record(db,WHO,reason,source)
                    before=db.execute('SELECT * FROM mumu_peer_blocks').fetchall()
                text=blocked_explanation(self.store,WHO)
                self.assertIn(expected,text)
                self.assertIn('команда Telegram' if source=='telegram' else 'MuMu ADB '+source,text)
                with self.store.connection() as db:
                    self.assertEqual(before,db.execute('SELECT * FROM mumu_peer_blocks').fetchall())
                with self.assertRaises(PeerCommunicationBlocked):ensure_communication_allowed(self.store,WHO)

    def test_manual_ban_notice_does_not_claim_a_contact_or_refusal(self):
        with self.store.connection() as db:record(db,WHO,'manual-block','telegram')
        sender=MagicMock(return_value=True)
        result=dict(reason='peer-contact-blocked')
        self.assertEqual(notify_exit(self.chain,WHO,result,sender=sender)['notification'],'manual-block-suppressed')
        text=blocked_explanation(self.store,WHO)
        self.assertIn('ручной запрет /num',text)
        self.assertNotIn('получен контакт',text);self.assertNotIn('явный отказ',text)
        self.assertEqual(notify_exit(self.chain,WHO,result,sender=sender)['notification'],'manual-block-suppressed')
        sender.assert_not_called()

    def test_database_strings_are_never_exported_as_source_or_reason(self):
        with self.store.connection() as db:record(db,WHO,'contact-refused','PRIVATE_TOKEN_BODY')
        self.assertNotIn('PRIVATE',blocked_explanation(self.store,WHO))
        with self.store.connection() as db:
            db.execute("UPDATE mumu_peer_blocks SET reason='PRIVATE_TOKEN_BODY'")
        self.assertIsNone(blocked_explanation(self.store,WHO))

    def test_unknown_question_is_explained_but_not_reset_or_replayed(self):
        before=snapshot(('Привет',False));_,action=self.chain.proposal(before)
        self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,False)
        with self.store.connection() as db:rows=db.execute('SELECT * FROM chain_actions').fetchall()
        detail=unknown_send_explanation(self.store,WHO)
        self.assertIn('вопрос — неизвестный исход',detail)
        sender=MagicMock(return_value=True)
        notify_exit(self.chain,WHO,dict(reason='send-outcome-unknown'),sender=sender)
        self.assertIn('Это не подтверждение доставки',sender.call_args.args[0])
        self.assertEqual(self.chain.proposal(before),('submission-unknown',None))
        with self.store.connection() as db:
            self.assertEqual(rows,db.execute('SELECT * FROM chain_actions').fetchall())


class MaxReceipt(unittest.TestCase):
    chain=alternatives.Alternatives.chain
    def test_hyphenated_phone_after_max_choice_is_contact_not_refusal(self):
        c,store,h=self.chain()
        h.append(('У меня нет ни телеграмм,ни ватсап,есть МАКС',False))
        stage,action=c.proposal(snapshot(*h))
        self.assertEqual((stage,action['kind']),('pending-clarify','clarify'))
        c.reserve_confirmed(WHO,action);c.finish(WHO,action,True)
        h.append((action['text'],True));c.proposal(snapshot(*h))
        self.assertEqual(c.proposal(snapshot(*h,('8-900-123-45-67',False))),('done',None))
