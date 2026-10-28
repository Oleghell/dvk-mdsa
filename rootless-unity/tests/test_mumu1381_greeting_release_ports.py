"""Reports after QZ2X7 (v1.3.80): the user again watched a freshly checked
profile open its dialog, sit in silence and back out with no greeting, and
port 5585 never connected at startup. Two root causes, both closed in 1.3.81:

* The pre-ACK sequence still had two holes that PERMANENTLY lost peers. The
  separate post-reserve terminal read cost one pooled cloud roundtrip on every
  greeting cycle - feeding the very pooler bursts it was meant to survive -
  and its transient exhaustion deferred with the RETAINED claim, leaving the
  peer claimed-but-never-greeted forever (the visible symptom: open chat,
  ~10s of host roundtrips, silent verified Back). The atomic blocked()
  re-check inside reserve() already covers mumu_peer_blocks, so the separate
  read was redundant; it is gone. And every path where a COMMITTED
  reservation provably never receives its ACK (root() returned first, host
  stopped, stale ACK) now RELEASES the claim back to the eligible pool
  instead of keeping it as a "durable unknown".
* Port 5585: the stagger-queued worker's single-shot adb preflight died when
  its MuMu instance was still raising the ADB listener. The worker now rides
  out transport-shaped and boot-pending evidence in a bounded jittered window
  before the 1.3.80 controller requeue is even needed; two ports pointing at
  ONE instance are named as a crossing instead of "another copy is running",
  and the legacy "#4 / 5563" wording is gone from every multi-port message.

Synthetic only; no device, database or worker process is touched."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assistant_pass as native
import mumu_worker
from cloud_database import CloudDatabaseError
from test_assistant import pending


def transient(): return CloudDatabaseError('cloud-database-unavailable')
def permission(): return CloudDatabaseError('cloud-database-permission')


def wired(store, *, ack=True, done_set=lambda: False, cancelled=lambda: False,
          preclaimed=frozenset(), approve=lambda *a: True):
    """Wire one monitor() call against a mock or real store.

    Returns (script, state, failures, run, done); ``done`` is the mock event
    whose is_set() tests can flip from inside a reserve side effect to
    reproduce the post-commit pre-ACK race.
    """
    script = MagicMock()
    script.exports_sync.cohortpending.return_value = pending()
    script.exports_sync.cohortack.return_value = ack
    done = MagicMock()
    done.wait.return_value = False
    done.is_set.side_effect = lambda: False
    state = {}; failures = []
    def run():
        with patch.object(native, 'SHARED_READ_RETRY_DELAYS', (0, 0)), \
             patch.object(native, 'RELEASE_RETRY_DELAYS', (0, 0)):
            native.monitor(script, store, 'Hi', approve, done, cancelled, state, failures, preclaimed)
    return script, state, failures, run, done


class ReleaseReservationStore(unittest.TestCase):
    """SharedStore.release_reservation: the claim returns to the eligible pool."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from mumu_store import SharedStore
        base = Path(self.temp.name)
        self.store = SharedStore(base / 'assistant.sqlite3', base / 'old',
                                 device_port=5585, installation_id='a' * 32)
        self.other = SharedStore(base / 'assistant.sqlite3', base / 'old',
                                 device_port=5585, installation_id='b' * 32)

    def claims(self, store, peer):
        with store.read_connection() as db:
            return db.execute('SELECT device FROM mumu_greeting_claims WHERE peer=?', (peer,)).fetchall()

    def status(self, action_id):
        with self.store.read_connection() as db:
            return db.execute('SELECT status FROM manual_actions WHERE id=?', (action_id,)).fetchone()[0]

    def test_release_deletes_only_the_own_claim_and_marks_the_journal(self):
        action = self.store.reserve(pending(), 'Hi', approved=True)
        self.assertTrue(self.claims(self.store, '200'))
        self.assertTrue(self.store.release_reservation(pending()))
        self.assertEqual(self.claims(self.store, '200'), [])
        self.assertEqual(self.status(action), 'not-invoked')
        # The shared registry is clean for every OTHER installation: the peer
        # is eligible again and will be greeted by another port.
        self.assertFalse(self.other.peer_claimed(pending()))

    def test_release_is_idempotent_and_ignores_finished_rows(self):
        action = self.store.reserve(pending(), 'Hi', approved=True)
        self.assertTrue(self.store.release_reservation(pending()))
        self.assertFalse(self.store.release_reservation(pending()))
        self.assertEqual(self.claims(self.store, '200'), [])

    def test_release_after_finish_is_a_no_not_found(self):
        action = self.store.reserve(pending(), 'Hi', approved=True)
        self.store.finish(action, dict(send_attempted=False, send_handler_returned=False))
        self.assertFalse(self.store.release_reservation(pending()))
        self.assertEqual(self.status(action), 'not-invoked')

    def test_release_finds_a_row_whose_rowid_was_never_seen(self):
        # The lost-COMMIT shape: both rows landed server-side but the client
        # never received an id. Matching by account+peer still finds it.
        with self.store.connection() as db:
            db.execute('INSERT INTO mumu_greeting_claims(peer,device,account) VALUES(?,?,?)',
                       ('200', self.store.device_owner, '100'))
            db.execute("INSERT INTO manual_actions(account,peer,initial_chat,text_hash,confirmed,status) "
                       "VALUES('100','200','-1','x',1,'reserved-unknown')")
        self.assertTrue(self.store.release_reservation(pending()))
        self.assertEqual(self.claims(self.store, '200'), [])

    def test_release_rejects_invalid_pending(self):
        from conversation_engine import PolicyError
        action = self.store.reserve(pending(), 'Hi', approved=True)
        with self.assertRaises(PolicyError):
            self.store.release_reservation(pending(peer=None))
        # Nothing was released by the rejected call.
        self.assertTrue(self.claims(self.store, '200'))

    def test_release_never_touches_another_port_reservation(self):
        action = self.store.reserve(pending(), 'Hi', approved=True)
        self.assertTrue(self.store.release_reservation(pending()))
        # Another installation greets the peer while our journal row stays.
        self.other.reserve(pending(account='101'), 'Their greeting', approved=True)
        self.assertFalse(self.store.release_reservation(pending()))
        self.assertEqual(self.claims(self.other, '200'), [('b' * 32 + ':5585',)])

    def test_released_peer_stays_deduped_while_claimed(self):
        action = self.store.reserve(pending(), 'Hi', approved=True)
        with self.assertRaises(Exception):
            self.other.reserve(pending(account='101'), 'Their greeting', approved=True)
        self.store.release_reservation(pending())
        # Eligible again after the release.
        self.other.reserve(pending(account='101'), 'Their greeting', approved=True)


class MonitorReleasePaths(unittest.TestCase):
    """monitor(): a committed reservation never outlives a proven no-ACK path."""

    def test_done_race_after_reserve_releases_the_claim(self):
        store = MagicMock(); store.mumu_shared_claims = True
        script, state, failures, run, done = wired(store)
        # The cycle ends exactly between the committed reserve and the ACK.
        def reserve_then_done(*a, **k):
            done.is_set.side_effect = lambda: True
            return 17
        store.reserve = MagicMock(side_effect=reserve_then_done)
        run()
        store.release_reservation.assert_called_once()
        self.assertEqual(state['action_id'], None)
        self.assertTrue(state['reservation_released'])
        self.assertFalse(failures)
        script.exports_sync.cohortack.assert_not_called()
        script.exports_sync.cancel.assert_not_called()

    def test_cancelled_after_reserve_releases_the_claim(self):
        store = MagicMock(); store.mumu_shared_claims = True
        flag = {'stop': False}
        def reserve_then_stop(*a, **k):
            flag['stop'] = True
            return 17
        store.reserve = MagicMock(side_effect=reserve_then_stop)
        script, state, failures, run, done = wired(store, cancelled=lambda: flag['stop'])
        run()
        store.release_reservation.assert_called_once()
        self.assertEqual(state['action_id'], None)
        self.assertFalse(failures)
        script.exports_sync.cohortack.assert_not_called()

    def test_stale_ack_releases_the_claim_and_fails_closed(self):
        store = MagicMock(); store.mumu_shared_claims = True
        store.reserve = MagicMock(return_value=17)
        script, state, failures, run, done = wired(store, ack=False)
        run()
        store.release_reservation.assert_called_once()
        self.assertEqual(state['action_id'], None)
        self.assertTrue(failures)
        self.assertEqual(state['authorization_checkpoint'], 'profile-ack')
        script.exports_sync.cancel.assert_called_once()

    def test_done_race_during_reserve_window_attempts_the_release(self):
        # A lost COMMIT may have left the claim row even though the window
        # raised: the device-scoped delete is safe either way.
        store = MagicMock(); store.mumu_shared_claims = True
        script, state, failures, run, done = wired(store)
        def refuse_then_done(*a, **k):
            done.is_set.side_effect = lambda: True
            raise transient()
        store.reserve = MagicMock(side_effect=refuse_then_done)
        run()
        store.release_reservation.assert_called_once()
        self.assertTrue(state['peer_check_deferred'])
        self.assertFalse(failures)
        script.exports_sync.cohortack.assert_not_called()

    def test_window_exhaustion_without_a_commit_never_releases(self):
        store = MagicMock(); store.mumu_shared_claims = True
        store.reserve = MagicMock(side_effect=[transient() for _ in range(5)])
        script, state, failures, run, done = wired(store)
        run()
        store.release_reservation.assert_not_called()
        self.assertNotIn('action_id', state)
        self.assertTrue(state['peer_check_deferred'])
        self.assertTrue(state['shared_peer_skipped'])

    def test_failed_release_keeps_the_pre_1381_shape(self):
        # A saturated pooler may refuse the release too: the reservation then
        # stays held exactly as before, finish() records 'not-invoked' and no
        # duplicate send is possible. The monitor never fails on it.
        store = MagicMock(); store.mumu_shared_claims = True
        store.release_reservation = MagicMock(side_effect=[transient() for _ in range(3)])
        script, state, failures, run, done = wired(store)
        def reserve_then_done(*a, **k):
            done.is_set.side_effect = lambda: True
            return 17
        store.reserve = MagicMock(side_effect=reserve_then_done)
        run()
        self.assertEqual(state['action_id'], 17)   # finish() still records it.
        self.assertNotIn('reservation_released', state)
        self.assertFalse(failures)

    def test_monitor_releases_on_the_real_store(self):
        # End-to-end on a real SharedStore: the claim is inserted by reserve()
        # and deleted by the release path, with the journal marked not-invoked.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from mumu_store import SharedStore
        base = Path(self.temp.name)
        store = SharedStore(base / 'assistant.sqlite3', base / 'old',
                            device_port=5585, installation_id='a' * 32)
        real_reserve = store.reserve
        action_box = {}
        script, state, failures, run, done = wired(store)
        def reserve_then_done(p, text, approved=True):
            action_box['id'] = real_reserve(p, text, approved=approved)
            done.is_set.side_effect = lambda: True
            return action_box['id']
        store.reserve = reserve_then_done
        run()
        self.assertFalse(failures)
        self.assertTrue(state['reservation_released'])
        with store.read_connection() as db:
            claims = db.execute('SELECT device FROM mumu_greeting_claims WHERE peer=?', ('200',)).fetchall()
            status = db.execute('SELECT status FROM manual_actions WHERE id=?', (action_box['id'],)).fetchone()
        self.assertEqual(claims, [])
        self.assertEqual(status[0], 'not-invoked')


class TerminalAuthority(unittest.TestCase):
    """The reserve transaction alone answers the terminal question."""

    def test_terminal_block_is_caught_by_reserve_on_a_real_store(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from mumu_store import SharedStore
        base = Path(self.temp.name)
        store = SharedStore(base / 'assistant.sqlite3', base / 'old',
                            device_port=5585, installation_id='a' * 32)
        other = SharedStore(base / 'assistant.sqlite3', base / 'old',
                            device_port=5585, installation_id='b' * 32)
        # A contact receipt without a greeting claim (legacy backfill shape).
        with other.connection() as db:
            other.record_peer_outcome(db, dict(account='100', peer='200', chat='300'), 'contact-received')
        script, state, failures, run, done = wired(store)
        run()
        self.assertFalse(failures)
        self.assertTrue(state['shared_peer_skipped'])
        script.exports_sync.cohortack.assert_called_once()
        self.assertTrue(script.exports_sync.cohortack.call_args.args[0].get('skip'))

    def test_inspect_report_carries_the_release_flag(self):
        source = (Path(__file__).resolve().parents[1] / 'assistant_pass.py').read_text(encoding='utf-8')
        self.assertIn("reservation_released=state.get('reservation_released', False)", source)

    def test_profiles_report_counts_released_reservations(self):
        import assistant_profiles
        self.assertEqual(assistant_profiles.report(5)['reservations_released'], 0)
        source = (Path(__file__).resolve().parents[1] / 'assistant_profiles.py').read_text(encoding='utf-8')
        self.assertIn("value.get('reservation_released')", source)


class PreflightRetryWindow(unittest.TestCase):
    """adb_preflight_retry: transport/boot shapes ride out, the rest stops."""

    def adb(self, check, reason):
        return MagicMock(adb_events=[dict(check=check, status='failed', reason=reason, return_code=0)])

    def attempt(self, adb, failures, *, delays=(0, 0, 0), stopped=lambda: False):
        messages = []
        with patch('target_only.preflight', side_effect=failures), \
             patch.object(mumu_worker, 'ADB_PREFLIGHT_RETRY_DELAYS', delays):
            mumu_worker.adb_preflight_retry(adb, stopped, messages.append, delays=delays, pause=lambda s: None)
        return messages

    def test_transport_failure_is_retried_until_success(self):
        from test_device import TestError
        adb = self.adb('test-state', 'device-offline')
        messages = self.attempt(adb, [TestError('down'), TestError('down'), '11111111-1111-1111-1111-111111111111'])
        self.assertEqual(len(messages), 2)
        self.assertIn('попытка 2 из 4', messages[0])
        self.assertIn('попытка 3 из 4', messages[1])

    def test_connection_refused_is_retried(self):
        from test_device import TestError
        adb = self.adb('test-connect', 'connection-refused')
        self.attempt(adb, [TestError('refused'), '11111111-1111-1111-1111-111111111111'])

    def test_boot_pending_is_retried(self):
        from test_device import TestError
        adb = self.adb('test-boot-completed', 'unexpected-response')
        self.attempt(adb, [TestError('not booted'), '11111111-1111-1111-1111-111111111111'])

    def test_missing_package_is_never_retried(self):
        from test_device import TestError
        adb = self.adb('test-package-presence', 'unexpected-response')
        with patch('target_only.preflight', side_effect=TestError('no package')) as probe, \
             patch.object(mumu_worker, 'ADB_PREFLIGHT_RETRY_DELAYS', (0, 0, 0)):
            with self.assertRaises(Exception):
                mumu_worker.adb_preflight_retry(adb, lambda: False, lambda _ : None,
                                                delays=(0, 0, 0), pause=lambda s: None)
        self.assertEqual(probe.call_count, 1)

    def test_unauthorized_is_never_retried(self):
        from test_device import TestError
        adb = self.adb('test-state', 'device-unauthorized')
        with patch('target_only.preflight', side_effect=TestError('unauthorized')) as probe:
            with self.assertRaises(Exception):
                mumu_worker.adb_preflight_retry(adb, lambda: False, lambda _ : None,
                                                delays=(0, 0), pause=lambda s: None)
        self.assertEqual(probe.call_count, 1)

    def test_null_evidence_is_never_retried(self):
        from test_device import TestError
        adb = MagicMock(adb_events=[dict(check='test-state', status='passed', reason='none', return_code=0)])
        with patch('target_only.preflight', side_effect=TestError('mystery')) as probe:
            with self.assertRaises(Exception):
                mumu_worker.adb_preflight_retry(adb, lambda: False, lambda _ : None,
                                                delays=(0, 0), pause=lambda s: None)
        self.assertEqual(probe.call_count, 1)

    def test_exhaustion_raises_the_last_evidenced_failure(self):
        from test_device import TestError
        adb = self.adb('test-state', 'device-offline')
        last = TestError('still down')
        with patch('target_only.preflight', side_effect=[TestError('down'), TestError('down'), last]) as probe:
            with self.assertRaises(TestError) as raised:
                mumu_worker.adb_preflight_retry(adb, lambda: False, lambda _ : None,
                                                delays=(0, 0), pause=lambda s: None)
        self.assertIs(raised.exception, last)
        self.assertEqual(probe.call_count, 3)  # 1 + two delays.
        evidence = getattr(last, '_dvk_failure')
        self.assertEqual(evidence['adb_check'], 'test-state')
        self.assertEqual(evidence['adb_reason'], 'device-offline')

    def test_stop_aborts_the_window_with_the_last_failure(self):
        from test_device import TestError
        adb = self.adb('test-state', 'device-offline')
        last = TestError('down')
        with patch('target_only.preflight', side_effect=[last]) as probe:
            with self.assertRaises(TestError) as raised:
                mumu_worker.adb_preflight_retry(adb, lambda: True, lambda _ : None,
                                                delays=(0, 0), pause=lambda s: None)
        self.assertIs(raised.exception, last)
        self.assertEqual(probe.call_count, 1)

    def test_retry_window_is_bounded_and_jittered(self):
        self.assertEqual(mumu_worker.ADB_PREFLIGHT_RETRY_DELAYS, (3.0, 7.0, 15.0))
        source = (Path(__file__).resolve().parents[1] / 'mumu_worker.py').read_text(encoding='utf-8')
        self.assertIn('uniform(1.0, 1.6)', source)


class PortMessages(unittest.TestCase):
    """Any local ADB port is valid; crossings and failures are named honestly."""

    def test_any_port_in_the_valid_range_is_accepted(self):
        from mumu_common import port, MumuError
        for value in (5585, 5555, 16384, 40000, 61000, '5591'):
            self.assertEqual(port(value), int(value))
        for value in (5037, 27042, 1023, 65536, 'abc', ''):
            with self.assertRaises(MumuError):
                port(value)

    def test_multi_port_messages_never_mention_the_legacy_device(self):
        source = (Path(__file__).resolve().parents[1] / 'target_only.py').read_text(encoding='utf-8')
        raises = [line.strip() for line in source.splitlines() if 'raise TestError(' in line]
        self.assertTrue(raises)
        for legacy in ('#4', '5563', 'тестовый MuMu', 'тестовое устройство', 'Тестовый Android'):
            for line in raises:
                self.assertNotIn(legacy, line)
        self.assertIn('MuMu на этом порту не подключается', source)

    def test_preflight_label_is_port_agnostic(self):
        from startup_failure import LABELS
        self.assertEqual(LABELS['adb-preflight'], 'Не удалось проверить подключение к MuMu этого порта.')

    def test_alias_crossing_is_named_as_a_crossing(self):
        source = (Path(__file__).resolve().parents[1] / 'mumu_worker.py').read_text(encoding='utf-8')
        self.assertIn('Два порта из списка подключаются к одному MuMu', source)

    def test_worker_keeps_the_no_direct_sleep_rule(self):
        source = (Path(__file__).resolve().parents[1] / 'mumu_worker.py').read_text(encoding='utf-8')
        self.assertNotIn('time.sleep', source)


if __name__ == '__main__':
    unittest.main()
