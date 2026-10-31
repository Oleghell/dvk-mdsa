"""v1.3.105: «ускорь эти все проверки а то бывает ждать 5-10 секунд пока оно
все прочекает» and «при проверки лички на входящее бывает секунд 20 что-то
проверяет когда все пусто и отвечено» - two structural costs, both measured
on the S5GK7 host (monitors 611-638: open_ms median 7.6s / avg 8.1s):

1. the cached-models scan paced 4 rejected rows per UI-frame callback - a
   static dialogs screen fires its watched update at roughly one hertz, so
   the 50-row all-read window burned ~13 callbacks (6-13 seconds of pure
   waiting) before reporting 'exhausted';
2. every steady-state monitor iteration spent one FULL device navigation
   (frida session + script + frames) on navigate('list','dialogs') purely to
   re-verify the screen the previous pass had just proved - the inbox pass
   that follows re-verifies the same entry natively on its own first open.

The fixes: ROWS_PER_FRAME rises to 16 (the existing deadline-40 guard, the
within-callback double-read stability proofs, the immediate end of a batch
on an open and the 4s SCAN_MILLISECONDS cursor split all unchanged), and the
monitor skips the redundant pre-pass navigation exactly when the previous
pass proved the dialogs screen. These tests pin both doctrines and their
bounds.
"""
import json
import threading
import unittest
from unittest.mock import MagicMock

import dialog_models
import dialog_browser
import assistant_monitor as monitor_module
from assistant_monitor import report as monitor_report
from assistant_settings import Settings
from assistant_inbox import report as inbox_report
from test_assistant_dialogs import nav_result


def list_result():
    result = nav_result('dialogs-ready')
    result['diagnostic'].update(selection_checkpoint='not-checked', rows_scanned=0, scan_batches=0)
    return result


def inbox_result(**kwargs):
    result = dict(inbox_report(), status='inbox-completed', reason='visible-exhausted',
                  dialogs_verified=True)
    result.update(kwargs)
    return result


class ScanPacing(unittest.TestCase):
    def test_sixteen_rows_per_frame_is_pinned_with_its_rationale(self):
        # The reported «ждать 5-10 секунд пока оно все прочекает» was this
        # number: 4 rows per callback on a ~1Hz static screen. 16 rows make
        # the 50-row recent window at most 4 scan callbacks.
        self.assertEqual(dialog_models.ROWS_PER_FRAME, 16)
        self.assertEqual(dialog_models.SCAN_MILLISECONDS, 4000)
        self.assertEqual(dialog_models.SLICE, 64)
        self.assertGreaterEqual(dialog_models.ROWS_PER_FRAME * 4, 50)

    def test_source_renders_the_new_batch_bound_with_every_old_guard(self):
        source = dialog_models.build(allowed=[], needs_reply_only=True)
        self.assertIn('batch<16&&', source)
        self.assertNotIn('batch<4&&', source)
        # The frame-budget guard refuses to START a row past 60ms of the
        # 100ms frame budget, whatever the batch bound is.
        self.assertIn('(batch===0||Date.now()<deadline-40)', source)
        # The scan-time budget still splits a slow scan across slices.
        self.assertIn('Date.now()-state.scanStarted<4000', source)
        # An open still ends the batch immediately; stability is still proven
        # by within-callback double reads plus the selection-*-changed fails.
        for text in ('stableModels(current,manager,cm,count,state.scanIndex,chat)',
                     'selection-unread-changed', 'selection-last-message-changed',
                     'state.rowBudgetYields<3', 'budget_yields<12'):
            self.assertIn(text, source)

    def test_browser_engine_cell_pacing_is_untouched(self):
        # The visible-cells engine (the developer read-check route, not the
        # MuMu inbox pass) keeps its own heavier per-row pacing.
        source = dialog_browser.build('open', allowed=[], entry='dialogs',
                                      unread_only=True, needs_reply_only=True)
        self.assertIn('for(let batch=0;batch<(needsReplyOnly?2:4)', source)

    def test_native_smoke_baseline_and_slow_tick_are_repinned(self):
        # The smoke proves the pacing wins (baseline batch<1 needs MORE
        # frames) and keeps the 4s budget-split coverage on a slow host: with
        # 16 rows per callback the slow fixture tick must be slow enough to
        # trip the slice split (2.2s ticks -> a 64-row slice splits after 32
        # rows -> slices>3 for the 130-model list).
        smoke = open('smoke_dialog_models.py', encoding='utf-8').read()
        self.assertIn("source.replace('batch<16&&','batch<1&&')", smoke)
        self.assertNotIn("source.replace('batch<4&&','batch<1&&')", smoke)
        self.assertIn('str(2.2 if slow else .003)', smoke)
        self.assertNotIn('str(.45 if slow else .003)', smoke)


class MonitorSkip(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.approve = MagicMock(return_value=True)
        self.initial = MagicMock(return_value=dict(status='completed', report_name='last-run.json',
                                                   inbox=inbox_result()))
        self.inbox = MagicMock(return_value=inbox_result())
        self.navigator = MagicMock(side_effect=lambda operation, *args, **kwargs:
                                   list_result() if operation == 'list' else dict(list_result(), state='search-ready'))
        self.reports = []
        self.held = False

    def run_monitor(self, **kwargs):
        from contextlib import contextmanager

        @contextmanager
        def lock():
            self.assertFalse(self.held)
            self.held = True
            try:
                yield
            finally:
                self.held = False

        def write(report):
            import copy
            self.reports.append(copy.deepcopy(report))
            return 'last-monitor.json'

        defaults = dict(initial=self.initial, inbox=self.inbox, navigator=self.navigator,
                        lock=lock, write=write)
        defaults.update(kwargs)
        return monitor_module.run(Settings(reply_interval=30, profile_interval=120),
                                  self.stop, self.approve, lambda _: None, **defaults)

    def test_steady_state_passes_skip_the_redundant_list_navigation(self):
        waits = []
        def wait(seconds):
            waits.append(seconds)
            if len(waits) == 3:
                self.stop.set()
                return True
            return False
        out = self.run_monitor(mode='inbox', wait=wait)
        # The recovery-capable FIRST navigation stays; the two later idle
        # iterations start straight at the pass (its own open verifies the
        # entry) - one full device session saved per check cycle.
        self.assertEqual([c.args[0] for c in self.navigator.call_args_list], ['list'])
        self.assertEqual(self.navigator.call_args_list[0].kwargs['entry'], 'either')
        self.assertEqual(self.inbox.call_count, 3)
        self.assertEqual(out['passes_completed'], 3)
        self.assertTrue(out['dialogs_verified'])

    def test_empty_pass_also_proves_the_screen_for_the_next_iteration(self):
        # «когда все пусто и отвечено»: the empty pass touches no screen at
        # all, so the screen it started on (dialogs, proved by the pass
        # before it) is exactly what the next iteration starts on.
        self.inbox.return_value = dict(inbox_report(), status='inbox-empty',
                                       dialogs_verified=True)
        def wait(seconds):
            self.stop.set()
            return True
        out = self.run_monitor(mode='inbox', wait=wait)
        self.assertEqual(self.navigator.call_count, 1)
        self.assertEqual(out['passes_completed'], 1)
        self.assertTrue(out['dialogs_verified'])

    def test_skip_only_after_a_completed_pass_keeps_verified_bookkeeping(self):
        # The skip path must leave the report state identical to a successful
        # list navigation: dialogs verified, UI not left open.
        def wait(seconds):
            self.stop.set()
            return True
        out = self.run_monitor(mode='inbox', wait=wait)
        self.assertEqual(self.navigator.call_count, 1)
        saved = [r for r in self.reports if r.get('status') == 'waiting']
        self.assertTrue(saved)
        self.assertTrue(saved[-1]['dialogs_verified'])
        self.assertFalse(saved[-1]['ui_may_remain_open'])

    def test_unverified_pass_result_still_stops_the_monitor(self):
        # A pass that cannot prove the dialogs screen (status completed but
        # dialogs_verified falsy) stops exactly as before - the skip never
        # fabricates verification for the NEXT iteration.
        self.inbox.return_value = inbox_result(dialogs_verified=False)
        out = self.run_monitor(mode='inbox', wait=lambda _: True)
        self.assertEqual(out['reason'], 'dialog-list-not-verified')
        self.assertEqual(self.inbox.call_count, 1)

    def test_source_pins_the_skip_and_its_bounds(self):
        source = open('assistant_monitor.py', encoding='utf-8').read()
        self.assertIn("if entry != 'dialogs' or not list_verified:", source)
        self.assertIn('list_verified = False', source)
        self.assertIn('list_verified = True', source)
        # The real transitions stay in the source: the recovery-capable first
        # navigation and the post-profile return to the dialogs list.
        self.assertIn("navigate('list', entry)", source)
        self.assertIn("navigate('list', 'search')", source)


if __name__ == '__main__':
    unittest.main()
