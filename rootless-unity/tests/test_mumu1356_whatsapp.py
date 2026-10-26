"""Explicit WhatsApp choice, bounded availability and durable no-replay."""
import unittest
import assistant_contact_intent as intent
import assistant_contact_clarify as clarify
import test_mumu1323_alternatives_statistics as fixtures
from test_guided_chain import snapshot, WHO

class WhatsApp(unittest.TestCase):
    chain = fixtures.Alternatives.chain
    def test_exact_reports_and_spaced_variants_continue_without_ai(self):
        for text in ('Ну работает вроде ватцап','Ватс ап','ватс апп','Вотс ап',
                     'Ну работает вроде бы ватс ап','Ватцап вроде работает',
                     'ТГ не работает, ватс ап работает'):
            with self.subTest(text=text):
                c,store,h=self.chain();s=snapshot(*h,(text,False))
                expected=('pending-clarify',dict(kind='clarify',text=clarify.WHATSAPP_TEXT))
                self.assertEqual(c.proposal(s),expected)
                self.assertEqual(c.proposal(s),expected)
                c.responder.assert_not_called()
    def test_negative_question_and_quoted_availability_are_not_choices(self):
        for text in ('Не работает вроде ватцап','Не очень работает ватс ап',
                     'Ватс ап вроде не работает','Ватс ап работает не очень',
                     'Ватс ап?', 'Ну работает вроде ватцап?',
                     '> Ватс ап\nНе знаю', 'Работает телеграм а ватс ап нет'):
            with self.subTest(text=text):
                self.assertNotEqual(intent.available_alternative([dict(text=text)]),'whatsapp')
    def test_explicit_refusals_still_win_in_full_chain(self):
        for text in ('Не пиши, ватс ап работает','Номер не дам, ватс ап работает',
                     'Не хочу переходить, ватцап работает'):
            with self.subTest(text=text):
                c,store,h=self.chain()
                self.assertEqual(c.proposal(snapshot(*h,(text,False))),('declined',None))
                c.responder.assert_not_called()
    def test_unknown_clarification_is_not_replayed(self):
        c,store,h=self.chain();s=snapshot(*h,('Ватс ап',False))
        _,action=c.proposal(s);self.assertIsNotNone(action)
        c.reserve_confirmed(WHO,action);c.finish(WHO,action,False)
        with store.connection() as db:before=db.execute('SELECT * FROM chain_actions').fetchall()
        self.assertIsNone(c.proposal(s)[1])
        with store.connection() as db:self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())
    def test_existing_terminal_refusal_not_reset(self):
        c,store,h=self.chain();s=snapshot(*h,('Номер не дам',False))
        self.assertEqual(c.proposal(s),('declined',None))
        self.assertEqual(c.proposal(snapshot(*h,('Номер не дам',False),('Ватс ап',False))),('declined',None))
