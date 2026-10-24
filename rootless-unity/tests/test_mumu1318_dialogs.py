"""Explicit MAX choice and stay-here variants; synthetic, never provider calls."""
import unittest
from unittest.mock import MagicMock,patch
import assistant_contact_clarify as clarify
import assistant_contact_followup as follow
import test_mumu1311_context as fixtures
from test_guided_chain import snapshot,WHO
from assistant_chain import text_hash

class Dialogs(unittest.TestCase):
    chain=fixtures.Refusals.chain
    def test_max_is_an_app_choice_not_a_contact_or_person(self):
        for text in ('У меня работает только Макс','У меня только MAX','Макс','Давай в Максе'):
            self.assertTrue(clarify.max_selected([dict(text=text)]),text)
            self.assertTrue(clarify.chosen([dict(text=text)]),text)
        for text in ('Макс сказал привет','У меня работает только Макс?',
                     '> У меня работает только Макс\nДля чего?', 'Не хочу в Макс', 'Макс не работает'):
            self.assertFalse(clarify.max_selected([dict(text=text)]),text)
    def test_new_max_choice_uses_fixed_clarification_without_ai(self):
        c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI for MAX'))
        stage,a=c.proposal(snapshot(*h,('У меня работает только Макс',False)))
        self.assertEqual((stage,a),('pending-clarify',dict(kind='clarify',text=clarify.MAX_TEXT)))
        c.responder.assert_not_called()
        with store.connection() as db:
            self.assertEqual(db.execute("SELECT text_hash,status FROM chain_actions WHERE kind='clarify'").fetchone(),(text_hash(clarify.MAX_TEXT),'awaiting-approval'))
    def test_one_unavailable_app_does_not_block_explicit_max_choice(self):
        c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
        stage,a=c.proposal(snapshot(*h,('Нет телеграма',False),('У меня только Макс',False)))
        self.assertEqual(stage,'pending-clarify');self.assertEqual(a['text'],clarify.MAX_TEXT)
    def test_old_max_choice_already_answered_here_is_recovered_once(self):
        c,store,h=self.chain();h += [('У меня работает только Макс',False)]
        # Simulate previous code falling back to a generic followup.
        with patch('assistant_chain.max_selected',return_value=False),patch('assistant_contact_clarify.max_selected',return_value=False):
            _,a=c.proposal(snapshot(*h));c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
            h += [(a['text'],True)];c.proposal(snapshot(*h))
        c.responder=MagicMock(side_effect=AssertionError('No AI'))
        stage,a=c.proposal(snapshot(*h,('Как хочешь',False)))
        self.assertEqual(stage,'pending-clarify');self.assertEqual(a['text'],clarify.MAX_TEXT)
        c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
        h += [('Как хочешь',False),(a['text'],True)]
        c.proposal(snapshot(*h))
        with store.connection() as db:before=db.execute("SELECT * FROM chain_actions WHERE kind='clarify'").fetchone()
        h += [('Ага',False)]
        self.assertEqual(c.proposal(snapshot(*h)),('wait-contact',None))
        c.responder.assert_not_called()
        # Arrival of a requested number is terminal, without another model call.
        stage,a=c.proposal(snapshot(*h,('89991234567',False)))
        self.assertEqual((stage,a),('done',None));c.responder.assert_not_called()
        with store.connection() as db:self.assertEqual(db.execute("SELECT * FROM chain_actions WHERE kind='clarify'").fetchone(),before)
    def test_unknown_clarification_is_not_reset(self):
        c,store,h=self.chain();stage,a=c.proposal(snapshot(*h,('У меня только Макс',False)))
        c.reserve_confirmed(WHO,a)
        c.responder=MagicMock(side_effect=AssertionError('No AI'))
        _,next_action=c.proposal(snapshot(*h,('У меня только Макс',False),('Давай',False)))
        self.assertIsNone(next_action)
        with store.connection() as db:self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='clarify'").fetchone()[0],'reserved-unknown')
    def test_typo_and_temporary_preference_terminal_even_in_old_history(self):
        for text in ('Сдесь','Первое время хотелось бы остаться здесь','Пока хочу остаться здесь'):
            self.assertTrue(follow.refused([dict(text=text)],requested=True))
            self.assertFalse(follow.refused([dict(text=text)],requested=False))
            c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
            self.assertEqual(c.proposal(snapshot(*h,(text,False))),('declined',None))
            self.assertEqual(c.proposal(snapshot(*h,(text,False),('Ага',False))),('declined',None))
            c.responder.assert_not_called()
    def test_already_answered_typo_and_temporary_preference_are_not_reopened(self):
        for text in ('Сдесь','Первое время хотелось бы остаться здесь'):
            c,store,h=self.chain();h += [(text,False)]
            with patch('assistant_contact_followup.refused',return_value=False),patch('assistant_chain.contact_refused',return_value=False):
                _,a=c.proposal(snapshot(*h));c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
                h += [(a['text'],True)];c.proposal(snapshot(*h))
            with store.connection() as db:before=db.execute('SELECT * FROM chain_actions').fetchall()
            c.responder=MagicMock(side_effect=AssertionError('No AI'))
            self.assertEqual(c.proposal(snapshot(*h,('Ага',False))),('declined',None))
            c.responder.assert_not_called()
            with store.connection() as db:self.assertEqual(db.execute('SELECT * FROM chain_actions').fetchall(),before)

    def test_questions_and_negations_not_preferences(self):
        for text in ('Хочу остаться здесь?', 'Не хочу остаться здесь','Первое время хотелось бы остаться здесь?',
                     'Сдесь твой номер?', '> Первое время хотелось бы остаться здесь\nДавай MAX'):
            self.assertFalse(follow.refused([dict(text=text)],requested=True),text)
