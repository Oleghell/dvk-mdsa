"""One-time conservative legacy journal copy in the SAME writer transaction.

Legacy rows have no machine provenance. Copy all safety records verbatim to each
new scope, never infer delivery/ownership or clear unknown attempts. A persistent
account owner guard prevents a later machine from running a stale private copy.
"""
import re
from cloud_sql import ident, schema_info


def initialize(db,device,prefix,legacy,tables):
    from assistant_store import StateError
    from cloud_database import Connection as CloudConnection
    db.execute('''CREATE TABLE IF NOT EXISTS mumu_installation_scopes(
        device TEXT PRIMARY KEY,prefix TEXT NOT NULL UNIQUE)''')
    db.execute('''CREATE TABLE IF NOT EXISTS mumu_account_owners(
        account TEXT PRIMARY KEY,device TEXT NOT NULL)''')
    row=db.execute('SELECT prefix FROM mumu_installation_scopes WHERE device=?',(device,)).fetchone()
    if row:
        if row!=(prefix,):raise StateError('installation-namespace-changed')
        return
    if db.execute('SELECT device FROM mumu_installation_scopes WHERE prefix=?',(prefix,)).fetchone():
        raise StateError('installation-namespace-collision')
    cloud=isinstance(db,CloudConnection)
    if cloud:
        sources=dict(db._run('SELECT name,sqlite_sql FROM _dvk_schema').fetchall())
    else:
        sources=dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
    for table in sorted(tables):
        source=legacy+table;target=prefix+table
        if target in sources:raise StateError('installation-namespace-unregistered')
        if source not in sources:continue
        info=schema_info(sources[source])
        if info['name']!=source:raise StateError('installation-legacy-schema-invalid')
        ddl=re.sub(r'^(\s*CREATE\s+TABLE\s+)(?:IF\s+NOT\s+EXISTS\s+)?'+re.escape(source)+r'\b',
                   lambda m:m[1]+'IF NOT EXISTS '+target,sources[source],count=1,flags=re.I)
        db.execute(ddl)
        # A legacy city could belong to either laptop. Do not adopt it. Leave
        # old claims held; choose a freshly verified, globally unoccupied city.
        suffix=" WHERE key<>'city'" if table=='search_session' else ''
        sql='INSERT INTO '+ident(target)+' SELECT * FROM '+ident(source)+suffix
        if cloud:
            db._run(sql)  # No per-row RETURNING and no message/key export to Python.
            if info['identity']:
                key=ident(info['identity'])
                db._run('SELECT setval(pg_get_serial_sequence(%s,%s), '
                        'COALESCE((SELECT MAX('+key+') FROM '+ident(target)+'),0)+1,false)',
                        (target,info['identity']))
        else:db.execute(sql)
        counts=db.execute('SELECT (SELECT COUNT(*) FROM '+ident(source)+suffix+'),'
                          '(SELECT COUNT(*) FROM '+ident(target)+')').fetchone()
        if counts[0]!=counts[1]:raise StateError('installation-journal-copy-incomplete')
    # The registry row commits atomically with EVERY copied table. A failed
    # migration rolls back, never leaves a completed marker or an empty journal.
    db.execute('INSERT INTO mumu_installation_scopes(device,prefix) VALUES(?,?)',(device,prefix))


def ensure_account(store,who,db=None):
    """Deny-only persistent binding. No automatic expiry, transfer or send retry."""
    if not getattr(store,'installation_id',None):return
    from assistant_store import StateError
    from conversation_engine import identifier
    account=identifier(who['account'])
    if db is None:
        with store.read_connection() as connection:
            row=connection.execute('SELECT device FROM mumu_account_owners WHERE account=?',(account,)).fetchone()
        if row==(store.device_owner,):return
        if row is not None:
            raise StateError('account-owned-by-other-scope')
        with store.connection() as connection:return ensure_account(store,who,connection)
    db.execute('INSERT OR IGNORE INTO mumu_account_owners(account,device) VALUES(?,?)',
               (account,store.device_owner))
    row=db.execute('SELECT device FROM mumu_account_owners WHERE account=?',(account,)).fetchone()
    if row!=(store.device_owner,):
        raise StateError('account-owned-by-other-scope')


def owns_account(store,who):
    """Copied outbox rows never acquire ownership or authorize a notification."""
    if not getattr(store,'installation_id',None):return True
    from conversation_engine import identifier
    account=identifier(who['account'])
    with store.read_connection() as db:
        return db.execute('SELECT device FROM mumu_account_owners WHERE account=?',(account,)).fetchone()==(store.device_owner,)
