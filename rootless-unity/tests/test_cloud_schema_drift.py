"""Cloud schema drift: a restored or reset dataset must not brick the run."""
import os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

import cloud_database as cloud
from cloud_sql import schema_info

DDL='CREATE TABLE IF NOT EXISTS chain_seen(chat TEXT,message TEXT,fingerprint TEXT,PRIMARY KEY(chat,message))'

class Rows:
    description=('relname',)
    def __init__(self,rows=()):self.rows=list(rows);self.rowcount=len(self.rows)
    def fetchall(self):return list(self.rows)
    def fetchone(self):return next(iter(self.rows),None)

class ScriptedRaw:
    closed=False
    def __init__(self,catalog_rows,schema_rows,meta_row):
        self.catalog=catalog_rows;self.schema=schema_rows;self.meta=meta_row;self.queries=[]
    def execute(self,sql,params=None,**kwargs):
        self.queries.append((sql,params))
        if 'pg_class' in sql:return Rows(self.catalog)
        if 'SELECT name,sqlite_sql' in sql and '_dvk_schema' in sql:return Rows(self.schema)
        if '_dvk_meta' in sql:return Rows([self.meta])
        return Rows()
    def close(self):self.closed=True

def config():
    return dict(format=cloud.FORMAT,host='aws-0-eu-west-1.pooler.supabase.com',port=5432,database='postgres',
        user='dvk_app_0123abcd.'+'a'*20,password='x'*48,schema=cloud.SCHEMA,dataset='b'*32,source_sha256='c'*64)

def connect_with(raw):
    with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,LOCALAPPDATA=folder,DVK_MORELOGIN='0'):
        root=Path(folder)/'DvkAssistant';root.mkdir();(root/'database.dpapi').write_bytes(b'stub')
        path=root/'assistant.sqlite3'
        with patch('cloud_database.load',return_value=config()),patch('cloud_database.raw_connect',return_value=raw):
            return cloud.connect(path)

class PhantomCatalogTests(unittest.TestCase):
    def test_registered_but_missing_table_is_not_trusted(self):
        raw=ScriptedRaw(
            catalog_rows=[('manual_actions',)],
            schema_rows=[('chain_seen',DDL),('manual_actions','CREATE TABLE IF NOT EXISTS manual_actions(id INTEGER PRIMARY KEY)')],
            meta_row=(cloud.PROTOCOL,'b'*32,True))
        db=connect_with(raw)
        # The phantom registration is dropped from the session cache ...
        self.assertNotIn('chain_seen',db.schemas)
        self.assertIn('manual_actions',db.schemas)
        # ... so the next ensure re-runs CREATE instead of silently skipping.
        db.execute('BEGIN IMMEDIATE');db.execute(DDL)
        self.assertTrue(any(q[0].startswith('CREATE TABLE IF NOT EXISTS "chain_seen"') for q in raw.queries))
        self.assertTrue(any('INSERT INTO _dvk_schema' in q[0] for q in raw.queries))
    def test_real_registered_tables_keep_their_cache(self):
        raw=ScriptedRaw(catalog_rows=[('chain_seen',),('manual_actions',)],schema_rows=[('chain_seen',DDL)],meta_row=(cloud.PROTOCOL,'b'*32,True))
        db=connect_with(raw)
        self.assertIn('chain_seen',db.schemas)
        db.execute('BEGIN IMMEDIATE');db.execute(DDL)
        self.assertFalse(any(q[0].startswith('CREATE TABLE') for q in raw.queries))
    def test_meta_checks_still_fail_closed(self):
        raw=ScriptedRaw(catalog_rows=[],schema_rows=[],meta_row=(cloud.PROTOCOL,'b'*32,False))
        with self.assertRaises(cloud.CloudDatabaseError) as caught:connect_with(raw)
        self.assertEqual(caught.exception.code,'cloud-dataset-not-ready')

PREFIX='i'+'a'*20+'_m5563__'
SCOPE_DDL='CREATE TABLE IF NOT EXISTS mumu_installation_scopes(device TEXT PRIMARY KEY,prefix TEXT NOT NULL UNIQUE)'
TARGET_DDL='CREATE TABLE IF NOT EXISTS '+PREFIX+'chain_seen(chat TEXT,message TEXT,fingerprint TEXT,PRIMARY KEY(chat,message))'

def scripted_scope_raw(real_tables,registered):
    rows=ScriptedRaw(catalog_rows=real_tables,schema_rows=[(PREFIX+'chain_seen',TARGET_DDL)] if registered else [],meta_row=(cloud.PROTOCOL,'b'*32,True))
    original=ScriptedRaw.execute
    def execute(sql,params=None,**kwargs):
        if 'FROM mumu_installation_scopes' in sql and 'SELECT prefix' in sql:return Rows([(PREFIX,)])
        return original(rows,sql,params,**kwargs)
    rows.execute=execute
    return rows

class NamespaceScopeHealTests(unittest.TestCase):
    def prepare(self,raw):
        db=cloud.Connection(raw,{},{})
        # Global scope tables already registered: their CREATEs stay skipped.
        db.schemas['mumu_installation_scopes']=schema_info(SCOPE_DDL)
        db.schemas['mumu_account_owners']=schema_info('CREATE TABLE IF NOT EXISTS mumu_account_owners(account TEXT PRIMARY KEY,device TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')  # SharedStore initialization runs inside one writer transaction.
        return db
    def finish(self,db):
        db.execute('COMMIT')
    def test_changed_prefix_fails_closed(self):
        from assistant_store import StateError
        from mumu_namespace import initialize
        raw=scripted_scope_raw(real_tables=[],registered=True)
        db=self.prepare(raw)
        with self.assertRaises(StateError):initialize(db,'dev','m5563__','legacy',('chain_seen',))
        db.execute('ROLLBACK')
    def test_heal_runs_for_matching_scope(self):
        from mumu_namespace import initialize
        raw=scripted_scope_raw(real_tables=[],registered=True)
        db=self.prepare(raw)
        initialize(db,'dev',PREFIX,'legacy',('chain_seen',))
        self.assertTrue(any(q[0].startswith('CREATE TABLE IF NOT EXISTS "'+PREFIX+'chain_seen"') for q in raw.queries))
        self.assertTrue(any('INSERT INTO _dvk_schema' in q[0] for q in raw.queries))
        self.assertIn(PREFIX+'chain_seen',db.pending)
        self.finish(db)
        self.assertIn(PREFIX+'chain_seen',db.schemas)
    def test_real_tables_are_not_touched(self):
        from mumu_namespace import initialize
        raw=scripted_scope_raw(real_tables=[(PREFIX+'chain_seen',)],registered=True)
        db=self.prepare(raw)
        initialize(db,'dev',PREFIX,'legacy',('chain_seen',))
        self.assertFalse(any('CREATE TABLE' in q[0] for q in raw.queries))
        self.assertEqual(db.pending,{})
        self.finish(db)
    def test_unregistered_tables_are_left_to_ensure(self):
        from mumu_namespace import initialize
        raw=scripted_scope_raw(real_tables=[],registered=False)
        db=self.prepare(raw)
        initialize(db,'dev',PREFIX,'legacy',('chain_seen',))
        self.assertFalse(any('CREATE TABLE IF NOT EXISTS "'+PREFIX in q[0] for q in raw.queries))
        self.assertEqual(db.pending,{})
        self.finish(db)
    def test_rollback_discards_healed_registration(self):
        from mumu_namespace import initialize
        raw=scripted_scope_raw(real_tables=[],registered=True)
        db=self.prepare(raw)
        initialize(db,'dev',PREFIX,'legacy',('chain_seen',))
        self.assertIn(PREFIX+'chain_seen',db.pending)
        db.execute('ROLLBACK')
        self.assertNotIn(PREFIX+'chain_seen',db.schemas)
        self.assertEqual(db.pending,{})
    def test_sqlite_path_stays_lazy(self):
        from mumu_namespace import initialize
        db=sqlite3.connect(':memory:')
        try:
            db.execute('CREATE TABLE mumu_installation_scopes(device TEXT PRIMARY KEY,prefix TEXT NOT NULL UNIQUE)')
            db.execute('INSERT INTO mumu_installation_scopes VALUES(?,?)',('dev',PREFIX))
            initialize(db,'dev',PREFIX,'legacy',('chain_seen',))
            self.assertIsNone(db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(PREFIX+'chain_seen',)).fetchone())
        finally:db.close()

if __name__=='__main__':unittest.main()
