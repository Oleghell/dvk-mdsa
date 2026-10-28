"""Reports 498-507 (v1.3.74, dropmefiles W8VPRYkX) + the user's report: "I
resume a port and another one dies a couple of minutes later, sometimes on
the other PC."

Ten ports on one shared session pooler. Resuming any port starts a fresh
journal/inbox/profile burst against the same ~45 application slots, and the
OTHER ports' pre-send checks then pay for it:

* Seven ports died through transition-timeout at prepare-greeting: the
  pre-send window (37s of nominal pauses, ~59s jittered, plus per-attempt
  connect retries) outlived the native cycle's ABSOLUTE 90s deadline, the
  script died waiting for its own approval, the port burned ~two minutes of
  blind screen repair and stopped with recovery-unfinished (masked as
  unrecognized-diagnostic-code on 1.3.74).
* Ports 503/505 hard-stopped with journal-error at profile-peer-check: the
  transient error surfaced AFTER root() had returned (done set), so the defer
  was refused and the whole port died - although the check runs before any
  approval, reservation or send.
* Port 499 died at 'Unverified direct search return': the absolute timer
  fired while the final frame was still running, and the deferred finish
  rewrote the JUST-VERIFIED search return into navigation-stopped.

Fixes under test: a wall-clock deadline for the pre-send window, the
done-set swallow for pre-send transient checks, and the truthfulness guard
for deferred finishes. Synthetic only; no device, database or network."""
import unittest
from unittest.mock import MagicMock, patch

import assistant_pass as native
import uikit_navigation as navigation
from cloud_database import CloudDatabaseError


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


def run_monitor(peer, *, phase='peer', cancelled=lambda: False, done_set=False, flip_done=True):
    """Monitor with a done flag that the failing read flips itself.

    The flag turning True inside the action reproduces the real race: the
    native cycle's absolute deadline fires while the host is still retrying
    the shared-registry read, so the error surfaces after root() returned.
    """
    script = MagicMock(); script.exports_sync.cohortpending.return_value = pending()
    script.exports_sync.cohortack.return_value = True
    flag = {'done': done_set}
    done = MagicMock(); done.wait.return_value = False
    done.is_set.side_effect = lambda: flag['done']
    store = MagicMock(); store.mumu_shared_claims = True
    def peer_claimed(*args, **kwargs):
        if flip_done:
            flag['done'] = True
        raise peer() if callable(peer) else peer
    def peer_terminal(*args, **kwargs):
        if flip_done:
            flag['done'] = True
        raise peer() if callable(peer) else peer
    store.peer_claimed = peer_claimed if phase == 'peer' else MagicMock(return_value=False)
    store.peer_terminal = MagicMock(return_value=False)
    if phase == 'reserve':
        # v1.3.81: the reservation is the only live pre-send database step
        # left (the terminal read is gone), so the done-set race surfaces
        # here; a flailing reserve may still have committed its claim row.
        def flailing_reserve(*args, **kwargs):
            if flip_done:
                flag['done'] = True
            raise peer() if callable(peer) else peer
        store.reserve = flailing_reserve
    else:
        store.reserve = MagicMock(return_value=17)
    state = {}; failures = []
    with patch.object(native, 'SHARED_READ_RETRY_DELAYS', (0, 0)), \
         patch.object(native, 'RELEASE_RETRY_DELAYS', (0, 0)):
        native.monitor(script, store, 'Hi', lambda *a: True, done, cancelled, state, failures)
    return script, store, state, failures


class PreSendWindowDeadline(unittest.TestCase):
    """The 37s-of-pauses window could stretch past the native 90s budget."""

    def test_deadline_constant_fits_the_native_cycle_budget(self):
        self.assertEqual(native.SHARED_READ_DEADLINE_SECONDS, 40.0)
        # The worst jittered span of the window must still leave the verified
        # no-send Back its own share of the absolute 90s native deadline.
        self.assertLess(native.SHARED_READ_DEADLINE_SECONDS + 20.0, 90.0)

    def test_window_exhausts_by_wall_clock_before_all_attempts(self):
        ticks = iter([0.0, 25.0, 25.0, 25.0])
        pauses = []
        action = MagicMock(side_effect=transient())
        with self.assertRaises(CloudDatabaseError) as raised:
            native.shared_registry_read(action, lambda: False,
                                         pause=pauses.append, clock=lambda: next(ticks))
        # Elapsed 25s + 10s*1.6 worst-case jitter = 41s >= 40s: the third
        # pause is never taken, so exhaustion happens on attempt three.
        self.assertEqual(action.call_count, 3)
        self.assertEqual(pauses, [2.0, 5.0])
        self.assertEqual(raised.exception.code, 'cloud-database-unavailable')

    def test_fast_failures_still_use_the_full_attempt_budget(self):
        ticks = iter([0.0] * 10)
        action = MagicMock(side_effect=[transient() for _ in range(5)])
        with self.assertRaises(CloudDatabaseError):
            native.shared_registry_read(action, lambda: False,
                                         pause=lambda _: None, clock=lambda: next(ticks))
        self.assertEqual(action.call_count, 5)

    def test_post_pause_stop_raises_without_another_attempt(self):
        ticks = iter([0.0, 0.0, 5.0])
        action = MagicMock(side_effect=transient())
        stop = {'done': False}
        with self.assertRaises(CloudDatabaseError):
            native.shared_registry_read(action, lambda: stop['done'],
                                         pause=lambda _: stop.update(done=True),
                                         clock=lambda: next(ticks))
        # done flipped DURING the pause: no second database attempt.
        self.assertEqual(action.call_count, 1)

    def test_jitter_worst_case_is_part_of_the_bound(self):
        # Elapsed 33s + 5s*1.6 = 41s >= 40s: the second pause is refused even
        # though its nominal 5s would fit a naive 33+5 < 40 check.
        ticks = iter([0.0, 3.0, 33.0])
        pauses = []
        action = MagicMock(side_effect=transient())
        with self.assertRaises(CloudDatabaseError):
            native.shared_registry_read(action, lambda: False,
                                         pause=pauses.append, clock=lambda: next(ticks))
        self.assertEqual(pauses, [2.0])
        self.assertEqual(action.call_count, 2)


class DoneSetSwallow(unittest.TestCase):
    """Reports 503/505: the transient error surfaced after root() returned.

    1.3.79 (aPYyN7weMm): the claimed-peer pre-check now reads the pass-start
    snapshot instead of the shared registry, so this done-set race can only
    surface on the remaining LIVE pre-send read - the post-reserve terminal
    outcome check. Its swallow/deferral semantics are unchanged.
    """

    def test_peer_check_is_snapshot_based_and_immune_to_the_done_race(self):
        # A flailing peer_claimed registry is never consulted: the snapshot
        # pre-check answers before any database dependency, and the cycle
        # proceeds to approval/reserve/ack without a defer or a failure.
        calls = []

        def flailing_registry(*args, **kwargs):
            calls.append(1)
            raise transient()

        script, store, state, failures = run_monitor(flailing_registry)
        self.assertFalse(calls)
        self.assertFalse(failures)
        self.assertFalse(state.get('peer_check_deferred'))
        store.reserve.assert_called_once()
        script.exports_sync.cohortack.assert_called_once()
        script.exports_sync.cancel.assert_not_called()

    def test_terminal_check_transient_after_done_is_swallowed(self):
        # v1.3.81: the same race one step later - the reservation window
        # raises after root() returned. The port survives, no ACK is sent,
        # and the best-effort release returns a possibly-committed claim to
        # the eligible pool instead of keeping it "durable unknown".
        script, store, state, failures = run_monitor(transient, phase='reserve')
        self.assertFalse(failures)
        self.assertTrue(state['peer_check_deferred'])
        store.release_reservation.assert_called_once()
        script.exports_sync.cohortack.assert_not_called()
        script.exports_sync.cancel.assert_not_called()

    def test_non_transient_after_done_keeps_the_hard_gate(self):
        script, store, state, failures = run_monitor(permission, phase='reserve')
        self.assertTrue(failures)
        self.assertEqual(state['authorization_checkpoint'], 'profile-reserve')
        script.exports_sync.cancel.assert_called_once()

    def test_cancelled_after_done_still_raises(self):
        flag = {'stop': False}

        def stop_during_read():
            flag['stop'] = True
            return transient()

        script, store, state, failures = run_monitor(
            stop_during_read, phase='reserve', cancelled=lambda: flag['stop'])
        self.assertTrue(failures)
        self.assertFalse(state.get('peer_check_deferred'))
        script.exports_sync.cancel.assert_called_once()

    def test_alive_cycle_still_defers_with_a_verified_skip(self):
        script, store, state, failures = run_monitor(
            lambda: transient(), phase='reserve', done_set=False, flip_done=False)
        self.assertFalse(failures)
        self.assertTrue(state['peer_check_deferred'])
        self.assertTrue(state['shared_peer_skipped'])
        store.release_reservation.assert_not_called()
        self.assertEqual(script.exports_sync.cohortack.call_args.args[0].get('skip'), True)


class DeferredFinishTruthfulness(unittest.TestCase):
    """Report 499: a verified cycle completed inside the frame the timer hit."""

    def test_pending_finish_only_stops_a_running_navigation(self):
        self.assertEqual(navigation.FUNCTION.count(
            "if(r.navigation.stage==='navigation-running'){r.navigation.stage='navigation-stopped';"
            "r.navigation.error=navState.stop||'observer-stopped';}"), 1)

    def test_cancel_during_a_frame_only_stops_a_running_navigation(self):
        self.assertEqual(navigation.FUNCTION.count(
            "if(r.navigation.stage==='navigation-running'){r.navigation.stage='navigation-stopped';"
            "r.navigation.error='cancelled';}"), 1)

    def test_the_timer_itself_already_guards_the_same_way(self):
        self.assertIn(
            "navState.stop='transition-timeout';if(r.navigation.stage==='navigation-running')"
            "{r.navigation.stage='navigation-stopped';r.navigation.error='transition-timeout';}",
            navigation.FUNCTION)

    def test_499_report_shapes(self):
        # The verified search return validates as a success; the corrupted
        # shape of port 499 (the same verified return with a stopped stage)
        # is still rejected - proving the truthfulness guard in the observer
        # is what makes that shape impossible to produce in the first place.
        import chat_batch
        from test_chat_batch import cycle

        def report(stage, error='none'):
            value = cycle()
            n = value['navigation']
            n.update(chat_return_route='search', close_attempted=False, close_completed=False,
                     controller_path=['root', 'dv-navigation', 'main-tabs', 'search'],
                     stage=stage, error=error)
            return value

        chat_batch.validate(report('navigation-ready'))
        with self.assertRaises(ValueError) as raised:
            chat_batch.validate(report('navigation-stopped', 'transition-timeout'))
        self.assertEqual(str(raised.exception), 'Unverified direct search return')


class RecoveringPortsStayRecoverable(unittest.TestCase):
    """The seven transition-timeout ports stop in a recoverable shape."""

    def test_transition_timeout_stop_is_recoverable(self):
        from mumu_recovery import recoverable
        report = dict(status='stopped', reason='initial-pass-stopped', initial_run=dict(
            status='stopped', reason='profiles-not-finished', profiles=dict(
                status='profiles-stopped', reason='profile-check-stopped',
                host_failure='state-check-failed', host_checkpoint='profile-verify',
                last_profile_diagnostics=dict(
                    stage='navigation-stopped', error='transition-timeout',
                    phase='prepare-greeting', frames=37, managed_calls=2424,
                    send_attempted=False, send_handler_returned=False,
                    chat_identity_verified=True, search_verified=True,
                    open_attempted=True, open_completed=True,
                    chat_open_attempted=True, chat_open_completed=True))))
        self.assertTrue(recoverable(report))


if __name__ == '__main__':
    unittest.main()
