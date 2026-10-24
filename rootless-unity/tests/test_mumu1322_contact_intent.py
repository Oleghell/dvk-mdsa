"""Gallery-derived text fixtures, no profiles, numbers, screenshots or API calls."""
import unittest
from unittest.mock import MagicMock,patch
import assistant_contact_clarify as clarify
import assistant_contact_followup as follow
import test_mumu1311_context as fixtures
from test_guided_chain import snapshot,WHO

MAX_CASES=(
 'Нет телеграмма и ватсапа, есть макс',
 'Ну у меня только друг вокруг есть Макс',
 'В мах можно',
 'У меня есть макс😉больше не где нет',
 'У меня макс',
 'Ни того ни другого Макс только',
 'Я только в максе',
 'У меня только мак',
 'MAX у меня работает, остальное нет',
 'Можно в Мак?',
 'Предпочитаю общаться в MAX, так удобнее',
 'Пользуюсь приложением макс, пиши туда',
 'В Максе мне удобнее',
 'Мак можешь скачать нормальный мессенджер',
)
# A question merely suggesting an option is ambiguous, not a confirmed choice.
MAX_CASES=tuple(x for x in MAX_CASES if x!='Можно в Мак?')
SKIPS=(
 'Я здесь, почему не хочешь? 🤔', 'Для начала здесь удобнее',
 'Удобнее здесь', 'А мне удобнее тут остаться', 'Здесь что не так?',
 'Ни где. Так как не охота постоянно включать впн, он перебивает другие приложения',
 'Да и тут нормально', 'Нигде,не сижу там',
 'Пока здесь', 'Извини, не раздаю номер',
 'А вообще не сторонница давать номер телефона незнакомым',
 'У меня нет ни того не другого, и для начала лучше тут',
 'Ну мне здесь удобно', 'Замужем',
 'Не работает', 'Здесь пообщаемся',
 'Прости, меня не интересуют разовые встречи',
)

class Intents(unittest.TestCase):
    chain=fixtures.Refusals.chain
    def test_gallery_max_choices_use_one_fixed_request_without_ai(self):
        for text in MAX_CASES:
            with self.subTest(text=text):
                self.assertTrue(clarify.max_selected([dict(text=text)]))
                c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
                self.assertEqual(c.proposal(snapshot(*h,(text,False))),('pending-clarify',dict(kind='clarify',text=clarify.MAX_TEXT)))
                c.responder.assert_not_called()
    def test_gallery_refusals_skip_before_ai_and_do_not_reopen(self):
        for text in SKIPS:
            with self.subTest(text=text):
                c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
                self.assertEqual(c.proposal(snapshot(*h,(text,False))),('declined',None))
                self.assertEqual(c.proposal(snapshot(*h,(text,False),('Хорошо',False))),('declined',None))
                c.responder.assert_not_called()
    def test_names_quotes_negations_and_other_apps_do_not_choose_max(self):
        for text in ('Макс сказал привет','Сын Макс','Мой друг Макс',
                     '> У меня макс\nТут удобнее', 'Максима знаю', 'Работаю в Макдональдсе',
                     'Макс не работает','Нет макса','Не хочу в мак','У меня нет MAX',
                     'У меня работает только Макс?','А у тебя есть Макс?',
                     'Не пользуюсь максом','Пользуюсь Максом не буду'):
            with self.subTest(text=text):self.assertFalse(clarify.max_selected([dict(text=text)]))
    def test_negative_unavailable_other_apps_does_not_cancel_max(self):
        c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
        self.assertEqual(c.proposal(snapshot(*h,('Ни того ни другого',False),('Есть мак',False))),
                         ('pending-clarify',dict(kind='clarify',text=clarify.MAX_TEXT)))
    def test_explicit_privacy_refusal_wins_over_max(self):
        c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
        self.assertEqual(c.proposal(snapshot(*h,('У меня макс',False),('Номер не дам',False))),('declined',None))
    def test_preference_is_not_location_or_quoted_question(self):
        for text in ('Здесь твой номер?', 'Здесь номер для MAX', 'Мне не удобно здесь',
                     'Не хочу остаться здесь','Где здесь удобнее?', '> Пока здесь\nДавай MAX'):
            with self.subTest(text=text):self.assertFalse(follow.refused([dict(text=text)],requested=True))
    def test_old_observed_generic_reply_can_be_corrected_without_repeating_it(self):
        c,store,h=self.chain();text='У меня есть макс';h.append((text,False))
        with patch('assistant_chain.max_selected',return_value=False),patch('assistant_contact_clarify.max_selected',return_value=False):
            _,a=c.proposal(snapshot(*h));c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
            h.append((a['text'],True));c.proposal(snapshot(*h))
        c.responder=MagicMock(side_effect=AssertionError('No AI'))
        self.assertEqual(c.proposal(snapshot(*h,('Как хочешь',False))),('pending-clarify',dict(kind='clarify',text=clarify.MAX_TEXT)))
    def test_old_preference_is_terminal_without_resetting_actions(self):
        c,store,h=self.chain();h.append(('Для начала здесь удобнее',False))
        with patch('assistant_chain.contact_refused',return_value=False),patch('assistant_contact_followup.refused',return_value=False):
            _,a=c.proposal(snapshot(*h));c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
            h.append((a['text'],True));c.proposal(snapshot(*h))
        with store.connection() as db:before=db.execute('SELECT * FROM chain_actions').fetchall()
        c.responder=MagicMock(side_effect=AssertionError('No AI'))
        self.assertEqual(c.proposal(snapshot(*h,('Чем занимаешься?',False))),('declined',None))
        with store.connection() as db:self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())
    def test_mac_labelled_number_is_contact_not_another_request(self):
        c,store,h=self.chain()
        self.assertEqual(c.proposal(snapshot(*h,('Мак 89991234567',False))),('done',None))

class StrictContactOnly(unittest.TestCase):
    def chain(self):
        c,store,h=fixtures.Refusals.chain(self)
        from assistant_contact_policy import enable
        enable(store)
        return c,store,h
    def test_questions_and_offtopic_after_proposal_never_call_ai(self):
        for text in ('Ты откуда?','Женат?','Чем занимаешься?','Зачем?',
                     'К чему такая настойчивость??','В каком городе?',
                     'Да, буду отдыхать','Хорошо','Давай','😉','Сам как?',
                     'Жду номер','Давай я тебя найду','Есть тг. Ты женат?', 'В макс можно, ты откуда?'):
            with self.subTest(text=text):
                c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
                self.assertEqual(c.proposal(snapshot(*h,(text,False))),('declined',None))
                self.assertEqual(c.proposal(snapshot(*h,(text,False),('Еще вопрос?',False))),('declined',None))
                c.responder.assert_not_called()
    def test_max_and_one_clarification_still_work_then_contact_wins(self):
        from assistant_chain import text_hash
        c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
        h.append(('Ни того ни другого, есть мак',False));stage,a=c.proposal(snapshot(*h))
        self.assertEqual((stage,a),('pending-clarify',dict(kind='clarify',text=clarify.MAX_TEXT)))
        c.reserve_confirmed(WHO,a);c.finish(WHO,a,True);h.append((a['text'],True));c.proposal(snapshot(*h))
        self.assertEqual(c.proposal(snapshot(*h,('89991234567',False))),('done',None))
        c.responder.assert_not_called()
    def test_unrelated_packet_while_send_unknown_does_not_replay_it(self):
        c,store,h=self.chain();h.append(('Есть MAX',False));_,a=c.proposal(snapshot(*h))
        c.reserve_confirmed(WHO,a);c.finish(WHO,a,False)
        with store.connection() as db:before=db.execute('SELECT * FROM chain_actions').fetchall()
        self.assertEqual(c.proposal(snapshot(*h,('Женат?',False))),('declined',None))
        with store.connection() as db:self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())
    def test_old_unsent_followup_draft_not_restored_or_sent(self):
        c,store,h=fixtures.Refusals.chain(self);h.append(('Ты откуда?',False))
        _,a=c.proposal(snapshot(*h));self.assertEqual(a['kind'],'followup')
        from assistant_contact_policy import enable
        enable(store);c.responder=MagicMock(side_effect=AssertionError('No AI'))
        with store.connection() as db:before=db.execute('SELECT * FROM chain_actions').fetchall()
        self.assertEqual(c.proposal(snapshot(*h)),('declined',None))
        with store.connection() as db:self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())
        c.responder.assert_not_called()
    def test_whatsapp_choice_and_indifferent_are_still_contact_related(self):
        for text in ('Да без разницы','Давай ватсап'):
            c,store,h=self.chain()
            stage,a=c.proposal(snapshot(*h,(text,False)))
            self.assertEqual(stage,'pending-clarify');self.assertEqual(a['kind'],'clarify')
    def test_strict_mode_does_not_change_greeting_question_contact_stages(self):
        import tempfile
        from pathlib import Path
        from assistant_store import Store
        from assistant_guided_chain import GuidedChain
        from assistant_contact_policy import enable
        from test_guided_chain import GREETING
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        store=Store(Path(folder.name)/'db',Path(folder.name)/'old')
        c=GuidedChain(store,choose=lambda:0,seal=lambda x:x,unseal=lambda x:x)
        c.bind(snapshot(),(GREETING,),approved=True);enable(store)
        stage,a=c.proposal(snapshot(('Привет',False)))
        self.assertEqual(stage,'pending-question')
        c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
        stage,b=c.proposal(snapshot(('Привет',False),(a['text'],True),('Нормально, а у тебя?',False)))
        self.assertEqual(stage,'pending-contact');self.assertEqual(b['kind'],'contact')
    def test_direct_contact_wins_even_when_same_packet_has_unrelated_question(self):
        c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
        self.assertEqual(c.proposal(snapshot(*h,('Мак 89991234567',False),('Ты откуда?',False))),('done',None))
        c.responder.assert_not_called()
