"""1.3.92 regression: a stalled anketa never parks the greeting pass.

Reported: «заходит в новую анкету, сидит там и не отписывает приветствие».
Two native waits used to be unbounded - the profile friends-model wait and the
wait-chat poll after OnMessageButton - so a stalled anketa sat on screen for
the whole 90-second cycle budget, stopped the profile pass and pushed the port
into recovery rounds without any greeting. Both waits are now bounded with
counted evidence, and a stalled anketa is closed with verified evidence so the
pass continues on the next candidate (bounded by the existing consecutive
recovery limit). Synthetic only; no device and no live services.
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
import assistant_pass
import assistant_profiles as profiles
import chat_batch
import uikit_profile_navigation as native
from assistant_store import Store
from test_profile_batch import good
from test_inbox_profiles import cycle_result, Config


def greeted():
    """A complete validator-clean greeting cycle (the happy path)."""
    from test_chat_batch import cycle
    value = cycle()
    value['navigation'].update(cycle_timeout_ms=90000,
        profile_read_budget_retries=0, profile_ready_waits=0, greeting_frame_splits=1)
    return value


def unreadable_saturation(extra=None):
    """The profile model never became readable inside the bounded wait.

    The read publishes the existing 'unavailable' outcome with the saturated
    profile_model_waits counter, the anketa is closed with verified evidence
    and the pass continues on the next candidate.
    """
    value = good(); n = value['navigation']
    n.update(copy.deepcopy(chat_batch.DEFAULTS))
    n.update(cycle_timeout_ms=90000,
        friends_status='unavailable', friends_count=None, friends_eligible=None,
        profile_model_waits=native.PROFILE_MODEL_WAIT_LIMIT, chat_open_waits=0,
        profile_read_budget_retries=0, profile_ready_waits=0, greeting_frame_splits=0,
        chat_open_attempted=False, chat_open_completed=False, chat_verified=False,
        chat_identity_verified=False, chat_back_attempted=False, chat_back_completed=False,
        chat_return_verified=False, chat_return_route='not-checked',
        history_status='unknown', message_count=None, samples=0,
        send_attempted=False, send_handler_returned=False, messages_sent=0, greeting_variant=None,
        chat_metadata_checkpoint='base', read_checkpoint='not-checked', wait_reason='not-checked')
    if extra:n.update(extra)
    return value


def chat_not_opened(extra=None):
    """OnMessageButton was invoked but the chat screen never appeared.

    The bounded chat_open_waits counter saturated, the skip is recorded with
    the inverse chat-side evidence and the anketa itself is closed and returned.
    """
    value = unreadable_saturation()
    n = value['navigation']
    n.update(friends_status='read', friends_count=13, friends_eligible=True,
        profile_model_waits=0, chat_open_waits=native.CHAT_OPEN_WAIT_LIMIT,
        chat_open_attempted=True, chat_open_completed=True,
        profile_read_skipped=True, profile_read_skip_reason='chat-not-opened',
        profile_input_enabled=None, history_status='not-ready')
    if extra:n.update(extra)
    return value


class NativeSource(unittest.TestCase):
    """The composed one-profile script carries both bounds and their gates."""

    def test_both_waits_are_bounded_with_counted_evidence(self):
        s = assistant_pass.build('Привет')
        bound = 'n.profile_model_waits<' + str(native.PROFILE_MODEL_WAIT_LIMIT)
        # wait-profile content wait + the capped waitForModel + the two
        # friends-model gate reads
        self.assertEqual(s.count(bound), 4)
        self.assertIn('if(n.chat_open_waits<' + str(native.CHAT_OPEN_WAIT_LIMIT)
                      + '){n.chat_open_waits++;state.nextActionAt=Date.now()+1000;return;}', s)
        # the chat-not-opened skip emits the evidence and routes into the
        # existing verified close of the profile itself
        self.assertIn("n.profile_read_skip_reason='chat-not-opened';", s)
        self.assertIn("n.phase='confirm-profile';state.nextActionAt=Date.now()+1000;return;", s)
        # the old unbounded profile poll inside wait-chat is gone
        self.assertNotIn("if(k==='profile'){if(!current.equals(target(state.card))"
                         "||!verifyProfile(current))fail('identity-changed');return;}", s)

    def test_structurally_unreadable_profile_fails_fast_instead_of_sitting(self):
        s = assistant_pass.build('Привет')
        # the base wait only counts (capped) and calls a no-op hook - no hidden
        # pacing, no in-base stop; the compose line arms the hook with the
        # bounded stop so pacing and bound can never be separated
        self.assertIn("if(!verifyProfile(current)){if(n.profile_model_waits<"
                      + str(native.PROFILE_MODEL_WAIT_LIMIT)
                      + ")n.profile_model_waits++;else profileWaitExhausted();return;}", s)
        self.assertIn("profileWaitExhausted=()=>fail('screen-not-ready');", s)
        self.assertIn('let profileWaitExhausted=()=>{};', s)

    def test_close_gate_accepts_only_a_saturated_unavailable_read(self):
        s = assistant_pass.build('Привет')
        self.assertIn("if(n.friends_status!=='read'&&!(n.friends_status==='unavailable'"
                      "&&n.profile_model_waits>=" + str(native.PROFILE_MODEL_WAIT_LIMIT)
                      + "))fail('screen-not-ready');", s)


class ValidatorContracts(unittest.TestCase):
    def test_saturated_unreadable_and_chat_not_opened_cycles_validate(self):
        for build in (unreadable_saturation, chat_not_opened):
            with self.subTest(build=build.__name__):
                value = build(); old = copy.deepcopy(value)
                self.assertIs(assistant_pass.validate(value), value)
                self.assertEqual(value, old)

    def test_a_slow_chat_that_eventually_opened_still_greets(self):
        value = greeted(); value['navigation']['chat_open_waits'] = 7
        self.assertIs(assistant_pass.validate(value), value)

    def test_unsaturated_unavailable_read_is_rejected(self):
        for waits in (0, 49, None, True):
            with self.subTest(waits=waits):
                with self.assertRaises(ValueError):
                    assistant_pass.validate(unreadable_saturation(dict(profile_model_waits=waits)))

    def test_forged_chat_open_skip_evidence_is_rejected(self):
        for key, bad in (('chat_open_waits', 14), ('chat_open_waits', 16), ('chat_open_waits', True),
                         ('chat_verified', True), ('chat_identity_verified', True),
                         ('chat_open_attempted', False), ('chat_open_completed', False),
                         ('chat_return_verified', True), ('chat_back_completed', True),
                         ('send_attempted', True), ('send_handler_returned', True),
                         ('return_verified', False), ('close_completed', False),
                         ('friends_eligible', False), ('friends_eligible', None),
                         ('history_status', 'empty'), ('message_count', 0), ('samples', 2),
                         ('phase', 'close-chat'), ('profile_read_skip_reason', 'PRIVATE'),
                         ('profile_read_skipped', False)):
            with self.subTest(key=key, bad=bad):
                with self.assertRaises(ValueError):
                    assistant_pass.validate(chat_not_opened({key: bad}))

    def test_wait_counters_are_strict_evidence(self):
        for key, bad in (('profile_model_waits', 51), ('profile_model_waits', -1),
                         ('profile_model_waits', True), ('chat_open_waits', -1),
                         ('chat_open_waits', True)):
            with self.subTest(key=key, bad=bad):
                value = unreadable_saturation() if key == 'profile_model_waits' else greeted()
                value['navigation'][key] = bad
                with self.assertRaises(ValueError):
                    assistant_pass.validate(value)
        # a chat-open wait without the attempted open is a forged counter
        value = greeted(); value['navigation'].update(
            chat_open_waits=3, chat_open_attempted=False, chat_open_completed=False,
            chat_verified=False, chat_identity_verified=False, chat_back_attempted=False,
            chat_back_completed=False, chat_return_verified=False, chat_return_route='not-checked',
            history_status='unknown', message_count=None, samples=0,
            send_attempted=False, send_handler_returned=False, messages_sent=0, greeting_variant=None,
            chat_metadata_checkpoint='base', read_checkpoint='not-checked', wait_reason='not-checked')
        with self.assertRaises(ValueError):
            assistant_pass.validate(value)

    def test_unavailable_without_open_is_rejected(self):
        value = unreadable_saturation(dict(open_attempted=False, open_completed=False,
            close_attempted=False, close_completed=False, profile_verified=False,
            return_verified=False, target_user_verified=False, profile_content_verified=False,
            selection_status='no-eligible-cell'))
        value['navigation']['selection_counts'].update(passes=3)
        with self.assertRaises(ValueError):
            assistant_pass.validate(value)


class ContinueAfterStalledAnketa(unittest.TestCase):
    """The reported symptom: enter an anketa, sit, no greeting - now bounded."""

    def go(self, values, *, errors=True, notifier=None, limit=1):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 's.sqlite3', Path(folder) / 'legacy')
            profiles.Session(store).set('city', 'Псков')
            calls = []
            def next_cycle(*args, **kwargs):
                calls.append(1)
                return values[len(calls) - 1]
            settings = SimpleNamespace(adb='fake', folder=folder, errors_enabled=errors)
            out = profiles.walk(settings, threading.Event(), MagicMock(return_value=True),
                                lambda _: None, store, cycle=next_cycle, config=Config(),
                                limit=limit, recovery_notifier=notifier)
            return out, len(calls)

    def test_stalled_friends_model_skips_the_anketa_and_the_next_greeting_still_sends(self):
        out, calls = self.go([unreadable_saturation(), greeted()])
        self.assertEqual((out['status'], calls), ('profiles-completed', 2))
        self.assertEqual(out['skipped_unreadable'], 1)
        self.assertEqual(out['qualified_profiles'], 1)
        self.assertEqual(out['send_attempts'], 1)
        self.assertEqual(out['reason'], 'profile-limit')

    def test_chat_that_never_opened_skips_the_anketa_and_the_pass_continues(self):
        out, calls = self.go([chat_not_opened(), greeted()])
        self.assertEqual((out['status'], calls), ('profiles-completed', 2))
        self.assertEqual(out['skipped_chat_not_opened'], 1)
        self.assertEqual(out['qualified_profiles'], 1)
        self.assertEqual(out['send_attempts'], 1)

    def test_three_consecutive_unreadable_anketas_stop_the_pass_bounded(self):
        out, calls = self.go([unreadable_saturation() for _ in range(3)])
        self.assertEqual((out['status'], out['reason']), ('profiles-stopped', 'profile-recovery-limit'))
        self.assertEqual(calls, 3)
        self.assertEqual(out['skipped_unreadable'], 3)
        self.assertEqual(out['consecutive_read_recoveries'], 3)

    def test_three_consecutive_unopened_chats_stop_the_pass_bounded(self):
        out, calls = self.go([chat_not_opened() for _ in range(3)])
        self.assertEqual((out['status'], out['reason']), ('profiles-stopped', 'profile-recovery-limit'))
        self.assertEqual(calls, 3)
        self.assertEqual(out['skipped_chat_not_opened'], 3)

    def test_a_successful_greeting_resets_the_consecutive_limit(self):
        out, calls = self.go([unreadable_saturation(), unreadable_saturation(), greeted(),
                              chat_not_opened(), greeted()], limit=2)
        self.assertEqual((out['status'], calls), ('profiles-completed', 5))
        self.assertEqual((out['skipped_unreadable'], out['skipped_chat_not_opened']), (2, 1))
        self.assertEqual(out['qualified_profiles'], 2)

    def test_forged_chat_open_skip_stops_instead_of_continuing(self):
        for change in ({'return_verified': False}, {'close_completed': False},
                       {'chat_open_waits': 3}, {'send_attempted': True}):
            with self.subTest(change=change):
                out, calls = self.go([chat_not_opened(change)])
                self.assertEqual(calls, 1)
                self.assertEqual(out['status'], 'profiles-stopped')
                self.assertIn(out['reason'], ('return-not-verified', 'send-outcome-unknown'))

    def test_recovery_events_report_the_reason_and_the_wait_counters(self):
        notified = []
        def notify(event):
            notified.append(copy.deepcopy(event)); return 'accepted'
        out, _ = self.go([chat_not_opened(), unreadable_saturation(), greeted()], notifier=notify)
        self.assertEqual(out['status'], 'profiles-completed')
        self.assertEqual([event['reason'] for event in out['recovery_events']],
                         ['chat-not-opened', 'friends-model-timeout'])
        self.assertEqual(out['recovery_events'][0]['diagnostic']['chat_open_waits'],
                         native.CHAT_OPEN_WAIT_LIMIT)
        self.assertEqual(out['recovery_events'][1]['diagnostic']['profile_model_waits'],
                         native.PROFILE_MODEL_WAIT_LIMIT)
        self.assertEqual([event['notification'] for event in out['recovery_events']],
                         ['accepted', 'accepted'])
        self.assertEqual(len(notified), 2)

    def test_stalled_anketas_do_not_count_as_friends_threshold_skips(self):
        out, _ = self.go([unreadable_saturation(), greeted()])
        self.assertEqual(out['skipped_friends'], 0)
        self.assertEqual(out['recovery_events'][0]['action'], 'verified-close-and-skip')
        self.assertTrue(out['recovery_events'][0]['return_verified'])
        self.assertFalse(out['recovery_events'][0]['send_attempted'])

    def test_notification_failure_never_stops_the_pass(self):
        def broken(event):
            raise RuntimeError('PRIVATE transport')
        out, calls = self.go([chat_not_opened(), unreadable_saturation(), greeted()], notifier=broken)
        self.assertEqual((out['status'], calls), ('profiles-completed', 3))
        self.assertEqual(out['recovery_events'][0]['notification'], 'unknown')

    def test_report_schema_carries_the_new_counters(self):
        out = dict(profiles.report(1))
        for key in ('skipped_unreadable', 'skipped_chat_not_opened'):
            self.assertIn(key, out)
            self.assertEqual(out[key], 0)


class TelegramProjection(unittest.TestCase):
    def test_stalled_anketa_reasons_survive_the_closed_diagnostic_enum(self):
        import json
        from assistant_error_notify import diagnostic_json
        event = dict(status='recovered', reason='chat-not-opened', action='verified-close-and-skip',
                     return_verified=True, send_attempted=False, send_handler_returned=False,
                     continue_work=True, sequence=1, notification='accepted',
                     diagnostic=dict(chat_open_waits=native.CHAT_OPEN_WAIT_LIMIT,
                                     profile_model_waits=0, stage='navigation-ready',
                                     phase='done', error='none'))
        raw = diagnostic_json(dict(profiles=dict(profiles.report(1), status='profiles-completed',
                                                 skipped_unreadable=2, skipped_chat_not_opened=1),
                                    recovery_events=[event]))
        text = raw.decode('utf-8')
        data = json.loads(text)['diagnostic']
        self.assertEqual(data['profiles']['skipped_unreadable'], 2)
        self.assertEqual(data['profiles']['skipped_chat_not_opened'], 1)
        self.assertEqual(data['recovery_events'][0]['reason'], 'chat-not-opened')
        self.assertEqual(data['recovery_events'][0]['action'], 'verified-close-and-skip')
        self.assertEqual(data['recovery_events'][0]['diagnostic']['chat_open_waits'],
                         native.CHAT_OPEN_WAIT_LIMIT)


if __name__ == '__main__':
    unittest.main()
