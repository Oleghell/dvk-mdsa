"""Synthetic fixed-preview tests: no Android, personal text, sending or contacts."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from one_chat_store import TestChatStore
from one_chat_preview import CODE, QUESTION, TEST_TEXT, FIELDS, decide, display, fields, report
from test_one_chat import WHO, message


def snap(extra=()):
    return dict(identity=dict(WHO), messages=[message(), message('1002', '200')] + list(extra))


class Preview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'one-chat-check.sqlite3'
        self.store = TestChatStore(self.path); self.addCleanup(lambda: self.store.close())
        self.store.bind(WHO)

    def read(self, value):
        return self.store.consume(value, preview=True)

    def baseline(self):
        # The exact existing 0.3.31 API, not preview mode.
        self.store.consume(snap())

    def ready(self):
        self.baseline()
        newer = snap([message('1003', '200', TEST_TEXT)])
        result = self.read(newer)
        self.assertEqual(result['new_incoming'], 1)
        self.assertTrue(result['preview_created'])
        self.assertIn(QUESTION, display(result))
        return newer

    def test_compatible_existing_state_new_preview_repeat_and_restart(self):
        newer = self.ready()
        for restart in (False, True):
            if restart:
                self.store.close(); self.store = TestChatStore(self.path)
            result = self.read(newer)
            self.assertEqual(result['new_incoming'], 0)
            self.assertFalse(result['preview_created'])
            self.assertTrue(result['preview_available'])
            self.assertIn('Сохранённый', display(result))
            self.assertEqual(self.store.bound(), WHO)

    def test_upgrade_from_database_without_preview_table_preserves_baseline(self):
        self.baseline()
        self.store.db.execute('DROP TABLE test_preview')
        self.store.close(); self.store = TestChatStore(self.path)
        result = self.read(snap())
        self.assertEqual(result['status'], 'read-complete')
        self.assertEqual(result['new_incoming'], 0)
        self.assertFalse(result['preview_available'])
        self.assertEqual(self.store.bound(), WHO)

    def test_saved_preview_survives_collection_reordering(self):
        newer = self.ready()
        newer['messages'].reverse()
        result = self.read(newer)
        self.assertTrue(result['preview_available'])
        self.assertFalse(result['preview_created'])
        self.assertEqual(result['preview_reason'], 'no-new-messages')

    def test_baseline_old_test_phrase_never_generates_a_draft(self):
        result = self.read(snap([message('1003', '200', TEST_TEXT)]))
        self.assertEqual(result['status'], 'baseline-recorded')
        self.assertFalse(result['preview_available'])
        self.assertEqual(result['new_incoming'], 0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM test_preview').fetchone()[0], 0)

    def test_order_is_never_time_and_only_one_new_incoming_allowed(self):
        self.baseline()
        newer = snap([message('1003', '200', TEST_TEXT), message('1004', '200', TEST_TEXT)])
        newer['messages'].reverse()
        result = self.read(newer)
        self.assertEqual(result['new_incoming'], 2)
        self.assertEqual(result['preview_reason'], 'multiple-new-incoming')
        self.assertFalse(result['preview_available'])

    def test_single_new_message_can_be_anywhere_in_collection(self):
        self.baseline()
        newer = snap([message('900', '200', TEST_TEXT)])
        newer['messages'].reverse()
        self.assertTrue(self.read(newer)['preview_created'])

    def test_new_outgoing_or_nontext_or_noncontrol_text_clears_old_draft(self):
        for sender, text, reason in [('100', TEST_TEXT, 'new-outgoing'), ('200', None, 'non-text-incoming'),
                                    ('200', 'Другое сообщение', 'unsupported-test-text')]:
            with self.subTest(reason=reason):
                # Separate DB lifetime is simpler than ever resetting production state.
                with tempfile.TemporaryDirectory() as directory:
                    store = TestChatStore(Path(directory) / 'one-chat-check.sqlite3')
                    try:
                        store.bind(WHO); store.consume(snap())
                        prev = message('1003', '200', TEST_TEXT)
                        store.consume(snap([prev]), preview=True)
                        result = store.consume(snap([prev, message('1004', sender, text)]), preview=True)
                        self.assertEqual(result['preview_reason'], reason)
                        self.assertFalse(result['preview_available'])
                        self.assertFalse(store.consume(snap([prev, message('1004', sender, text)]), preview=True)['preview_available'])
                    finally:
                        store.close()

    def test_incoming_plus_new_outgoing_requires_manual_review(self):
        self.baseline()
        result = self.read(snap([message('1003', '200', TEST_TEXT), message('1004', '100', 'MANUAL')]))
        self.assertEqual(result['preview_reason'], 'new-outgoing')
        self.assertFalse(result['preview_available'])

    def test_bad_identity_or_history_rolls_back_seen_and_saved_preview(self):
        newer = self.ready()
        original_seen = self.store.db.execute('SELECT * FROM test_seen ORDER BY message_key').fetchall()
        original_preview = self.store.db.execute('SELECT * FROM test_preview').fetchall()
        for kind in ('edit', 'delete', 'different-chat', 'duplicate'):
            invalid = copy.deepcopy(newer)
            invalid['messages'].append(message('1004', '200', TEST_TEXT))
            if kind == 'edit': invalid['messages'][0]['text'] = 'CHANGED'
            if kind == 'delete': invalid['messages'].pop(0)
            if kind == 'different-chat': invalid['identity']['chat'] = '301'
            if kind == 'duplicate': invalid['messages'].append(message('1004', '200', TEST_TEXT))
            with self.assertRaises(ValueError): self.read(invalid)
            self.assertEqual(original_seen, self.store.db.execute('SELECT * FROM test_seen ORDER BY message_key').fetchall())
            self.assertEqual(original_preview, self.store.db.execute('SELECT * FROM test_preview').fetchall())

    def test_failed_transaction_does_not_consume_event(self):
        self.baseline()
        newer = snap([message('1003', '200', TEST_TEXT)])
        self.store.db.execute("CREATE TRIGGER deny_preview BEFORE INSERT ON test_preview BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.read(newer)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM test_seen').fetchone()[0], 2)
        self.store.db.execute('DROP TRIGGER deny_preview')
        self.assertTrue(self.read(newer)['preview_created'])

    def test_recovery_after_report_write_failure_is_saved_not_new(self):
        newer = self.ready()
        with patch.object(Path, 'write_text', side_effect=OSError('synthetic disk fault')):
            with self.assertRaises(OSError):
                Path(self.tmp.name, 'report.json').write_text(json.dumps(report(self.read(newer))))
        result = self.read(newer)
        self.assertEqual(result['new_incoming'], 0)
        self.assertTrue(result['preview_available'])
        self.assertFalse(result['preview_created'])

    def test_old_version_can_read_extra_table_and_expires_stale_preview(self):
        newer = self.ready()
        # Simulate original 0.3.31 consuming an event without knowledge of the new table.
        row = self.store.db.execute('SELECT * FROM test_preview').fetchone()
        newer['messages'].append(message('1004', '100', 'OWN MANUAL REPLY'))
        self.store.consume(newer)
        self.store.db.execute('INSERT OR REPLACE INTO test_preview VALUES(?,?,?)', row)
        result = self.read(newer)
        self.assertEqual(result['new_incoming'], 0)
        self.assertEqual(result['preview_reason'], 'saved-preview-expired')
        self.assertFalse(result['preview_available'])

    def test_preview_never_persists_message_or_proposal_bodies_or_raw_message_ids(self):
        newer = self.ready(); self.read(newer); self.store.close()
        raw = self.path.read_bytes()
        for text in (TEST_TEXT, QUESTION, 'PRIVATE TEST TEXT'):
            self.assertNotIn(text.encode('utf-8'), raw)
        self.store = TestChatStore(self.path)
        self.assertEqual([r[1] for r in self.store.db.execute('PRAGMA table_info(test_preview)')], ['singleton', 'code', 'snapshot_key'])
        code, key = self.store.db.execute('SELECT code,snapshot_key FROM test_preview').fetchone()
        self.assertEqual(code, CODE); self.assertRegex(key, '^[0-9a-f]{64}$')

    def test_corrupt_saved_preview_stops_before_consuming(self):
        self.baseline()
        self.store.db.execute("INSERT INTO test_preview VALUES(1,'PRIVATE','not-a-hash')")
        with self.assertRaises(ValueError): self.read(snap([message('1003', '200', TEST_TEXT)]))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM test_seen').fetchone()[0], 2)

    def test_report_is_fixed_codes_and_counts_not_a_text_export(self):
        newer = self.ready()
        public = report(self.read(newer))
        text = json.dumps(public, ensure_ascii=False)
        for private in (TEST_TEXT, QUESTION, 'PRIVATE TEST TEXT', '1001', '1002', '1003'):
            self.assertNotIn(private, text)
        self.assertEqual(public['messages_sent'], 0)
        self.assertFalse(public['draft_inserted'])
        self.assertFalse(public['automatic_replies_available'])
        self.assertFalse(public['chronological_order_verified'])
        self.assertTrue(public['preview_test_phrase_only'])

    def test_report_rejects_unknown_fields_and_contradictory_codes(self):
        self.baseline()
        valid = self.read(snap([message('1003', '200', TEST_TEXT)]))
        changes = [dict(preview_code=TEST_TEXT), dict(preview_reason=TEST_TEXT), dict(preview_created=1),
                   dict(preview_available=False), dict(preview_code='none'), dict(new_incoming=0),
                   dict(status='baseline-recorded'), dict(private_text='SECRET')]
        for change in changes:
            with self.assertRaises(ValueError): report(dict(valid, **change))
        with self.assertRaises(ValueError): display(dict(valid, preview_reason='PRIVATE'))

    def test_no_device_sender_engine_or_notifier_is_part_of_preview(self):
        source = (Path(__file__).parents[1] / 'one_chat_preview.py').read_text(encoding='utf-8')
        for forbidden in ('Engine(', 'telegram_notify', 'set_Text', 'OnSend', 'subprocess', 'requests.', 'socket.', 'TargetOnlyAdb('):
            self.assertNotIn(forbidden, source)
        self.assertEqual(report()['status'], 'binding-ready')
        self.assertEqual(report(failure=True)['status'], 'stopped')
