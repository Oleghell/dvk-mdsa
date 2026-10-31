"""1.3.94 regressions: the anketa patience window and the dialog-check churn.

Reported (two ports of the same host):
(1) «в последней версии всё также заходит в новую анкету, сидит так и выходит,
    исправь точно» / «на второй пишет просмотрено 15 анкет и не одной не
    отписало» - the 1.3.92 bounded wait paced the profile-readiness polls at
    100ms, so the whole window was 5 seconds; on a loaded multi-port MuMu host
    a slow-but-good anketa never became readable inside it and was skipped
    before it could be greeted. The waits now poll at the one-second chat
    gate (50 polls = up to 50 seconds), and a saturated content wait routes
    into the verified close-and-skip instead of hard-failing the pass.
(2) «когда идет проверка диалогов не надо открывать все обработанные диалоги
    или неотвеченные обработанные, открывать только те что нужно» / «мне
    пишет обработано 22 диалога на анкете это бред» - the flat 60-second
    deferral cooldown re-opened every deferred dialog every minute (an
    open+read costs 10-30s under multi-port latency, so a handful of deferred
    chats consumed the whole pass), and a fully read row that came back with
    ZERO work re-opened on every later pass in the same state. Deferrals now
    double their cooldown per consecutive miss (capped, reset on a clean
    read) and a proven workless read records the durable row-skip marker of
    the v1.3.90 contract («в то же состояние не захожу, только в новое»).
Synthetic only; no device and no live services.
"""
import copy
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistant_history_wait as history_wait
import assistant_inbox as inbox
import assistant_pass
import assistant_profiles as profiles
import uikit_profile_navigation as native
from assistant_store import Store
from test_profile_batch import good
from test_inbox_profiles import Base, Config, msg, nav, snap

WHO = dict(account='100', peer='200', chat='300')


def greeted():
    """A complete validator-clean greeting cycle (the happy path)."""
    from test_chat_batch import cycle
    from test_mumu1392_anketa_greeting_guarantee import greeted as base_greeted
    return base_greeted()


def content_saturation(extra=None):
    """The profile CONTENT controller never appeared inside the bounded wait.

    v1.3.94: the armed profileWaitExhausted routing pinned the queue card,
    published the saturated 'unavailable' outcome and closed the anketa with
    verified evidence - profile_verified pins the ACTING queue screen (its
    tick preamble verified kind/presentation/view), while the content-level
    flags stay false because no content controller was ever verified, and
    the saturated counter is the evidence that the bounded wait actually
    expired. The pass continues on the next candidate instead of dying at
    profile-check-stopped.
    """
    from test_mumu1392_anketa_greeting_guarantee import unreadable_saturation
    value = unreadable_saturation()
    n = value['navigation']
    n.update(profile_verified=True, target_user_verified=False,
             profile_content_verified=False)
    if extra:
        n.update(extra)
    return value


class NativeSource(unittest.TestCase):
    """The composed one-profile script waits at the chat-phase gate."""

    def test_profile_waits_poll_at_the_one_second_gate(self):
        s = assistant_pass.build('Привет')
        self.assertIn("if(n.phase==='wait-profile'||n.phase==='confirm-profile'"
                      "||n.phase==='wait-return')state.nextActionAt=Date.now()+1000;", s)
        self.assertNotIn("||n.phase==='wait-return')state.nextActionAt=Date.now()+100;", s)

    def test_content_saturation_routes_into_the_verified_close(self):
        s = assistant_pass.build('Привет')
        self.assertIn("profileWaitExhausted=()=>{state.card=own(current);"
                      "held.splice(held.indexOf(state.card),1);n.profile_verified=true;"
                      "n.friends_status='unavailable';n.friends_count=null;"
                      "n.friends_eligible=null;n.phase='confirm-profile';"
                      "state.nextActionAt=Date.now()+1000;};", s)

    def test_friends_stage_guard_only_waits_while_the_read_is_pending(self):
        s = assistant_pass.build('Привет')
        # A saturated-content cycle arrives in confirm-profile with
        # friends_status already 'unavailable': it must fall through to the
        # verified close, not wait for a content controller that never came.
        self.assertIn("if(!verifyProfile(current)&&n.friends_status==='not-read')return;", s)
        self.assertNotIn("if(!verifyProfile(current))return;\n    if(n.friends_status==='not-read')", s)

    def test_base_hook_stays_a_no_op_for_the_smoke_baseline_contract(self):
        self.assertIn('let profileWaitExhausted=()=>{};', native.FUNCTION)
        self.assertIn('else profileWaitExhausted();return;}', native.FUNCTION)


class ValidatorContracts(unittest.TestCase):
    def test_saturated_content_skip_validates(self):
        value = content_saturation(); old = copy.deepcopy(value)
        self.assertIs(assistant_pass.validate(value), value)
        self.assertEqual(value, old)

    def test_unsaturated_content_skip_is_rejected(self):
        for waits in (0, 49, None, True):
            with self.subTest(waits=waits):
                with self.assertRaises(ValueError):
                    assistant_pass.validate(content_saturation(dict(profile_model_waits=waits)))

    def test_forged_unavailable_without_saturation_or_profile_is_rejected(self):
        # An unavailable outcome WITHOUT the verified queue screen is
        # legitimate only with the genuinely saturated counter - whatever the
        # friends source resolved to.
        for source in ('not-found', 'signature-unsupported', 'Profile.get_FriendsCount'):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    assistant_pass.validate(content_saturation(
                        dict(friends_source=source, profile_verified=False,
                             target_user_verified=False, profile_content_verified=False,
                             profile_model_waits=49)))

    def test_invalid_without_verified_profile_is_still_rejected(self):
        value = content_saturation(dict(friends_status='invalid'))
        with self.assertRaises(ValueError):
            assistant_pass.validate(value)

    def test_a_model_read_that_needed_many_slow_polls_still_greets(self):
        # 49 one-second polls and the 50th read succeeds: the greeting must
        # still go out - this is the reported slow-anketa happy path.
        value = greeted(); value['navigation']['profile_model_waits'] = 49
        self.assertIs(assistant_pass.validate(value), value)


class ContinueAfterStalledAnketa(unittest.TestCase):
    """The reported symptom: enter an anketa, sit, exit - now it greets."""

    def go(self, values, *, limit=1):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 's.sqlite3', Path(folder) / 'legacy')
            profiles.Session(store).set('city', 'Псков')
            calls = []
            def next_cycle(*args, **kwargs):
                calls.append(1)
                return values[len(calls) - 1]
            settings = SimpleNamespace(adb='fake', folder=folder, errors_enabled=True)
            out = profiles.walk(settings, threading.Event(), MagicMock(return_value=True),
                                lambda _: None, store, cycle=next_cycle, config=Config(),
                                limit=limit)
            return out, len(calls)

    def test_content_saturation_skips_the_anketa_and_the_next_greeting_sends(self):
        out, calls = self.go([content_saturation(), greeted()])
        self.assertEqual((out['status'], calls), ('profiles-completed', 2))
        self.assertEqual(out['skipped_unreadable'], 1)
        self.assertEqual(out['qualified_profiles'], 1)
        self.assertEqual(out['send_attempts'], 1)
        self.assertEqual(out['reason'], 'profile-limit')

    def test_three_consecutive_content_saturation_stops_the_pass_bounded(self):
        out, calls = self.go([content_saturation() for _ in range(3)])
        self.assertEqual((out['status'], out['reason']), ('profiles-stopped', 'profile-recovery-limit'))
        self.assertEqual(calls, 3)
        self.assertEqual(out['skipped_unreadable'], 3)
        self.assertEqual(out['consecutive_read_recoveries'], 3)

    def test_content_and_model_saturation_alternating_stay_bounded(self):
        out, calls = self.go([content_saturation(), greeted(), content_saturation(),
                              greeted()], limit=2)
        self.assertEqual((out['status'], calls), ('profiles-completed', 4))
        self.assertEqual(out['skipped_unreadable'], 2)
        self.assertEqual(out['qualified_profiles'], 2)

    def test_recovery_event_reports_the_saturation_counters(self):
        out, _ = self.go([content_saturation(), greeted()])
        self.assertEqual(out['recovery_events'][0]['reason'], 'friends-model-timeout')
        self.assertEqual(out['recovery_events'][0]['diagnostic']['profile_model_waits'],
                         native.PROFILE_MODEL_WAIT_LIMIT)


class DeferralBackoff(unittest.TestCase):
    """«обработано 22 диалога»: consecutive deferrals stop re-opening a chat
    every minute; a clean read resets the ladder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'a.sqlite3', Path(self.tmp.name) / 'old')
        history_wait.initialize(self.store)
        self.now = 1000.0

    def clock(self):
        return self.now

    def test_first_deferral_keeps_the_historic_sixty_seconds(self):
        until = history_wait.defer(self.store, WHO, clock=self.clock)
        self.assertAlmostEqual(until - self.now, history_wait.COOLDOWN_SECONDS)

    def test_consecutive_deferrals_double_the_cooldown(self):
        first = history_wait.defer(self.store, WHO, clock=self.clock)
        self.now = first + 1.0
        second = history_wait.defer(self.store, WHO, clock=self.clock)
        self.assertAlmostEqual(second - self.now, 2 * history_wait.COOLDOWN_SECONDS)
        self.now = second + 1.0
        third = history_wait.defer(self.store, WHO, clock=self.clock)
        self.assertAlmostEqual(third - self.now, 4 * history_wait.COOLDOWN_SECONDS)

    def test_the_ladder_is_capped(self):
        duration = 0.0
        for _ in range(12):
            started = self.now
            until = history_wait.defer(self.store, WHO, clock=self.clock)
            duration = until - started
            self.now = until + 1.0
        self.assertAlmostEqual(duration, history_wait.COOLDOWN_MAX_SECONDS)

    def test_a_clean_read_resets_the_ladder(self):
        history_wait.defer(self.store, WHO, clock=self.clock)
        self.now += 61.0
        history_wait.defer(self.store, WHO, clock=self.clock)
        history_wait.clear(self.store, WHO)
        until = history_wait.defer(self.store, WHO, clock=self.clock)
        self.assertAlmostEqual(until - self.now, history_wait.COOLDOWN_SECONDS)

    def test_eligible_still_blocks_only_while_cooling(self):
        history_wait.defer(self.store, WHO, clock=self.clock)
        attention, unread, skipped = history_wait.eligible(
            self.store, [], [dict(WHO)], clock=lambda: self.now + 1.0)
        self.assertEqual((attention, unread, skipped), ([], [], 1))
        attention, unread, skipped = history_wait.eligible(
            self.store, [], [dict(WHO)], clock=lambda: self.now + history_wait.COOLDOWN_SECONDS + 1.0)
        self.assertEqual((len(attention), len(unread), skipped), (0, 1, 0))

    def test_pre_1_3_94_table_is_migrated_in_place(self):
        with self.store.connection() as db:
            db.execute('DROP TABLE inbox_history_deferrals')
            db.execute('''CREATE TABLE inbox_history_deferrals(
                    account TEXT NOT NULL,peer TEXT NOT NULL,chat TEXT NOT NULL,
                    retry_after REAL NOT NULL,PRIMARY KEY(account,peer))''')
            db.execute('INSERT INTO inbox_history_deferrals VALUES(?,?,?,?)',
                       (WHO['account'], WHO['peer'], WHO['chat'], 5.0))
        # The migration latch is per store object (the warm path must not
        # touch schema at all); a rebuilt table re-arms it explicitly.
        self.store._dvk_deferrals_migrated = False
        history_wait.initialize(self.store)
        with self.store.read_connection() as db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(inbox_history_deferrals)')}
            row = db.execute('SELECT retry_after,deferrals FROM inbox_history_deferrals').fetchone()
        self.assertIn('deferrals', columns)
        self.assertEqual(row, (5.0, 0))
        until = history_wait.defer(self.store, WHO, clock=self.clock)
        self.assertAlmostEqual(until - self.now, history_wait.COOLDOWN_SECONDS)


class WorklessRowMarkers(Base):
    """«открывать только те что нужно»: a fully read row with ZERO work done
    records the durable state marker and stops re-opening in that state."""

    def setUp(self):
        super().setUp()
        from test_mumu1386_reopen_cycle import shared
        self.store = shared(self)

    def selected_nav(self, state, who, message_id):
        from test_assistant_dialogs import nav_result
        value = nav_result(state, who)
        value['diagnostic'].update(reply_filter_applied=state in ('opened', 'exhausted'),
                                   reply_needed_verified=state == 'opened',
                                   waiting_rows_skipped=0, handled_rows_skipped=0,
                                   selected_message=message_id)
        return value

    def test_clean_waiting_read_records_the_marker_and_uploads_it(self):
        from conversation_engine import QUESTIONS
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        # First pass: she replies, the engine answers - stage becomes
        # wait-mood and everything is observed.
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['workless_row_markers'], 0)
        # Second pass: the SAME row state re-admitted (the pending-receipt
        # exclusion) - the read comes back wait-mood with ZERO work done.
        marker_nav = self.selected_nav('opened', WHO, '1003')
        out = self.walk([marker_nav, nav('returned', WHO), nav('search-ready')],
                        [snap(hello, question), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['workless_row_markers'], 1)
        with self.store.read_connection() as db:
            row = db.execute('SELECT chat,last_message,reason FROM operator_rejects').fetchone()
        self.assertEqual(row, (WHO['chat'], '1003', 'workless-state'))
        # The next pass uploads the marker id inside the target's own
        # seen_ids, so the native needs-reply filter answers alreadyHandled
        # and the same row state is skipped in every scan mode.
        uploaded = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        self.assertEqual(len(uploaded), 1)
        self.assertIn('1003', uploaded[0]['seen_ids'])

    def test_a_read_that_submits_work_records_no_marker(self):
        from conversation_engine import QUESTIONS
        self.journal()
        hello = msg(1002, 'Привет')
        marker_nav = self.selected_nav('opened', WHO, '1002')
        out = self.walk([marker_nav, nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, msg(1003, QUESTIONS[0], True))])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['submission_calls'], 1)
        self.assertEqual(out['workless_row_markers'], 0)
        with self.store.read_connection() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM operator_rejects').fetchone())

    def test_an_open_without_selected_message_records_no_marker(self):
        # An older native without the v1.3.90 field degrades to the bounded
        # old behaviour instead of guessing a marker id.
        from conversation_engine import QUESTIONS
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                  [snap(hello), snap(hello), snap(hello, question)])
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello, question), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['workless_row_markers'], 0)
        with self.store.read_connection() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM operator_rejects').fetchone())

    def test_a_genuinely_new_message_replaces_the_marker(self):
        from conversation_engine import QUESTIONS
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                  [snap(hello), snap(hello), snap(hello, question)])
        first = self.selected_nav('opened', WHO, '1003')
        self.walk([first, nav('returned', WHO), nav('search-ready')],
                  [snap(hello, question), snap(hello, question)])
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT last_message FROM operator_rejects').fetchall(),
                             [('1003',)])
        # The upload proves the split contract: the marked state ('1003') is
        # already handled, a GENUINELY new message id is not - the native
        # needs-reply filter re-admits exactly the new state.
        uploaded = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        self.assertIn('1003', uploaded[0]['seen_ids'])
        self.assertNotIn('1004', uploaded[0]['seen_ids'])
        # Her genuinely new message re-opens the row. v1.3.96 quick exit: the
        # visit sends its reply, performs the ONE verification read and leaves
        # immediately; the still-unobserved outgoing keeps her answer receipt
        # pending, so the leave reason is the pending-answer cooldown (the row
        # is re-admitted on the next pass through the pending-receipt
        # exclusion) instead of the former same-visit three-poll quarantine.
        # The stale '1003' marker only skips that exact old state - the row's
        # current '1004' state stays admitted.
        newer = msg(1004, 'Пока')
        second = self.selected_nav('opened', WHO, '1004')
        out = self.walk([second, nav('returned', WHO), nav('search-ready')],
                        [snap(hello, question, newer), snap(hello, question, newer)])
        self.assertEqual(out['new_incoming_messages'], 1)
        self.assertEqual(out['submission_calls'], 1)
        self.assertEqual(out['outcomes'], {'chain-waiting:incoming-answer-pending': 1})
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT last_message,reason FROM operator_rejects').fetchall(),
                             [('1003', 'workless-state')])
        # Safety net unchanged: the next pass re-opens the deferred chat, the
        # stale receipt still cannot observe the outgoing, the bounded three
        # polls exhaust and the chat is isolated with the terminal marker
        # pinned to the row's CURRENT last message.
        import assistant_history_wait as history_wait
        history_wait.clear(self.store, WHO)
        third = self.selected_nav('opened', WHO, '1004')
        out = self.walk([third, nav('returned', WHO), nav('search-ready')],
                        [snap(hello, question, newer), snap(hello, question, newer)])
        self.assertEqual(out['outcomes'], {'isolated:outgoing-not-observed': 1})
        with self.store.read_connection() as db:
            rows = db.execute('SELECT last_message,reason FROM operator_rejects').fetchall()
        self.assertEqual([row[0] for row in rows], ['1004'])
        self.assertTrue(all(row[1] in ('workless-state', 'terminal-state') for row in rows))

    def test_report_schema_carries_the_new_counter(self):
        out = dict(inbox.report())
        self.assertEqual(out['workless_row_markers'], 0)


class OnlyNeededRowsOpen(unittest.TestCase):
    """The native admission rule itself: waiting rows and consumed rows are
    skipped before any open; only genuinely NEW INCOMING UNREAD rows open
    (pinned on the composed scan source, both engines). v1.3.103: the unread
    badge is an admission signal for the reply filter too - a badge-less row
    is a read row and stays closed whatever its last message is; the only
    badge-less open is the host-marked retry target (the scheduled recheck
    of owed work: a deferral-ladder step that expired, or a pending receipt).
    """

    def test_dialog_browser_needs_reply_filter_skips_waiting_and_handled(self):
        import dialog_browser
        s = dialog_browser.build('open', allowed=[dict(account='1', peer='2', chat='3', seen_ids=['9'])],
                                 needs_reply_only=True)
        self.assertIn("if(!header.incoming){n.waiting_rows_skipped++;return false;}", s)
        self.assertIn("if(alreadyHandled(model.who,header.id)){n.handled_rows_skipped++;return false;}", s)
        self.assertIn("if(unread===0&&!retryRow(model.who)){n.read_rows_skipped++;return false;}", s)
        self.assertIn("if(unread===0)n.retry_rows_opened++;", s)

    def test_dialog_models_needs_reply_filter_is_the_same_rule(self):
        import dialog_models
        s = dialog_models.build(allowed=[dict(account='1', peer='2', chat='3', seen_ids=['9'])],
                                needs_reply_only=True, recent_limit=50, reverse=True, start=0)
        self.assertIn("if(!header.incoming){n.waiting_rows_skipped++;return false;}", s)
        self.assertIn("if(alreadyHandled(model.who,header.id)){n.handled_rows_skipped++;return false;}", s)
        self.assertIn("if(unread===0&&!retryRow(model.who)){n.read_rows_skipped++;return false;}", s)
        self.assertIn("if(needsReplyOnly&&unread===0)n.retry_rows_opened++;", s)


if __name__ == '__main__':
    unittest.main()
