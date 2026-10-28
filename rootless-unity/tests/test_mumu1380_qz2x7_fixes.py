"""Reports QZ2X7 (v1.3.79, dropmefiles): thirteen Telegram JSON diagnostics from
a two-PC fleet. Four distinct death shapes, all fixed in 1.3.80:

* 524/526/528/530/531/532/533/534 (eight of eleven): stopped at
  prepare-profile-reserve-failed, CloudDatabaseError
  cloud-database-unavailable/connect at profile-reserve - the pre-ACK
  reservation met the same synchronized pooler burst the reads survive, the
  cycle died as journal-error (a recovery BLOCK code) and the port never
  recovered. The reservation now rides the bounded jittered transient window
  and defers into the verified no-send skip on exhaustion.
* 525/527: dialog-list-not-verified with identity-not-bound and
  entry_binding_waits=25 - a cold-restoring chat model outlived the whole
  bounded wait, and the SHARED identity-not-bound label matched the recovery
  BLOCK set, so both ports stayed dead instead of recovering. The exhausted
  wait now fails closed with its own entry-binding-timeout readiness code
  (RETRY set); structural identity failures keep the fatal code.
* 533 (reporting only): inbox-empty arrived as
  unrecognized-diagnostic-code because no-chain-dialogs/history-cooldown were
  missing from the closed notification set.
* startup (9) port 5585: adb-preflight died with evidence=null, so the
  controller's bounded pre-send requeue could not prove the death transient;
  the worker now attaches the closed ADB evidence and transport-shaped
  preflight deaths requeue like the journal bootstrap ones.

Synthetic only; no device, database or worker process is touched."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assistant_pass as native
import dialog_browser
import mumu_recovery
import mumu_controller
from cloud_database import CloudDatabaseError
from test_assistant import pending


def transient(): return CloudDatabaseError('cloud-database-unavailable')
def capacity(): return CloudDatabaseError('cloud-database-capacity')
def permission(): return CloudDatabaseError('cloud-database-permission')


class ReserveTransientWindow(unittest.TestCase):
    """monitor(): the pre-ACK reservation survives pooler saturation."""

    def run_monitor(self, reserve=None, cancelled=lambda: False):
        script = MagicMock(); script.exports_sync.cohortpending.return_value = pending()
        script.exports_sync.cohortack.return_value = True
        done = MagicMock(); done.wait.return_value = False; done.is_set.return_value = False
        store = MagicMock(); store.mumu_shared_claims = True
        store.peer_terminal = MagicMock(return_value=False)
        store.reserve = reserve if reserve is not None else MagicMock(return_value=17)
        state = {}; failures = []
        with patch.object(native, 'SHARED_READ_RETRY_DELAYS', (0, 0)):
            native.monitor(script, store, 'Hi', lambda *a: True, done, cancelled, state, failures)
        return script, store, state, failures

    def test_transient_reserve_failure_is_retried_until_success(self):
        reserve = MagicMock(side_effect=[transient(), 17])
        script, store, state, failures = self.run_monitor(reserve)
        self.assertEqual(reserve.call_count, 2)
        self.assertFalse(failures)
        self.assertEqual(state['action_id'], 17)
        script.exports_sync.cohortack.assert_called_once()
        script.exports_sync.cohortack.assert_called_with(pending())
        script.exports_sync.cancel.assert_not_called()

    def test_capacity_reserve_failure_is_also_retried(self):
        reserve = MagicMock(side_effect=[capacity(), 17])
        script, store, state, failures = self.run_monitor(reserve)
        self.assertEqual(reserve.call_count, 2)
        self.assertFalse(failures)
        self.assertEqual(state['action_id'], 17)

    def test_exhausted_reserve_window_defers_to_verified_no_send_skip(self):
        # The exact QZ2X7 shape: every attempt refused while the chat is
        # already open. No reservation, no ACK authorization, no failure -
        # the peer is skipped with the verified Back and stays eligible.
        # Two retry pauses on the (0, 0) delay ladder: three attempts total.
        reserve = MagicMock(side_effect=[transient() for _ in range(3)])
        script, store, state, failures = self.run_monitor(reserve)
        self.assertEqual(reserve.call_count, 3)
        self.assertFalse(failures)
        self.assertTrue(state['peer_check_deferred'])
        self.assertTrue(state['shared_peer_skipped'])
        script.exports_sync.cohortack.assert_called_once()
        self.assertTrue(script.exports_sync.cohortack.call_args.args[0].get('skip'))
        script.exports_sync.cancel.assert_not_called()

    def test_done_race_after_exhaustion_marks_deferred_without_failure(self):
        # root() already returned (its own budget stop) while the retry window
        # was still running: the native report alone decides the cycle, no
        # skip ACK may be sent after the cycle ended, and the port survives.
        script = MagicMock(); script.exports_sync.cohortpending.return_value = pending()
        script.exports_sync.cohortack.return_value = True
        done = MagicMock(); done.wait.return_value = False; done.is_set.return_value = False
        store = MagicMock(); store.mumu_shared_claims = True
        store.peer_terminal = MagicMock(return_value=False)

        def refuse_then_done(*args, **kwargs):
            done.is_set.return_value = True
            raise transient()

        store.reserve = MagicMock(side_effect=refuse_then_done)
        state = {}; failures = []
        with patch.object(native, 'SHARED_READ_RETRY_DELAYS', (0,)):
            native.monitor(script, store, 'Hi', lambda *a: True, done, lambda: False, state, failures)
        self.assertFalse(failures)
        self.assertTrue(state['peer_check_deferred'])
        self.assertNotIn('shared_peer_skipped', state)
        script.exports_sync.cohortack.assert_not_called()
        script.exports_sync.cancel.assert_not_called()

    def test_non_transient_reserve_failure_keeps_the_hard_stop(self):
        reserve = MagicMock(side_effect=permission())
        script, store, state, failures = self.run_monitor(reserve)
        self.assertEqual(reserve.call_count, 1)
        self.assertEqual(state['authorization_checkpoint'], 'profile-reserve')
        self.assertTrue(failures)
        script.exports_sync.cancel.assert_called_once()

    def test_cancelled_during_reserve_retry_cancels(self):
        flag = {'stop': False}

        def fail_then_stop(*args, **kwargs):
            flag['stop'] = True
            raise transient()

        script, store, state, failures = self.run_monitor(
            MagicMock(side_effect=fail_then_stop), cancelled=lambda: flag['stop'])
        self.assertEqual(state['authorization_checkpoint'], 'profile-reserve')
        script.exports_sync.cancel.assert_called_once()

    def test_shared_peer_claimed_during_retry_keeps_the_verified_skip(self):
        # Another port claimed the peer while this one waited: the retry's
        # blocked() re-check raises SharedPeerClaimed into the skip path.
        from mumu_store import SharedPeerClaimed
        reserve = MagicMock(side_effect=[transient(), SharedPeerClaimed('claimed')])
        script, store, state, failures = self.run_monitor(reserve)
        self.assertEqual(reserve.call_count, 2)
        self.assertFalse(failures)
        self.assertTrue(state['shared_peer_skipped'])
        self.assertNotIn('action_id', state)
        script.exports_sync.cohortack.assert_called_once()
        self.assertTrue(script.exports_sync.cohortack.call_args.args[0].get('skip'))

    def test_source_pins_the_new_reserve_window(self):
        source = (Path(__file__).resolve().parents[1] / 'assistant_pass.py').read_text(encoding='utf-8')
        self.assertIn('lambda: store.reserve(pending, text, approved=True)', source)
        self.assertNotIn('shared_registry_read(lambda: store.finish', source)


class EntryBindingTimeout(unittest.TestCase):
    """The exhausted startup binding wait is recoverable readiness, not identity."""

    def test_dialog_browser_errors_include_the_new_closed_code(self):
        self.assertIn('entry-binding-timeout', dialog_browser.ERRORS)
        self.assertIn('identity-not-bound', dialog_browser.ERRORS)

    def test_recovery_retry_set_includes_the_wait_exhaustion(self):
        self.assertIn('entry-binding-timeout', mumu_recovery.RETRY_CODES)
        self.assertIn('identity-not-bound', mumu_recovery.BLOCK_CODES)

    def test_exhausted_startup_binding_wait_is_recoverable(self):
        # The exact 525/527 report shape: dialog-list-not-verified with a
        # fully waited-out entry binding and no other code anywhere.
        navigation = dict(stage='navigation-stopped', error='entry-binding-timeout',
                          phase='entry', entry_binding_waits=25)
        report = dict(status='stopped', reason='dialog-list-not-verified',
                      last_navigation=navigation,
                      last_navigation_failure=dict(stage='navigation-destination',
                                                   error='startup-navigation-destination-failed',
                                                   error_type='ValueError'))
        self.assertTrue(mumu_recovery.recoverable(report))

    def test_structural_identity_failure_stays_blocked(self):
        navigation = dict(stage='navigation-stopped', error='identity-not-bound', phase='entry')
        report = dict(status='stopped', reason='dialog-list-not-verified',
                      last_navigation=navigation)
        self.assertFalse(mumu_recovery.recoverable(report))

    def test_json_notification_keeps_the_new_code(self):
        from assistant_error_notify import diagnostic_json
        import json as encoder
        value = encoder.loads(diagnostic_json(
            dict(status='stopped', reason='dialog-list-not-verified',
                 last_navigation=dict(stage='navigation-stopped', error='entry-binding-timeout'))))
        error = value['diagnostic']['last_navigation']['error']
        self.assertEqual(error, 'entry-binding-timeout')


class InboxEmptyReasons(unittest.TestCase):
    """533: benign inbox-empty reasons must survive the closed projection."""

    def test_benign_inbox_empty_reasons_survive_diagnostic_json(self):
        from assistant_error_notify import diagnostic_json
        import json as encoder
        for reason in ('no-chain-dialogs', 'history-cooldown'):
            value = encoder.loads(diagnostic_json(
                dict(status='inbox-empty', reason=reason)))['diagnostic']
            self.assertEqual(value['reason'], reason)

    def test_the_reasons_are_part_of_the_closed_known_set(self):
        from assistant_error_notify import KNOWN
        self.assertIn('no-chain-dialogs', KNOWN)
        self.assertIn('history-cooldown', KNOWN)


def startup_report(port=5585, evidence=None, error_type='TestError'):
    return dict(tool_version='1.3.79', platform='MuMu', device_port=port,
                installation_id='9104352dfec24d2bcb7f9ce40becaa8c', status='stopped',
                stage='adb-preflight', error_type=error_type, reason='startup-failed',
                evidence=evidence, automatic_retry=False)


def adb_evidence(check, reason):
    return dict(stage='adb-preflight', error='startup-adb-preflight-failed',
                error_type='TestError', adb_check=check, adb_reason=reason)


class PreflightRequeue(unittest.TestCase):
    """5585: transport-shaped adb-preflight deaths requeue, everything else stops."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        env = patch.dict(os.environ, LOCALAPPDATA=folder.name)
        env.start()
        self.addCleanup(folder.cleanup)
        self.addCleanup(env.stop)
        self.since = time.time() - 5.0

    def reason(self, value):
        from mumu_common import atomic, device_directory
        atomic(device_directory(value['device_port']) / 'last-startup.json', value)
        return mumu_controller.startup_requeue_reason(value['device_port'], self.since)

    def test_transport_shaped_preflight_deaths_are_requeueable(self):
        for check, reason in (('test-connect', 'connection-refused'),
                              ('test-connect', 'connection-failed'),
                              ('test-state', 'device-offline'),
                              ('test-state', 'device-not-found'),
                              ('test-state', 'no-device'),
                              ('test-identity', 'connection-timeout'),
                              ('adb-version', 'adb-server-unavailable'),
                              ('test-state', 'command-timeout')):
            with self.subTest(check=check, reason=reason):
                value = startup_report(evidence=adb_evidence(check, reason))
                self.assertIn('поднимался', self.reason(value))

    def test_boot_not_completed_is_requeueable(self):
        value = startup_report(evidence=adb_evidence('test-boot-completed', 'unexpected-response'))
        self.assertIn('загружался', self.reason(value))

    def test_missing_package_stays_fatal(self):
        value = startup_report(evidence=adb_evidence('test-package-presence', 'unexpected-response'))
        self.assertIsNone(self.reason(value))

    def test_unauthorized_device_stays_fatal(self):
        value = startup_report(evidence=adb_evidence('test-state', 'device-unauthorized'))
        self.assertIsNone(self.reason(value))

    def test_permission_denied_stays_fatal(self):
        value = startup_report(evidence=adb_evidence('test-connect', 'permission-denied'))
        self.assertIsNone(self.reason(value))

    def test_null_evidence_keeps_the_hard_stop(self):
        self.assertIsNone(self.reason(startup_report()))

    def test_other_error_types_are_never_requeued(self):
        for name in ('MumuError', 'StateError', 'OSError', 'OtherError'):
            with self.subTest(name=name):
                value = startup_report(evidence=adb_evidence('test-state', 'device-offline'),
                                       error_type=name)
                self.assertIsNone(self.reason(value))

    def test_evidence_must_match_the_closed_startup_schema(self):
        for evidence in (None, 'x', dict(stage='adb-preflight'),
                         dict(stage='adb-preflight', error='startup-adb-preflight-failed',
                              error_type='TestError', adb_check='test-state')):
            with self.subTest(evidence=evidence):
                value = startup_report(evidence=evidence)
                self.assertIsNone(self.reason(value))

    def test_cancelled_and_running_reports_are_never_requeued(self):
        running = startup_report(evidence=adb_evidence('test-state', 'device-offline'))
        running['status'] = 'running'
        self.assertIsNone(self.reason(running))
        cancelled = startup_report(evidence=adb_evidence('test-state', 'device-offline'))
        cancelled['reason'] = 'cancelled'
        self.assertIsNone(self.reason(cancelled))


class WorkerPreflightEvidence(unittest.TestCase):
    """mumu_worker attaches the closed ADB evidence to preflight deaths."""

    def test_preflight_runs_inside_the_checkpoint(self):
        source = (Path(__file__).resolve().parents[1] / 'mumu_worker.py').read_text(encoding='utf-8')
        self.assertIn("with checkpoint('adb-preflight', adb=adb):", source)
        self.assertIn('boot=preflight(adb)', source)

    def test_checkpoint_attaches_the_last_failed_adb_event(self):
        from startup_failure import checkpoint
        from test_device import TestError
        adb = MagicMock()
        adb.adb_events = [
            dict(check='test-connect', status='failed', reason='connection-refused', return_code=1),
            dict(check='test-state', status='passed', reason='none', return_code=0),
            dict(check='test-state', status='failed', reason='device-offline', return_code=0),
        ]
        with self.assertRaises(TestError) as raised:
            with checkpoint('adb-preflight', adb=adb):
                raise TestError('Запусти только тестовый MuMu #4 и разреши его обычный ADB.')
        error = raised.exception
        evidence = getattr(error, '_dvk_failure', None)
        self.assertEqual(evidence['stage'], 'adb-preflight')
        self.assertEqual(evidence['error'], 'startup-adb-preflight-failed')
        self.assertEqual(evidence['adb_check'], 'test-state')
        self.assertEqual(evidence['adb_reason'], 'device-offline')
        from startup_failure import clean, recoverable_adb
        self.assertTrue(recoverable_adb(clean(evidence)))


if __name__ == '__main__':
    unittest.main()
