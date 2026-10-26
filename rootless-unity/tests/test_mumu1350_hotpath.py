"""Hot-path query/process budgets; no live chats, API requests or timing claims."""
import json,os,sqlite3,tempfile,threading,unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch,MagicMock
from assistant_store import Store
from assistant_inbox import InboxChain,with_seen_ids,inbox_targets
from assistant_profiles import Session
from assistant_history_wait import initialize as history_tables
from assistant_reply_window import enable,eligible_groups
from test_assistant import pending
from test_mumu_fast_adb import Sock,TARGET,BOOT_ID,BOOT,TestError
import test_mumu_fast_adb as harness
import mumu_fast_adb as adb_fast
from target_only import TargetOnlyAdb,preflight,recheck

class Database(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db')
    @contextmanager
    def traced(self):
        import cloud_database
        original=cloud_database.connect;sql=[]
        def connect(*a,**kw):
            db=original(*a,**kw);db.set_trace_callback(sql.append);return db
        with patch('cloud_database.connect',side_effect=connect):yield sql
    def test_warm_components_have_no_schema_transactions(self):
        InboxChain(self.store);Session(self.store);history_tables(self.store)
        with self.traced() as sql:
            for _ in range(10):InboxChain(self.store);Session(self.store);history_tables(self.store)
        self.assertEqual(sql,[])
    def test_new_store_runs_initializer_again_and_schema_cache_is_not_rows(self):
        statement='CREATE TABLE IF NOT EXISTS synthetic_schema_test(id INTEGER)'
        self.store.ensure_tables(statement)
        other=Store(self.store.path)
        with self.traced() as sql:other.ensure_tables(statement)
        self.assertIn('BEGIN IMMEDIATE',sql)
        with self.store.connection() as db:db.execute('INSERT INTO synthetic_schema_test VALUES(1)')
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT * FROM synthetic_schema_test').fetchall(),[(1,)])
    def test_rolled_back_initializer_is_not_cached(self):
        original=self.store.connection
        @contextmanager
        def fail():
            with original() as db:
                yield db
                raise OSError('synthetic commit failure')
        statement='CREATE TABLE IF NOT EXISTS retry_schema_test(id INTEGER)'
        with patch.object(self.store,'connection',fail),self.assertRaises(OSError):self.store.ensure_tables(statement)
        with self.traced() as sql:self.store.ensure_tables(statement)
        self.assertIn(statement,sql)
    def test_schema_initialization_serializes_only_this_store(self):
        calls=[];original=self.store.connection
        @contextmanager
        def counted():
            calls.append(1)
            with original() as db:yield db
        errors=[]
        def run():
            try:self.store.ensure_tables('CREATE TABLE IF NOT EXISTS concurrent_schema_test(id INTEGER)')
            except Exception as e:errors.append(e)
        with patch.object(self.store,'connection',counted):
            threads=[threading.Thread(target=run) for _ in range(8)]
            for t in threads:t.start()
            for t in threads:t.join(5)
        self.assertFalse(errors);self.assertEqual(len(calls),1)
    def test_read_interface_is_fresh_and_rejects_writes(self):
        Session(self.store).set('city','Synthetic')
        with self.traced() as sql:
            self.assertEqual(Session(self.store).get('city'),'Synthetic')
            self.store.summary()
        self.assertEqual(sql.count('BEGIN'),2);self.assertNotIn('BEGIN IMMEDIATE',sql)
        with self.assertRaises(sqlite3.OperationalError):
            with self.store.read_connection() as db:db.execute('DELETE FROM search_session')
        Session(self.store).set('city','Changed')
        self.assertEqual(Session(self.store).get('city'),'Changed')
    def test_draft_restoration_and_authorization_do_not_take_writer_lock(self):
        from assistant_ai_drafts import restore
        self.store.reserve(pending(),'Hi',approved=True);chain=InboxChain(self.store)
        who=dict(account='100',peer='200',chat='300')
        with self.traced() as sql:
            self.assertIsInstance(chain.authorized(who),str)
            self.assertIsNone(restore(chain,'300','question','hash'))
        self.assertNotIn('BEGIN IMMEDIATE',sql)
        with self.store.connection() as db:db.execute("UPDATE manual_actions SET status='not-invoked'")
        from assistant_store import StateError
        with self.assertRaises(StateError):chain.authorized(who)
    def test_seen_id_scan_is_readonly_after_one_time_schema_warmup(self):
        chain=InboxChain(self.store);who=dict(account='100',peer='200',chat='300')
        with_seen_ids(chain,[who])
        with self.traced() as sql:self.assertEqual(with_seen_ids(chain,[who]),[dict(who,seen_ids=[])])
        self.assertNotIn('BEGIN IMMEDIATE',sql);self.assertFalse(any(q.startswith('CREATE') for q in sql))
    def test_exclusions_share_one_fresh_snapshot_without_losing_legacy_migration(self):
        enable(self.store);one=dict(account='100',peer='200',chat='300');two=dict(account='100',peer='201',chat='301')
        with self.store.connection() as db:
            db.execute("INSERT INTO inbox_reply_exclusions VALUES('100','200','new-start-excluded')")
            db.execute("INSERT INTO inbox_reply_exclusions VALUES('100','201','reply-window-expired')")
        with self.traced() as sql:self.assertEqual(eligible_groups(self.store,[one],[two]),([],[two]))
        self.assertEqual(sql.count('BEGIN IMMEDIATE'),1)
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT peer FROM inbox_reply_exclusions').fetchall(),[('200',)])

class AdbPreparation(unittest.TestCase):
    setUp=harness.WorkerRouting.setUp
    def test_version_only_cache_invalidates_on_executable_change(self):
        original=MagicMock(return_value='Android Debug Bridge synthetic')
        with patch.object(TargetOnlyAdb,'run',original),adb_fast.transport(TARGET,socket_factory=lambda *a,**kw:Sock()) as timings:
            self.adb.run(['version']);self.adb.run(['version'])
            self.assertEqual(original.call_count,1)
            Path(self.adb.executable).write_text('changed executable')
            self.adb.run(['version']);self.assertEqual(original.call_count,2)
            self.assertEqual(timings.snapshot()['version_cache']['calls'],1)
    def test_version_failure_is_not_cached(self):
        original=MagicMock(side_effect=[TestError('synthetic'), 'success'])
        with patch.object(TargetOnlyAdb,'run',original),adb_fast.transport(TARGET,socket_factory=lambda *a,**kw:Sock()):
            with self.assertRaises(TestError):self.adb.run(['version'])
            self.assertEqual(self.adb.run(['version']),'success')
        self.assertEqual(original.call_count,2)
    def test_connected_target_is_freshly_probed_not_cli_reconnected(self):
        sockets=[];original=MagicMock(return_value='local-cli')
        def connect(*a,**kw):s=Sock();sockets.append(s);return s
        with patch.object(TargetOnlyAdb,'run',original),adb_fast.transport(TARGET,socket_factory=connect) as timings:
            for _ in range(2):self.assertEqual(preflight(self.adb),BOOT)
            self.assertEqual(original.call_count,1) # version only; no connect CLI
            self.assertEqual(len(sockets),10) # All original reads PLUS two fresh connect probes.
            self.assertEqual(timings.snapshot()['connect_ready']['calls'],2)
    def test_offline_probe_uses_only_original_exact_target_connect_then_full_preflight(self):
        sockets=[];original=MagicMock(return_value='local-cli')
        def connect(*a,**kw):
            s=Sock(state=b'offline' if not sockets else b'device');sockets.append(s);return s
        with patch.object(TargetOnlyAdb,'run',original),adb_fast.transport(TARGET,socket_factory=connect):
            self.assertEqual(preflight(self.adb),BOOT)
        self.assertEqual([c.args[1] for c in original.call_args_list],[['version'],['connect',TARGET]])
    def test_context_cache_never_survives_a_worker_transport(self):
        original=MagicMock(return_value='version')
        with patch.object(TargetOnlyAdb,'run',original):
            for _ in range(2):
                with adb_fast.transport(TARGET):self.adb.run(['version'])
        self.assertEqual(original.call_count,2)
