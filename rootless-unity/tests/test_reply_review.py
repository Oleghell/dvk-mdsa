"""Synthetic snapshots only; no device, real identity, network or credentials."""
from dataclasses import replace
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from conversation_engine import Snapshot, Message, PolicyError, QUESTIONS
from greetings import get_greeting
import reply_review as p


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.source = self.folder / 'new-ten.sqlite3'
        db = sqlite3.connect(self.source)
        db.executescript('''CREATE TABLE cohort(singleton INTEGER PRIMARY KEY,state TEXT);
          INSERT INTO cohort VALUES(1,'closed');
          CREATE TABLE bindings(attempt INTEGER PRIMARY KEY,account TEXT,peer TEXT,
            initial_chat TEXT,variant INTEGER,status TEXT);''')
        # The source holds seven bindings, including a real unresolved draft ID.
        db.executemany('INSERT INTO bindings VALUES(?,?,?,?,?,?)',
                       [(i, '10', str(19+i), '-1' if i == 1 else str(49+i), 0,
                         'reserved-unknown' if i == 1 else 'handler-returned-unconfirmed')
                        for i in range(1, 8)])
        db.commit()
        db.close()
        self.original = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.path = self.folder / 'reply-review.sqlite3'
        # In-memory private-envelope test double, NOT encryption for production.
        self.sealed = {}
        def seal(raw):
            key = ('test-envelope-' + str(len(self.sealed))).encode()
            self.sealed[key] = raw
            return key
        self.seal = seal
        self.store = self.open()
        self.addCleanup(lambda: self.store.close())
        self.sender = Mock(return_value=True)

    def open(self):
        return p.ReviewStore(self.source, self.path, choose=lambda: 0,
                             seal=self.seal, unseal=self.sealed.__getitem__)

    def restart(self):
        self.store.close()
        self.store = self.open()

    def snapshot(self, *extra, **kw):
        values = dict(account='10', peer='20', chat='50', name='Synthetic Name',
                      messages=(Message('1', '10', get_greeting(0)),) + tuple(extra))
        values.update(kw)
        return Snapshot(**values)

    def incoming(self, i=2, text='Здравствуйте!'):
        return Message(str(i), '20', text)

    def own(self, i, text):
        return Message(str(i), '10', text)

    def draft(self, s=None):
        s = self.snapshot(self.incoming()) if s is None else s
        self.assertEqual(self.store.ingest(s), 'draft_ready')
        return self.store.drafts()[0], s

    def confirm(self, draft, s):
        return self.store.confirm(draft, s, self.sender, approved=True)

    def test_original_seven_are_loaded_without_changing_enrollment(self):
        self.assertEqual(len(self.store.bindings), 7)
        self.assertEqual(self.store.summary()['bound_dialogs'], 7)
        self.assertEqual(self.store.bindings[0].initial_chat, '-1')
        self.draft()
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.original)
        self.assertFalse(self.store.summary()['live_backend_available'])

    def test_no_automatic_send_on_read_or_restart(self):
        draft, s = self.draft()
        self.store.ingest(s)
        self.restart()
        self.store.ingest(s)
        self.assertEqual(self.store.drafts()[0], draft)
        self.sender.assert_not_called()

    def test_confirmation_required_and_unknown_outcome_not_retried(self):
        draft, s = self.draft()
        for approved in (False, 1, None):
            with self.assertRaises(p.ReviewError):
                self.store.confirm(draft, s, self.sender, approved=approved)
        self.sender.assert_not_called()
        self.sender.side_effect = RuntimeError('PRIVATE')
        self.assertEqual(self.confirm(draft, s), 'unknown')
        self.restart()
        self.assertEqual(self.store.ingest(s), 'await_outgoing_observation')
        with self.assertRaises(p.ReviewError):
            self.confirm(draft, s)
        self.assertEqual(self.sender.call_count, 1)
        self.assertNotIn('PRIVATE', json.dumps(self.store.summary()))

    def test_full_flow_waits_for_confirmation_and_observed_own_message(self):
        reply = self.incoming()
        draft, s = self.draft(self.snapshot(reply))
        self.assertEqual(draft.text, QUESTIONS[0])
        self.assertEqual(self.confirm(draft, s), 'handler_returned')
        self.assertEqual(self.store.ingest(s), 'await_outgoing_observation')
        question = self.own(3, draft.text)
        mood = self.incoming(4, 'Хорошо')
        s2 = self.snapshot(reply, question, mood)
        contact_draft, _ = self.draft(s2)
        self.assertEqual(contact_draft.kind, 'contact')
        self.assertEqual(contact_draft.text, p.CONTACT_DRAFT)
        self.assertEqual(self.sender.call_count, 1)
        self.confirm(contact_draft, s2)
        invite = self.own(5, contact_draft.text)
        contact = self.incoming(6, 'Мой Telegram @test_user')
        self.assertEqual(self.store.ingest(self.snapshot(reply, question, mood, invite, contact)), 'contact_saved')
        self.assertEqual(self.store.drafts(), ())
        notify = Mock(return_value=True)
        self.assertEqual(self.store.notify_one(notify), 'accepted')
        self.assertEqual(notify.call_args.args, ({'name': 'Synthetic Name', 'contacts': ['@test_user']},))
        self.restart()
        self.assertEqual(self.store.notify_one(notify), 'nothing_pending')
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(self.sender.call_count, 2)

    def test_new_input_invalidates_displayed_draft(self):
        draft, s = self.draft()
        changed = self.snapshot(self.incoming(), self.incoming(3, 'Ещё сообщение'))
        with self.assertRaises(p.ReviewError):
            self.confirm(draft, changed)
        self.sender.assert_not_called()
        self.store.ingest(changed)
        new = self.store.drafts()[0]
        self.assertNotEqual(new.id, draft.id)
        with self.assertRaises(p.ReviewError):
            self.confirm(draft, s)

    def test_edited_incoming_same_id_invalidates_draft(self):
        draft, s = self.draft()
        with self.assertRaises(p.ReviewError):
            self.confirm(draft, self.snapshot(self.incoming(text='Изменено')))
        self.sender.assert_not_called()

    def test_edit_requires_confirmation_of_the_new_text(self):
        draft, s = self.draft()
        self.store.edit(draft.id, 'Здравствуйте, как настроение?')
        with self.assertRaises(p.ReviewError):
            self.confirm(draft, s)
        updated = self.store.drafts()[0]
        self.confirm(updated, s)
        self.assertEqual(self.sender.call_args.args[1], updated.text)

    def test_invalid_edits_and_rejection(self):
        draft, s = self.draft()
        for text in ('', ' ', 'x'*4097, 'x\x00y', None):
            with self.assertRaises(p.ReviewError):
                self.store.edit(draft.id, text)
        self.store.reject(draft.id)
        self.assertEqual(self.store.ingest(s), 'manual_review')
        with self.assertRaises(p.ReviewError):
            self.confirm(draft, s)
        self.assertEqual(self.store.drafts(), ())

    def test_greeting_must_match_the_recorded_variant(self):
        s = self.snapshot(self.incoming(), messages=(self.own(1, get_greeting(1)), self.incoming()))
        with self.assertRaises(PolicyError):
            self.store.ingest(s)
        self.assertEqual(self.store.drafts(), ())

    def test_unknown_identity_is_rejected_before_body_read(self):
        backend = Mock()
        backend.identity.return_value = p.Identity('10', '99', '50')
        session = p.ReviewSession(self.store, backend)
        with self.assertRaises(p.ReviewError):
            session.read_once()
        backend.snapshot.assert_not_called()
        backend.submit_reply.assert_not_called()

    def test_session_identity_changed_between_reads(self):
        backend = Mock()
        backend.identity.return_value = p.Identity('10', '20', '50')
        backend.snapshot.return_value = replace(self.snapshot(), peer='21')
        with self.assertRaises(p.ReviewError):
            p.ReviewSession(self.store, backend).read_once()
        self.assertEqual(self.store.drafts(), ())

    def test_session_confirm_revalidates_freshly(self):
        draft, s = self.draft()
        backend = Mock()
        backend.identity.return_value = draft.identity
        backend.snapshot.return_value = s
        backend.submit_reply.return_value = True
        session = p.ReviewSession(self.store, backend)
        with self.assertRaises(p.ReviewError):
            session.confirm(draft)
        backend.snapshot.assert_not_called()
        self.assertEqual(session.confirm(draft, approved=True), 'handler_returned')
        backend.submit_reply.assert_called_once()

    def test_session_different_open_chat_is_not_read_for_confirmation(self):
        draft, _ = self.draft()
        backend = Mock()
        backend.identity.return_value = p.Identity('10', '21', '51')
        with self.assertRaises(p.ReviewError):
            p.ReviewSession(self.store, backend).confirm(draft, approved=True)
        backend.snapshot.assert_not_called()

    def test_draft_chat_mapping_is_pinned_after_greeting_verification(self):
        self.draft()
        with self.assertRaises(p.ReviewError):
            self.store.ingest(self.snapshot(self.incoming(), chat='999'))
        with self.assertRaises(p.ReviewError):
            self.store.authorize(p.Identity('10', '21', '999'))

    def test_partial_history_and_unverified_order_rejected(self):
        for flags in (dict(fully_loaded=False), dict(loading=True), dict(samples=1),
                      dict(identity_verified=False), dict(chronological=False)):
            with self.assertRaises(PolicyError):
                self.store.ingest(self.snapshot(self.incoming(), **flags))
        self.assertEqual(self.store.drafts(), ())

    def test_refusal_overrides_contact_and_cancels_old_draft(self):
        self.draft()
        s = self.snapshot(self.incoming(), self.incoming(3, 'Не пиши мне @test_user'))
        self.assertEqual(self.store.ingest(s), 'declined')
        self.assertEqual(self.store.drafts(), ())
        notify = Mock()
        self.assertEqual(self.store.notify_one(notify), 'nothing_pending')
        notify.assert_not_called()

    def test_negative_or_nontext_needs_manual_review(self):
        for peer, text in (('21', 'Плохо'), ('22', None), ('23', '')):
            s = self.snapshot(Message('2', peer, text), peer=peer, chat=str(int(peer)+30))
            self.assertEqual(self.store.ingest(s), 'manual_review')
        self.assertEqual(self.store.drafts(), ())

    def test_contact_can_arrive_before_first_question(self):
        self.draft()
        s = self.snapshot(self.incoming(), self.incoming(3, '+7 (999) 123-45-67'))
        self.assertEqual(self.store.ingest(s), 'contact_saved')
        self.assertEqual(self.store.drafts(), ())
        notify = Mock(return_value=True)
        self.store.notify_one(notify)
        self.assertEqual(notify.call_args.args[0]['contacts'], ['+79991234567'])

    def test_private_envelope_and_counts_only_summary(self):
        s = self.snapshot(self.incoming(text='SECRET-BODY @test_user'))
        self.store.ingest(s)
        self.store.db.execute('PRAGMA wal_checkpoint(FULL)')
        raw = self.path.read_bytes()
        for value in (b'SECRET-BODY', b'@test_user', b'Synthetic Name'):
            self.assertNotIn(value, raw)
            self.assertNotIn(value.decode(), json.dumps(self.store.summary()))

    def test_no_plaintext_fallback_on_encryption_failure(self):
        self.store.seal = Mock(side_effect=RuntimeError('PRIVATE'))
        self.assertEqual(self.store.ingest(self.snapshot(self.incoming(text='@test_user'))), 'contact_storage_unavailable')
        self.assertEqual(self.store.summary()['notifications'], {'blocked': 1})
        self.assertEqual(self.store.ingest(self.snapshot(self.incoming())), 'done')
        notify = Mock()
        self.assertEqual(self.store.notify_one(notify), 'nothing_pending')
        notify.assert_not_called()

    def test_notify_unknown_never_retried(self):
        self.store.ingest(self.snapshot(self.incoming(text='@test_user')))
        notify = Mock(side_effect=OSError('PRIVATE'))
        self.assertEqual(self.store.notify_one(notify), 'unknown')
        self.restart()
        self.assertEqual(self.store.notify_one(notify), 'nothing_pending')
        notify.assert_called_once()

    def test_crash_after_send_reservation_does_not_repeat(self):
        draft, s = self.draft()
        self.sender.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.confirm(draft, s)
        self.restart()
        self.assertEqual(self.store.ingest(s), 'await_outgoing_observation')
        with self.assertRaises(p.ReviewError):
            self.confirm(draft, s)
        self.sender.assert_called_once()

    def test_reservation_is_durable_before_sender_called(self):
        draft, s = self.draft()
        def send(*args):
            with closing(sqlite3.connect(self.path)) as other:
                self.assertEqual(other.execute('SELECT status FROM review_drafts').fetchone()[0], 'attempted')
                self.assertEqual(other.execute('SELECT stage FROM review_dialogs WHERE peer=\'20\'').fetchone()[0], 'pending_question')
            return True
        self.store.confirm(draft, s, send, approved=True)

    def test_existing_source_cannot_be_used_as_output(self):
        for path in (self.source, Path(str(self.source)+'-wal'), Path(str(self.source)+'-shm')):
            with self.assertRaises(p.ReviewError):
                p.ReviewStore(self.source, path)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.original)

    def test_different_source_cohort_cannot_rebind_existing_review(self):
        db = sqlite3.connect(self.source)
        db.execute("UPDATE bindings SET peer='99' WHERE attempt=7")
        db.commit()
        db.close()
        with self.assertRaises(p.ReviewError):
            self.open()

    def test_incomplete_source_and_mixed_accounts_rejected(self):
        db = sqlite3.connect(self.source)
        db.execute("UPDATE cohort SET state='reserved'")
        db.commit()
        with self.assertRaises(p.ReviewError):
            p.load_bindings(self.source)
        db.execute("UPDATE cohort SET state='closed'")
        db.execute("UPDATE bindings SET account='11' WHERE attempt=7")
        db.commit()
        db.close()
        with self.assertRaises(p.ReviewError):
            p.load_bindings(self.source)

    def test_missing_journal_is_not_created(self):
        missing = self.folder / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError):
            p.load_bindings(missing)
        self.assertFalse(missing.exists())

    def test_unexpected_manual_outgoing_stops(self):
        s = self.snapshot(self.incoming(), self.own(3, 'Ручной ответ'))
        self.assertEqual(self.store.ingest(s), 'manual_review')
        self.assertEqual(self.store.drafts(), ())

    def test_duplicate_callback_after_confirmation_cannot_send_twice(self):
        draft, s = self.draft()
        self.confirm(draft, s)
        with self.assertRaises(p.ReviewError):
            self.confirm(draft, s)
        self.sender.assert_called_once()


if __name__ == '__main__':
    unittest.main()
