"""Reports 9104352d (v1.3.98): live contact-stage replies were closed declined.

Telegram exit notices received from the running ports:
1. 5571 «89098384279 пиши» - the peer's own phone number with an invitation
   verb; the non-punctuation remainder refused it and the chain closed
   declined with the contact lost.
2. 5557 «вацапа нет / а макс» - WhatsApp negated, MAX chosen after the «а»
   conjunction; no pattern recognized the conjunction choice.
3. 5559 «У меня только ватсап» - ownership + «только» without any verb; the
   WhatsApp ownership form was not a positive availability signal.
4. 5567 «В ват сап» - the spaced spelling «ват сап» (space inside the
   consonant cluster) was outside the family.
5. 5563 «Вптсап» - the «п»-for-«о» keyboard typo was outside the family.
6. 5563 «Вптсап»/5567 «Вайцап» - re-pinned together with the rest of the
   family after the shared detector was widened.
Monitoring snapshots 611-638 (1.3.97) also show four ports stopped DEAD on
navigation error 'observer-stopped' (recoverable()=False, no recovery round
ever ran), city transitions stopping on frame-budget in the wait-city phase
with city_read_budget_retries=0, and profile reads stopping on frame-budget
in wait-profile/confirm-profile with profile_read_budget_retries=0.
No device, accounts or external requests.
"""
import unittest

import test_guided_chain as guide
import test_1210_context_loading as base
import shared_contact
from shared_contact import self_shared
from assistant_contact_clarify import chosen, WHATSAPP_TEXT, MAX_TEXT
from assistant_contact_intent import available_alternative, max_selected
from assistant_contact_policy import enable, should_close
from assistant_contact_followup import refused as contact_refused

WHO = guide.WHO


class SpellingFamily(unittest.TestCase):
    """«В ват сап»/«Вптсап» are WhatsApp choices exactly like «Ватсап»."""

    def test_spaced_cluster_and_keyboard_typo_choose_whatsapp(self):
        for text in ('В ват сап', 'в ват сап', 'Ват сап', 'вот сап', 'Вптсап',
                     'вптсап', 'В ватсап', 'Я в ват сапе'):
            with self.subTest(text=text):
                self.assertTrue(chosen([dict(text=text)]), text)
                self.assertEqual(available_alternative([dict(text=text)]), 'whatsapp', text)

    def test_old_family_members_still_choose(self):
        for text in ('Ватсап', 'Вацап', 'вотсап', 'Вайцап', 'Ватс ап', 'ватсапп'):
            with self.subTest(text=text):
                self.assertTrue(chosen([dict(text=text)]), text)
                self.assertEqual(available_alternative([dict(text=text)]), 'whatsapp', text)

    def test_negated_spaced_spelling_stays_unavailable(self):
        for text in ('Ват сап не работает', 'вптсапа нет', 'Не пользуюсь ват сап'):
            with self.subTest(text=text):
                self.assertIsNone(available_alternative([dict(text=text)]), text)


class MaxConjunction(unittest.TestCase):
    """«а макс» after a negated app, and «У меня Макс и …» are MAX choices."""

    def test_reported_conjunction_forms_choose_max(self):
        for text in ('вацапа нет / а макс', 'Ватсапа нет, а в максе сижу',
                     'У меня Макс и вацап.', 'телеграма нет а макс есть',
                     'а макс', 'а в максе сижу', 'зато макс работает'):
            with self.subTest(text=text):
                self.assertTrue(max_selected([dict(text=text)]), text)

    def test_negations_of_max_stay_denied_before_the_conjunction(self):
        for text in ('а макс не работает', 'а нет макса', 'У меня нет MAX',
                     'не пользуюсь максом', 'Макс не работает'):
            with self.subTest(text=text):
                self.assertFalse(max_selected([dict(text=text)]), text)

    def test_person_named_max_is_not_an_app_choice(self):
        for text in ('Мой друг Макс', 'Сын Макс', 'Макс сказал привет'):
            with self.subTest(text=text):
                self.assertFalse(max_selected([dict(text=text)]), text)


class WhatsappOwnership(unittest.TestCase):
    """«У меня (только) ватсап» is an available WhatsApp without any verb."""

    def test_reported_ownership_forms_choose_whatsapp(self):
        for text in ('У меня только ватсап', 'у меня есть ватсап',
                     'У меня ватсап', 'у меня только вайцап'):
            with self.subTest(text=text):
                self.assertEqual(available_alternative([dict(text=text)]), 'whatsapp', text)
                self.assertTrue(chosen([dict(text=text)]), text)

    def test_negated_ownership_stays_refused(self):
        for text in ('у меня нет ватсапа', 'нету ватсапа', 'У меня нет MAX'):
            with self.subTest(text=text):
                self.assertIsNone(available_alternative([dict(text=text)]), text)
        self.assertTrue(contact_refused([dict(text='у меня нет ватсапа')], requested=True))


class PhoneWithInvitation(unittest.TestCase):
    """«89098384279 пиши» answers the request with the peer's own number."""

    def test_reported_number_with_invitation_verbs_is_self_shared(self):
        for text in ('89098384279 пиши', '89098384279 пиши мне',
                     '89098384279, пиши', 'пиши 89098384279',
                     '89098384279 звони', 'напиши на 89098384279',
                     '89098384279 пиши, вот'):
            with self.subTest(text=text):
                self.assertEqual(self_shared(text, requested=True), ['+79098384279'], text)
        # Without the explicit request only the ownership forms may pass; the
        # bare invitation verbs alone stay insufficient (the OWNER branch's
        # «пиши мне» form keeps its own pre-existing doctrine).
        for text in ('89098384279 пиши', '89098384279, пиши',
                     'пиши 89098384279', '89098384279 звони'):
            with self.subTest(text=text):
                self.assertEqual(self_shared(text, requested=False), [], text)

    def test_number_with_spaced_whatsapp_label_is_self_shared(self):
        self.assertEqual(self_shared('в ват сап 89098384279 пиши', requested=True),
                         ['+79098384279'])

    def test_third_party_and_offtopic_remainders_stay_rejected(self):
        for text in ('89098384279 пиши моей подруге',
                     '89098384279 пиши вечером'):
            with self.subTest(text=text):
                self.assertEqual(self_shared(text, requested=True), [], text)

    def test_phone_during_in_flight_clarification_does_not_close_the_chain(self):
        import tempfile
        from pathlib import Path
        from assistant_store import Store
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'a.sqlite3', Path(tmp) / 'old')
            enable(store)
            with store.connection() as db:
                self.assertFalse(should_close(
                    db, dict(identity=dict(WHO)), 'pending-clarify',
                    [dict(text='89098384279 пиши')], requested=True))


class SupervisionObserverStopped(unittest.TestCase):
    """A port stopped on observer-stopped must enter recovery, not die."""

    REPORT = dict(status='stopped', reason='profile-pass-stopped',
                  last_profile_run=dict(status='stopped', reason='profiles-not-finished',
                      profiles=dict(status='profiles-stopped', reason='profile-check-stopped',
                          host_failure='state-check-failed', host_checkpoint='profile-verify',
                          last_error='observer-stopped',
                          last_profile_diagnostics=dict(stage='navigation-stopped',
                              error='observer-stopped', phase='wait-chat', frames=5,
                              managed_calls=386, chat_open_completed=True))))

    def test_observer_stopped_navigation_is_recoverable(self):
        from mumu_recovery import recoverable, RETRY_CODES
        self.assertIn('observer-stopped', RETRY_CODES)
        self.assertTrue(recoverable(self.REPORT))

    def test_frame_budget_profile_stop_stays_recoverable(self):
        from mumu_recovery import recoverable
        report = dict(self.REPORT)
        profiles = dict(report['last_profile_run']['profiles'])
        profiles['last_error'] = 'frame-budget'
        profiles['last_profile_diagnostics'] = dict(stage='navigation-stopped',
            error='frame-budget', phase='wait-profile', frames=30, managed_calls=2778)
        report['last_profile_run'] = dict(report['last_profile_run'], profiles=profiles)
        self.assertTrue(recoverable(report))


class NativeRetryClauses(unittest.TestCase):
    """The wait-city and wait-profile observation frames retry their budget."""

    def test_city_wait_city_phase_retries_frame_budget(self):
        import search_city
        source = search_city.build('Москва')
        self.assertIn("(n.phase==='wait-city'&&n.city_open_completed)", source)

    def test_profile_wait_phases_retry_frame_budget_before_close(self):
        from assistant_profile_read import specialize
        import chat_batch
        source = specialize(chat_batch.FUNCTION)
        self.assertIn("['wait-profile','confirm-profile'].includes(n.phase)", source)
        self.assertIn("!n.close_attempted", source)


class ContactOnlyReportedCases(base.Context):
    """The production path: contact-only policy active, the chain must work."""

    def test_reported_phone_reply_completes_the_chain(self):
        h = self.seed_contact() + [('89098384279 пиши', False)]
        out = self.walk([guide.snapshot(*h)])
        self.assertEqual(out['status'], 'chain-completed')
        self.assertFalse(self.sent)
        self.notifier.assert_called_once_with(dict(name=guide.PEER_NAME,
                                                   contacts=['+79098384279']))

    def test_reported_conjunction_max_choice_asks_the_max_number(self):
        h = self.seed_contact()
        enable(self.store)
        stage, action = self.chain.proposal(guide.snapshot(*h, ('вацапа нет / а макс', False)))
        self.assertEqual((stage, action), ('pending-clarify', dict(kind='clarify', text=MAX_TEXT)))

    def test_reported_max_and_whatsapp_ownership_asks_the_max_number(self):
        h = self.seed_contact()
        enable(self.store)
        stage, action = self.chain.proposal(guide.snapshot(*h, ('У меня Макс и вацап.', False)))
        self.assertEqual((stage, action), ('pending-clarify', dict(kind='clarify', text=MAX_TEXT)))

    def test_reported_whatsapp_ownership_asks_the_whatsapp_number(self):
        h = self.seed_contact()
        enable(self.store)
        stage, action = self.chain.proposal(guide.snapshot(*h, ('У меня только ватсап', False)))
        self.assertEqual((stage, action), ('pending-clarify', dict(kind='clarify', text=WHATSAPP_TEXT)))

    def test_reported_spaced_and_typo_spellings_ask_the_whatsapp_number(self):
        import tempfile
        from pathlib import Path
        import assistant_guided_chain as guided
        from assistant_store import Store
        h = self.seed_contact()
        for phrase in ('В ват сап', 'Вптсап', 'Вайцап'):
            with self.subTest(phrase=phrase):
                with tempfile.TemporaryDirectory() as tmp:
                    store = Store(Path(tmp) / 'a.sqlite3', Path(tmp) / 'old')
                    chain = guided.GuidedChain(store, choose=lambda: 0,
                                               seal=lambda v: v, unseal=lambda v: v)
                    chain.bind(guide.snapshot(), (guide.GREETING,), approved=True)
                    for sample in [guide.snapshot(*h[:1]), guide.snapshot(*h[:2]),
                                   guide.snapshot(*h[:3]), guide.snapshot(*h)]:
                        stage, action = chain.proposal(sample)
                        if action:
                            chain.reserve_confirmed(WHO, action)
                            chain.finish(WHO, action, True)
                    enable(store)
                    stage, action = chain.proposal(guide.snapshot(*h, (phrase, False)))
                    self.assertEqual((stage, action), ('pending-clarify',
                                                       dict(kind='clarify', text=WHATSAPP_TEXT)))

    def test_phone_arriving_before_the_clarify_is_visible_is_not_lost(self):
        import assistant_contact_clarify as clarify
        h = self.seed_contact() + [('Ватсап', False)]
        before = guide.snapshot(*h)
        sent = guide.snapshot(*h, (clarify.WHATSAPP_TEXT, True))
        # Her number arrives BEFORE our clarify becomes visible in history:
        # the chain must not close declined, and once the clarify is observed
        # the same number is safely attributed and forwarded.
        with_number = guide.snapshot(*h, (clarify.WHATSAPP_TEXT, True), ('89098384279 пиши', False))
        out = self.walk([before, before, sent, with_number, with_number])
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(self.sent, [clarify.WHATSAPP_TEXT])
        self.notifier.assert_called_once_with(dict(name=guide.PEER_NAME,
                                                   contacts=['+79098384279']))


# Reuse the Context fixtures, never its inherited tests (test_1212 convention).
for _name in dir(base.Context):
    if _name.startswith('test_') and _name not in ContactOnlyReportedCases.__dict__:
        setattr(ContactOnlyReportedCases, _name, None)


if __name__ == '__main__':
    unittest.main()
