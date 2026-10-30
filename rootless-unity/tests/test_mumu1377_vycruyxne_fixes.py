"""Reports 508-510 (v1.3.76, dropmefiles vYCRUyXNE): the user's twelve-port
start - "the first nine ports started fine, the last three died with this
error". The stagger queue from 1.3.73 put the last ports minutes behind the
first nine, and they died in two provably pre-send shapes:

* 5577/5579: status=stopped, stage=journal-initialization,
  CloudDatabaseError cloud-database-unavailable (connect) - the pooler
  pressure of nine running ports' first pass outlasted the worker's whole
  internal retry ladder, and nothing re-queued the dead port.
* 5575: the worker died silently right after its initial report
  (status=starting, stage=worker-bootstrap, installation_id still null) and
  the port stayed dead until a manual restart.

Fix under test: run_many re-queues such a port automatically - bounded
(STARTUP_REQUEUE_LIMIT), jittered cooldowns, Stop-aware, a fresh PortControl
per attempt, the real failure text preserved on exhaustion. Every other
report shape stays a hard stop. Synthetic only; no device, database or
worker process is touched."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import mumu_controller
from mumu_common import atomic, device_directory
from mumu_pause import PortControl
from assistant_settings import Settings


def report_5577(port=5577, code='cloud-database-unavailable', operation='connect'):
    """The exact closed report shape the worker wrote for ports 5577/5579."""
    return dict(tool_version='1.3.76', platform='MuMu', device_port=port,
                installation_id='9104352dfec24d2bcb7f9ce40becaa8c', status='stopped',
                stage='journal-initialization', error_type='CloudDatabaseError',
                reason='startup-failed', evidence=None, automatic_retry=False,
                database=dict(code=code, operation=operation, automatic_retry=False))


def report_5575(port=5575):
    """The exact initial-report shape port 5575 was left stuck at."""
    return dict(tool_version='1.3.76', platform='MuMu', device_port=port,
                installation_id=None, status='starting', stage='worker-bootstrap',
                automatic_retry=False)


def write_report(n, value):
    atomic(device_directory(n) / 'last-startup.json', value)


class RequeueConstants(unittest.TestCase):
    def test_budget_is_two_extra_attempts_over_jittered_cooldowns(self):
        self.assertIs(type(mumu_controller.STARTUP_REQUEUE_LIMIT), int)
        # v1.3.96 (report LAZ5VEvy): three requeues over (20, 45, 90) s ride
        # out a multi-minute journal-connect refusal; every wait observes
        # Stop and every non-transient death evidence stays fatal.
        self.assertEqual(mumu_controller.STARTUP_REQUEUE_LIMIT, 3)
        delays = mumu_controller.STARTUP_REQUEUE_DELAYS
        self.assertIsInstance(delays, tuple)
        self.assertEqual(len(delays), mumu_controller.STARTUP_REQUEUE_LIMIT)
        for value in delays:
            self.assertIs(type(value), float)
            self.assertGreater(value, 0)
            self.assertLessEqual(value, 120)

    def test_requeue_cooldowns_use_the_production_delays_by_default(self):
        self.assertEqual(mumu_controller.STARTUP_REQUEUE_DELAYS, (20.0, 45.0, 90.0))

    def test_database_codes_pin_the_engine_transient_set(self):
        from cloud_database import TRANSIENT_CODES
        self.assertEqual(mumu_controller.REQUEUE_DATABASE_CODES, TRANSIENT_CODES)
        self.assertEqual(mumu_controller.REQUEUE_DATABASE_CODES,
                         frozenset({'cloud-database-unavailable', 'cloud-database-capacity'}))


class RequeueReasonEvidence(unittest.TestCase):
    """startup_requeue_reason accepts exactly the two observed shapes."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        env = patch.dict(os.environ, LOCALAPPDATA=folder.name)
        env.start()
        self.addCleanup(folder.cleanup)
        self.addCleanup(env.stop)
        self.since = time.time() - 5.0

    def reason(self, n, value):
        write_report(n, value)
        return mumu_controller.startup_requeue_reason(n, self.since)

    def test_report_5577_shape_is_requeueable(self):
        self.assertIn('общая база', self.reason(5577, report_5577()))

    def test_report_5575_shape_is_requeueable(self):
        self.assertIn('рабочий процесс', self.reason(5575, report_5575()))

    def test_capacity_connect_is_requeueable_too(self):
        self.assertIsNotNone(self.reason(5579, report_5577(port=5579, code='cloud-database-capacity')))

    def test_non_transient_codes_stay_fatal(self):
        for code in ('cloud-database-permission', 'cloud-database-lock-timeout',
                     'cloud-database-config-invalid', 'cloud-database-query-timeout',
                     'cloud-dataset-not-ready', 'cloud-schema-missing'):
            with self.subTest(code=code):
                self.assertIsNone(self.reason(5577, report_5577(code=code)))

    def test_non_connect_operations_stay_fatal(self):
        for operation in ('read', 'write', 'lock', 'commit', 'unknown'):
            with self.subTest(operation=operation):
                self.assertIsNone(self.reason(5577, report_5577(operation=operation)))

    def test_user_cancellation_is_never_requeued(self):
        value = report_5577(); value['reason'] = 'cancelled'
        self.assertIsNone(self.reason(5577, value))

    def test_later_stages_are_never_requeued(self):
        for stage in ('monitor', 'settings-check', 'adb-preflight'):
            with self.subTest(stage=stage):
                value = report_5577(); value['stage'] = stage
                self.assertIsNone(self.reason(5577, value))

    def test_other_error_types_are_never_requeued(self):
        for name in ('MumuError', 'StateError', 'OSError', 'OtherError'):
            with self.subTest(name=name):
                value = report_5577(); value['error_type'] = name
                self.assertIsNone(self.reason(5577, value))

    def test_running_or_finished_reports_are_never_requeued(self):
        for status in ('running', 'finished'):
            with self.subTest(status=status):
                value = report_5575(); value['status'] = status
                self.assertIsNone(self.reason(5575, value))

    def test_database_block_must_match_the_closed_schema(self):
        for database in (None, 'x', dict(code='cloud-database-unavailable'),
                         dict(code='cloud-database-unavailable', operation='connect', automatic_retry=True),
                         dict(code='cloud-database-unavailable', operation='connect', automatic_retry=False, extra=1)):
            with self.subTest(database=database):
                value = report_5577(); value['database'] = database
                self.assertIsNone(self.reason(5577, value))

    def test_stale_report_from_an_earlier_run_never_requeues(self):
        write_report(5577, report_5577())
        path = device_directory(5577) / 'last-startup.json'
        old = time.time() - 3600.0
        os.utime(path, (old, old))
        self.assertIsNone(mumu_controller.startup_requeue_reason(5577, time.time()))

    def test_missing_corrupt_or_foreign_reports_never_requeue(self):
        self.assertIsNone(mumu_controller.startup_requeue_reason(5559, time.time() - 5.0))
        write_report(5559, report_5577())  # wrong device_port inside the report
        self.assertIsNone(mumu_controller.startup_requeue_reason(5559, time.time() - 5.0))
        path = device_directory(5559) / 'last-startup.json'
        path.write_text('{not json', encoding='utf-8')
        self.assertIsNone(mumu_controller.startup_requeue_reason(5559, time.time() - 5.0))
        path.write_text('[1,2]', encoding='utf-8')
        self.assertIsNone(mumu_controller.startup_requeue_reason(5559, time.time() - 5.0))

    def test_reason_ignores_every_field_outside_the_closed_shape(self):
        value = report_5577()
        value.update(evidence=None, tool_version='1.3.77', installation_id=None,
                     extra_closed_field='ignored')
        self.assertIn('общая база', self.reason(5577, value))


class RequeueInRunMany(unittest.TestCase):
    """The controller itself re-queues the port, bounded and Stop-aware."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        env = patch.dict(os.environ, LOCALAPPDATA=folder.name)
        env.start()
        self.addCleanup(folder.cleanup)
        self.addCleanup(env.stop)
        delays = patch.object(mumu_controller, 'STARTUP_REQUEUE_DELAYS', (0.0, 0.0, 0.0))
        delays.start()
        self.addCleanup(delays.stop)

    def run_many(self, worker, ports=(5577,), stopped=None, controls=None):
        if stopped is None:
            stopped = threading.Event()
        messages = []
        progress = lambda n, text: messages.append((n, text))
        out = mumu_controller.run_many(list(ports), Settings(), 'inbox', False,
                                       stopped, progress, worker=worker,
                                       controls=controls, spacing=0,
                                       jitter=lambda: 1.0)
        return out, messages

    def failing_worker(self, shape):
        """Worker that always dies leaving `shape` reports; records launches."""
        calls = []
        controls = []

        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            calls.append(n)
            controls.append(control)
            write_report(n, shape(n))
            return 'Этап: journal-initialization. Тип: CloudDatabaseError. См. last-startup.json.'
        return worker, calls, controls

    def test_transient_connect_death_is_requeued_until_success(self):
        state = {'failed': 0}

        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            if state['failed'] < 2:
                state['failed'] += 1
                write_report(n, report_5577(n))
                return 'ошибка'
            return 'ok'
        out, messages = self.run_many(worker)
        self.assertEqual(out, {5577: 'ok'})
        self.assertEqual(state['failed'], 2)
        self.assertTrue(any(n == 5577 and 'Автоповтор запуска (попытка 2 из 4)' in text
                            and 'общая база была занята' in text and 'отправки не повторяются' in text
                            for n, text in messages), messages)

    def test_silent_bootstrap_death_is_requeued(self):
        state = {'failed': 0}

        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            if state['failed'] < 1:
                state['failed'] += 1
                write_report(n, report_5575(n))
                return 'Рабочий процесс завершился без отчёта.'
            return 'ok'
        out, messages = self.run_many(worker, ports=(5575,))
        self.assertEqual(out, {5575: 'ok'})
        self.assertEqual(state['failed'], 1)
        self.assertTrue(any(n == 5575 and 'Автоповтор запуска (попытка 2 из 4)' in text
                            and 'рабочий процесс' in text for n, text in messages), messages)

    def test_budget_is_bounded_and_the_real_error_survives(self):
        worker, calls, _ = self.failing_worker(report_5577)
        out, _ = self.run_many(worker)
        self.assertEqual(calls, [5577, 5577, 5577, 5577])
        self.assertTrue(out[5577].startswith('Этап: journal-initialization'))

    def test_stop_after_the_first_death_never_requeues(self):
        stop = threading.Event()
        worker, calls, _ = self.failing_worker(report_5577)
        wrapped = self.stop_after_first(worker, stop)
        out, messages = self.run_many(wrapped, stopped=stop)
        self.assertEqual(calls, [5577])
        self.assertFalse(any('Автоповтор' in text for _, text in messages), messages)

    def stop_after_first(self, worker, stop):
        def wrapped(n, settings, mode, fresh, stopped, progress, *, control=None):
            value = worker(n, settings, mode, fresh, stopped, progress, control=control)
            stop.set()
            return value
        return wrapped

    def test_non_requeueable_failure_keeps_one_attempt(self):
        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            write_report(n, report_5577(n, code='cloud-database-permission'))
            return 'ошибка прав'
        out, messages = self.run_many(worker)
        self.assertEqual(out, {5577: 'ошибка прав'})
        self.assertFalse(any('Автоповтор' in text for _, text in messages), messages)

    def test_aged_stale_report_plus_unwriting_failure_keeps_one_attempt(self):
        # A spawn failure that writes nothing plus a shape-A report aged to an
        # earlier run: the evidence is not this attempt's, no requeue.
        write_report(5579, report_5577(port=5579))
        os.utime(device_directory(5579) / 'last-startup.json', (time.time() - 600.0,) * 2)

        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            return 'Ошибка запуска рабочего процесса. См. папку отчётов этого порта.'
        out, messages = self.run_many(worker, ports=(5579,))
        self.assertIn('Ошибка запуска', out[5579])
        self.assertFalse(any('Автоповтор' in text for _, text in messages), messages)

    def test_each_requeued_attempt_gets_a_fresh_live_control(self):
        worker, calls, controls = self.failing_worker(report_5577)
        live = {5577: PortControl()}
        first = live[5577]
        out, _ = self.run_many(worker, controls=live)
        self.assertEqual(calls, [5577, 5577, 5577, 5577])
        # Attempt 1 ran on the original control; every requeued attempt got a
        # DIFFERENT fresh one, so the GUI never sees a finished control while
        # an attempt is still live.
        self.assertIs(controls[0], first)
        self.assertIsNot(controls[1], first)
        self.assertIsNot(controls[2], first)
        self.assertIsNot(controls[3], first)
        self.assertIsNot(controls[1], controls[2])
        self.assertIsNot(controls[2], controls[3])
        # The dict now holds the LAST swapped control, finished by run_many.
        self.assertIs(live[5577], controls[3])
        self.assertTrue(live[5577].finished)

    def test_control_swap_keeps_pause_usable_between_attempts(self):
        worker, calls, _ = self.failing_worker(report_5577)
        live = {5577: PortControl()}
        seen = []

        def observing(n, settings, mode, fresh, stopped, progress, *, control=None):
            seen.append(control.state())
            return worker(n, settings, mode, fresh, stopped, progress, control=control)
        out, _ = self.run_many(observing, controls=live)
        # All four attempts ran on a live 'running' control - never finished.
        self.assertEqual(seen, ['running', 'running', 'running', 'running'])
        self.assertTrue(live[5577].finished)

    def test_requeue_waits_its_jittered_cooldown_between_attempts(self):
        class StopRecorder:
            """Event-compatible stop that records every wait timeout."""
            def __init__(self):
                self.inner = threading.Event()
                self.waits = []
            def is_set(self):
                return self.inner.is_set()
            def set(self):
                return self.inner.set()
            def wait(self, timeout=None):
                self.waits.append(timeout)
                return self.inner.wait(timeout)
        recorder = StopRecorder()
        worker, calls, _ = self.failing_worker(report_5577)
        out, _ = self.run_many(worker, stopped=recorder)
        self.assertEqual(calls, [5577, 5577, 5577, 5577])
        # spacing=0 and a single port mean no stagger waits: exactly the three
        # requeue cooldowns (patched to 0.0, jitter 1.0) are observed.
        self.assertEqual(recorder.waits, [0.0, 0.0, 0.0])

    def test_requeue_survives_multi_port_run_alongside_healthy_ports(self):
        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            if n == 5577:
                if worker.bad < 1:
                    worker.bad += 1
                    write_report(n, report_5577(n))
                    return 'ошибка'
            return 'ok'
        worker.bad = 0
        out, messages = self.run_many(worker, ports=(5557, 5577, 5579), controls=None)
        self.assertEqual(out, {5557: 'ok', 5577: 'ok', 5579: 'ok'})
        self.assertTrue(any(n == 5577 and 'Автоповтор' in text for n, text in messages), messages)
        self.assertFalse(any(n != 5577 and 'Автоповтор' in text for n, text in messages), messages)


class OriginalQueueBehaviourPreserved(unittest.TestCase):
    """The 1.3.73 stagger queue and its messages stay exactly as they were."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        env = patch.dict(os.environ, LOCALAPPDATA=folder.name)
        env.start()
        self.addCleanup(folder.cleanup)
        self.addCleanup(env.stop)

    def test_queue_message_and_start_order_unchanged(self):
        started = []
        messages = []

        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            started.append((n, time.monotonic()))
            return 'ok'
        out = mumu_controller.run_many([5557, 5559, 5561], Settings(), 'inbox', False,
                                       threading.Event(),
                                       lambda n, text: messages.append((n, text)),
                                       worker=worker, spacing=0.08, jitter=lambda: 1.0)
        self.assertEqual(out, {5557: 'ok', 5559: 'ok', 5561: 'ok'})
        times = dict(started)
        self.assertGreaterEqual(times[5559] - times[5557], 0.07)
        self.assertGreaterEqual(times[5561] - times[5557], 0.15)
        self.assertTrue(any(n == 5559 and 'очередь запуска' in text for n, text in messages))
        self.assertFalse(any('Автоповтор' in text for _, text in messages), messages)

    def test_stopped_run_records_not_launched_without_requeue(self):
        stop = threading.Event(); stop.set()
        launched = []

        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            launched.append(n)
            return 'ok'
        out = mumu_controller.run_many([5557, 5559], Settings(), 'inbox', False, stop,
                                       lambda *a: None, worker=worker, spacing=0)
        self.assertEqual(launched, [])
        for n in (5557, 5559):
            self.assertEqual(out[n], 'Остановлено до запуска.')


if __name__ == '__main__':
    unittest.main()
