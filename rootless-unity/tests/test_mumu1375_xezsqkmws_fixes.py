"""Reports 494-497 (xEZsQkmWS): frozen-screen read must not stop the port and
recovery-unfinished must stay visible in the closed Telegram JSON projection.

Report 494 (v1.3.74): ReadStopped frame-budget at read_checkpoint=identity with
identity_checkpoint=not-checked - the identity getters never ran - stopped the
initial inbox pass and recoverable() blocked the read-only repair as an
unverified host failure, killing the port. The same empty shape now rides the
bounded budget retry, defers the chat on exhaustion and permits read-only
recovery. Reports 495 (cloud connect on profile-peer-check) and 497
(city-not-found with a single candidate) were already covered by 1.3.74/rotation
recovery; report 496's masked top reason is unmasked here.
"""
import json, unittest

import assistant_history_wait as history
from assistant_error_notify import KNOWN, diagnostic_json, reasons
from one_chat_device import ReadStopped, verified_identity_budget
from test_inbox_profiles import Base, WHO, nav, snap, msg


def frozen494(**changes):
    """Exact report 494 evidence: the emptiest interrupted observation."""
    value = dict(stage='navigation-stopped', metadata_checkpoint='ready', read_checkpoint='identity',
                 identity_checkpoint='not-checked', scalar_checkpoint='not-read', scalar_state='not-read',
                 wait_reason='none', frames=1, managed_calls=33, message_kind='not-read',
                 message_direction='not-read', message_slot=-1)
    value.update(changes)
    return ReadStopped('frame-budget', value)


class FrozenClassification(unittest.TestCase):
    def test_report_494_shape_is_an_interrupted_read_not_a_host_failure(self):
        good = dict(error='frame-budget', **frozen494().diagnostic)
        self.assertTrue(history.verified_read_budget(good))
        self.assertTrue(verified_identity_budget(good))
        transition = dict(good, error='transition-timeout')
        self.assertTrue(verified_identity_budget(transition))
        self.assertTrue(history.verified_read_budget(transition))

    def test_near_misses_never_match_the_recovery_evidence_gate(self):
        good = dict(error='frame-budget', **frozen494().diagnostic)
        for changes in (dict(error='identity-changed'), dict(error='identity-not-bound'),
                        dict(error='wrong-screen'), dict(error='call-limit'),
                        dict(identity_checkpoint='initial-ids'), dict(identity_checkpoint='saved-binding'),
                        dict(scalar_checkpoint='peer-id'), dict(scalar_state='zero'),
                        dict(read_checkpoint='not-checked'), dict(read_checkpoint='sample'),
                        dict(metadata_checkpoint='base'), dict(wait_reason='history-loading'),
                        dict(message_slot=0), dict(message_kind='text'),
                        dict(frames=1000001), dict(managed_calls=1000001),
                        dict(frames=-1), dict(managed_calls=-1)):
            value = dict(good, **changes)
            self.assertFalse(verified_identity_budget(value), changes)

    def test_a_completely_frozen_first_tick_is_still_an_interrupted_observation(self):
        dead = dict(error='frame-budget', **dict(frozen494().diagnostic, frames=0, managed_calls=0))
        self.assertTrue(verified_identity_budget(dead))
        self.assertTrue(history.verified_read_budget(dead))

    def test_budget_gate_still_rejects_unbounded_or_partial_shapes(self):
        good = dict(error='frame-budget', **frozen494().diagnostic)
        for changes in (dict(error='identity-changed'), dict(error='identity-not-bound'),
                        dict(error='wrong-screen'), dict(error='call-limit'),
                        dict(identity_checkpoint='saved-binding'), dict(scalar_state='zero'),
                        dict(metadata_checkpoint='base'), dict(wait_reason='history-loading'),
                        dict(read_checkpoint='sample')):
            self.assertFalse(history.verified_read_budget(dict(good, **changes)), changes)

    def test_report_516_pre_checkpoint_freeze_is_now_an_interrupted_read(self):
        # Reports aPYyN7weMm (monitor 516, v1.3.78): the frame budget expired
        # BEFORE the read checkpoint itself began (read_checkpoint not-checked,
        # identity not-checked, scalar not-read) - emptier than report 494's
        # identity-phase freeze. Nothing was observed at all, so the same
        # bounded read-only retry/deferral applies instead of killing the
        # worker with bound-chat-read-failed.
        pre = dict(error='frame-budget', **frozen494(read_checkpoint='not-checked').diagnostic)
        self.assertTrue(history.verified_read_budget(pre))
        # Near-misses of the new shape stay rejected: any partial observation
        # (an identity checkpoint, a scalar, a message slot) is evidence of a
        # DIFFERENT, bounded phase and keeps its own classification.
        for changes in (dict(identity_checkpoint='initial-ids'), dict(identity_checkpoint='recheck'),
                        dict(scalar_checkpoint='chat-id'), dict(scalar_state='positive'),
                        dict(wait_reason='history-loading')):
            value = dict(pre, **changes)
            self.assertFalse(history.verified_read_budget(value), changes)


class FrozenScreen(Base):
    def test_report_494_shape_retries_only_read_and_then_answers(self):
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, 'Как дела?)', True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [frozen494(), snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(self.sent, ['Как дела?)'])
        self.assertEqual(out['last_chat_diagnostics']['read_retries'], 1)
        self.assertEqual(self.nav.call_count, 3)

    def test_persistent_frozen_screen_defers_the_chat_without_send(self):
        self.journal()
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [frozen494() for _ in range(4)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['history_deferred'], 1)
        self.assertFalse(self.sent)
        self.assertEqual(self.reader.call_count, 4)


class RecoveryDecision(unittest.TestCase):
    def report(self, failure):
        return dict(status='stopped', reason='initial-pass-stopped',
                    initial_run=dict(status='stopped', reason='inbox-not-finished',
                                     inbox=dict(status='inbox-stopped', reason='chat-bound-chat-read-failed',
                                                last_chat_diagnostics=dict(
                                                    failure_point='bound-chat-read-failed',
                                                    host_failure='internal-error',
                                                    host_checkpoint='chat-read',
                                                    error_type='ReadStopped',
                                                    last_read_failure=failure))))

    def test_report_494_gets_read_only_recovery_instead_of_port_death(self):
        from mumu_recovery import recoverable
        self.assertTrue(recoverable(self.report(dict(error='frame-budget', **frozen494().diagnostic))))
        self.assertTrue(recoverable(self.report(dict(error='transition-timeout', **frozen494().diagnostic))))

    def test_identity_and_unverified_evidence_still_block_recovery(self):
        from mumu_recovery import recoverable
        for changes in (dict(error='identity-changed'), dict(error='identity-not-bound'),
                        dict(error='wrong-screen'), dict(identity_checkpoint='saved-binding'),
                        dict(scalar_state='zero'), dict(read_checkpoint='not-checked'),
                        dict(message_slot=0)):
            failure = dict(frozen494().diagnostic, **changes)
            failure.setdefault('error', 'frame-budget')
            self.assertFalse(recoverable(self.report(failure)), changes)

    def test_host_checkpoint_must_still_be_a_bound_chat_read(self):
        from mumu_recovery import recoverable
        report = self.report(dict(error='frame-budget', **frozen494().diagnostic))
        report['initial_run']['inbox']['last_chat_diagnostics']['host_checkpoint'] = 'inbox-read'
        self.assertFalse(recoverable(report))
        report['initial_run']['inbox']['last_chat_diagnostics']['host_checkpoint'] = 'chat-read'
        report['initial_run']['inbox']['last_chat_diagnostics']['error_type'] = 'StateError'
        self.assertFalse(recoverable(report))


class RecoveryUnfinishedVisibility(unittest.TestCase):
    def test_reason_and_counters_survive_the_closed_json_projection(self):
        report = dict(status='stopped', reason='recovery-unfinished',
                      recovery_failure=dict(host_failure='state-check-failed', recovery_rounds=8))
        projection = json.loads(diagnostic_json(report))['diagnostic']
        self.assertEqual(projection['reason'], 'recovery-unfinished')
        self.assertEqual(projection['recovery_failure']['host_failure'], 'state-check-failed')
        self.assertEqual(projection['recovery_failure']['recovery_rounds'], 8)

    def test_transport_exhaustion_counters_survive_the_closed_json_projection(self):
        report = dict(status='stopped', reason='recovery-unfinished',
                      recovery_failure=dict(host_failure='native-transport-error', transport_failures=30))
        projection = json.loads(diagnostic_json(report))['diagnostic']
        self.assertEqual(projection['reason'], 'recovery-unfinished')
        self.assertEqual(projection['recovery_failure']['transport_failures'], 30)
        self.assertEqual(projection['recovery_failure']['host_failure'], 'native-transport-error')

    def test_telegram_reason_list_names_recovery_unfinished(self):
        self.assertIn('recovery-unfinished', KNOWN)
        report = dict(status='stopped', reason='recovery-unfinished',
                      recovery_failure=dict(host_failure='state-check-failed', recovery_rounds=8))
        self.assertIn('recovery-unfinished', reasons(report))
