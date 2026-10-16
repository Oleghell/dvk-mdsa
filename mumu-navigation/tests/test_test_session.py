import hashlib
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from test_session import TestSession, SessionError


def fp(n):
    return hashlib.sha256(str(n).encode()).hexdigest()

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'test.sqlite'
        self.s = TestSession(self.path)
    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()
    def draft(self, n=1):
        self.s.begin_visit()
        self.s.transition(('opening',), 'chat_opening')
        self.assertTrue(self.s.bind_empty_chat(fp(n)))
        self.s.reserve_input(fp(n), n % 10)
        self.s.finish_input(fp(n), 'draft_verified')
    def send(self, n=1):
        self.draft(n)
        self.s.transition(('draft_native',), 'finish_reserved')
        self.s.transition(('finish_reserved',), 'draft_finished')
        self.s.reserve_send()
        self.s.send_injected()
        self.s.observe_sent()
        self.s.returned()
    def test_no_autostart(self):
        self.assertEqual(self.s.status()['state'],'not_started')
        with self.assertRaises(SessionError): self.s.begin_visit()
    def test_targets_are_finite(self):
        for value in [0,6,True,'5',None,-1]:
            with self.subTest(value=value),self.assertRaises(SessionError): self.s.start(value)
    def test_five_visits_stop_with_separate_counters(self):
        self.s.start(5)
        self.send(1)
        for _ in range(4):
            self.s.begin_visit();self.s.skip();self.s.returned()
        out=self.s.status()
        self.assertEqual((out['visited'],out['input_attempts'],out['send_attempts'],out['sent_observed_by_agent'],out['skipped']),(5,1,1,1,4))
        self.assertEqual(out['state'],'completed')
        with self.assertRaises(SessionError):self.s.begin_visit()
    def test_four_remaining_is_explicit_local_target(self):
        self.s.start(4)
        self.assertEqual(self.s.status()['remaining'],4)
    def test_skips_count_toward_target(self):
        self.s.start(1);self.s.begin_visit();self.s.skip();self.s.returned()
        self.assertEqual(self.s.status()['state'],'completed')
        self.assertEqual(self.s.status()['input_attempts'],0)
    def test_restart_resumes_same_run(self):
        first=self.s.start(5)['run_id'];self.s.begin_visit();self.s.skip();self.s.returned()
        other=TestSession(self.path)
        try:
            self.assertEqual(other.status()['run_id'],first)
            self.assertEqual(other.status()['remaining'],4)
            with self.assertRaises(SessionError):other.start(5)
        finally:other.close()
    def test_no_two_current_visits(self):
        self.s.start(5);self.s.begin_visit()
        with self.assertRaises(SessionError):self.s.begin_visit()
    def test_input_attempt_committed_before_device(self):
        self.s.start(5);self.s.begin_visit();self.s.transition(('opening',),'chat_opening');self.s.bind_empty_chat(fp(1));self.s.reserve_input(fp(1),0)
        self.assertEqual(self.s.status()['input_attempts'],1)
        other=TestSession(self.path)
        try:
            self.assertTrue(other.status()['manual_review_required'])
            with self.assertRaises(SessionError):other.start(5)
            with self.assertRaises(SessionError):other.reserve_input(fp(2),0)
        finally:other.close()
    def test_send_attempt_committed_before_device(self):
        self.s.start(5);self.draft();self.s.transition(('draft_native',),'draft_finished');self.s.reserve_send()
        self.assertEqual(self.s.status()['send_attempts'],1)
        other=TestSession(self.path)
        try:self.assertTrue(other.status()['manual_review_required'])
        finally:other.close()
    def test_finish_back_crash_holds(self):
        self.s.start(5);self.draft();self.s.transition(('draft_native',),'finish_reserved')
        other=TestSession(self.path)
        try:self.assertTrue(other.status()['manual_review_required'])
        finally:other.close()
    def test_unreviewed_injected_send_does_not_resume_after_restart(self):
        self.s.start(5);self.draft();self.s.transition(('draft_native',),'draft_finished');self.s.reserve_send();self.s.send_injected()
        other=TestSession(self.path)
        try:
            self.assertTrue(other.status()['manual_review_required'])
            self.assertEqual(other.status()['sent_observed_by_agent'],0)
        finally:other.close()
    def test_injection_not_observed_send(self):
        self.s.start(5);self.draft();self.s.transition(('draft_native',),'draft_finished');self.s.reserve_send();self.s.send_injected()
        self.assertEqual(self.s.status()['sent_observed_by_agent'],0)
        with self.assertRaises(SessionError):self.s.reserve_send()
        with self.assertRaises(SessionError):self.s.begin_visit()
    def test_duplicate_persists_across_explicit_tests(self):
        self.s.start(1);self.send(1);self.s.start(1);self.s.begin_visit();self.s.transition(('opening',),'chat_opening')
        self.assertFalse(self.s.bind_empty_chat(fp(1)))
        with self.assertRaises(SessionError):self.s.reserve_input(fp(1),0)
        self.s.returned()
        self.assertEqual(self.s.status()['skipped'],1)
    def test_wrong_profile_cannot_consume_input(self):
        self.s.start(5);self.s.begin_visit();self.s.transition(('opening',),'chat_opening');self.s.bind_empty_chat(fp(1))
        with self.assertRaises(SessionError):self.s.reserve_input(fp(2),0)
        self.assertEqual(self.s.used(),0)
    def test_variant_is_validated(self):
        self.s.start(5);self.s.begin_visit();self.s.transition(('opening',),'chat_opening');self.s.bind_empty_chat(fp(1))
        for variant in [True,-1,10,'Привет']:
            with self.subTest(variant=variant),self.assertRaises(SessionError):self.s.reserve_input(fp(1),variant)
    def test_unknown_halts_across_runs(self):
        self.s.start(5);self.s.begin_visit();self.s.unknown()
        with self.assertRaises(SessionError):self.s.start(5)
        self.assertTrue(self.s.status()['manual_review_required'])
    def test_input_refusal_counts_but_is_not_send(self):
        self.s.start(1);self.s.begin_visit();self.s.transition(('opening',),'chat_opening');self.s.bind_empty_chat(fp(1));self.s.reserve_input(fp(1),0);self.s.finish_input(fp(1),'refused');self.s.returned()
        out=self.s.status();self.assertEqual((out['input_attempts'],out['send_attempts'],out['skipped']),(1,0,1))
    def test_no_skip_after_draft(self):
        self.s.start(5);self.draft()
        with self.assertRaises(SessionError):self.s.skip()
    def test_no_return_before_outcome(self):
        self.s.start(5);self.draft()
        with self.assertRaises(SessionError):self.s.returned()
    def test_legacy_read_only_import_preserves_bytes_and_five_attempts(self):
        legacy=Path(self.tmp.name)/'legacy.sqlite'
        c=sqlite3.connect(legacy);c.execute('CREATE TABLE attempts(fingerprint TEXT PRIMARY KEY,state TEXT)')
        for n in range(5):c.execute('INSERT INTO attempts VALUES (?,?)',(fp(n),'draft_verified'))
        c.commit();c.close();before=legacy.read_bytes()
        other=TestSession(Path(self.tmp.name)/'migrated.sqlite',legacy)
        try:
            self.assertEqual(legacy.read_bytes(),before)
            self.assertEqual(other.db.execute('SELECT COUNT(*) FROM contacts').fetchone()[0],5)
            self.assertEqual(other.status()['state'],'not_started')
            other.start(4);other.begin_visit();other.transition(('opening',),'chat_opening')
            self.assertFalse(other.bind_empty_chat(fp(1)))
            self.assertEqual(other.status()['sent_observed_by_agent'],0)
        finally:other.close()
    def test_legacy_unknown_blocks_new_test(self):
        legacy=Path(self.tmp.name)/'legacy.sqlite';c=sqlite3.connect(legacy);c.execute('CREATE TABLE attempts(fingerprint TEXT,state TEXT)');c.execute('INSERT INTO attempts VALUES (?,?)',(fp(1),'unknown'));c.commit();c.close()
        other=TestSession(Path(self.tmp.name)/'migrated.sqlite',legacy)
        try:
            with self.assertRaises(SessionError):other.start(5)
        finally:other.close()
    def test_invalid_legacy_fails_closed(self):
        legacy=Path(self.tmp.name)/'bad.sqlite';legacy.write_bytes(b'not a database')
        with self.assertRaises(SessionError):TestSession(Path(self.tmp.name)/'new.sqlite',legacy)
    def test_missing_legacy_does_not_create_file(self):
        missing=Path(self.tmp.name)/'absent.sqlite';other=TestSession(Path(self.tmp.name)/'new.sqlite',missing)
        other.close();self.assertFalse(missing.exists())
    def test_no_messages_or_names_persisted(self):
        self.s.start(1);self.send()
        data=self.path.read_bytes()
        for secret in ['Привет','private-recipient-name','Bearer','trycloudflare']:
            self.assertNotIn(secret.encode(),data)
    def test_two_connections_cannot_claim_same_slot(self):
        self.s.start(1)
        errors=[];success=[];barrier=threading.Barrier(2)
        def claim():
            c=TestSession(self.path)
            try:
                barrier.wait()
                try:success.append(c.begin_visit())
                except SessionError:errors.append(True)
            finally:c.close()
        ts=[threading.Thread(target=claim) for _ in range(2)]
        for t in ts:t.start()
        for t in ts:t.join()
        self.assertEqual((len(success),len(errors)),(1,1))

if __name__=='__main__':unittest.main()
