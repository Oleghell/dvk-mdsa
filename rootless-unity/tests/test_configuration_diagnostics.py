"""Closed configuration evidence survives Telegram export; no device or network."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import assistant_error_notify as notify
import assistant_profiles
from assistant_config import ConfigError, entries
from assistant_settings import Settings
import run_preparation as prep

PRIVATE = 'PRIVATE_TOKEN_MESSAGE_PATH'


class ConfigurationDiagnostics(unittest.TestCase):
    def failure(self, field='cities', reason='invalid-json'):
        return prep.record(ConfigError(PRIVATE, field=field, reason=reason), 'run-profiles')

    def test_nested_preparation_survives_export_and_reexport(self):
        for field in prep.CONFIG_FIELDS:
            for reason in prep.CONFIG_REASONS:
                with self.subTest(field=field, reason=reason):
                    evidence = self.failure(field, reason)
                    report = dict(status='stopped', reason='initial-pass-stopped',
                                  initial_run=dict(status='stopped', reason='initialization-failed',
                                                   preparation_failure=evidence),
                                  last_preparation_failure=evidence)
                    data = notify.diagnostic_json(report)
                    exported = json.loads(data)['diagnostic']
                    self.assertEqual(exported['last_preparation_failure'], evidence)
                    self.assertEqual(exported['initial_run']['preparation_failure'], evidence)
                    self.assertEqual(prep.from_report(exported), evidence)
                    self.assertIn('config/' + field + '.json', prep.message(exported))
                    self.assertNotIn(PRIVATE.encode(), data)
                    self.assertEqual(json.loads(notify.diagnostic_json(exported))['diagnostic'], exported)

    def test_database_category_is_preserved_without_raw_exception(self):
        import sqlite3
        error = sqlite3.OperationalError(PRIVATE)
        error.sqlite_errorname = 'SQLITE_AUTH'
        evidence = prep.record(error, 'inbox-database')
        exported = json.loads(notify.diagnostic_json(dict(preparation_failure=evidence)))['diagnostic']
        self.assertEqual(exported['preparation_failure'], evidence)
        self.assertNotIn(PRIVATE, json.dumps(exported))

    def test_injected_fields_and_values_never_escape(self):
        good = self.failure()
        for evidence in (dict(good, config_field=PRIVATE), dict(good, config_reason=PRIVATE),
                         dict(good, stage=PRIVATE), dict(good, error_type=PRIVATE),
                         dict(good, exception=PRIVATE), dict(good, config_field=['cities'])):
            for key in ('preparation_failure', 'last_preparation_failure'):
                data = notify.diagnostic_json({key: evidence})
                self.assertNotIn(PRIVATE.encode(), data)

    def test_document_caption_identifies_file_without_exception_body(self):
        sender = MagicMock(return_value=True)
        report = dict(status='stopped', last_preparation_failure=self.failure('cities', 'invalid-text'))
        self.assertEqual(notify.notify_json(report, loader=lambda: ('TOKEN', 'CHAT'), sender=sender), 'accepted')
        sender.assert_called_once()
        caption = sender.call_args.args[2]
        self.assertIn('config/cities.json', caption)
        self.assertIn('invalid-text', caption)
        self.assertNotIn(PRIVATE, caption)

    def test_unknown_document_submission_is_not_retried(self):
        sender = MagicMock(side_effect=TimeoutError(PRIVATE))
        report = dict(status='stopped', last_preparation_failure=self.failure())
        self.assertEqual(notify.notify_json(report, loader=lambda: ('TOKEN', 'CHAT'), sender=sender), 'unknown')
        sender.assert_called_once()

    def test_profile_config_failure_keeps_innermost_stage_before_any_cycle(self):
        cycle = MagicMock()
        city = MagicMock()
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'cities.json').write_text('{', encoding='utf-8')
            def broken():
                return entries(folder, 'cities', 80)
            with patch('assistant_config.load', side_effect=broken):
                with self.assertRaises(ConfigError) as caught:
                    assistant_profiles.walk(Settings(), threading.Event(), MagicMock(), MagicMock(),
                                            MagicMock(), cycle=cycle, city_next=city)
        evidence = prep.record(caught.exception, 'run-profiles')
        self.assertEqual(evidence['stage'], 'profiles-config')
        self.assertEqual((evidence['config_field'], evidence['config_reason']), ('cities', 'invalid-json'))
        cycle.assert_not_called()
        city.assert_not_called()
