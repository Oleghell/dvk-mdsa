"""1.3.102 regression: a pass may not walk ankety without greeting anybody.

Reported: «опять баг, прошло 14 анкет и не одному не написало, сделай более
жесткую проверку уже надоело это фиксить 5 сборок». The 1.3.100 failed-open
budget bound only FAILURE opens; every other no-greeting outcome stayed
unbounded, so a pass could legally walk 14 (up to 200) opened ankety with
zero greetings: clean verdicts (friends>=50, existing chat, input disabled)
spent nothing, and shared-peer skips (a fresh claim by another port, or a
saturated pooler refusing reserve AFTER the anketa was opened and viewed)
were even misfiled as «уже есть переписка».

The strict doctrine («более жесткая проверка»):
* EVERY anketa opened without a confirmed outgoing greeting spends the
  pass-wide no-greet accounting, whatever its reason - verdict, skip,
  shared claim or failure.
* While nobody has been greeted the bound is tight: MAX_NO_GREET_OPENS=5 -
  a zero-greeting pass has no business opening a sixth anketa.
* Once a greeting has landed the pass has proven it delivers; only a longer
  collapse streak (MAX_NO_GREET_STREAK=8) ends it, and a new greeting
  resets the streak.
* The stop is graceful and honest: status 'profiles-completed' with reason
  'no-greet-limit' (the monitor schedules the next profile batch instead of
  killing the port), the failure budget keeps priority for failure-shaped
  stops ('profile-recovery-limit'), and the report/summary/diagnostics
  carry the full per-reason distribution.
* A shared-peer skip is its own outcome - never a disguised «уже есть
  переписка» verdict - and no longer resets the failure streak.

Synthetic only; no device and no live services.
"""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assistant_profiles as profiles
from test_inbox_profiles import cycle_result, Config
from test_mumu1311_autorecovery import skipped
from test_mumu1320_skip_budget import disabled


def greeted():
    return cycle_result(send_attempted=True, send_handler_returned=True)


def friends_verdict():
    return cycle_result(friends_eligible=False)


def shared_skip():
    value = cycle_result()
    value['navigation']['shared_peer_skipped'] = True
    return value


class StrictBudget(unittest.TestCase):
    """Every opened-without-send anketa spends the no-greet accounting."""

    def go(self, values, *, limit=2, errors=False, progress=None):
        with tempfile.TemporaryDirectory() as folder:
            from assistant_store import Store
            store = Store(Path(folder) / 's.sqlite3', Path(folder) / 'legacy')
            profiles.Session(store).set('city', 'Псков')
            calls = []

            def next_cycle(*args, **kwargs):
                calls.append(1)
                return values[len(calls) - 1]

            settings = SimpleNamespace(adb='fake', folder=folder, errors_enabled=errors)
            out = profiles.walk(settings, threading.Event(), MagicMock(return_value=True),
                                progress or (lambda _: None), store, cycle=next_cycle,
                                config=Config(), limit=limit)
            return out, len(calls)

    def test_constants_pin_the_strict_doctrine(self):
        self.assertEqual(profiles.MAX_NO_GREET_OPENS, 5)
        self.assertEqual(profiles.MAX_NO_GREET_STREAK, 8)
        self.assertGreater(profiles.MAX_NO_GREET_STREAK, profiles.MAX_NO_GREET_OPENS)
        empty = profiles.report(5)
        self.assertEqual((empty['no_greet_opens'], empty['no_greet_open_limit']),
                         (0, profiles.MAX_NO_GREET_OPENS))
        self.assertEqual(empty['no_greet_streak_limit'], profiles.MAX_NO_GREET_STREAK)
        self.assertFalse(empty['no_greet_limit_hit'])

    def test_zero_greeting_pass_stops_at_five_whatever_the_reasons(self):
        # The exact reported shape: 14 opened, 0 written. Whatever the mix of
        # verdicts, the fifth opened ankety without a single greeting ends
        # the pass - gracefully, with the full distribution in the report.
        values = [friends_verdict(), cycle_result(), disabled(), friends_verdict(), cycle_result()]
        out, calls = self.go(values)
        self.assertEqual((out['status'], out['reason']), ('profiles-completed', 'no-greet-limit'))
        self.assertEqual(calls, 5)
        self.assertEqual(out['no_greet_opens'], profiles.MAX_NO_GREET_OPENS)
        self.assertEqual(out['no_greet_limit_hit'], True)
        self.assertEqual(out['failed_opens'], 0)
        self.assertEqual(out['consecutive_read_recoveries'], 0)
        self.assertFalse(out['recovery_events'])
        self.assertEqual((out['skipped_friends'], out['skipped_existing_chat'],
                          out['skipped_input_disabled']), (2, 2, 1))
        self.assertEqual(out['qualified_profiles'], 0)

    def test_mixed_failures_and_verdicts_stop_at_the_strict_bound(self):
        # The interleaved carousel that defeated the consecutive bound in
        # 1.3.100 and the verdict exemption in 1.3.102's predecessor: with a
        # zero-greeting pass, [verdict, fail, verdict, verdict, verdict] ends
        # at the FIFTH open even though only one failure was ever booked.
        values = [cycle_result(), skipped(), cycle_result(), friends_verdict(), cycle_result()]
        out, calls = self.go(values)
        self.assertEqual((out['status'], out['reason']), ('profiles-completed', 'no-greet-limit'))
        self.assertEqual(calls, 5)
        self.assertEqual(out['no_greet_opens'], profiles.MAX_NO_GREET_OPENS)
        self.assertEqual(out['failed_opens'], 1)

    def test_four_opens_then_a_greeting_still_complete(self):
        # The strict bound does not strangle a delivering feed: four verdicts
        # in a row leave room for the fifth cycle to greet, and the pass
        # completes on the greeting limit exactly as before.
        values = [cycle_result()] * 4 + [greeted()]
        out, calls = self.go(values, limit=1)
        self.assertEqual((out['status'], out['reason']), ('profiles-completed', 'profile-limit'))
        self.assertEqual(calls, 5)
        self.assertEqual(out['no_greet_opens'], 0)
        self.assertEqual(out['qualified_profiles'], 1)

    def test_a_greeting_resets_the_streak(self):
        values = [greeted()] + [cycle_result()] * 7 + [greeted()]
        out, calls = self.go(values, limit=2)
        self.assertEqual((out['status'], out['reason']), ('profiles-completed', 'profile-limit'))
        self.assertEqual(calls, 9)
        self.assertEqual(out['no_greet_opens'], 0)
        self.assertEqual(out['qualified_profiles'], 2)

    def test_post_greeting_collapse_ends_at_the_longer_streak_bound(self):
        # After a delivered greeting the pass is proven working; only a LONGER
        # collapse streak (8) ends it - seven verdicts are survived, the
        # eighth ends the pass.
        values = [greeted()] + [cycle_result()] * 8
        out, calls = self.go(values, limit=2)
        self.assertEqual((out['status'], out['reason']), ('profiles-completed', 'no-greet-limit'))
        self.assertEqual(calls, 9)
        self.assertEqual(out['no_greet_opens'], profiles.MAX_NO_GREET_STREAK)

    def test_failure_budget_keeps_priority_for_failure_shaped_stops(self):
        # A pass stopped by three failure opens keeps its 1.3.100 reason
        # ('profile-recovery-limit'); the strict counter is present in the
        # report but never rewrites a failure stop.
        values = [skipped(), cycle_result()] * 3
        out, calls = self.go(values)
        self.assertEqual((out['status'], out['reason']), ('profiles-stopped', 'profile-recovery-limit'))
        self.assertEqual(calls, 5)
        self.assertEqual(out['failed_opens'], profiles.MAX_FAILED_OPENS)
        self.assertEqual(out['no_greet_opens'], 4)

    def test_shared_skips_are_their_own_outcome_and_spend_the_bound(self):
        # An anketa claimed by another port (or refused by a saturated pooler)
        # was opened and viewed; it is NOT «уже есть переписка», it spends the
        # strict accounting, and five of them end a zero-greeting pass.
        values = [shared_skip()] * 5
        out, calls = self.go(values)
        self.assertEqual((out['status'], out['reason']), ('profiles-completed', 'no-greet-limit'))
        self.assertEqual(calls, 5)
        self.assertEqual(out['shared_peer_skips'], 5)
        self.assertEqual(out['skipped_existing_chat'], 0)
        self.assertEqual(out['no_greet_opens'], profiles.MAX_NO_GREET_OPENS)

    def test_shared_skip_no_longer_resets_the_failure_streak(self):
        # The old fall-through reset the consecutive recovery counter for a
        # shared skip; the strict walk keeps failure pressure across it.
        values = [skipped(), shared_skip(), skipped(), skipped()]
        out, calls = self.go(values)
        self.assertEqual((out['status'], out['reason']), ('profiles-stopped', 'profile-recovery-limit'))
        self.assertEqual(calls, 4)
        self.assertEqual(out['failed_opens'], profiles.MAX_FAILED_OPENS)

    def test_stopped_shared_skip_keeps_the_honest_stop(self):
        # A shared skip that arrived STOPPED (cancellation or budget stop
        # before the native observed the skip) is never treated as a clean
        # continue: the pass stops with profile-check-stopped exactly as
        # the validator's stopped-skip form demands.
        value = shared_skip()
        value['navigation'].update(stage='navigation-stopped', error='frame-budget')
        out, calls = self.go([value])
        self.assertEqual((out['status'], out['reason']), ('profiles-stopped', 'profile-check-stopped'))
        self.assertEqual(calls, 1)

    def test_progress_line_names_the_no_greet_counter(self):
        seen = []

        def progress(text):
            seen.append(text)

        values = [cycle_result()] * 5
        self.go(values, progress=progress)
        self.assertTrue(any('без отправки' in text for text in seen), seen[:3])
        self.assertTrue(any('просмотрено' in text for text in seen))


class HonestReporting(unittest.TestCase):
    """The stop is visible in the summary, the reasons and the diagnostics."""

    def go(self, values, *, limit=2):
        with tempfile.TemporaryDirectory() as folder:
            from assistant_store import Store
            store = Store(Path(folder) / 's.sqlite3', Path(folder) / 'legacy')
            profiles.Session(store).set('city', 'Псков')
            calls = []

            def next_cycle(*args, **kwargs):
                calls.append(1)
                return values[len(calls) - 1]

            settings = SimpleNamespace(adb='fake', folder=folder, errors_enabled=False)
            return profiles.walk(settings, threading.Event(), MagicMock(return_value=True),
                                 lambda _: None, store, cycle=next_cycle, config=Config(),
                                 limit=limit), len(calls)

    def test_summary_names_the_strict_bound_and_the_reason(self):
        from assistant_run import PROFILE_REASONS, summary
        out, _ = self.go([friends_verdict(), cycle_result(), disabled(), cycle_result(),
                          friends_verdict()])
        self.assertEqual(out['reason'], 'no-greet-limit')
        text = summary(dict(tool_version='test', mode='full', status='stopped',
                            reason='profiles-not-finished', inbox=None, profiles=out,
                            preparation_failure=None))
        self.assertIn('подряд без приветствия 5/5', text)
        self.assertIn('просмотрено 5', text)
        self.assertIn('пропущено (50+ друзей) 2', text)
        self.assertIn('ввод недоступен 1', text)
        self.assertIn('занято другими портами 0', text)
        self.assertIn(PROFILE_REASONS['no-greet-limit'], text)

    def test_completed_profile_limit_stays_quiet_in_the_summary(self):
        from assistant_run import summary
        out = dict(profiles.report(5), status='profiles-completed', reason='profile-limit',
                   current_city='Псков', send_attempts=1, handlers_returned=1,
                   skipped_friends=0, skipped_existing_chat=0)
        text = summary(dict(tool_version='test', mode='full', status='completed',
                            reason='done', inbox=None, profiles=out,
                            preparation_failure=None))
        self.assertIn('открыто без отправки 0/3', text)
        self.assertNotIn('no-greet-limit', text)

    def test_diagnostic_json_carries_the_new_counters(self):
        from assistant_error_notify import diagnostic_json
        published = json.loads(diagnostic_json(dict(
            status='stopped', reason='no-greet-limit', no_greet_opens=5,
            no_greet_open_limit=5, no_greet_streak_limit=8,
            skipped_friends=2, skipped_existing_chat=2, skipped_input_disabled=1,
            shared_peer_skips=1)).decode('utf-8'))['diagnostic']
        self.assertEqual(published['no_greet_opens'], 5)
        self.assertEqual(published['no_greet_open_limit'], 5)
        self.assertEqual(published['skipped_friends'], 2)
        self.assertEqual(published['skipped_input_disabled'], 1)
        self.assertEqual(published['reason'], 'no-greet-limit')

    def test_the_walk_source_pins_the_strict_accounting(self):
        source = (Path(__file__).resolve().parents[1] / 'assistant_profiles.py').read_text(encoding='utf-8')
        # Every no-greet exit advances the accounting; only a confirmed
        # greeting resets it; the graceful stop names its own reason.
        self.assertEqual(source.count('advance_no_greet()'), 6)
        self.assertIn("out['no_greet_opens'] = 0", source)
        self.assertIn("reason='no-greet-limit' if out['no_greet_limit_hit'] else 'profile-limit'", source)
        # The shared-skip branch is gated on the READY form only.
        self.assertIn("n.get('shared_peer_skipped') and n['stage'] == 'navigation-ready'", source)


if __name__ == '__main__':
    unittest.main()
