"""Opt-in real Postgres smoke: ONLY session-temporary tables, no sends.

Usage: python smoke_cloud_database.py /private/connection.json
The JSON is never printed. No production dataset activation or mutation.
"""
import json,os,sqlite3,sys,tempfile
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
import cloud_database as cloud
import cloud_migration as migration
from cloud_sql import schema_info
from mumu_store import SharedStore

TEST_LOCK=732489102129

def run(config_path):
    cfg=cloud.validate(json.loads(Path(config_path).read_text()))
    raw=cloud.raw_connect(cfg)
    try:
        raw.execute('CREATE TEMP TABLE _dvk_schema(name TEXT PRIMARY KEY,sqlite_sql TEXT)')
        raw.execute('SET search_path TO pg_temp,pg_catalog')
        class TemporaryConnection(cloud.Connection):
            def close(self):
                if self.in_transaction:self.execute('ROLLBACK')
                self.closed=True
        def connection(*args,**kwargs):
            schemas={n:schema_info(s) for n,s in raw.execute('SELECT name,sqlite_sql FROM _dvk_schema')}
            return TemporaryConnection(raw,cfg,schemas)
        with tempfile.TemporaryDirectory() as folder,patch('mumu_store.connect',connection),patch('cloud_database.connect',connection),patch.object(cloud,'LOCK_ID',TEST_LOCK):
            store=SharedStore(Path(folder)/'assistant.sqlite3',device_port=5559)
            with store.connection() as db:
                cur=db.execute("INSERT OR IGNORE INTO manual_actions(account,peer,initial_chat,text_hash,confirmed,status) VALUES(?,?,?,?,1,'reserved-unknown')",('101','202','303','hash'))
                assert cur.lastrowid>0
                db.execute("INSERT OR REPLACE INTO inbox_reply_policy(key,value) VALUES('smoke',1)")
            from assistant_chain import Chain,step,QUESTIONS,CONTACT_TEXT
            store2=SharedStore(Path(folder)/'assistant.sqlite3',device_port=5563)
            action=store2.reserve(dict(attempt=1,account='100',peer='200',chat='-1',variant=0),'Привет 🙂',approved=True)
            store2.finish(action,dict(send_attempted=True,send_handler_returned=True))
            chain=Chain(store2,choose=lambda:0,contact_notifications=False)
            who=dict(account='100',peer='200',chat='300')
            messages=[dict(id='1001',sender='100',text='Привет 🙂')];sent=[]
            def snapshot():return dict(identity=who,messages=list(messages))
            def fake_send(before,text):sent.append(text);return dict(attempted=True,handler_returned=True)
            assert step(chain,snapshot(),fake_send)=='wait-reply'
            sequence=[('200','Привет','await-outgoing'),('100',QUESTIONS[0],'wait-mood'),('200','Отлично','await-outgoing'),('100',CONTACT_TEXT,'wait-contact'),('200','Не пиши мне','declined')]
            for index,(sender,text,expected) in enumerate(sequence,1002):
                messages.append(dict(id=str(index),sender=sender,text=text))
                assert step(chain,snapshot(),fake_send)==expected
            assert len(sent)==2
            with store2.connection() as db:
                db.execute('CREATE TABLE IF NOT EXISTS float_test(id TEXT PRIMARY KEY,value REAL)')
                value=float.fromhex('0x1.ab701a79cfa37p+30')
                db.execute('INSERT INTO float_test VALUES(?,?)',('one',value))
                assert db.execute('SELECT value FROM float_test').fetchone()[0].hex()==value.hex()
            # New policies use the same primary transaction, not local caches.
            from mumu_store import SharedPeerClaimed
            person=dict(attempt=1,account='100',peer='9001',chat='-1',variant=0)
            store2.reserve(person,'Synthetic',approved=True)
            assert store.peer_claimed(dict(person,account='101'))
            assert not store.peer_terminal(dict(person,account='101'))
            try:store.reserve(dict(person,account='101'),'Synthetic',approved=True)
            except SharedPeerClaimed:pass
            else:raise AssertionError('Cross-port duplicate greeting authorized')
            import mumu_cities
            names=['Synthetic city '+chr(65+i) for i in range(20)]
            token,allowed,_=mumu_cities.reserve(store,names)
            other_token,other_allowed,_=mumu_cities.reserve(store2,names)
            assert not set(allowed)&set(other_allowed)
            # Strict native-result validation has separate unit/native tests;
            # use their complete synthetic result to exercise PG completion SQL.
            sys.path.insert(0,str(Path(__file__).parent/'tests'))
            from test_search_city import ready_city
            city_value=ready_city()
            city_value['navigation'].update(city_selected_name=allowed[0],city_previous_name=None,city_round_reset=False)
            mumu_cities.complete(store,token,allowed,city_value)
            assert mumu_cities.owns(store,allowed[0])
            # Preview writes must not touch PG, even when the real journal is PG.
            with patch.object(cloud,'readonly',lambda _:connection()):
                with cloud.memory_snapshot(Path(folder)/'assistant.sqlite3',1024*1024) as ram:
                    ram.execute('DELETE FROM manual_actions')
                with store2.connection() as db:assert db.execute('SELECT COUNT(*) FROM manual_actions').fetchone()[0]==2
            # A tiny synthetic SQLite source tests binary/float/NULL migration,
            # latest-local cutover, and refusal to overwrite an active cloud DB.
            source=Path(folder)/'source.sqlite3'
            with sqlite3.connect(source) as db:
                db.executescript('CREATE TABLE manual_actions(id INTEGER PRIMARY KEY,confirmed INTEGER NOT NULL,status TEXT NOT NULL);CREATE TABLE mumu_peer_blocks(peer TEXT PRIMARY KEY);CREATE TABLE chain_actions(chat TEXT PRIMARY KEY,payload BLOB,stamp REAL,optional TEXT);')
                db.execute("INSERT INTO manual_actions VALUES(1,1,'attempted-unknown')")
                db.execute("INSERT INTO mumu_peer_blocks VALUES('original')")
                db.execute('INSERT INTO chain_actions VALUES(?,?,?,?)',('chat',b'\x00\xffopaque',value,None))
            with patch.object(migration,'SCHEMA','pg_temp'),patch.object(migration,'LOCK_ID',TEST_LOCK):
                first=migration.import_source(raw,cfg,source,activate=False)
                assert sum(x['rows'] for x in first)==3
                assert raw.execute('SELECT ready FROM _dvk_meta').fetchone()==(False,)
                # A reset/older local snapshot must not erase known bans.
                with sqlite3.connect(source) as db:db.execute("DELETE FROM mumu_peer_blocks WHERE peer='original'")
                try:migration.import_source(raw,cfg,source,activate=True)
                except cloud.CloudDatabaseError as e:assert e.code=='cloud-local-journal-older-than-upload'
                else:raise AssertionError('Older journal accepted')
                assert raw.execute('SELECT ready FROM _dvk_meta').fetchone()==(False,)
                with sqlite3.connect(source) as db:db.execute("INSERT INTO mumu_peer_blocks VALUES('original')")
                # Fresh data appearing AFTER initial upload is included at cutover.
                with sqlite3.connect(source) as db:db.execute("INSERT INTO mumu_peer_blocks VALUES('fresh')")
                latest=migration.import_source(raw,cfg,source,activate=True)
                assert sum(x['rows'] for x in latest)==4
                assert raw.execute('SELECT ready FROM _dvk_meta').fetchone()==(True,)
                try:migration.import_source(raw,cfg,source,activate=True)
                except cloud.CloudDatabaseError as e:assert e.code=='cloud-dataset-already-live'
                else:raise AssertionError('Active dataset overwritten')
                assert raw.execute('SELECT COUNT(*) FROM mumu_peer_blocks').fetchone()[0]==2
                assert raw.execute('SELECT payload,stamp,optional FROM chain_actions').fetchone()==(b'\x00\xffopaque',value,None)
        print('PASS: Postgres temporary-only namespace, chain, float precision, RAM preview, verified COPY, latest-local cutover, active overwrite guard')
    finally:raw.close() # All test tables disappear with this session.

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('A private connection JSON file is required')
    try:run(sys.argv[1])
    except Exception as e:
        print('FAIL: '+(e.code if isinstance(e,cloud.CloudDatabaseError) else type(e).__name__))
        raise SystemExit(1) from None
