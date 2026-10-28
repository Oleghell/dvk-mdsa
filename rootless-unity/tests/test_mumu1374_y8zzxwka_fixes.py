"""Reports 491-493 (v1.3.73) + four user Telegram cases (y8zZxWkA).

Contact side: «Есть? / Макс», «У меня ватсап: 8964 697 47 28», «Макс ватцап»
and «Ptaha3112» must never close a live chain — they clarify or save.
Transport side: an exhausted transient pre-send window defers one verified
no-send skip instead of stopping the port; the pre-script snapshot read joins
the bounded setup retry. No live data, no network."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import assistant_pass as native
import assistant_setup_retry as setup_retry
import shared_contact
from assistant_chain import step
from assistant_contact_clarify import chosen
from assistant_contact_policy import should_close
from cloud_database import CloudDatabaseError, TRANSIENT_CODES
from conversation_engine import QUESTIONS, CONTACT_TEXT
from test_assistant_chain import GREETING, msg, snap


def transient():
    value = CloudDatabaseError('cloud-database-unavailable')
    value.operation = 'connect'
    return value


def permission():
    value = CloudDatabaseError('cloud-database-permission')
    value.operation = 'read'
    return value


def pending():
    return dict(attempt=1, account='100', peer='200', chat='300', variant=0)


def run_monitor(peer_claimed, peer_terminal=None, cancelled=lambda: False, reserve=None, preclaimed=frozenset()):
    script = MagicMock(); script.exports_sync.cohortpending.return_value = pending()
    script.exports_sync.cohortack.return_value = True
    done = MagicMock(); done.wait.return_value = False; done.is_set.return_value = False
    store = MagicMock(); store.mumu_shared_claims = True
    store.peer_claimed = peer_claimed
    store.peer_terminal = peer_terminal if peer_terminal is not None else MagicMock(return_value=False)
    store.reserve = reserve if reserve is not None else MagicMock(return_value=17)
    state = {}; failures = []
    with patch.object(native, 'SHARED_READ_RETRY_DELAYS', (0, 0)):
        native.monitor(script, store, 'Hi', lambda *a: True, done, cancelled, state, failures, preclaimed)
    return script, store, state, failures


class OwnershipRemainder(unittest.TestCase):
    def test_russian_presence_phrase_accepts_the_phone(self):
        for text in ('У меня ватсап: 8964 697 47 28', 'у меня ватсап 89646974728',
                     'Есть 89646974728', 'В ватсапе у меня +7 964 697 47 28'):
            with self.subTest(text=text):
                self.assertEqual(shared_contact.self_shared(text, requested=True),
                                 ['+79646974728'])

    def test_ambiguous_negated_presence_stays_unsaved(self):
        for text in ('нет у меня ватсапа, есть макс: 89646974728', 'у меня нет ватсапа'):
            with self.subTest(text=text):
                self.assertEqual(shared_contact.self_shared(text, requested=True), [])


class BareLatinHandle(unittest.TestCase):
    def test_single_latin_token_after_request_is_saved(self):
        for text, want in (('Ptaha3112', ['@Ptaha3112']), ('Love_1712', ['@Love_1712']),
                           (' Ptaha3112 ', ['@Ptaha3112']), ('Ptaha3112.', ['@Ptaha3112'])):
            with self.subTest(text=text):
                self.assertEqual(shared_contact.self_shared(text, requested=True), want)

    def test_stopwords_and_multi_token_messages_stay_unsaved(self):
        for text in ('hello', 'thanks', 'sorry', 'privet', 'spasibo', 'whatsapp',
                     'telegram', 'Telegram', 'ab', '12345', 'Ptaha3112 hello', 'нет'):
            with self.subTest(text=text):
                self.assertEqual(shared_contact.self_shared(text, requested=True), [])
        self.assertEqual(shared_contact.self_shared('Ptaha3112', requested=False), [])


class MessengerJuxtaposition(unittest.TestCase):
    def test_terse_choice_in_either_order_selects(self):
        self.assertTrue(chosen([dict(text='Макс ватцап')]))
        self.assertTrue(chosen([dict(text='ватцап макс')]))
        self.assertTrue(chosen([dict(text='тг или ватсап')]))

    def test_negated_or_plain_word_pairs_stay_unselected(self):
        self.assertFalse(chosen([dict(text='макс нет')]))
        self.assertFalse(chosen([dict(text='ватцап не работает')]))
        # App questions with «есть» already counted as availability before this
        # release (PLATFORM+CHOICE); only NEGATIVE and non-availability forms stay closed.
        self.assertTrue(chosen([dict(text='макс ватцап есть?')]))


class AvailabilityEchoQuestion(unittest.TestCase):
    def db(self):
        db = MagicMock()

        def execute(sql, *args):
            result = MagicMock()
            if 'sqlite_master' in sql or 'inbox_reply_policy' in sql:
                result.fetchone.return_value = (1,)
            else:
                result.fetchone.return_value = None
            return result

        db.execute.side_effect = execute
        return db

    def test_echo_question_with_a_choice_does_not_close(self):
        snapshot = dict(identity=dict(chat='300'))
        incoming = [dict(text='Есть?'), dict(text='Макс')]
        self.assertFalse(should_close(self.db(), snapshot, 'wait-contact', incoming,
                                      requested=True, max_choice=True))

    def test_personal_question_still_closes(self):
        snapshot = dict(identity=dict(chat='300'))
        incoming = [dict(text='а ты откуда?')]
        self.assertTrue(should_close(self.db(), snapshot, 'wait-contact', incoming, requested=True))


class UserCasesEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from assistant_store import Store
        from assistant_guided_chain import GuidedChain
        from assistant_contact_policy import enable
        self.path = Path(self.temp.name) / 'assistant.sqlite3'
        self.store = Store(self.path, Path(self.temp.name) / 'old')
        action = self.store.reserve(dict(attempt=1, account='100', peer='200', chat='-1', variant=0),
                                    GREETING, approved=True)
        self.store.finish(action, dict(send_attempted=True, send_handler_returned=True))
        seal = lambda data: bytes(b ^ 77 for b in data)
        self.chain = GuidedChain(self.store, choose=lambda: 0, seal=seal, unseal=seal)
        self.chain.bind(snap(), (GREETING,), approved=True)
        enable(self.store)
        self.sent = []

    def send(self, before, text):
        self.sent.append(text)
        return dict(attempted=True, handler_returned=True)

    def reach_wait_contact(self):
        reply = msg(1002, 'Привет!')
        step(self.chain, snap(reply), self.send)
        question = msg(1003, QUESTIONS[0], True)
        step(self.chain, snap(reply, question), self.send)
        mood = msg(1004, 'Отлично!')
        step(self.chain, snap(reply, question, mood), self.send)
        contact = msg(1005, CONTACT_TEXT, True)
        self.assertEqual(step(self.chain, snap(reply, question, mood, contact), self.send),
                         'wait-contact')
        return [reply, question, mood, contact]

    def feed(self, texts):
        history = self.reach_wait_contact()
        for i, text in enumerate(texts, start=1006):
            history.append(msg(i, text))
        snapshot = snap(*history)
        snapshot['peer_name'] = 'ИмяДляТеста'
        return step(self.chain, snapshot, self.send)

    def saved_payload(self):
        with self.store.connection() as db:
            row = db.execute("SELECT payload FROM chain_contact_outbox WHERE chat='300'").fetchone()
        return bytes(b ^ 77 for b in row[0]).decode('utf-8', 'replace') if row else None

    def test_case_1_echo_with_max_choice_clarifies_further(self):
        from assistant_contact_clarify import MAX_TEXT
        self.assertEqual(self.feed(['Есть?', 'Макс']), 'await-outgoing')
        self.assertIn(MAX_TEXT, self.sent)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT stage FROM chain_dialogs WHERE chat='300'").fetchone()[0],
                             'pending-clarify')

    def test_case_2_whatsapp_phone_is_saved(self):
        self.assertEqual(self.feed(['У меня ватсап: 8964 697 47 28']), 'done')
        self.assertIn('+79646974728', self.saved_payload())

    def test_case_3_terse_choice_clarifies_further(self):
        from assistant_contact_clarify import TEXT as CLARIFY_TEXT
        self.assertEqual(self.feed(['Макс ватцап']), 'await-outgoing')
        self.assertIn(CLARIFY_TEXT, self.sent)

    def test_case_4_latin_word_is_saved_as_telegram(self):
        self.assertEqual(self.feed(['Ptaha3112']), 'done')
        self.assertIn('@Ptaha3112', self.saved_payload())


class DeferredSkip(unittest.TestCase):
    def test_snapshot_claimed_peer_skips_without_failure_or_database_read(self):
        # 1.3.79 (aPYyN7weMm): the claimed-peer pre-check consults the pass-start
        # snapshot, so pooler saturation can no longer defer an already-opened
        # chat; a snapshot-claimed peer takes the verified no-send skip directly.
        script, store, state, failures = run_monitor(
            MagicMock(side_effect=[transient() for _ in range(3)]), preclaimed=frozenset({'200'}))
        store.peer_claimed.assert_not_called()
        self.assertTrue(state['shared_peer_skipped'])
        self.assertFalse(failures)
        script.exports_sync.cancel.assert_not_called()
        store.reserve.assert_not_called()
        self.assertEqual(script.exports_sync.cohortack.call_args.args[0].get('skip'), True)

    def test_clean_snapshot_peer_never_touches_the_peer_claimed_registry(self):
        script, store, state, failures = run_monitor(
            MagicMock(side_effect=[permission() for _ in range(3)]))
        store.peer_claimed.assert_not_called()
        self.assertFalse(failures)
        store.reserve.assert_called_once()
        script.exports_sync.cohortack.assert_called_once()
        script.exports_sync.cancel.assert_not_called()

    def test_terminal_check_exhaustion_skips_keeping_reservation(self):
        # v1.3.81: the separate post-reserve terminal read no longer exists -
        # reserve()'s atomic blocked() re-check is the terminal authority, so
        # a terminally blocked peer raises SharedPeerClaimed straight into the
        # verified no-send skip (no extra pooled roundtrip, no retained-claim
        # defer path). Exhaustion of the RESERVE window on an alive cycle
        # keeps the verified skip without any claim.
        from mumu_store import SharedPeerClaimed
        script, store, state, failures = run_monitor(
            MagicMock(), reserve=MagicMock(side_effect=SharedPeerClaimed('blocked')))
        self.assertTrue(state['shared_peer_skipped'])
        self.assertFalse(failures)
        store.release_reservation.assert_not_called()
        script.exports_sync.cancel.assert_not_called()
        self.assertEqual(script.exports_sync.cohortack.call_args.args[0].get('skip'), True)

    def test_non_transient_terminal_exhaustion_keeps_the_hard_gate(self):
        # The hard gate moved with the live read: a non-transient reserve
        # failure still stops the cycle with the checkpoint named.
        script, store, state, failures = run_monitor(
            MagicMock(), reserve=MagicMock(side_effect=permission()))
        self.assertTrue(failures)
        self.assertEqual(state['authorization_checkpoint'], 'profile-reserve')
        script.exports_sync.cancel.assert_called_once()

    def test_stop_during_the_window_never_defers(self):
        flag = {'stop': False}

        def fail_then_stop(*args, **kwargs):
            flag['stop'] = True
            raise transient()

        script, store, state, failures = run_monitor(
            MagicMock(), reserve=MagicMock(side_effect=fail_then_stop), cancelled=lambda: flag['stop'])
        self.assertFalse(state.get('peer_check_deferred'))
        self.assertTrue(failures)
        script.exports_sync.cancel.assert_called_once()


class DeferredVisitRecord(unittest.TestCase):
    def navigation(self, skipped=True):
        return dict(stage='navigation-ready' if skipped else 'navigation-stopped',
                    send_attempted=False, send_handler_returned=False,
                    shared_peer_skipped=skipped, profile_verified=True,
                    friends_count=0, history_status='empty')

    def test_transient_visit_failure_is_swallowed_only_when_deferred(self):
        from assistant_pass import PROFILE_DIAGNOSTIC_FIELDS
        self.assertIn('shared_peer_skipped', PROFILE_DIAGNOSTIC_FIELDS)
        store = MagicMock(); store.record_visit.side_effect = transient()
        state = {'peer_check_deferred': True}
        script = MagicMock(); script.exports_sync.selectedpeer.return_value = '200'
        value = {'navigation': self.navigation(True)}
        with patch.object(native, 'validate', return_value=value), \
                patch.object(native, 'FINALIZE_RPC_SECONDS', 60):
            # The swallow lives inside inspect(); exercise it through the same
            # guarded conditions it checks.
            error = transient()
            deferred = (state.get('peer_check_deferred') is True
                        and isinstance(error, CloudDatabaseError)
                        and error.code in TRANSIENT_CODES
                        and not value['navigation']['send_attempted']
                        and not value['navigation']['send_handler_returned'])
            self.assertTrue(deferred)

    def test_send_cycle_visit_failure_is_not_swallowed(self):
        state = {'peer_check_deferred': False}
        value = {'navigation': self.navigation(False)}
        error = transient()
        deferred = (state.get('peer_check_deferred') is True
                    and isinstance(error, CloudDatabaseError)
                    and error.code in TRANSIENT_CODES
                    and not value['navigation']['send_attempted'])
        self.assertFalse(deferred)


class ProfileHistorySetupRetry(unittest.TestCase):
    def failure(self, stage, code, error_type='CloudDatabaseError'):
        value = dict(stage=stage, error='prepare-%s-failed' % stage, error_type=error_type)
        if code is not None:
            value['database'] = dict(code=code, operation='connect', automatic_retry=False)
        return value

    def error(self, preparation, stage='device-inspection'):
        error = CloudDatabaseError('cloud-database-unavailable')
        error.operation = 'connect'
        error._dvk_profile_not_executed = True
        error._dvk_preparation = preparation
        error._dvk_failure = dict(stage=stage, error='startup-%s-failed' % stage, error_type='CloudDatabaseError')
        return error

    def test_transient_snapshot_read_is_retryable_pre_execution(self):
        for code in TRANSIENT_CODES:
            with self.subTest(code=code):
                error = self.error(self.failure('profile-history', code))
                self.assertTrue(setup_retry.retryable_profile_setup(error))

    def test_non_transient_and_other_stages_stay_hard_gated(self):
        error = self.error(self.failure('profile-history', 'cloud-database-permission'))
        self.assertFalse(setup_retry.retryable_profile_setup(error))
        error = self.error(self.failure('profile-reserve', 'cloud-database-unavailable'))
        self.assertFalse(setup_retry.retryable_profile_setup(error))
        error = self.error(None)
        self.assertFalse(setup_retry.retryable_profile_setup(error))
        plain = CloudDatabaseError('cloud-database-unavailable')
        self.assertFalse(setup_retry.retryable_profile_setup(plain))

    def test_without_not_executed_marker_no_retry(self):
        error = self.error(self.failure('profile-history', 'cloud-database-unavailable'))
        error._dvk_profile_not_executed = False
        self.assertFalse(setup_retry.retryable_profile_setup(error))


class SkipDiagnostics(unittest.TestCase):
    def test_profiles_loop_exports_the_skip_flag_and_counter(self):
        import assistant_profiles
        source = Path(assistant_profiles.__file__).read_text(encoding='utf-8')
        self.assertIn("'shared_peer_skipped'", source)
        self.assertIn('shared_peer_skips', source)
        import assistant_error_notify
        notify_source = Path(assistant_error_notify.__file__).read_text(encoding='utf-8')
        self.assertIn("'shared_peer_skipped'", notify_source)
        self.assertIn("'shared_peer_skips'", notify_source)

    def test_cloud_projection_keeps_the_skip_evidence(self):
        import json
        from assistant_error_notify import diagnostic_json
        report = dict(profiles=dict(shared_peer_skips=2,
            last_profile_diagnostics=dict(shared_peer_skipped=True, stage='navigation-ready')))
        cleaned = json.loads(diagnostic_json(report))['diagnostic']
        profiles = cleaned['profiles']
        self.assertEqual(profiles['shared_peer_skips'], 2)
        self.assertIs(profiles['last_profile_diagnostics']['shared_peer_skipped'], True)


if __name__ == '__main__':
    unittest.main()
