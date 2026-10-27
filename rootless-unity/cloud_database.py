"""Opt-in PostgreSQL primary store. A configured failure NEVER falls back to SQLite.

The local path is an identity/backup path only when cloud mode is configured.
No SQL/body/credentials are included in raised public exception messages.
"""
import hashlib,json,os,re,sqlite3,threading,time
from pathlib import Path
from cloud_sql import ident,schema_info,create_sql,translate

FORMAT='dvk-postgres-v1';PROTOCOL=1;SCHEMA='dvk_private';LOCK_ID=732489102128
_cache={};_mutex=threading.Lock();_local=threading.local()

class CloudDatabaseError(sqlite3.OperationalError):
    def __init__(self,code='cloud-database-unavailable'):
        super().__init__(code);self.code=code

DATABASE_CODES={'cloud-database-unavailable','cloud-database-config-invalid','cloud-dataset-not-ready',
    'cloud-database-lock-timeout','cloud-database-query-timeout','cloud-database-capacity',
    'cloud-database-permission','cloud-database-constraint','cloud-sql-syntax-error','cloud-schema-missing',
    'cloud-sql-unsupported','cloud-transaction-invalid','cloud-transaction-required','cloud-readonly-violation'}
DATABASE_OPERATIONS={'connect','begin','commit','rollback','schema','catalog','read','write','lock','unknown'}
SAFE_RELATIONS=frozenset('''_dvk_meta _dvk_schema manual_actions profile_visits search_session city_rotation_used
chain_send_authorizations chain_send_attempts chain_contact_media chain_contact_outbox chain_dialogs chain_review_reasons chain_seen chain_actions chain_notifications ai_drafts ai_draft_inputs chain_unknown_reply_retries chain_selection_recovery profile_recovery_skips inbox_reply_policy inbox_reply_exclusions inbox_read_round inbox_history_deferrals inbox_reported_inputs chain_exit_notices chain_exit_payloads read_only_bindings guided_bindings guided_notices chain_reply_receipts chain_followup_archive chain_recovered_anchors chain_legacy_probes chain_contact_review_probes
mumu_peer_claims mumu_profile_visits mumu_recovery_skips mumu_peer_blocks mumu_manual_silences mumu_installation_scopes mumu_account_owners mumu_greeting_claims mumu_city_claims
global_greeting_statistics global_contact_statistics global_peer_city'''.split())
RELATION_HINTS=SAFE_RELATIONS|{'other-application-table'}

def safe_relation_hint(schema_name, table_name):
    # Redact installation and device namespaces; expose only known logical names.
    if schema_name!=SCHEMA or not isinstance(table_name,str):return None
    match=re.fullmatch(r'(?:i[a-f0-9]{20}_m[0-9]{4,5}__|m[0-9]{4,5}__)?([a-z][a-z0-9_]*)',table_name)
    if not match:return 'other-application-table'
    name=match.group(1)
    return name if name in SAFE_RELATIONS else 'other-application-table'

def clean_diagnostic(value):
    base={'code','operation','automatic_retry'}
    if not isinstance(value,dict) or set(value) not in (base,base|{'relation'}):return None
    if type(value['code']) is not str or value['code'] not in DATABASE_CODES:return None
    if type(value['operation']) is not str or value['operation'] not in DATABASE_OPERATIONS:return None
    if value['automatic_retry'] is not False:return None
    if 'relation' in value and (value['code']!='cloud-schema-missing' or type(value['relation']) is not str or value['relation'] not in RELATION_HINTS):return None
    return dict(value)

def diagnostic(error):
    if type(error) is not CloudDatabaseError:return None
    code=error.code if error.code in DATABASE_CODES else 'cloud-database-unavailable'
    operation=getattr(error,'operation','unknown')
    result=dict(code=code,operation=operation if operation in DATABASE_OPERATIONS else 'unknown',automatic_retry=False)
    relation=getattr(error,'relation',None)
    if code=='cloud-schema-missing' and relation in RELATION_HINTS:result['relation']=relation
    return result

def operation(sql):
    if 'pg_advisory_xact_lock' in sql:return 'lock'
    token=sql.lstrip().split(None,1)[0].upper() if sql.strip() else ''
    if token in {'BEGIN','COMMIT','ROLLBACK'}:return token.lower()
    if token=='CREATE':return 'schema'
    if '_dvk_schema' in sql:return 'catalog'
    return 'read' if token=='SELECT' else 'write'

def root():
    value=os.environ.get('LOCALAPPDATA')
    if not value:raise CloudDatabaseError('cloud-database-config-invalid')
    return Path(value)/'DvkAssistant'

def settings_path():return root()/'database.dpapi'
def marker_path():return root()/'database-cloud-primary.json'

def enabled(path=None):
    if os.environ.get('DVK_MORELOGIN')=='1':return False
    try:
        if path is not None and Path(path).resolve()!=(root()/'assistant.sqlite3').resolve():return False
        return settings_path().exists() or marker_path().exists()
    except CloudDatabaseError:return False

def available(path):return enabled(path) or Path(path).exists()

def validate(value):
    required={'format','host','port','database','user','password','schema','dataset','source_sha256'}
    if not isinstance(value,dict) or set(value)!=required or value['format']!=FORMAT:raise CloudDatabaseError('cloud-database-config-invalid')
    if not isinstance(value['host'],str) or not re.fullmatch(r'[a-z0-9-]+\.pooler\.supabase\.com',value['host']):raise CloudDatabaseError('cloud-database-config-invalid')
    if type(value['port']) is not int or value['port']!=5432 or value['database']!='postgres' or value['schema']!=SCHEMA:raise CloudDatabaseError('cloud-database-config-invalid')
    if not isinstance(value['user'],str) or not re.fullmatch(r'dvk_app_[a-f0-9]{8}\.[a-z0-9]{20}',value['user']):raise CloudDatabaseError('cloud-database-config-invalid')
    if not isinstance(value['password'],str) or not 32<=len(value['password'])<=128:raise CloudDatabaseError('cloud-database-config-invalid')
    if not isinstance(value['dataset'],str) or not re.fullmatch('[a-f0-9]{32}',value['dataset']):raise CloudDatabaseError('cloud-database-config-invalid')
    if not isinstance(value['source_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['source_sha256']):raise CloudDatabaseError('cloud-database-config-invalid')
    return dict(value)

def load():
    try:
        p=settings_path();stat=p.stat();key=(str(p.resolve()),stat.st_mtime_ns,stat.st_size)
        with _mutex:
            if _cache.get('key')==key:return dict(_cache['value'])
        if stat.st_size>16384:raise ValueError()
        from telegram_notify import protect
        value=validate(json.loads(protect(p.read_bytes(),decrypt=True)))
        with _mutex:_cache.update(key=key,value=value)
        return value
    except Exception:raise CloudDatabaseError('cloud-database-config-invalid') from None

def check_selection(value):
    p=marker_path()
    if not p.exists():return
    try:
        if p.stat().st_size>1024:raise ValueError()
        marker=json.loads(p.read_text(encoding='utf-8'))
        if marker!={'format':FORMAT,'dataset':value['dataset'],'host':value['host']}:raise ValueError()
    except Exception:raise CloudDatabaseError('cloud-dataset-marker-mismatch') from None


def save(value):
    value=validate(value);check_selection(value)
    from telegram_notify import protect
    import tempfile
    data=protect(json.dumps(value).encode());p=settings_path();p.parent.mkdir(parents=True,exist_ok=True)
    # Durable non-secret sentinel prevents an absent/deleted DPAPI file from
    # silently selecting the stale local SQLite journal after cutover.
    marker={'format':FORMAT,'dataset':value['dataset'],'host':value['host']}
    mfd,mname=tempfile.mkstemp(prefix='.database-mode-',dir=p.parent)
    try:
        with os.fdopen(mfd,'w',encoding='utf-8') as f:json.dump(marker,f);f.flush();os.fsync(f.fileno())
        os.replace(mname,marker_path())
    finally:
        if os.path.exists(mname):os.unlink(mname)
    fd,name=tempfile.mkstemp(prefix='.database-',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)
    with _mutex:_cache.clear()

def raw_connect(cfg):
    """Only connection/setup can retry, before a journal transaction exists."""
    for attempt in range(2):
        try:return _raw_connect_once(cfg)
        except CloudDatabaseError as error:
            if attempt or not getattr(error,'connect_retryable',False):raise
            time.sleep(.15)

def _raw_connect_once(cfg):
    db=None
    try:
        import psycopg
        from assistant_runtime import phase
        with phase('db_connect'):
            db=psycopg.connect(host=cfg['host'],port=cfg['port'],dbname=cfg['database'],user=cfg['user'],
            password=cfg['password'],sslmode='verify-full',sslrootcert=str(Path(__file__).with_name('supabase-ca.crt')),connect_timeout=8,
            autocommit=True,prepare_threshold=None,application_name='DvkAssistant')
        # Supabase may default to 0: that rounds epoch/REAL values on SELECT.
        db.execute("SET extra_float_digits=3; SET statement_timeout='15000'; SET lock_timeout='10000'",prepare=False)
        return db
    except Exception as error:
        if db is not None:
            try:db.close()
            except Exception:pass
        state=getattr(error,'sqlstate',None)
        value=CloudDatabaseError('cloud-database-capacity' if state=='53300' else
            'cloud-database-permission' if state in ('28P01','28000','42501') else 'cloud-database-unavailable')
        value.operation='connect'
        value.connect_retryable=(state=='53300' or isinstance(state,str) and state.startswith('08')
            or state is None and (isinstance(error,(OSError,TimeoutError)) or
                type(error).__name__ in ('OperationalError','InterfaceError')))
        raise value from None

class Cursor:
    def __init__(self,rows=(),*,rowcount=None,lastrowid=None):
        self.rows=list(rows);self.position=0;self.rowcount=len(self.rows) if rowcount is None else rowcount;self.lastrowid=lastrowid
    def __iter__(self):
        while self.position<len(self.rows):
            value=self.rows[self.position];self.position+=1;yield value
    def fetchall(self):return list(self)
    def fetchone(self):return next(iter(self),None)

class Connection:
    def __init__(self,raw,cfg,schemas):
        self.raw=raw;self.cfg=cfg;self.schemas=dict(schemas);self.pending={};self.in_transaction=False;self.read_only=False;self.closed=False;self.reusable=True
    def __enter__(self):return self
    def __exit__(self,kind,error,tb):
        if self.in_transaction:self.execute('ROLLBACK' if kind else 'COMMIT')
    def _run(self,sql,params=()):
        try:
            from assistant_runtime import phase
            kind=operation(sql)
            stage='db_lock' if kind=='lock' else 'db_read' if kind in ('read','catalog') else 'db_commit' if kind=='commit' else 'db_write'
            with phase(stage):return self.raw.execute(sql,params or None,prepare=False)
        except Exception as error:
            self.reusable=False # Never pool a session after an unknown SQL/commit outcome.
            state=getattr(error,'sqlstate',None)
            if state=='23505':raise sqlite3.IntegrityError('cloud-journal-conflict') from None
            codes={'55P03':'cloud-database-lock-timeout','57014':'cloud-database-query-timeout',
                '53300':'cloud-database-capacity','42501':'cloud-database-permission',
                '23502':'cloud-database-constraint','23514':'cloud-database-constraint',
                '42601':'cloud-sql-syntax-error','42P01':'cloud-schema-missing'}
            value=CloudDatabaseError(codes.get(state,'cloud-database-unavailable'))
            value.operation=operation(sql)
            if state=='42P01':
                diag=getattr(error,'diag',None)
                value.relation=safe_relation_hint(getattr(diag,'schema_name',None),getattr(diag,'table_name',None))
            raise value from None
    def execute(self,sql,params=()):
        if self.closed:raise CloudDatabaseError()
        upper=sql.strip().rstrip(';').upper()
        if upper.startswith('PRAGMA '):
            if upper=='PRAGMA QUERY_ONLY=ON':self.read_only=True
            elif upper not in ('PRAGMA SYNCHRONOUS=FULL','PRAGMA JOURNAL_MODE=WAL'):raise CloudDatabaseError('cloud-sql-unsupported')
            return Cursor()
        if upper in ('BEGIN','BEGIN IMMEDIATE'):
            if self.in_transaction:raise CloudDatabaseError('cloud-transaction-invalid')
            begin='BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if self.read_only else 'BEGIN'
            self._run(begin);self.in_transaction=True
            initializing=getattr(_local,"initializing",False)
            settings=("SET LOCAL statement_timeout='65000'; SET LOCAL lock_timeout='60000'; SET LOCAL synchronous_commit=on" if initializing else
                      "SET LOCAL statement_timeout='15000'; SET LOCAL lock_timeout='10000'; SET LOCAL synchronous_commit=on")
            self._run(settings)
            if not self.read_only:
                # Keep the original FIFO waiter for up to 10s. Restarting every
                # 2s in 1.3.60 lost queue position under multi-port contention.
                # There is NO retry of this transaction or its caller's body.
                try:self._run('SELECT pg_advisory_xact_lock(%s)',(LOCK_ID,))
                except CloudDatabaseError as error:
                    if error.code=='cloud-database-lock-timeout' and error.operation=='lock':
                        self._run('ROLLBACK');self.in_transaction=False
                    raise
            return Cursor()
        if upper in ('COMMIT','ROLLBACK'):
            self._run(upper);self.in_transaction=False
            if upper=='COMMIT':self.schemas.update(self.pending)
            self.pending.clear();return Cursor()
        if re.match(r'\s*CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b',sql,re.I):
            info=schema_info(sql);name=info['name']
            if name in self.schemas or name in self.pending:return Cursor(rowcount=-1)
            if self.read_only or not self.in_transaction:raise CloudDatabaseError('cloud-transaction-invalid')
            self._run(create_sql(info))
            self._run('INSERT INTO _dvk_schema(name,sqlite_sql) VALUES(%s,%s) ON CONFLICT(name) DO NOTHING',(name,sql))
            self.pending[name]=info;return Cursor(rowcount=-1)
        # Catalog checks refer only to our migrated schema, not auth/public.
        if 'sqlite_master' in sql:
            match=re.fullmatch(r"\s*SELECT\s+(1|name)\s+FROM\s+sqlite_master\s+WHERE\s+(?:type\s*=\s*'table'\s*(?:AND\s*)?)?(?:name\s*=\s*(\?|'[a-z0-9_]+'))?\s*",sql,re.I)
            if match:
                needle=match.group(2)
                if needle:
                    wanted=params[0] if needle=='?' and len(params)==1 else needle.strip("'")
                    rows=self._run('SELECT name FROM _dvk_schema WHERE name=%s',(wanted,)).fetchall()
                else:rows=self._run('SELECT name FROM _dvk_schema ORDER BY name').fetchall()
                return Cursor([(1 if match.group(1)=='1' else name,) for name, in rows])
        if self.read_only and not upper.startswith('SELECT'):raise CloudDatabaseError('cloud-readonly-violation')
        if not self.in_transaction and not upper.startswith('SELECT'):raise CloudDatabaseError('cloud-transaction-required')
        try:query,returning=translate(sql,self.schemas|self.pending)
        except Exception:raise CloudDatabaseError('cloud-sql-unsupported') from None
        cur=self._run(query,tuple(params));rows=cur.fetchall() if cur.description else []
        last=rows[0][0] if returning and rows else None
        return Cursor([] if returning else rows,rowcount=cur.rowcount,lastrowid=last)
    def executemany(self,sql,values):
        total=0;last=None
        for value in values:
            cur=self.execute(sql,value);total+=max(0,cur.rowcount);last=cur.lastrowid
        return Cursor(rowcount=total,lastrowid=last)
    def close(self):
        if self.closed:return
        try:
            if self.in_transaction:self.raw.execute('ROLLBACK');self.in_transaction=False;self.pending.clear()
            if not self.raw.closed:
                pool=getattr(_local,'idle',[])
                if self.reusable and len(pool)<1:pool.append((self.cfg,self.raw,self.schemas,time.monotonic()));_local.idle=pool;self.raw=None
        except Exception:pass
        finally:
            if self.raw is not None:
                try:self.raw.close()
                except Exception:pass
            self.closed=True

def close_idle_connections():
    """Release only this thread's idle sockets, never an active transaction."""
    pool=getattr(_local,'idle',[]);_local.idle=[]
    for _,candidate,_,_ in pool:
        try:candidate.close()
        except Exception:pass

def connect(path,*,timeout=5,isolation_level=None,uri=False):
    if not enabled(path):return sqlite3.connect(path,timeout=timeout,isolation_level=isolation_level,uri=uri)
    cfg=load();raw=None;schemas=None
    pool=getattr(_local,'idle',[])
    while pool:
        old,candidate,known,returned_at=pool.pop()
        if old==cfg and not candidate.closed:
            # Probe ONLY idle sessions BEFORE handing one to a journal caller.
            # Failure can discard the connection, never replay a transaction.
            try:
                if time.monotonic()-returned_at>=10:
                    meta=candidate.execute('SELECT protocol,dataset,ready FROM _dvk_meta WHERE singleton=1',prepare=False).fetchone()
                    if meta!=(PROTOCOL,cfg['dataset'],True):
                        candidate.close();raise CloudDatabaseError('cloud-dataset-not-ready')
            except CloudDatabaseError:raise
            except Exception:
                candidate.close();continue
            raw=candidate;schemas=known;break
        candidate.close()
    if raw is None:
        raw=raw_connect(cfg)
        try:
            raw.execute('SET search_path TO '+ident(SCHEMA)+',pg_catalog',prepare=False)
            meta=raw.execute('SELECT protocol,dataset,ready FROM _dvk_meta WHERE singleton=1').fetchone()
            if meta!=(PROTOCOL,cfg['dataset'],True):raise CloudDatabaseError('cloud-dataset-not-ready')
            schemas={name:schema_info(sql) for name,sql in raw.execute('SELECT name,sqlite_sql FROM _dvk_schema').fetchall()}
        except CloudDatabaseError:raw.close();raise
        except Exception:raw.close();raise CloudDatabaseError() from None
    return Connection(raw,cfg,schemas)

def readonly(path):
    if enabled(path):
        db=connect(path)
        db.execute('PRAGMA query_only=ON')
        return db
    return sqlite3.connect(Path(path).resolve(strict=True).as_uri()+'?mode=ro',uri=True,timeout=5)

from contextlib import contextmanager,closing
@contextmanager
def memory_snapshot(path,limit):
    """Consistent bounded cloud snapshot for hypothetical writes ONLY in RAM."""
    with closing(readonly(path)) as source, closing(sqlite3.connect(':memory:')) as memory:
        source.execute('BEGIN');memory.execute('PRAGMA temp_store=MEMORY')
        total=0
        for name,sql in source.raw.execute('SELECT name,sqlite_sql FROM _dvk_schema ORDER BY name'):
            info=schema_info(sql);memory.execute(sql)
            cols=','.join(ident(x[1]) for x in info['columns'])
            with source.raw.cursor(name='snapshot_'+name) as cur:
                cur.execute('SELECT '+cols+' FROM '+ident(name))
                while True:
                    batch=cur.fetchmany(256)
                    if not batch:break
                    for row in batch:
                        total+=sum(len(x) if isinstance(x,(bytes,str)) else 8 for x in row)+64
                    if total>limit:raise CloudDatabaseError('journal-size-limit')
                    memory.executemany('INSERT INTO '+ident(name)+' VALUES('+','.join('?' for _ in info['columns'])+')',batch)
        memory.commit()
        yield memory

@contextmanager
def journal_initialization():
    """Longer lock wait ONLY at bootstrap, never an automatic retry or send."""
    previous=getattr(_local,'initializing',False);_local.initializing=True
    try:yield
    finally:_local.initializing=previous
