"""Query-count regressions; synthetic data, no cloud, Android, contacts or sends."""
import tempfile,unittest,json
from pathlib import Path
from contextlib import contextmanager
from assistant_store import Store,StateError
from assistant_inbox import InboxChain,with_seen_ids
from assistant_reply_window import enable,eligible
from assistant_contact_receipt import candidates,reviewable
from assistant_reply_audit import initialize as replies
from assistant_skip_audit import initialize as skips

class CountedStore:
    def __init__(self,store):self.store=store;self.queries=[]
    def __getattr__(self,key):return getattr(self.store,key)
    @contextmanager
    def connection(self):
        with self.store.connection() as db:
            outer=self
            class Proxy:
                def __getattr__(self,n):return getattr(db,n)
                def execute(self,sql,params=()):outer.queries.append(sql);return db.execute(sql,params)
            yield Proxy()

class InboxBatchQueries(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=CountedStore(Store(Path(self.tmp.name)/'assistant.sqlite3'))
        self.chain=InboxChain(self.store);enable(self.store)
    def test_thousand_eligible_rows_use_one_exclusion_key_query(self):
        rows=[dict(account='100',peer=str(200+i),chat=str(2000+i)) for i in range(1000)]
        with self.store.connection() as db:
            db.execute("INSERT INTO inbox_reply_exclusions VALUES('100','201','new-start-excluded')")
            db.execute("INSERT INTO inbox_reply_exclusions VALUES('100','202','reply-window-expired')")
        self.store.queries.clear();out=eligible(self.store,rows)
        self.assertEqual(out,[x for x in rows if x['peer']!='201'])
        self.assertEqual(sum('SELECT account,peer FROM inbox_reply_exclusions' in s for s in self.store.queries),1)
        self.assertFalse(any('SELECT reason FROM' in s for s in self.store.queries))
    def test_receipt_candidates_match_per_chat_guard_without_n_plus_one(self):
        with self.store.connection() as db:
            for i in range(200):
                chat=str(2000+i)
                db.execute('INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)',('100',str(300+i),chat,'1','manual-review','salt'))
                db.execute("INSERT INTO chain_review_reasons VALUES(?,'contact-batch-ambiguous')",(chat,))
                db.execute("INSERT INTO chain_actions VALUES(?,'contact',NULL,'hash','outgoing-observed')",(chat,))
            db.execute("UPDATE chain_review_reasons SET reason='other' WHERE chat='2001'")
            db.execute("UPDATE chain_dialogs SET greeting=NULL WHERE chat='2002'")
        self.store.queries.clear();out=candidates(self.store)
        self.assertEqual(sum(s.lstrip().startswith('SELECT') for s in self.store.queries),1)
        with self.store.connection() as db:
            expected={(a,p,c) for a,p,c in db.execute('SELECT account,peer,chat FROM chain_dialogs') if reviewable(db,c)}
        self.assertEqual(out,expected);self.assertEqual(len(out),198)
    def test_seen_ids_use_bounded_chunks_and_keep_pending_receipts_unseen(self):
        allowed=[dict(account='100',peer=str(300+i),chat=str(2000+i)) for i in range(260)]
        with self.store.connection() as db:
            replies(db);skips(db)
            for who in allowed:
                for m in ('1','2','3'):db.execute('INSERT INTO chain_seen VALUES(?,?,?)',(who['chat'],m,'fp'))
            db.execute("INSERT INTO chain_reply_receipts VALUES('2000','2','fp','pending',NULL)")
        self.store.queries.clear();out=with_seen_ids(self.chain,allowed)
        self.assertEqual(out[0]['seen_ids'],['1','3'])
        self.assertTrue(all(x['seen_ids']==['1','2','3'] for x in out[1:]))
        self.assertEqual(sum('ROW_NUMBER()' in s for s in self.store.queries),3)
    def test_seen_overflow_still_fails_closed(self):
        who=dict(account='100',peer='300',chat='2000')
        with self.store.connection() as db:
            replies(db);skips(db)
            for i in range(129):db.execute('INSERT INTO chain_seen VALUES(?,?,?)',('2000',str(i+1),'fp'))
        with self.assertRaisesRegex(StateError,'observed-history-too-large'):with_seen_ids(self.chain,[who])
    def test_cloud_failure_survives_preparation_and_private_export(self):
        import cloud_database as cloud,run_preparation
        from assistant_error_notify import diagnostic_json
        err=cloud.CloudDatabaseError('cloud-database-lock-timeout');err.operation='lock'
        evidence=run_preparation.record(err,'inbox-targets')
        exported=json.loads(diagnostic_json(dict(last_preparation_failure=evidence)))['diagnostic']['last_preparation_failure']
        self.assertEqual(exported,evidence);self.assertEqual(exported['error_type'],'CloudDatabaseError')
        self.assertEqual(exported['database']['code'],'cloud-database-lock-timeout')
        self.assertIsNone(run_preparation.clean(dict(evidence,database=dict(evidence['database'],password='PRIVATE'))))
