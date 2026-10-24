"""Synthetic regression for explicit extended stay-here preferences."""
import unittest
from unittest.mock import MagicMock,patch
import assistant_contact_followup as follow
import test_mumu1311_context as fixtures
from test_guided_chain import snapshot,WHO

CASES=('Мне удобнее здесь, пока не увижу человека в живую',
       'Будем общаться здесь,а потом будем видно.',
       'Мне здесь удобно общаться', 'Ни где)')

class StayHere(unittest.TestCase):
    chain=fixtures.Refusals.chain

    def test_exact_screenshots_and_variants_require_contact_context(self):
        for text in CASES+('Мне удобнее здесь','Мне комфортнее тут.',
                           'Будем общаться здесь, а потом будет видно.',
                           'Давайте будем переписываться тут',
                           'Мне удобнее здесь, пока не увижу тебя вживую'):
            with self.subTest(text=text):
                self.assertTrue(follow.refused([dict(text=text)],requested=True))
                self.assertFalse(follow.refused([dict(text=text)],requested=False))

    def test_questions_quotes_negations_and_contact_instructions_are_not_refusals(self):
        for text in ('Нигде не могу найти твой профиль', 'Ты здесь?', 'Будем общаться здесь?', 'Мне удобнее здесь?',
                     'Мне не удобнее здесь','Не будем общаться здесь',
                     'Мне удобнее здесь получить твой номер',
                     'Будем общаться здесь или в Telegram?',
                     'Здесь мой номер 89123456789',
                     '> Будем общаться здесь,а потом будем видно.\nДавай Telegram',
                     '> Мне удобнее здесь, пока не увижу человека в живую\nДля чего?'):
            with self.subTest(text=text):
                self.assertFalse(follow.refused([dict(text=text)],requested=True))

    def test_declines_before_ai_without_new_send_and_never_reopens(self):
        for text in CASES:
            with self.subTest(text=text):
                c,store,h=self.chain()
                with store.connection() as db:
                    actions=db.execute('SELECT * FROM chain_actions').fetchall()
                c.responder=MagicMock(side_effect=AssertionError('No AI after refusal'))
                self.assertEqual(c.proposal(snapshot(*h,(text,False))),('declined',None))
                self.assertEqual(c.proposal(snapshot(*h,(text,False),('Давай',False))),('declined',None))
                c.responder.assert_not_called()
                with store.connection() as db:
                    self.assertEqual(db.execute('SELECT * FROM chain_actions').fetchall(),actions)
                    self.assertEqual(db.execute('SELECT stage FROM chain_dialogs').fetchone()[0],'declined')

    def test_preference_in_packet_with_questions_still_declines(self):
        c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
        packet=[(CASES[0],False),('Случайно городами не ошибаются',False),('А в каком моём городе?',False)]
        self.assertEqual(c.proposal(snapshot(*h,*packet)),('declined',None))
        c.responder.assert_not_called()

    def test_unknown_reservation_is_never_reset_by_extended_preference(self):
        for text in CASES:
            c,store,h=self.chain()
            with store.connection() as db:db.execute("UPDATE chain_actions SET status='reserved-unknown' WHERE kind='contact'")
            self.assertEqual(c.proposal(snapshot(*h,(text,False))),('declined',None))
            with store.connection() as db:self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='contact'").fetchone()[0],'reserved-unknown')

    def test_history_answered_by_old_version_is_terminal_without_reset(self):
        for text in CASES:
            with self.subTest(text=text):
                c,store,h=self.chain();h += [(text,False)]
                # Simulate an older version which already answered the preference.
                with patch('assistant_contact_followup.refused',return_value=False),patch('assistant_chain.contact_refused',return_value=False):
                    _,a=c.proposal(snapshot(*h));self.assertIsNotNone(a)
                    c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
                    h += [(a['text'],True)];c.proposal(snapshot(*h))
                with store.connection() as db:actions=db.execute('SELECT * FROM chain_actions').fetchall()
                c.responder=MagicMock(side_effect=AssertionError('No AI'))
                self.assertEqual(c.proposal(snapshot(*h,('Давай',False))),('declined',None))
                c.responder.assert_not_called()
                with store.connection() as db:self.assertEqual(db.execute('SELECT * FROM chain_actions').fetchall(),actions)

if __name__=='__main__':unittest.main()
