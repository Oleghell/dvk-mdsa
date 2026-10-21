"""Synthetic tracked-inbox monitoring: no accounts, Android or network."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import assistant_monitor as monitor
from assistant_settings import Settings
from assistant_inbox import report as inbox_report
from assistant_profiles import report as profiles_report
from test_assistant_dialogs import nav_result


def list_result():
    result = nav_result('dialogs-ready')
    result['diagnostic'].update(selection_checkpoint='not-checked', rows_scanned=0, scan_batches=0)
    return result


def inbox_result(**kwargs):
    return dict(inbox_report(), status='inbox-completed', reason='visible-exhausted',
                dialogs_verified=True, **kwargs)


class Monitor(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.approve = MagicMock(return_value=True)
        self.initial = MagicMock(return_value=dict(status='completed', report_name='last-run.json',
                                                   inbox=inbox_result(), profiles=profiles_report(5)))
        self.inbox = MagicMock(return_value=inbox_result())
        self.navigator = MagicMock(side_effect=lambda operation, *args, **kwargs:
                                   list_result() if operation == 'list' else dict(list_result(), state='search-ready'))
        self.reports = []
        self.held = False
        self.progress = MagicMock()

    @contextmanager
    def lock(self):
        self.assertFalse(self.held)
        self.held = True
        try:
            yield
        finally:
            self.held = False

    def write(self, report):
        self.reports.append(copy.deepcopy(report))
        return 'last-monitor.json'

    def wait_stop(self, interval):
        self.assertTrue(self.held)
        self.assertEqual(interval, 30)
        self.stop.set()
        return True

    def run_monitor(self, **kwargs):
        defaults = dict(initial=self.initial, inbox=self.inbox, navigator=self.navigator,
                        lock=self.lock, write=self.write, wait=self.wait_stop)
        defaults.update(kwargs)
        return monitor.run(Settings(), self.stop, self.approve, self.progress, **defaults)

    def test_full_pass_once_then_only_inbox_and_one_lock(self):
        waits = []
        def wait(seconds):
            self.assertTrue(self.held)
            waits.append(seconds)
            if len(waits) == 3:
                self.stop.set()
                return True
            return False
        self.inbox.side_effect = lambda *args, **kwargs: (
            self.assertTrue(self.held) or inbox_result(submission_calls=1, handler_returns=1, outgoing_observed=1))
        out = self.run_monitor(wait=wait, fresh_session=True)
        self.assertEqual(out['status'], 'cancelled')
        self.assertEqual(out['passes_completed'], 3)
        self.assertEqual(self.initial.call_count, 1)
        self.assertTrue(self.initial.call_args.kwargs['fresh_session'])
        self.assertEqual(self.inbox.call_count, 3)
        self.assertTrue(all(c.kwargs == dict(entry='dialogs', return_to='dialogs') for c in self.inbox.call_args_list))
        self.assertEqual([c.kwargs['entry'] for c in self.navigator.call_args_list], ['either', 'dialogs', 'search', 'dialogs', 'dialogs'])
        self.assertEqual([c.args[0] for c in self.navigator.call_args_list],
                         ['list', 'return', 'list', 'list', 'list'])
        self.assertEqual(out['totals']['outgoing_observed'], 3)
        self.assertFalse(self.held)
        self.assertTrue(out['automatic_profile_repeat'])
        self.assertFalse(out['delivery_confirmed'])
        self.assertFalse(out['all_dialogs_covered'])
        self.assertIs(self.inbox.call_args.args[2], self.approve)
        self.assertTrue(any(r['status'] == 'waiting' for r in self.reports))

    def test_replies_mode_never_calls_initial_profiles(self):
        out = self.run_monitor(mode='inbox')
        self.initial.assert_not_called()
        self.assertEqual(out['passes_completed'], 1)
        self.assertEqual(self.inbox.call_count, 1)
        self.assertTrue(out['dialogs_verified'])

    def test_stop_before_start_does_not_touch_device_or_lock(self):
        self.stop.set()
        lock = MagicMock()
        out = self.run_monitor(lock=lock)
        lock.assert_not_called()
        self.initial.assert_not_called()
        self.navigator.assert_not_called()
        self.inbox.assert_not_called()
        self.assertEqual(out['status'], 'cancelled')

    def test_empty_inbox_stays_idle_and_verifies_list(self):
        self.inbox.return_value = dict(inbox_report(), status='inbox-empty')
        out = self.run_monitor(mode='inbox')
        self.assertTrue(out['dialogs_verified'])
        self.assertEqual(self.navigator.call_count, 1)
        self.approve.assert_not_called()

    def test_unknown_send_stops_without_wait_or_repeat(self):
        self.inbox.return_value = dict(inbox_report(), status='inbox-stopped', reason='chat-send-outcome-unknown')
        wait = MagicMock()
        out = self.run_monitor(wait=wait)
        self.assertEqual(out['reason'], 'inbox-pass-stopped')
        wait.assert_not_called()
        self.assertEqual(self.inbox.call_count, 1)
        self.assertFalse(out['dialogs_verified'])
        self.assertTrue(out['ui_may_remain_open'])

    def test_declining_message_pauses_instead_of_reprompting(self):
        self.inbox.return_value = inbox_result(outcomes={'message-not-approved': 1})
        wait = MagicMock()
        out = self.run_monitor(wait=wait)
        self.assertEqual(out['status'], 'paused')
        self.assertEqual(out['reason'], 'message-not-approved')
        wait.assert_not_called()
        self.assertEqual(self.inbox.call_count, 1)

    def test_manual_review_pauses_but_peer_refusal_is_terminal_only_for_peer(self):
        for reason, status in (('manual-review', 'paused'), ('telegram-outcome-unknown', 'paused'),
                               ('declined', 'cancelled')):
            with self.subTest(reason=reason):
                self.stop.clear()
                self.inbox.return_value = inbox_result(outcomes={reason: 1})
                self.assertEqual(self.run_monitor()['status'], status)

    def test_stopped_initial_pass_prevents_monitoring(self):
        self.initial.return_value['status'] = 'stopped'
        out = self.run_monitor()
        self.assertEqual(out['reason'], 'initial-pass-stopped')
        self.assertEqual(self.navigator.call_count, 2)
        self.inbox.assert_not_called()

    def test_failed_initial_report_prevents_monitoring(self):
        self.initial.return_value['report_name'] = None
        out = self.run_monitor()
        self.assertEqual(out['reason'], 'report-write-failed')
        self.assertEqual(self.navigator.call_count, 2)

    def test_initial_pause_never_navigates_or_reprompts(self):
        self.initial.return_value['status'] = 'paused'
        out = self.run_monitor()
        self.assertEqual(out['status'], 'paused')
        self.assertEqual(self.navigator.call_count, 2)
        self.inbox.assert_not_called()

    def test_device_lock_refusal_prevents_all_operations(self):
        out = self.run_monitor(lock=MagicMock(side_effect=RuntimeError('PRIVATE lock')))
        self.assertEqual(out['status'], 'stopped')
        self.initial.assert_not_called()
        self.navigator.assert_not_called()
        self.inbox.assert_not_called()
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_unverified_list_never_reads_or_sends(self):
        for changes in ({'state': 'stopped'}, {'identity': dict(account='100', peer='200', chat='300')}):
            self.navigator.side_effect = None
            self.navigator.return_value = dict(list_result(), **changes)
            out = self.run_monitor(mode='inbox')
            self.assertEqual(out['reason'], 'dialog-list-not-verified')
        self.inbox.assert_not_called()
        self.approve.assert_not_called()

    def test_switched_screen_during_wait_stops_next_pass(self):
        self.navigator.side_effect = [list_result(), RuntimeError('PRIVATE')]
        out = self.run_monitor(mode='inbox', wait=lambda _: False)
        self.assertEqual(self.inbox.call_count, 1)
        self.assertEqual(out['reason'], 'dialog-list-not-verified')
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_bad_report_stops_before_next_pass_and_masks_exception(self):
        writer = MagicMock(side_effect=OSError('PRIVATE path'))
        wait = MagicMock()
        out = self.run_monitor(mode='inbox', write=writer, wait=wait)
        self.assertEqual(out['reason'], 'report-write-failed')
        self.assertIsNone(out['report_name'])
        wait.assert_not_called()
        self.assertEqual(self.inbox.call_count, 1)
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_bad_interval_fails_without_any_device_access(self):
        out = monitor.run(Settings(reply_interval=True), self.stop, self.approve,
                          navigator=self.navigator, write=self.write)
        self.assertEqual(out['reason'], 'settings-check-stopped')
        self.navigator.assert_not_called()

    def test_stop_after_list_verification_prevents_inbox_pass(self):
        def listed(*args, **kwargs):
            self.stop.set()
            return list_result()
        out = self.run_monitor(mode='inbox', navigator=listed)
        self.assertEqual(out['status'], 'cancelled')
        self.inbox.assert_not_called()

    def test_report_atomic_write_and_summary_do_not_claim_delivery(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(monitor, 'data_directory', return_value=Path(temp)):
            out = self.run_monitor(write=monitor.write_report)
            saved = json.loads((Path(temp) / 'last-monitor.json').read_text())
            self.assertFalse((Path(temp) / 'last-monitor.tmp').exists())
            self.assertEqual(saved['status'], 'cancelled')
        text = monitor.summary(out)
        self.assertIn('не подтверждает доставку', text)
        self.assertIn('попыток приветствия', text)
        self.assertNotIn('отправлено', text)

    def test_invalid_mode_cannot_repeat_profile_only_passes(self):
        with self.assertRaises(ValueError):
            self.run_monitor(mode='profiles')


if __name__ == '__main__':
    unittest.main()


class RepeatedProfiles(Monitor):
    def test_two_minute_timer_rotates_without_repeating_full_initial_or_clearing_journal(self):
        now=[0.0];waits=[];batches=[]
        def repeat(*args,**kwargs):
            self.assertTrue(self.held)
            batches.append(now[0]);self.assertEqual(kwargs['mode'],'profiles')
            self.assertTrue(kwargs['fresh_session']);self.assertIs(kwargs['lock'],__import__('contextlib').nullcontext)
            return dict(status='completed',report_name='last-run.json',profiles=profiles_report(5))
        def wait(seconds):
            waits.append(seconds);now[0]+=seconds
            if len(waits)==10:self.stop.set();return True
            return False
        out=self.run_monitor(clock=lambda:now[0],wait=wait,repeat=repeat)
        self.assertEqual(batches,[120,240]);self.assertEqual(out['profile_batches_completed'],3)
        self.assertEqual(out['profile_interval_seconds'],120)
        self.assertEqual(self.initial.call_count,1);self.assertEqual(self.inbox.call_count,10)
        operations=[c.args[0] for c in self.navigator.call_args_list]
        self.assertEqual(operations.count('return'),3)
        self.assertTrue(out['dialogs_verified'])

    def test_inbox_only_never_repeats_even_after_due_time(self):
        now=[0];repeat=MagicMock()
        def wait(seconds):
            now[0]+=1000
            if now[0]>=3000:self.stop.set();return True
            return False
        out=self.run_monitor(mode='inbox',clock=lambda:now[0],repeat=repeat,wait=wait)
        repeat.assert_not_called();self.assertFalse(out['automatic_profile_repeat'])

    def test_long_batch_does_not_create_catchup_storm(self):
        now=[0];calls=[]
        def repeat(*a,**kw):
            calls.append(now[0]);now[0]+=300
            return dict(status='completed',report_name='last-run.json',profiles=profiles_report(5))
        def wait(seconds):
            now[0]+=seconds
            if now[0]>=450:self.stop.set();return True
            return False
        out=self.run_monitor(clock=lambda:now[0],repeat=repeat,wait=wait)
        self.assertEqual(calls,[120]);self.assertEqual(out['profile_batches_completed'],2)

    def test_unknown_repeated_profile_send_stops_and_alerts_once(self):
        now=[0];alert=MagicMock(return_value='accepted')
        repeat=MagicMock(return_value=dict(status='stopped',reason='profiles-not-finished',profiles=dict(reason='send-outcome-unknown')))
        def wait(seconds):now[0]+=seconds;return False
        out=self.run_monitor(clock=lambda:now[0],repeat=repeat,wait=wait,alert=alert)
        self.assertEqual(out['reason'],'profile-pass-stopped')
        repeat.assert_called_once();alert.assert_called_once()
        self.assertEqual(out['error_notification'],'accepted')
        self.assertNotIn('sendMessage',json.dumps(out))

    def test_fatal_report_failure_also_alerts_once(self):
        alert=MagicMock(return_value='unknown')
        out=self.run_monitor(write=MagicMock(side_effect=OSError('PRIVATE')),alert=alert)
        self.assertEqual(out['reason'],'report-write-failed');alert.assert_called_once()
        self.assertNotIn('PRIVATE',json.dumps(out))
