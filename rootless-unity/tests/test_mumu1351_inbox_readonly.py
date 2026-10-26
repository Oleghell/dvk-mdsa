"""215-219: exercise the actual cloud guard at the full inbox target entry."""
import tempfile,unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
import cloud_database as cloud
from assistant_store import Store
from assistant_inbox import InboxChain,inbox_targets
from test_assistant import pending

class Raw:
    closed=False
    def __init__(self):self.queries=[]
    def execute(self,sql,params=None,**kwargs):
        self.queries.append(sql)
        class Result:
            description=[('synthetic',)];rowcount=0
            def fetchall(self):
                if sql.lstrip().startswith('SELECT s.account'):
                    return [('100','200','300',None,False,False,False)]
                return []
        return Result()
    def close(self):self.closed=True

class InboxReadonly(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db');self.chain=InboxChain(self.store)
    def test_real_cloud_guard_accepts_entire_target_builder_without_writer_lock(self):
        raws=[]
        @contextmanager
        def readonly():
            raw=Raw();raws.append(raw);db=cloud.Connection(raw,{},{});
            try:
                db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
                yield db
                db.execute('COMMIT')
            finally:
                if db.in_transaction:db.execute('ROLLBACK')
                db.close()
        with patch.object(self.store,'read_connection',readonly):
            attention,unread=inbox_targets(self.chain)
        self.assertEqual(attention,[])
        self.assertEqual(unread,[dict(account='100',peer='200',chat='300')])
        queries=[q for raw in raws for q in raw.queries]
        self.assertTrue(any(q.startswith('SELECT s.account') for q in queries))
        self.assertTrue(any('READ ONLY' in q for q in queries))
        self.assertFalse(any('pg_advisory_xact_lock' in q for q in queries))
        self.assertFalse(any(q.lstrip().startswith(('INSERT','UPDATE','DELETE','CREATE')) for q in queries))
    def test_readonly_guard_not_relaxed_to_allow_writes_or_arbitrary_ctes(self):
        raw=Raw();db=cloud.Connection(raw,{},{});db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        prior=len(raw.queries)
        for sql in ('DELETE FROM x','UPDATE x SET y=1','INSERT INTO x VALUES(1)',
                    'WITH removed AS (DELETE FROM x RETURNING *) SELECT * FROM removed'):
            with self.subTest(sql=sql),self.assertRaisesRegex(cloud.CloudDatabaseError,'cloud-readonly-violation'):db.execute(sql)
        self.assertEqual(len(raw.queries),prior);db.execute('ROLLBACK')
    def test_source_precedence_pending_and_terminal_filters_remain_identical(self):
        for peer in ('200','201','202','203'):
            action=self.store.reserve(pending(peer=peer),'Hi',approved=True)
            self.store.finish(action,dict(send_attempted=peer!='201',send_handler_returned=peer!='201'))
        with self.store.connection() as db:
            db.execute("INSERT INTO guided_bindings VALUES('100','200','300','hash')")
            db.execute("INSERT INTO chain_dialogs VALUES('100','202','302','1','pending-question','salt')")
            db.execute("INSERT INTO chain_dialogs VALUES('100','203','303','1','done','salt')")
        attention,unread=inbox_targets(self.chain)
        self.assertEqual(attention,[dict(account='100',peer='202',chat='302')])
        self.assertEqual(unread,[dict(account='100',peer='200',chat='300')])
