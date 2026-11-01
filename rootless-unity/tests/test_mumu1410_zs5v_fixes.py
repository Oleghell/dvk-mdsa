"""Reports dropmefiles zS5V (monitors 708-712): the port-killing fixes.

Synthetic only. Three families pinned here:
  708/711 - a TRANSIENT cloud refusal on the inbox pass's own journal reads
            stopped the whole pass as host_failure=journal-error (711 died at
            inbox-open on operation='read', 708 at inbox-prepare on the
            ROLLBACK cleanup of a failed read block); BLOCK_CODES then kept
            the port dead until a human restart. The pass now takes the
            cloud-journal-transient soft exit - no host_failure, database
            diagnostic attached - and the supervisor's bounded recovery
            restarts the pass. Write/commit/lock/connect refusals and every
            non-transient code keep the hard stop exactly as before.
  712     - the same refusal on the profile pass's post-cycle BOOKKEEPING
            write (session.set('checked_at') at host_checkpoint
            profile-journal) killed the batch as device-or-journal-check-
            stopped. The bookkeeping checkpoints (profile-journal/
            profile-verify/city-journal) run strictly after the cycle
            returned, so the send outcome is already recorded; a transient
            refusal there takes the same soft exit. A failure DURING the
            cycle (cycle pending) or a non-transient code keeps the hard
            stop.
  708     - the cloud report masked the guided chain's authored send labels
            (failure_point 'send-adapter-exception' etc.) to
            'unrecognized-diagnostic-code', hiding the very code that named
            the broken step; the closed set keeps them now, and the send arm
            rides the database diagnostic into the send_failure_event.
"""
import json
import unittest
from unittest.mock import MagicMock, patch

import cloud_database
import assistant_inbox as inbox
import assistant_profiles as profiles
import assistant_error_notify as notify
from mumu_recovery import RETRY_CODES, recoverable
from test_inbox_profiles import Base, WHO, nav, msg, snap, Config, cycle_result


def transient(code='cloud-database-unavailable', operation='read'):
    error = cloud_database.CloudDatabaseError(code)
    error.operation = operation
    return error


DATABASE = dict(code='cloud-database-unavailable', operation='read', automatic_retry=False)


class UnmaskedSendLabels(unittest.TestCase):
    """708: the authored failure_point labels survive the cloud projection."""

    def test_send_labels_and_new_reasons_join_the_closed_set(self):
        for code in ('send-adapter-exception', 'send-handler-unconfirmed',
                     'guided-stage-changed', 'guided-send-already-reserved',
                     'ai-temporarily-unavailable', 'cloud-journal-transient'):
            self.assertIn(code, notify.KNOWN, code)
        self.assertIn('cloud-journal-transient', RETRY_CODES)

    def test_send_failure_event_keeps_its_labels_and_database(self):
        # The exact 708 shape: reason send-outcome-unknown with the (formerly
        # masked) failure_point and the newly attached database diagnostic.
        raw = notify.diagnostic_json(dict(send_failure_events=[dict(
            reason='send-outcome-unknown',
            diagnostic=dict(failure_point='send-adapter-exception',
                            send_host_failure='journal-error',
                            database=dict(code='cloud-database-unavailable',
                                          operation='lock', automatic_retry=False)))]))
        event = json.loads(raw)['diagnostic']['send_failure_events'][0]
        self.assertEqual(event['reason'], 'send-outcome-unknown')
        self.assertEqual(event['diagnostic']['failure_point'], 'send-adapter-exception')
        self.assertEqual(event['diagnostic']['send_host_failure'], 'journal-error')
        self.assertEqual(event['diagnostic']['database'],
                         dict(code='cloud-database-unavailable', operation='lock', automatic_retry=False))

    def test_soft_pass_reasons_survive_the_cloud_report(self):
        raw = notify.diagnostic_json(dict(
            status='stopped', reason='inbox-pass-stopped',
            last_pass=dict(status='inbox-stopped', reason='cloud-journal-transient',
                           database=DATABASE),
            last_profile_run=dict(status='stopped', reason='profiles-not-finished',
                                  profiles=dict(status='profiles-stopped',
                                                reason='cloud-journal-transient',
                                                database=DATABASE))))
        value = json.loads(raw)['diagnostic']
        self.assertEqual(value['last_pass']['reason'], 'cloud-journal-transient')
        self.assertEqual(value['last_pass']['database'], DATABASE)
        self.assertEqual(value['last_profile_run']['profiles']['reason'], 'cloud-journal-transient')
        self.assertEqual(value['last_profile_run']['profiles']['database'], DATABASE)


class InboxTransientDeferral(Base):
    """708/711: the pass's own journal reads defer instead of journal-error."""

    def prepare_failure(self, error):
        self.journal()
        with patch('assistant_inbox.with_seen_ids', side_effect=error):
            return self.walk([nav('opened', WHO)], [snap(msg(1002, 'Привет'))])

    def test_transient_read_takes_the_soft_exit(self):
        # Monitor 711's family: CloudDatabaseError('cloud-database-unavailable',
        # operation='read') on the pass's journal read.
        out = self.prepare_failure(transient(operation='read'))
        self.assertEqual(out['status'], 'inbox-stopped')
        self.assertEqual(out['reason'], 'cloud-journal-transient')
        self.assertEqual(out['database'], DATABASE)
        self.assertNotIn('host_failure', out)
        self.assertFalse(self.sent)

    def test_transient_rollback_cleanup_takes_the_soft_exit(self):
        # Monitor 708's exact shape: the ROLLBACK cleanup of a failed read
        # block refused transitively - the server discarded the transaction,
        # so nothing unknown was committed.
        out = self.prepare_failure(transient(operation='rollback'))
        self.assertEqual(out['status'], 'inbox-stopped')
        self.assertEqual(out['reason'], 'cloud-journal-transient')
        self.assertEqual(out['database'],
                         dict(code='cloud-database-unavailable', operation='rollback', automatic_retry=False))

    def test_transient_write_keeps_the_hard_stop(self):
        out = self.prepare_failure(transient(operation='write'))
        self.assertEqual(out['status'], 'inbox-stopped')
        self.assertEqual(out['host_failure'], 'journal-error')
        self.assertEqual(out['reason'], 'navigation-check-stopped')
        self.assertEqual(out['database'],
                         dict(code='cloud-database-unavailable', operation='write', automatic_retry=False))
        self.assertFalse(self.sent)

    def test_nontransient_lock_keeps_the_hard_stop(self):
        out = self.prepare_failure(transient(code='cloud-database-lock-timeout', operation='lock'))
        self.assertEqual(out['status'], 'inbox-stopped')
        self.assertEqual(out['host_failure'], 'journal-error')
        self.assertEqual(out['reason'], 'navigation-check-stopped')

    def test_supervisor_recovers_the_soft_stop_and_keeps_writes_dead(self):
        soft = dict(status='stopped', reason='inbox-pass-stopped',
                    last_pass=dict(status='inbox-stopped', reason='cloud-journal-transient',
                                   database=DATABASE))
        self.assertTrue(recoverable(soft))
        write_side = dict(status='stopped', reason='inbox-pass-stopped',
                          last_pass=dict(status='inbox-stopped', reason='navigation-check-stopped',
                                         host_failure='journal-error',
                                         database=dict(code='cloud-database-unavailable',
                                                       operation='write', automatic_retry=False)))
        self.assertFalse(recoverable(write_side))
        lock_side = dict(status='stopped', reason='inbox-pass-stopped',
                         last_pass=dict(status='inbox-stopped', reason='navigation-check-stopped',
                                        host_failure='journal-error',
                                        database=dict(code='cloud-database-lock-timeout',
                                                      operation='lock', automatic_retry=False)))
        self.assertFalse(recoverable(lock_side))


class ProfileTransientDeferral(Base):
    """712: post-cycle bookkeeping defers instead of device-or-journal-check."""

    def bookkeeping_failure(self, error):
        profiles.Session(self.store).set('city', 'Псков')
        cycle = MagicMock(return_value=cycle_result(send_attempted=False, send_handler_returned=False))
        with patch.object(profiles.Session, 'set', side_effect=error):
            out = profiles.walk(self.settings, self.stop, self.approve, lambda _: None,
                                self.store, cycle=cycle, config=Config(), limit=1)
        return out, cycle

    def test_transient_bookkeeping_write_takes_the_soft_exit(self):
        # Monitor 712's shape: session.set('checked_at') after the cycle
        # returned hit a transient shared-pooler refusal at profile-journal.
        out, cycle = self.bookkeeping_failure(transient(operation='write'))
        self.assertEqual(out['status'], 'profiles-stopped')
        self.assertEqual(out['reason'], 'cloud-journal-transient')
        self.assertEqual(out['database'],
                         dict(code='cloud-database-unavailable', operation='write', automatic_retry=False))
        self.assertNotIn('host_failure', out)
        self.assertEqual(cycle.call_count, 1)
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_transient_commit_on_bookkeeping_takes_the_soft_exit(self):
        out, _ = self.bookkeeping_failure(transient(operation='commit'))
        self.assertEqual(out['reason'], 'cloud-journal-transient')
        self.assertNotIn('host_failure', out)

    def test_failure_during_the_cycle_keeps_the_hard_stop(self):
        # cycle_pending is True: the native cycle died mid-flight, the send
        # outcome is unknown - never deferred.
        profiles.Session(self.store).set('city', 'Псков')
        cycle = MagicMock(side_effect=transient())
        out = profiles.walk(self.settings, self.stop, self.approve, lambda _: None,
                            self.store, cycle=cycle, config=Config(), limit=1)
        self.assertEqual(out['status'], 'profiles-stopped')
        self.assertEqual(out['reason'], 'device-or-journal-check-stopped')
        self.assertEqual(out['host_failure'], 'journal-error')
        self.assertTrue(out['send_attempts_unknown'])

    def test_nontransient_busy_keeps_the_hard_stop(self):
        import sqlite3
        error = sqlite3.OperationalError('PRIVATE SQL PATH')
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        out, _ = self.bookkeeping_failure(error)
        self.assertEqual(out['status'], 'profiles-stopped')
        self.assertEqual(out['reason'], 'device-or-journal-check-stopped')
        self.assertEqual(out['host_failure'], 'journal-busy')
        self.assertEqual(out['host_checkpoint'], 'profile-journal')

    def test_nontransient_lock_timeout_keeps_the_hard_stop(self):
        out, _ = self.bookkeeping_failure(transient(code='cloud-database-lock-timeout', operation='lock'))
        self.assertEqual(out['reason'], 'device-or-journal-check-stopped')
        self.assertEqual(out['host_failure'], 'journal-error')

    def test_supervisor_recovers_the_soft_batch(self):
        report = dict(status='stopped', reason='profile-pass-stopped',
                      last_profile_run=dict(status='stopped', reason='profiles-not-finished',
                                            profiles=dict(status='profiles-stopped',
                                                          reason='cloud-journal-transient',
                                                          database=DATABASE)))
        self.assertTrue(recoverable(report))
        hard = dict(status='stopped', reason='profile-pass-stopped',
                    last_profile_run=dict(status='stopped', reason='profiles-not-finished',
                                          profiles=dict(status='profiles-stopped',
                                                        reason='device-or-journal-check-stopped',
                                                        host_failure='journal-error')))
        self.assertFalse(recoverable(hard))


class SendRefusalDiagnostics(Base):
    """708: the send arm's journal refusal keeps its closed database code."""

    def test_send_refusal_attaches_database_and_keeps_labels(self):
        self.journal()
        hello = msg(1002, 'Привет')
        sender = MagicMock(side_effect=transient(operation='lock'))
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello)], sender=sender)
        # The chat is isolated without a retry - an unknown send outcome is
        # never deferred - but the report now names the exact database code.
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['outcomes'], {'isolated:send-outcome-unknown': 1})
        self.assertEqual(out['last_chat_diagnostics']['failure_point'], 'send-adapter-exception')
        self.assertEqual(out['last_chat_diagnostics']['send_host_failure'], 'journal-error')
        self.assertEqual(out['last_chat_diagnostics']['database'],
                         dict(code='cloud-database-unavailable', operation='lock', automatic_retry=False))
        self.assertEqual(sender.call_count, 1)
        self.assertNotIn('PRIVATE', json.dumps(out))
        raw = notify.diagnostic_json(out)
        event = json.loads(raw)['diagnostic']['send_failure_events'][0]
        self.assertEqual(event['reason'], 'send-outcome-unknown')
        self.assertEqual(event['diagnostic']['failure_point'], 'send-adapter-exception')
        self.assertEqual(event['diagnostic']['database'],
                         dict(code='cloud-database-unavailable', operation='lock', automatic_retry=False))


class RussianSummaries(unittest.TestCase):
    def test_window_text_names_the_soft_deferral(self):
        import assistant_run as run
        self.assertIn('Общая база', run.INBOX_REASONS['cloud-journal-transient'])
        self.assertIn('Общая база', run.PROFILE_REASONS['cloud-journal-transient'])


if __name__ == '__main__':
    unittest.main()
