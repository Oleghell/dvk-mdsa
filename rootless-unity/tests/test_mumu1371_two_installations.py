"""Reports 468-470 (v1.3.70, dropmefiles Lm4hUk): two laptops run the same
ports against one shared Supabase session pooler (~45 application slots of a
60-connection project after internal services).

Port 470 stopped at startup-result-validation-failed with the invariant
'Inconsistent avatar counts': the cooperative search scan counts a cell in
`cells` only once per visit, but a selection-changed retry re-examines that
same cell without advancing the scan and re-increments one avatar or skip
counter. The validator now grants the exact +selection_retries allowance the
rows bound already had, so a legitimate retried selection is no longer
rejected after a successful cycle.

Ports 468/469 lost live batches when the pooler outage outlasted the 17s
pre-send window while BOTH installations retried at the identical instants:
the window now spans a fifth 20s attempt (37s of pause, still inside the 90s
native cycle budget) and every database backoff pause - shared reads, journal
start, raw connect - is jittered so the two machines stop reconnecting as one
synchronized wave.

Synthetic only; no device, database or credentials."""
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistant_pass as native
import cloud_database as cloud
import uikit_profile_navigation as validator
from cloud_database import CloudDatabaseError
from test_profile_navigation import ready_profile
from unittest.mock import call


def transient(): return CloudDatabaseError('cloud-database-unavailable')


class AvatarRetryArithmetic(unittest.TestCase):
    """Port 470: cells=1, one noninteractive avatar re-examined by two
    selection-changed retries -> avatar_noninteractive=3 against cells=1."""

    def profile(self, **counts):
        value = ready_profile(); n = value['navigation']
        n['selection_retries'] = counts.pop('retries', 2)
        n['selection_counts'].update(counts)
        return value

    def test_port470_retried_avatar_counts_validate(self):
        validator.validate(self.profile(cells=1, avatar_noninteractive=3, retries=2))

    def test_avatar_counter_tolerance_boundary(self):
        validator.validate(self.profile(cells=1, avatar_hidden=3))
        validator.validate(self.profile(cells=1, avatar_noninteractive=3))
        for key in ('avatar_hidden', 'avatar_noninteractive'):
            with self.assertRaises(ValueError) as raised:
                validator.validate(self.profile(cells=1, **{key: 4}))
            self.assertEqual(str(raised.exception), 'Inconsistent avatar counts')

    def test_skip_tolerance_boundary(self):
        validator.validate(self.profile(cells=1, avatar_unready=3))
        with self.assertRaises(ValueError) as raised:
            validator.validate(self.profile(cells=1, avatar_unready=4))
        self.assertEqual(str(raised.exception), 'Inconsistent selection skips')

    def test_zero_retries_keeps_the_original_strictness(self):
        for key in ('avatar_hidden', 'avatar_noninteractive', 'avatar_unready'):
            with self.assertRaises(ValueError):
                validator.validate(self.profile(cells=1, retries=0, **{key: 2}))

    def test_retry_count_stays_bounded(self):
        with self.assertRaises(ValueError):
            validator.validate(self.profile(retries=3, cells=1, avatar_noninteractive=4))


class LockstepJitter(unittest.TestCase):
    def test_shared_read_default_pause_is_jittered(self):
        action = MagicMock(side_effect=[transient(), 'ok'])
        with patch('random.uniform', return_value=1.25) as spread, patch('time.sleep') as sleep:
            value = native.shared_registry_read(action, lambda: False)
        self.assertEqual(value, 'ok')
        spread.assert_called_once_with(1.0, 1.6)
        sleep.assert_called_once_with(2.0 * 1.25)

    def test_shared_read_jitter_never_exceeds_its_slot(self):
        action = MagicMock(side_effect=[transient(), transient(), 'ok'])
        with patch('random.uniform', side_effect=[1.6, 1.0]), patch('time.sleep') as sleep:
            native.shared_registry_read(action, lambda: False)
        self.assertEqual(sleep.call_args_list,
                         [call(2.0 * 1.6), call(5.0 * 1.0)])

    def test_journal_start_default_pause_is_jittered(self):
        import mumu_worker
        stopped = MagicMock(); stopped.is_set.return_value = False
        with patch('assistant_store.Store', side_effect=[transient(), 'JOURNAL']), \
             patch('assistant_reply_window.enable'), patch('assistant_contact_policy.enable'), \
             patch('random.uniform', return_value=1.5) as spread, patch('time.sleep') as sleep:
            journal = mumu_worker.open_shared_journal(True, stopped, lambda _: None)
        self.assertEqual(journal, 'JOURNAL')
        spread.assert_called_once_with(1.0, 1.6)
        sleep.assert_called_once_with(3.0 * 1.5)

    def test_raw_connect_backoff_is_jittered(self):
        def retryable():
            error = CloudDatabaseError('cloud-database-unavailable')
            error.connect_retryable = True
            return error
        raw = object()
        with patch.object(cloud, '_raw_connect_once', side_effect=[retryable(), raw]), \
             patch('random.uniform', return_value=0.5) as spread, patch('time.sleep') as sleep:
            self.assertIs(cloud.raw_connect({}), raw)
        spread.assert_called_once_with(0.0, 0.5)
        sleep.assert_called_once_with(0.5 * 1.5)

    def test_raw_connect_budget_is_three_attempts(self):
        def retryable():
            error = CloudDatabaseError('cloud-database-unavailable')
            error.connect_retryable = True
            return error
        with patch.object(cloud, '_raw_connect_once', side_effect=[retryable() for _ in range(3)]) as once, \
             patch('random.uniform', return_value=0.0), patch('time.sleep') as sleep:
            with self.assertRaises(CloudDatabaseError) as raised:
                cloud.raw_connect({})
        self.assertEqual(once.call_count, 3)
        self.assertEqual(raised.exception.code, 'cloud-database-unavailable')
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.5, 1.5])

    def test_raw_connect_non_retryable_fails_immediately(self):
        denied = CloudDatabaseError('cloud-database-permission')
        with patch.object(cloud, '_raw_connect_once', side_effect=[denied]) as once, \
             patch('time.sleep') as sleep:
            with self.assertRaises(CloudDatabaseError):
                cloud.raw_connect({})
        self.assertEqual(once.call_count, 1)
        sleep.assert_not_called()


class TwoInstallationBudgets(unittest.TestCase):
    def test_pre_send_window_spans_five_attempts_inside_the_cycle_budget(self):
        self.assertEqual(native.SHARED_READ_RETRY_DELAYS, (2.0, 5.0, 10.0, 20.0))
        self.assertEqual(sum(native.SHARED_READ_RETRY_DELAYS), 37.0)

    def test_jittered_pauses_are_pinned_in_all_three_backoff_sites(self):
        base = Path(__file__).resolve().parents[1]
        assistant = (base / 'assistant_pass.py').read_text(encoding='utf-8')
        worker = (base / 'mumu_worker.py').read_text(encoding='utf-8')
        database = (base / 'cloud_database.py').read_text(encoding='utf-8')
        self.assertIn('time.sleep(seconds * uniform(1.0, 1.6))', assistant)
        self.assertIn('sleep(seconds * uniform(1.0, 1.6))', worker)
        self.assertIn('time.sleep(delay * (1.0 + uniform(0.0, 0.5)))', database)
        # The old lockstep retries are gone everywhere.
        self.assertNotIn('= time.sleep\n', assistant)
        self.assertNotIn('time.sleep(.15)', database)


if __name__ == '__main__':
    unittest.main()
