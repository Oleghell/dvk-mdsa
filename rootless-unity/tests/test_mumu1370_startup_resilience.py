"""Reports 458-461 (v1.3.69, logs CVc5): two installation pools hammer one
shared session pooler. Four ports died at startup-failed because a single
transient pooler-connect refusal at journal-initialization had no retry at
all (the raw connect retry is one 0.15s repeat), one port lost a live batch
when the pooler outage outlasted the 1.3.69 two-pause retry window at
profile-peer-check, and one port stopped at startup-result-validation-failed
while the closed report never named WHICH authored invariant rejected the
navigation. 1.3.70 retries the whole idempotent journal bootstrap with a wide
bounded backoff, widens the pre-send read window inside the native cycle
budget, and exports the authored ValueError literal as a closed enum.
Synthetic only; no device, database or credentials."""
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistant_pass as native
import run_preparation
import startup_failure
from cloud_database import CloudDatabaseError


def transient(): return CloudDatabaseError('cloud-database-unavailable')
def capacity(): return CloudDatabaseError('cloud-database-capacity')
def permission(): return CloudDatabaseError('cloud-database-permission')


class JournalStartRetry(unittest.TestCase):
    def setUp(self):
        import mumu_worker
        self.worker = mumu_worker

    def open(self, factory, stopped=None):
        """Return (journal, store, enable, contact, pauses, texts); mocks stay bound."""
        pauses = []
        texts = []
        if stopped is None:
            stopped = MagicMock()
            stopped.is_set.return_value = False
        with patch('assistant_store.Store', side_effect=factory) as store, \
             patch('assistant_reply_window.enable') as enable, \
             patch('assistant_contact_policy.enable') as contact:
            journal = self.worker.open_shared_journal(True, stopped, texts.append, pause=pauses.append)
        return journal, store, enable, contact, pauses, texts

    def attempt(self, factory, stopped=None):
        """Run the helper expecting an exception; return (raised, store, pauses)."""
        pauses = []
        if stopped is None:
            stopped = MagicMock()
            stopped.is_set.return_value = False
        with patch('assistant_store.Store', side_effect=factory) as store, \
             patch('assistant_reply_window.enable'), \
             patch('assistant_contact_policy.enable'):
            with self.assertRaises(CloudDatabaseError) as raised:
                self.worker.open_shared_journal(True, stopped, lambda _: None, pause=pauses.append)
        return raised.exception, store, pauses

    def test_transient_connects_are_retried_until_success(self):
        journal, store, enable, contact, pauses, texts = self.open(
            [transient(), transient(), 'JOURNAL'])
        self.assertEqual(journal, 'JOURNAL')
        self.assertEqual(store.call_count, 3)
        self.assertEqual(pauses, [3.0, 7.0])
        self.assertEqual(len(texts), 2)
        self.assertIn('(2 из 7)', texts[0])
        enable.assert_called_with('JOURNAL', new_only=True)
        contact.assert_called_with('JOURNAL')

    def test_capacity_failure_is_also_retried(self):
        journal, store, enable, contact, pauses, texts = self.open([capacity(), 'JOURNAL'])
        self.assertEqual(journal, 'JOURNAL')
        self.assertEqual(store.call_count, 2)
        self.assertEqual(pauses, [3.0])

    def test_exhaustion_reraises_the_last_transient_failure(self):
        error, store, pauses = self.attempt([transient() for _ in range(7)])
        self.assertEqual(error.code, 'cloud-database-unavailable')
        self.assertEqual(store.call_count, 7)
        self.assertEqual(pauses, [3.0, 7.0, 15.0, 30.0, 60.0, 120.0])

    def test_non_transient_code_is_not_retried(self):
        error, store, pauses = self.attempt([permission()])
        self.assertEqual(error.code, 'cloud-database-permission')
        self.assertEqual(store.call_count, 1)
        self.assertEqual(pauses, [])

    def test_stop_during_pause_reraises_the_last_failure(self):
        flag = {'stop': False}
        stopped = MagicMock()
        stopped.is_set.side_effect = lambda: flag['stop']

        def fail_once_then_stop():
            flag['stop'] = True
            raise transient()
        with patch('assistant_store.Store', side_effect=fail_once_then_stop), \
             patch('assistant_reply_window.enable'), patch('assistant_contact_policy.enable'):
            with self.assertRaises(CloudDatabaseError) as raised:
                self.worker.open_shared_journal(True, stopped, lambda _: None, pause=lambda _: None)
        self.assertEqual(raised.exception.code, 'cloud-database-unavailable')

    def test_production_budget_is_five_attempts_over_wide_backoff(self):
        # v1.3.96 (report LAZ5VEvy, port 5563): the pooler refused connects
        # longer than the whole 5-attempt ladder plus both controller
        # requeues, and the port stayed dead until a manual restart. Two more
        # minute-scale rungs widen the in-worker window to ~4 minutes; Stop
        # stays responsive at every rung and non-transient codes stay fatal.
        self.assertEqual(self.worker.JOURNAL_START_RETRY_DELAYS, (3.0, 7.0, 15.0, 30.0, 60.0, 120.0))
        source = Path(self.worker.__file__).read_text(encoding='utf-8')
        self.assertEqual(source.count('JOURNAL_START_RETRY_DELAYS'), 3)

    def test_worker_startup_uses_the_retry_helper(self):
        source = Path(self.worker.__file__).read_text(encoding='utf-8')
        self.assertIn("journal=open_shared_journal(spec['mode']=='new',stopped,progress)", source)
        # The retry helper is the only journal-initialization context in run().
        self.assertEqual(source.count('with journal_initialization():'), 1)


class SharedReadWiderWindow(unittest.TestCase):
    def test_production_window_widened_for_pooler_outages(self):
        # 1.3.71 (reports 468-470): a fifth 20s attempt extends the pre-send
        # window to 37s of pause, still inside the 90s native cycle budget.
        self.assertEqual(native.SHARED_READ_RETRY_DELAYS, (2.0, 5.0, 10.0, 20.0))

    def test_exhaustion_reraises_the_final_transport_error(self):
        action = MagicMock(side_effect=[transient() for _ in range(5)])
        pauses = []
        with self.assertRaises(CloudDatabaseError):
            native.shared_registry_read(action, lambda: False, pause=pauses.append)
        self.assertEqual(action.call_count, 5)
        self.assertEqual(pauses, [2.0, 5.0, 10.0, 20.0])


class ValidationEvidence(unittest.TestCase):
    def failure(self, validation=None):
        value = dict(stage='result-validation', error='startup-result-validation-failed',
                     error_type='ValueError')
        if validation is not None:
            value['validation'] = validation
        return value

    def test_recorded_valueerror_names_the_broken_invariant(self):
        error = ValueError('Unverified shared peer skip')
        recorded = startup_failure.record(error, 'result-validation')
        self.assertEqual(recorded['validation'], 'Unverified shared peer skip')
        self.assertEqual(error._dvk_failure['validation'], 'Unverified shared peer skip')
        self.assertIsNotNone(startup_failure.clean(recorded))

    def test_known_invariant_survives_both_closed_schemas(self):
        value = self.failure('Unverified shared peer skip')
        self.assertEqual(startup_failure.clean(value), value)
        self.assertEqual(run_preparation.clean(dict(stage='profile-peer-check',
            error='prepare-profile-peer-check-failed', error_type='ValueError',
            validation='Unverified shared peer skip')),
            dict(stage='profile-peer-check', error='prepare-profile-peer-check-failed',
                 error_type='ValueError', validation='Unverified shared peer skip'))

    def test_unknown_valueerror_text_is_never_exported(self):
        error = ValueError('secret path C:/users and private text')
        recorded = startup_failure.record(error, 'result-validation')
        self.assertNotIn('validation', recorded)
        self.assertIsNone(startup_failure.clean(self.failure('secret path C:/users and private text')))
        self.assertIsNone(run_preparation.clean(dict(stage='profile-peer-check',
            error='prepare-profile-peer-check-failed', error_type='ValueError',
            validation='anything else')))

    def test_non_valueerror_gets_no_invariant(self):
        from assistant_store import StateError
        recorded = startup_failure.record(StateError('profile-check-stopped'), 'script-run')
        self.assertNotIn('validation', recorded)

    def test_preparation_message_names_the_invariant(self):
        recorded = run_preparation.record(ValueError('Unverified shared peer skip'), 'profile-peer-check')
        self.assertEqual(recorded['validation'], 'Unverified shared peer skip')
        text = run_preparation.message({'last_preparation_failure': recorded})
        self.assertIn('Нарушенный инвариант: Unverified shared peer skip.', text)

    def test_startup_schema_failure_exports_the_invariant_in_json(self):
        import json
        import assistant_error_notify
        report = dict(status='stopped', last_preparation_failure=self.failure('Unverified shared peer skip'))
        exported = json.loads(assistant_error_notify.diagnostic_json(report))['diagnostic']['last_preparation_failure']
        self.assertEqual(exported['validation'], 'Unverified shared peer skip')
        leaked = dict(report, last_preparation_failure=self.failure('secret path C:/users'))
        exported = json.loads(assistant_error_notify.diagnostic_json(leaked))['diagnostic']['last_preparation_failure']
        self.assertNotIn('validation', exported)

    def test_validator_literals_stay_inside_the_closed_set(self):
        base = Path(__file__).resolve().parents[1]
        pattern = re.compile(r"raise ValueError\(\s*'([^'\n]+)'\s*\)")
        for name in ('assistant_pass.py', 'chat_batch.py', 'assistant_profile_read.py',
                     'uikit_profile_navigation.py', 'uikit_navigation.py'):
            source = (base / name).read_text(encoding='utf-8')
            for message in pattern.findall(source):
                self.assertIn(message, startup_failure.VALIDATION_CODES,
                              name + ' raises an unmapped ValueError literal: ' + message)

    def test_adb_evidence_still_validates_alongside_the_invariant(self):
        value = dict(stage='adb-preflight', error='startup-adb-preflight-failed',
                     error_type='OSError', adb_check='test-connect', adb_reason='device-offline',
                     validation='Unfinished navigation')
        self.assertEqual(startup_failure.clean(value), value)
        broken = dict(value, adb_reason='not-a-reason')
        self.assertIsNone(startup_failure.clean(broken))


if __name__ == '__main__':
    unittest.main()
