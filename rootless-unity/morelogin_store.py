"""ONE local SQLite file: shared peer claims + phone-isolated engine journals.

The unchanged engine has chat-only primary keys. A finite identifier adapter gives
those internal tables a phone namespace in the SAME database; chat IDs are never
assumed unique across accounts/phones. Only authored SQL uses this adapter; bound
message/key values are not rewritten. Shared claims commit with greeting reserves.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import sqlite3
from assistant_store import Store as BaseStore, StateError
from assistant_config import check_text
from cohort_pass import Store as LegacyStore
from morelogin_common import root_directory, phone_id

TABLES = frozenset(('manual_actions profile_visits search_session city_rotation_used '
    'chain_contact_media chain_contact_outbox chain_dialogs chain_review_reasons '
    'chain_seen chain_actions chain_notifications guided_bindings ai_drafts ai_draft_inputs '
    'inbox_read_round inbox_history_deferrals chain_exit_notices read_only_bindings guided_notices').split())
TOKENS = re.compile(r'\b(' + '|'.join(sorted(TABLES, key=len, reverse=True)) + r')\b')

class SharedPeerClaimed(StateError):
    """An atomic peer claim already exists; no authorization may be sent."""

class Cursor:
    def __init__(self, cursor, prefix, schema=False):
        self.cursor, self.prefix, self.schema = cursor, prefix, schema
    @property
    def lastrowid(self): return self.cursor.lastrowid
    @property
    def rowcount(self): return self.cursor.rowcount
    def row(self, row):
        if row is None: return None
        if self.schema:
            return (row[0][len(self.prefix):],) if row[0].startswith(self.prefix) else None
        return row
    def __iter__(self):
        for value in self.cursor:
            row = self.row(value)
            if row is not None: yield row
    def fetchall(self): return list(self)
    def fetchone(self):
        for row in self: return row
        return None

class Connection:
    def __init__(self, db, prefix): self.db, self.prefix = db, prefix
    def executemany(self, sql, values):
        return Cursor(self.db.executemany(TOKENS.sub(lambda m: self.prefix + m.group(), sql), values), self.prefix)
    def execute(self, sql, params=()):
        # All callers are fixed engine SQL. Never replace bound payloads/IDs.
        rewritten = TOKENS.sub(lambda m: self.prefix + m.group(), sql)
        if 'sqlite_master' in sql and 'name=?' in sql:
            params = tuple(self.prefix+x if isinstance(x,str) and x in TABLES else x for x in params)
        return Cursor(self.db.execute(rewritten, params), self.prefix,
                      bool(re.match(r'\s*SELECT\s+name\s+FROM\s+sqlite_master', sql, re.I)))

class SharedStore(BaseStore):
    def __init__(self, path=None, legacy_directory=None, *, cloud_id=None):
        self.cloud_id = phone_id(cloud_id if cloud_id is not None else os.environ.get('DVK_MORELOGIN_PHONE_ID'))
        self.prefix = 'p' + self.cloud_id + '__'
        path = Path(path) if path is not None else root_directory() / 'shared.sqlite3'
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=30) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS cloud_schema(version INTEGER PRIMARY KEY CHECK(version=1))')
            db.execute('INSERT OR IGNORE INTO cloud_schema VALUES(1)')
            db.execute('''CREATE TABLE IF NOT EXISTS global_peer_claims(
                peer TEXT PRIMARY KEY, phone TEXT NOT NULL, account TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('''CREATE TABLE IF NOT EXISTS global_profile_visits(
                peer TEXT PRIMARY KEY, phone TEXT NOT NULL,
                checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        super().__init__(path, legacy_directory=path.parent/'no-mumu-import')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL')
            def authorize(action, table, column, database, trigger):
                if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
                    return sqlite3.SQLITE_DENY
                if action in (sqlite3.SQLITE_READ, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE,
                              sqlite3.SQLITE_DELETE, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE):
                    allowed = {'sqlite_master','sqlite_sequence','global_peer_claims','global_profile_visits'}
                    if table not in allowed and table not in {self.prefix+x for x in TABLES}:
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            db.set_authorizer(authorize)
            db.execute('BEGIN IMMEDIATE')
            yield Connection(db, self.prefix)
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction: db.execute('ROLLBACK')
            raise
        finally:
            db.close()

    def check_legacy(self, account, peer):
        # MoreLogin is a separate enrollment scope. Never consume/reset MuMu journals.
        return None

    def reserve(self, pending, text, *, approved=False):
        pending = LegacyStore.check(pending)
        check_text(text)
        if approved is not True: raise StateError('Нужно разрешение запуска.')
        with self.connection() as db:
            if db.execute('SELECT 1 FROM global_peer_claims WHERE peer=?', (pending['peer'],)).fetchone():
                raise SharedPeerClaimed('Анкета уже зарезервирована другим Cloud Phone.')
            # Both inserts are in one IMMEDIATE transaction, before native ack.
            db.execute('INSERT INTO global_peer_claims(peer,phone,account) VALUES(?,?,?)',
                       (pending['peer'], self.cloud_id, pending['account']))
            cur = db.execute('''INSERT INTO manual_actions
              (account,peer,initial_chat,text_hash,confirmed,status) VALUES(?,?,?,?,1,'reserved-unknown')''',
              (pending['account'],pending['peer'],pending['chat'],hashlib.sha256(text.encode()).hexdigest()))
            return cur.lastrowid

    def visited_peers(self):
        from conversation_engine import identifier
        with self.connection() as db:
            values = [row[0] for row in db.execute('SELECT peer FROM global_profile_visits UNION SELECT peer FROM global_peer_claims')]
        if len(values) > 10000: raise StateError('Общая история больше лимита безопасного снимка. Нужен архив, не удаление резервов.')
        return [identifier(x) for x in values]

    def record_visit(self, peer, navigation):
        super().record_visit(peer, navigation)
        if navigation['profile_verified'] is True:
            with self.connection() as db:
                db.execute('INSERT OR IGNORE INTO global_profile_visits(peer,phone) VALUES(?,?)', (peer,self.cloud_id))
