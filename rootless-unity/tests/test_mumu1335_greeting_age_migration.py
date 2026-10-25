"""Greeting age must not stand in for the age of an unanswered peer message."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import assistant_reply_window as window
from assistant_store import Store
from mumu_store import SharedStore
from mumu_peer_policy import ensure_communication_allowed, PeerCommunicationBlocked
from test_inbox_profiles import WHO


class AgeMigration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.db';self.old=Path(self.tmp.name)/'old'
        self.store=Store(self.path,self.old)
        window.enable(self.store)
        self.store.reserve(dict(attempt=1,account=WHO['account'],peer=WHO['peer'],chat='-1',variant=0),'Synthetic',approved=True)

    def test_legacy_age_exclusion_removed_without_touching_unknown_journal(self):
        with self.store.connection() as db:
            before=db.execute('SELECT * FROM manual_actions').fetchall()
        for reason in window.LEGACY_AGE_REASONS:
            with self.store.connection() as db:
                db.execute('INSERT OR REPLACE INTO inbox_reply_exclusions VALUES(?,?,?)',(WHO['account'],WHO['peer'],reason))
            self.assertIsNone(window.reason(self.store,WHO))
            self.assertEqual(window.eligible(self.store,[WHO]),[WHO])
            with self.store.connection() as db:
                self.assertEqual(db.execute('SELECT * FROM manual_actions').fetchall(),before)
                self.assertEqual(db.execute('SELECT * FROM inbox_reply_exclusions').fetchall(),[])

    def test_startup_migration_preserves_explicit_new_start(self):
        with self.store.connection() as db:
            db.execute('INSERT INTO inbox_reply_exclusions VALUES(?,?,?)',(WHO['account'],WHO['peer'],'reply-window-expired'))
            db.execute("INSERT INTO inbox_reply_exclusions VALUES('100','201','new-start-excluded')")
        window.enable(self.store)
        self.assertIsNone(window.reason(self.store,WHO))
        self.assertEqual(window.reason(self.store,dict(WHO,peer='201')),'new-start-excluded')

    def test_clock_or_missing_greeting_time_never_invents_peer_message_age(self):
        with self.store.connection() as db:
            db.execute("UPDATE manual_actions SET created_at='invalid'")
        clock=lambda: (_ for _ in ()).throw(AssertionError('Not incoming sent_at'))
        self.assertIsNone(window.reason(self.store,WHO,clock=clock))
        with patch.object(window.time,'time',side_effect=AssertionError('Not message time')):
            self.assertEqual(window.eligible(self.store,[WHO]),[WHO])

    def test_policy_is_explicitly_not_claiming_actual_incoming_timestamp_support(self):
        from pathlib import Path
        source=(Path(__file__).resolve().parents[1]/'build_manifest.py').read_text()
        self.assertIn('incoming_message_time_verified=False',source)
        self.assertIn('reply_window_seconds=None',source)
        self.assertNotIn('durable-first-greeting-reservation-utc',source)


class SharedMigration(unittest.TestCase):
    def test_port_scoped_age_cleanup_never_removes_global_deny_or_other_port_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db';old=Path(temp)/'old'
            a=SharedStore(path,old,device_port=5563);b=SharedStore(path,old,device_port=5557)
            for store in (a,b):
                window.enable(store)
                with store.connection() as db:
                    db.execute('INSERT INTO inbox_reply_exclusions VALUES(?,?,?)',(WHO['account'],WHO['peer'],'reply-window-expired'))
            with a.connection() as db:
                a.record_peer_outcome(db,WHO,'manual-block')
            window.enable(a)
            with a.connection() as db:self.assertEqual(db.execute('SELECT * FROM inbox_reply_exclusions').fetchall(),[])
            with b.connection() as db:
                self.assertEqual(db.execute('SELECT reason FROM inbox_reply_exclusions').fetchall(),[('reply-window-expired',)])
                self.assertEqual(db.execute('SELECT peer,reason FROM mumu_peer_blocks').fetchall(),[(WHO['peer'],'manual-block')])
            for store in (a,b):
                with self.assertRaises(PeerCommunicationBlocked):ensure_communication_allowed(store,WHO)
