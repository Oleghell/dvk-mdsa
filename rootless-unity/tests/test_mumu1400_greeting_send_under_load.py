"""1.3.99 regression: the greeting itself must survive twelve ports at once.

Reported: «еще проверь чтобы даже если 12 портов было в работе одновременно,
то приветственные сообщение отправлялись а не просто висели в диалоге и потом
выходили». The ACKed submit-greeting frame carries the whole re-verified
context plus the send invocation inside ONE 100ms native tick; under a loaded
multi-port MuMu host that tick regularly blew its budget exactly at the send
call - which the old latch ordering recorded as 'attempted-unknown' even
though the invocation never ran. The peer then kept a committed claim with no
greeting, the chat sat open until recovery backed out of it («висели в
диалоге и потом выходили»), and the port parked in recovery rounds.

Three closes, mirroring the reply path's own submission fix:
* the greeting's budget/stop guards now run BEFORE the send latch
  (chat_send_probe.SEND), so an exhausted tick fails as NOT-invoked;
* the ACKed submit frame gets its OWN bounded fresh-frame budget
  (submit_frame_retries, 8) that the read phases cannot starve;
* its exhaustion is a verified close-and-skip (submit-frame-budget) - the
  pass continues, and the committed claim is returned to the eligible pool
  (release_acknowledged_no_send) so another port can still greet the peer.

Synthetic only; no device and no live services.
"""
import copy
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assistant_pass
import assistant_profiles as profiles
import chat_send_probe
from assistant_profile_read import SUBMIT_FRAME_RETRY_LIMIT
from assistant_store import Store
from test_chat_batch import cycle
from test_inbox_profiles import Config


def greeted():
    """A complete validator-clean greeting cycle (the happy path)."""
    value = cycle()
    value['navigation'].update(cycle_timeout_ms=90000,
        profile_read_budget_retries=0, profile_ready_waits=0,
        greeting_frame_splits=1, submit_frame_retries=0)
    return value


def submit_budget_exhausted(extra=None):
    """The ACKed submit frame exhausted its dedicated budget without a send.

    The two-sample empty-history read completed and split (splits=1), the
    reservation was approved and ACKed, but no fresh frame could fit the send
    invocation: both send flags stay false, the dedicated counter saturated,
    and the chat was closed with the same verified evidence every other skip
    uses instead of parking the port on the open dialog.
    """
    value = greeted(); n = value['navigation']
    n.update(profile_read_skipped=True, profile_read_skip_reason='submit-frame-budget',
        submit_frame_retries=SUBMIT_FRAME_RETRY_LIMIT,
        history_status='not-ready', message_count=None, samples=0,
        send_attempted=False, send_handler_returned=False,
        greeting_variant=None, messages_sent=0,
        wait_reason='none')
    if extra:
        n.update(extra)
    return value


class NativeSource(unittest.TestCase):
    """The composed one-profile script orders guards, latch and invocation."""

    def test_greeting_guards_precede_the_latch_and_the_invocation(self):
        s = chat_send_probe.build(0)
        guard = s.index("if(deadline<Date.now())fail('frame-budget');")
        latch = s.index('greetingAttempted=true')
        invoke = s.index('call(s.send,current,args)')
        self.assertLess(guard, latch)
        self.assertLess(latch, invoke)
        # the guards run after the last identity/screen recheck, never before it
        self.assertLess(s.index("!checkView(current))fail('screen-not-ready');"), guard)
        self.assertIn('if(state.stop!==null)fail(state.stop);', s)
        self.assertIn("if(fixedCancellationRequested)fail('cancelled');", s)

    def test_batch_greeting_keeps_the_same_ordering(self):
        s = assistant_pass.build('Привет')
        guard = s.index("if(deadline<Date.now())fail('frame-budget');")
        latch = s.index('batchSent.add(batchCandidateKey)')
        invoke = s.index('call(s.send,current,args)')
        self.assertLess(guard, latch)
        self.assertLess(latch, invoke)
        self.assertLess(s.index('n.greeting_variant=batchVariants[batchAttempts-1];'), invoke)

    def test_acknowledged_submit_frame_has_its_own_budget_and_skip(self):
        s = assistant_pass.build('Привет')
        self.assertIn("if(e==='frame-budget'&&n.phase==='submit-greeting'&&cohortApproved!==null&&", s)
        self.assertIn('n.submit_frame_retries<' + str(SUBMIT_FRAME_RETRY_LIMIT) + '){', s)
        self.assertIn('n.submit_frame_retries===' + str(SUBMIT_FRAME_RETRY_LIMIT) + '){', s)
        self.assertIn("const reason='submit-frame-budget';", s)
        # the exhaustion routes into the SAME verified close as every skip
        start = s.index("const reason='submit-frame-budget';")
        end = s.index('if(e===', start)
        self.assertIn("n.profile_read_skipped=true;n.profile_read_skip_reason=reason;", s[start:end])
        self.assertIn("n.phase='close-chat';state.nextActionAt=Date.now();return;", s[start:end])
        # the shared read budget still exists and still guards the read phases
        self.assertIn('n.profile_read_budget_retries<4){', s)


class ValidatorContracts(unittest.TestCase):
    def test_submit_budget_exhausted_cycle_validates(self):
        value = submit_budget_exhausted()
        old = copy.deepcopy(value)
        self.assertIs(assistant_pass.validate(value), value)
        self.assertEqual(value, old)

    def test_forged_submit_budget_evidence_is_rejected(self):
        for key, bad in (('submit_frame_retries', 7), ('submit_frame_retries', 9),
                         ('submit_frame_retries', True), ('submit_frame_retries', None),
                         ('greeting_frame_splits', 0), ('send_attempted', True),
                         ('send_handler_returned', True), ('chat_identity_verified', False),
                         ('chat_return_verified', False), ('chat_back_completed', False),
                         ('history_status', 'empty'), ('samples', 2), ('message_count', 0),
                         ('profile_read_skipped', False), ('profile_read_skip_reason', 'frame-budget'),
                         ('profile_read_skip_reason', 'PRIVATE')):
            with self.subTest(key=key, bad=bad):
                with self.assertRaises(ValueError):
                    assistant_pass.validate(submit_budget_exhausted({key: bad}))

    def test_the_budget_skip_is_exempt_from_the_wait_reason_match(self):
        # the skip fires from a frame-budget error, never from a wait
        # condition - exactly like the pre-existing 'frame-budget' form
        value = submit_budget_exhausted({'wait_reason': 'history-loading'})
        self.assertIs(assistant_pass.validate(value), value)

    def test_missing_submit_counter_is_rejected(self):
        value = submit_budget_exhausted()
        del value['navigation']['submit_frame_retries']
        with self.assertRaises(ValueError):
            assistant_pass.validate(value)


class ContinueAfterExhaustedSubmitFrame(unittest.TestCase):
    """The reported symptom: the port sat in the open dialog, then exited."""

    def go(self, values, *, approve_greeting=False, errors=True, limit=1, notifier=None):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 's.sqlite3', Path(folder) / 'legacy')
            profiles.Session(store).set('city', 'Псков')
            calls = []
            def next_cycle(adb, folder_, text, ask, cancelled, store=None):
                calls.append(1)
                if approve_greeting:
                    # the exhaustion skip exists ONLY after the authorization
                    # actually ran: the cycle asks, the host reserves and ACKs
                    ask(dict(attempt=1, account='100', peer='200', chat='-1', variant=0),
                        text, cancelled)
                return values[len(calls) - 1]
            settings = SimpleNamespace(adb='fake', folder=folder, errors_enabled=errors)
            out = profiles.walk(settings, threading.Event(), MagicMock(return_value=True),
                                lambda _: None, store, cycle=next_cycle, config=Config(),
                                limit=limit, recovery_notifier=notifier)
            return out, len(calls)

    def test_exhausted_submit_frame_skips_and_the_next_greeting_still_sends(self):
        out, calls = self.go([submit_budget_exhausted(), greeted()], approve_greeting=True)
        self.assertEqual((out['status'], calls), ('profiles-completed', 2))
        self.assertEqual(out['skipped_submit_frame_budget'], 1)
        self.assertEqual(out['qualified_profiles'], 1)
        self.assertEqual(out['send_attempts'], 1)
        self.assertEqual(out['reason'], 'profile-limit')

    def test_the_skip_without_the_authorization_stops_the_pass(self):
        # the exact inverse of every other skip form: no ACK, no skip
        out, calls = self.go([submit_budget_exhausted()])
        self.assertEqual(calls, 1)
        self.assertEqual(out['status'], 'profiles-stopped')
        self.assertEqual(out['reason'], 'return-not-verified')

    def test_forged_submit_budget_skip_stops_instead_of_continuing(self):
        for change in ({'submit_frame_retries': 7}, {'chat_return_verified': False},
                       {'greeting_frame_splits': 0}):
            with self.subTest(change=change):
                out, calls = self.go([submit_budget_exhausted(change)], approve_greeting=True)
                self.assertEqual(calls, 1)
                self.assertEqual(out['status'], 'profiles-stopped')
                self.assertEqual(out['reason'], 'return-not-verified')
        # an attempted-but-unreturned send on a skip row is the unknown-send
        # guard, which fires before the skip branch can ever be reached
        out, calls = self.go([submit_budget_exhausted({'send_attempted': True})], approve_greeting=True)
        self.assertEqual(calls, 1)
        self.assertEqual((out['status'], out['reason']), ('profiles-stopped', 'send-outcome-unknown'))

    def test_three_consecutive_exhaustions_stop_the_pass_bounded(self):
        out, calls = self.go([submit_budget_exhausted() for _ in range(3)], approve_greeting=True)
        self.assertEqual((out['status'], out['reason']), ('profiles-stopped', 'profile-recovery-limit'))
        self.assertEqual(calls, 3)
        self.assertEqual(out['skipped_submit_frame_budget'], 3)

    def test_recovery_events_report_the_reason_and_the_counter(self):
        notified = []
        def notify(event):
            notified.append(copy.deepcopy(event)); return 'accepted'
        out, _ = self.go([submit_budget_exhausted(), greeted()],
                         approve_greeting=True, notifier=notify)
        self.assertEqual(out['status'], 'profiles-completed')
        self.assertEqual(out['recovery_events'][0]['reason'], 'submit-frame-budget')
        self.assertEqual(out['recovery_events'][0]['diagnostic']['submit_frame_retries'],
                         SUBMIT_FRAME_RETRY_LIMIT)
        self.assertEqual(out['recovery_events'][0]['diagnostic']['greeting_frame_splits'], 1)
        self.assertTrue(out['recovery_events'][0]['continue_work'])


class ReleaseAcknowledgedClaim(unittest.TestCase):
    """The ACKed claim returns to the eligible pool on the proven no-send."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from mumu_store import SharedStore
        base = Path(self.temp.name)
        self.store = SharedStore(base / 'assistant.sqlite3', base / 'old',
                                 device_port=5555, installation_id='a' * 32)
        self.pending = dict(attempt=1, account='100', peer='200', chat='-1', variant=0)

    def claims(self, peer):
        with self.store.read_connection() as db:
            return db.execute('SELECT device FROM mumu_greeting_claims WHERE peer=?', (peer,)).fetchall()

    def journal(self, peer):
        with self.store.read_connection() as db:
            return db.execute('SELECT status FROM manual_actions WHERE peer=?', (peer,)).fetchall()

    def test_acknowledged_claim_is_released_after_the_exhaustion_skip(self):
        self.store.reserve(self.pending, 'Привет', approved=True)
        self.assertEqual(len(self.claims('200')), 1)
        state = {'acknowledged': dict(self.pending)}
        navigation = dict(submit_budget_exhausted()['navigation'])
        with self.patched_delays():
            self.assertTrue(assistant_pass.release_acknowledged_no_send(
                self.store, state, navigation, lambda: False))
        self.assertEqual(self.claims('200'), [])
        self.assertTrue(state['reservation_released'])
        # the journal row keeps its audit trail as a finished no-send
        self.assertEqual(self.journal('200'), [('not-invoked',)])

    def test_only_the_exhaustion_skip_releases(self):
        self.store.reserve(self.pending, 'Привет', approved=True)
        for navigation in (
            dict(send_attempted=False, send_handler_returned=False,
                 profile_read_skip_reason='frame-budget'),
            dict(send_attempted=False, send_handler_returned=False,
                 profile_read_skip_reason='input-disabled'),
            dict(send_attempted=False, send_handler_returned=False,
                 profile_read_skip_reason='none'),
            dict(send_attempted=True, send_handler_returned=True,
                 profile_read_skip_reason='submit-frame-budget'),
            dict(send_attempted=False, send_handler_returned=False,
                 profile_read_skip_reason='submit-frame-budget'),
            dict(send_attempted=False, send_handler_returned=False,
                 profile_read_skip_reason='submit-frame-budget', submit_frame_retries=7),
            None,
        ):
            with self.subTest(navigation=navigation):
                state = {'acknowledged': dict(self.pending)}
                with self.patched_delays():
                    self.assertFalse(assistant_pass.release_acknowledged_no_send(
                        self.store, state, navigation, lambda: False))
                self.assertFalse(state.get('reservation_released', False))
        # the reason, BOTH send flags and the saturated counter are required
        # together; the claim survives every one of them
        self.assertEqual(len(self.claims('200')), 1)

    def test_no_acknowledged_reservation_never_releases(self):
        self.assertFalse(assistant_pass.release_acknowledged_no_send(
            self.store, {}, submit_budget_exhausted()['navigation'], lambda: False))

    def test_transport_failure_is_best_effort_and_keeps_the_claim(self):
        from cloud_database import CloudDatabaseError
        self.store.reserve(self.pending, 'Привет', approved=True)
        broken = MagicMock()
        broken.release_reservation.side_effect = CloudDatabaseError('cloud-database-unavailable')
        state = {'acknowledged': dict(self.pending)}
        with self.patched_delays():
            self.assertFalse(assistant_pass.release_acknowledged_no_send(
                broken, state, submit_budget_exhausted()['navigation'], lambda: False))
        self.assertFalse(state.get('reservation_released', False))
        self.assertEqual(len(self.claims('200')), 1)

    @contextmanager
    def patched_delays(self):
        with patch.object(assistant_pass, 'RELEASE_RETRY_DELAYS', (0, 0)):
            yield


if __name__ == '__main__':
    unittest.main()
