"""Verified one-way SQLite import. No decryption, sends or local journal mutation."""
import hashlib,json,sqlite3,re
from pathlib import Path
from contextlib import closing
from cloud_sql import ident,schema_info,create_sql
from cloud_database import SCHEMA,PROTOCOL,LOCK_ID,CloudDatabaseError,validate,raw_connect
MAX_BYTES=64*1024*1024

def row_digest(rows):
    h=hashlib.sha256();count=0
    for row in rows:
        # Preserve types, binary DPAPI payloads and NULL without lossy JSON casts.
        for value in row:
            if value is None:tag=b'n';raw=b''
            elif isinstance(value,bytes):tag=b'b';raw=value
            elif isinstance(value,str):tag=b's';raw=value.encode('utf-8')
            elif isinstance(value,int):tag=b'i';raw=str(value).encode()
            elif isinstance(value,float):tag=b'f';raw=value.hex().encode()
            else:raise CloudDatabaseError('migration-value-type')
            h.update(tag+len(raw).to_bytes(8,'big')+raw)
        h.update(b'\xff');count+=1
    return count,h.hexdigest()

def source_info(db):
    if db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise CloudDatabaseError('migration-source-invalid')
    if db.execute('PRAGMA page_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0]>MAX_BYTES:raise CloudDatabaseError('migration-size-limit')
    infos=[]
    for name,ddl in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        info=schema_info(ddl)
        if info['name']!=name or not info['pk']:raise CloudDatabaseError('migration-schema-invalid')
        infos.append(info)
    names={x['name'] for x in infos}
    if not {'manual_actions','mumu_peer_blocks','chain_actions'}<=names:raise CloudDatabaseError('migration-source-invalid')
    if len(infos)>512:raise CloudDatabaseError('migration-size-limit')
    return infos

def init_metadata(raw,cfg):
    raw.execute('SET LOCAL search_path TO '+ident(SCHEMA)+',pg_catalog')
    raw.execute('CREATE TABLE IF NOT EXISTS _dvk_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),protocol INTEGER NOT NULL,dataset TEXT NOT NULL,ready BOOLEAN NOT NULL,source_sha256 TEXT NOT NULL)')
    raw.execute('CREATE TABLE IF NOT EXISTS _dvk_schema(name TEXT PRIMARY KEY,sqlite_sql TEXT NOT NULL)')
    raw.execute('INSERT INTO _dvk_meta VALUES(1,%s,%s,false,%s) ON CONFLICT DO NOTHING',(PROTOCOL,cfg['dataset'],cfg['source_sha256']))
    meta=raw.execute('SELECT protocol,dataset,ready FROM _dvk_meta WHERE singleton=1 FOR UPDATE').fetchone()
    if meta[:2]!=(PROTOCOL,cfg['dataset']):raise CloudDatabaseError('cloud-dataset-mismatch')
    return meta[2]

def require_latest_journals(raw,source,infos):
    """Never replace staging with a different/reset/older local send journal.

    Durable rows are append-only; mutable statuses may advance but immutable
    authorization/attempt fields and all original terminal bans must remain.
    Ephemeral drafts/actions are deliberately NOT treated as append-only.
    """
    names={x['name'] for x in infos}
    for name,ddl in raw.execute('SELECT name,sqlite_sql FROM _dvk_schema').fetchall():
        if name!='mumu_peer_blocks' and not re.fullmatch(r'(?:m[0-9]{4,5}__)?(?:manual_actions|chain_send_attempts|chain_send_authorizations)',name):continue
        if name not in names:raise CloudDatabaseError('cloud-local-journal-older-than-upload')
        info=schema_info(ddl)
        columns=[x[1] for x in info['columns'] if x[1] not in {'status','outcome','error'}]
        cols=','.join(map(ident,columns))
        try:current=set(source.execute('SELECT '+cols+' FROM '+ident(name)))
        except sqlite3.Error:raise CloudDatabaseError('cloud-local-journal-older-than-upload') from None
        with raw.cursor(name='baseline_'+name) as cursor:
            cursor.execute('SELECT '+cols+' FROM '+ident(name))
            if any(row not in current for row in cursor):raise CloudDatabaseError('cloud-local-journal-older-than-upload')


def import_source(raw,cfg,source,*,activate=False):
    """Replace ONLY our not-ready staging dataset, atomically. Never overwrite live DB."""
    validate(cfg)
    with closing(sqlite3.connect(Path(source).resolve(strict=True).as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        infos=source_info(db)
        with raw.transaction():
            raw.execute('SET LOCAL statement_timeout=120000');raw.execute('SET LOCAL lock_timeout=10000')
            raw.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK_ID,))
            if init_metadata(raw,cfg):raise CloudDatabaseError('cloud-dataset-already-live')
            if activate:require_latest_journals(raw,db,infos)
            previous=[x[0] for x in raw.execute('SELECT name FROM _dvk_schema')]
            for name in previous:raw.execute('DROP TABLE '+ident(name))
            raw.execute('DELETE FROM _dvk_schema')
            manifest=[]
            for info in infos:
                name=info['name'];cols=','.join(ident(x[1]) for x in info['columns']);order=','.join(ident(x) for x in info['pk'])
                raw.execute(create_sql(info))
                with raw.cursor().copy('COPY '+ident(name)+'('+cols+') FROM STDIN') as copy:
                    for row in db.execute('SELECT '+cols+' FROM '+ident(name)+' ORDER BY '+order):copy.write_row(row)
                source_hash=row_digest(db.execute('SELECT '+cols+' FROM '+ident(name)+' ORDER BY '+order))
                with raw.cursor(name='verify_'+name) as cur:
                    cur.execute('SELECT '+cols+' FROM '+ident(name)+' ORDER BY '+order)
                    dest_hash=row_digest(cur)
                if source_hash!=dest_hash:raise CloudDatabaseError('migration-verification-failed')
                if info['identity']:
                    col=ident(info['identity']);maximum=raw.execute('SELECT MAX('+col+') FROM '+ident(name)).fetchone()[0]
                    seq=raw.execute('SELECT pg_get_serial_sequence(%s,%s)',(name,info['identity'])).fetchone()[0]
                    raw.execute('SELECT setval(%s,%s,false)',(seq,max(1,(maximum or 0)+1)))
                raw.execute('INSERT INTO _dvk_schema VALUES(%s,%s)',(name,info['sqlite_sql']))
                manifest.append(dict(table=name,rows=source_hash[0],sha256=source_hash[1]))
            raw.execute('UPDATE _dvk_meta SET ready=%s,source_sha256=%s WHERE singleton=1',(activate,cfg['source_sha256']))
            return manifest
