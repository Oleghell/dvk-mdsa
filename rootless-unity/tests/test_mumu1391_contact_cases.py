"""Reports 9104352d port 5567 (v1.3.91): two contact-stage replies were skipped.

1. «Вайцап» - the colloquial WhatsApp spelling with «й» - was outside the
   spelling family, so the peer's messenger CHOICE was unrecognized and the
   live chain closed declined («Цепочка закрыта без нового ответа…»).
2. «Ватсап можно 89241810009 толком без пошлости прошу вас» - the peer chose
   the messenger AND attached her number with a polite condition; the
   non-punctuation remainder refused her own number and the chain closed
   declined with the contact lost.
No device, accounts or external requests.
"""
import unittest
from unittest.mock import MagicMock

import test_guided_chain as guide
import shared_contact
from shared_contact import self_shared, voluntary_batch
from assistant_contact_clarify import chosen, WHATSAPP_TEXT
from assistant_contact_intent import available_alternative
from assistant_contact_policy import enable, should_close
from assistant_contact_followup import refused as contact_refused
import test_1210_context_loading as base

REPORTED = 'Ватсап можно 89241810009 толком без пошлости прошу вас'
WHO = guide.WHO


class SpellingFamily(unittest.TestCase):
    """«Вайцап» is a WhatsApp choice exactly like «Ватсап»."""

    def test_y_spelling_is_a_recognized_whatsapp_choice(self):
        for text in ('Вайцап', 'вайцап', 'Войцап', 'Вайцапе сижу', 'вайсап',
                     'Ватсап можно', 'Ватсапом пользуюсь'):
            with self.subTest(text=text):
                self.assertTrue(chosen([dict(text=text)]), text)
                self.assertEqual(available_alternative([dict(text=text)]), 'whatsapp', text)

    def test_old_family_members_still_choose(self):
        for text in ('Ватсап', 'Вацап', 'вотсап', 'Ватсапп', 'ватапп', 'воцап'):
            with self.subTest(text=text):
                self.assertTrue(chosen([dict(text=text)]), text)
                self.assertEqual(available_alternative([dict(text=text)]), 'whatsapp', text)

    def test_negated_y_spelling_stays_unavailable_not_a_choice(self):
        for text in ('Вайцап не работает', 'вайцапа нет', 'Не пользуюсь вайцап',
                     'Ватсап не работает', 'Телеграм нет'):
            with self.subTest(text=text):
                self.assertIsNone(available_alternative([dict(text=text)]), text)
        for text in ('У меня нет вайцапа', 'нету вайцапа', 'Нет ватсапа'):
            with self.subTest(text=text):
                self.assertTrue(contact_refused([dict(text=text)], requested=True), text)

    def test_negated_presence_with_y_spelling_keeps_the_phone_refused(self):
        for text in ('нет у меня вайцапа, есть макс: 89646974728',
                     'у меня нет вайцапа'):
            with self.subTest(text=text):
                self.assertEqual(self_shared(text, requested=True), [], text)

    def test_y_spelling_clause_stays_contact_related(self):
        # The should_close clause gate: a question naming the app is not
        # an off-topic arrival even with the new spelling.
        import tempfile
        from pathlib import Path
        from assistant_store import Store
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'a.sqlite3', Path(tmp) / 'old')
            enable(store)
            with store.connection() as db:
                self.assertFalse(should_close(db, dict(identity=dict(WHO)), 'wait-contact',
                                              [dict(text='Вайцап есть?')], requested=True))


class ConsentContact(unittest.TestCase):
    """A number attached to an explicit messenger consent is the peer's own."""

    def test_the_reported_message_saves_the_phone(self):
        self.assertEqual(self_shared(REPORTED, requested=True), ['+79241810009'])
        self.assertEqual(self_shared(REPORTED, requested=False), [])
        self.assertTrue(voluntary_batch([dict(text=REPORTED)]))

    def test_consent_variants_with_polite_remainder_save_the_phone(self):
        for text in ('вайцап можно 89241810009', 'Ватсап можно, только без пошлости прошу вас, 89241810009',
                     'Телеграм давай 89991234567, пишите по делу', 'Ватсап есть, можно 89241810009'):
            with self.subTest(text=text):
                self.assertTrue(self_shared(text, requested=True), text)

    def test_clarify_answer_shape_still_saves_the_bare_number(self):
        self.assertEqual(self_shared('89241810009', requested=True), ['+79241810009'])
        self.assertEqual(self_shared('89241810009', requested=False), [])

    def test_questions_third_party_negations_and_quotes_stay_rejected(self):
        for text in ('На ватсап нельзя 89991234567',
                     'Ватсап можно 89991234567?',
                     'Ватсап можно номер подруги 89991234567',
                     'Не пиши мне, ватсап можно 89991234567',
                     '«Ватсап можно 89991234567»',
                     'Ватсап можно код из смс 89991234567',
                     'вот телеграм мужа, можно 89991234567'):
            with self.subTest(text=text):
                self.assertEqual(self_shared(text, requested=True), [], text)

    def test_owner_phrasing_keeps_its_stricter_branch(self):
        # «У меня …» routes through the ownership branch and is unchanged.
        self.assertEqual(self_shared('У меня ватсап: 8964 697 47 28', requested=True),
                         ['+79646974728'])
        self.assertEqual(self_shared('у меня нет ватсапа', requested=True), [])


class ContactOnlyReportedCases(base.Context):
    """The production path: contact-only policy active, the chain must work."""

    def test_reported_choice_no_longer_closes_the_chain(self):
        import tempfile
        from pathlib import Path
        import assistant_guided_chain as guided
        from assistant_store import Store
        from conversation_engine import QUESTIONS, CONTACT_TEXT
        for phrase in ('Вайцап', 'Ватсап можно'):
            with self.subTest(phrase=phrase):
                with tempfile.TemporaryDirectory() as tmp:
                    store = Store(Path(tmp) / 'a.sqlite3', Path(tmp) / 'old')
                    chain = guided.GuidedChain(store, choose=lambda: 0,
                                               seal=lambda x: x, unseal=lambda x: x)
                    chain.bind(guide.snapshot(), (guide.GREETING,), approved=True)
                    h = [('Приветик', False), (QUESTIONS[0], True),
                         ('нормально!а у тебя?😊', False), (CONTACT_TEXT, True)]
                    for sample in [guide.snapshot(*h[:1]), guide.snapshot(*h[:2]),
                                   guide.snapshot(*h[:3]), guide.snapshot(*h)]:
                        stage, action = chain.proposal(sample)
                        if action:
                            chain.reserve_confirmed(WHO, action)
                            chain.finish(WHO, action, True)
                    self.assertEqual(stage, 'wait-contact')
                    enable(store)
                    stage, action = chain.proposal(guide.snapshot(*h, (phrase, False)))
                    self.assertEqual(stage, 'pending-clarify')
                    self.assertEqual(action['kind'], 'clarify')
                    self.assertEqual(action['text'], WHATSAPP_TEXT)

    def test_reported_contact_message_is_saved_not_declined(self):
        h = self.seed_contact()
        enable(self.store)
        stage, action = self.chain.proposal(guide.snapshot(*h, (REPORTED, False)))
        self.assertEqual((stage, action), ('done', None))
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT stage FROM chain_dialogs").fetchone()[0], 'done')

    def test_full_reported_dialog_choice_then_number_completes(self):
        import assistant_contact_clarify as clarify
        h = self.seed_contact() + [('Вайцап', False)]
        before = guide.snapshot(*h)
        sent = guide.snapshot(*h, (clarify.WHATSAPP_TEXT, True))
        contact = guide.snapshot(*h, (clarify.WHATSAPP_TEXT, True), (REPORTED, False))
        out = self.walk([before, before, sent, contact])
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(self.sent, [clarify.WHATSAPP_TEXT])
        self.notifier.assert_called_once_with(dict(name=guide.PEER_NAME, contacts=['+79241810009']))

    def test_reported_message_directly_in_wait_contact_is_forwarded(self):
        h = self.seed_contact() + [(REPORTED, False)]
        out = self.walk([guide.snapshot(*h)])
        self.assertEqual(out['status'], 'chain-completed')
        self.assertFalse(self.sent)
        self.notifier.assert_called_once_with(dict(name=guide.PEER_NAME, contacts=['+79241810009']))


# Reuse the Context fixtures, never its inherited tests (test_1212 convention).
for _name in dir(base.Context):
    if _name.startswith('test_') and _name not in ContactOnlyReportedCases.__dict__:
        setattr(ContactOnlyReportedCases, _name, None)


if __name__ == '__main__':
    unittest.main()
