"""ONE MuMu SQLite file: terminal peer outcomes + phone-isolated send journals.

The unchanged engine has chat-only primary keys. A finite identifier adapter gives
those internal tables a device namespace in the SAME database; chat IDs are never
assumed unique across accounts/phones. Only authored SQL uses this adapter; bound
message/key values are not rewritten. Only accepted contacts and explicit refusals block new greetings globally.
"""
from contextlib import contextmanager, closing
import json
import hashlib
import os
from pathlib import Path
import re
import sqlite3
from assistant_store import Store as BaseStore, StateError
from assistant_config import check_text
from cohort_pass import Store as LegacyStore
from mumu_common import root_directory, port

TABLES = frozenset(('manual_actions profile_visits search_session city_rotation_used '
    'chain_contact_media chain_contact_outbox chain_dialogs chain_review_reasons '
    'chain_seen chain_actions chain_notifications guided_bindings ai_drafts ai_draft_inputs '
    'profile_recovery_skips inbox_reply_policy inbox_reply_exclusions inbox_read_round inbox_history_deferrals inbox_reported_inputs chain_exit_notices read_only_bindings guided_notices chain_reply_receipts chain_followup_archive chain_recovered_anchors chain_legacy_probes').split())
TOKENS = re.compile(r'\b(' + '|'.join(sorted(TABLES, key=len, reverse=True)) + r')\b')

class SharedPeerClaimed(StateError):
    """Local attempt or a global terminal outcome prevents authorization."""

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
    mumu_shared_claims=True
    def __init__(self,path=None,legacy_directory=None,*,device_port=None):
        self.device_port=port(device_port if device_port is not None else os.environ.get('DVK_MUMU_PORT','5563'))
        self.prefix='' if self.device_port==5563 else 'm'+str(self.device_port)+'__'
        path=Path(path) if path is not None else root_directory()/'assistant.sqlite3'
        path.parent.mkdir(parents=True,exist_ok=True)
        self.path=path
        self.legacy=Path(legacy_directory) if legacy_directory is not None else path.parent.parent/'DvkRootless'
        with closing(sqlite3.connect(path,timeout=30,isolation_level=None)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('''CREATE TABLE IF NOT EXISTS mumu_peer_claims(
                  peer TEXT PRIMARY KEY,device TEXT NOT NULL,account TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
                db.execute('''CREATE TABLE IF NOT EXISTS mumu_profile_visits(
                  peer TEXT PRIMARY KEY,checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
                db.execute('CREATE TABLE IF NOT EXISTS mumu_recovery_skips(peer TEXT PRIMARY KEY)')
                # Old global claims/visits/skips remain an audit, NOT a ban.
                # A greeting on another phone is not a contact/refusal outcome.
                from mumu_peer_policy import initialize, backfill_contacts
                initialize(db)
                backfill_contacts(db)
                # Old releases accidentally shared receipt keys across devices.
                # Copy ONLY receipts whose salted fingerprint matches this
                # phone's persisted observation; never guess the owner by ChatId.
                if self.prefix and db.execute("SELECT 1 FROM sqlite_master WHERE name='chain_reply_receipts'").fetchone() and db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(self.prefix+'chain_seen',)).fetchone():
                    table=self.prefix+'chain_reply_receipts'
                    db.execute('CREATE TABLE IF NOT EXISTS '+table+'(chat TEXT,message TEXT,fingerprint TEXT,status TEXT NOT NULL,reply_message TEXT,PRIMARY KEY(chat,message))')
                    db.execute('INSERT OR IGNORE INTO '+table+' SELECT r.* FROM chain_reply_receipts r JOIN '+self.prefix+'chain_seen s ON r.chat=s.chat AND r.message=s.message AND r.fingerprint=s.fingerprint')
                db.execute('COMMIT')
            except BaseException:
                if db.in_transaction:db.execute('ROLLBACK')
                raise
        super().__init__(path,self.legacy)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS profile_recovery_skips(peer TEXT PRIMARY KEY)')

    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield Connection(db,self.prefix)
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()

    def check_legacy(self,account,peer):
        # The anonymous legacy journal belonged to original MuMu port 5563.
        # Keep its same-phone replay protection, not a greeting-only global ban.
        if self.device_port==5563:super().check_legacy(account,peer)

    @staticmethod
    def blocked(db,peer):
        return (db.execute('SELECT 1 FROM mumu_peer_blocks WHERE peer=?',(peer,)).fetchone() is not None
            or db.execute('SELECT 1 FROM manual_actions WHERE peer=?',(peer,)).fetchone() is not None
            or db.execute('SELECT 1 FROM profile_recovery_skips WHERE peer=?',(peer,)).fetchone() is not None)

    def peer_claimed(self,pending):
        # Preserve the native checked-skip API; its meaning is now local send
        # history OR a confirmed global terminal outcome, not another greeting.
        pending=LegacyStore.check(pending)
        with self.connection() as db:return self.blocked(db,pending['peer'])

    def peer_terminal(self,pending):
        pending=LegacyStore.check(pending)
        with self.connection() as db:
            return db.execute('SELECT 1 FROM mumu_peer_blocks WHERE peer=?',(pending['peer'],)).fetchone() is not None

    def record_peer_outcome(self,db,who,reason):
        from one_chat_probe import identity
        from mumu_peer_policy import record
        who=identity(who)
        record(db,who,reason,str(self.device_port))

    def reserve(self,pending,text,*,approved=False):
        pending=LegacyStore.check(pending);check_text(text)
        if approved is not True:raise StateError('Нужно разрешение запуска.')
        self.check_legacy(pending['account'],pending['peer'])
        with self.connection() as db:
            # Outcome and reservation serialize in the SAME SQLite transaction.
            # No global lock is acquired by a mere greeting on another port.
            if self.blocked(db,pending['peer']):
                raise SharedPeerClaimed('Локальная попытка уже сохранена или контакт/отказ получен на одном из MuMu.')
            cur=db.execute("""INSERT INTO manual_actions
              (account,peer,initial_chat,text_hash,confirmed,status) VALUES(?,?,?,?,1,'reserved-unknown')""",
              (pending['account'],pending['peer'],pending['chat'],hashlib.sha256(text.encode()).hexdigest()))
            from assistant_statistics import remember_city,greeting_reserved
            remember_city(db,pending['account'],pending['peer'])
            greeting_reserved(db,pending['account'],pending['peer'])
            return cur.lastrowid

    def visited_peers(self):
        from conversation_engine import identifier
        with self.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS profile_visits(peer TEXT PRIMARY KEY,friends_count INTEGER,history_status TEXT NOT NULL,checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            values=[x[0] for x in db.execute('SELECT peer FROM profile_visits UNION SELECT peer FROM manual_actions UNION SELECT peer FROM profile_recovery_skips UNION SELECT peer FROM mumu_peer_blocks')]
        if len(values)>10000:raise StateError('История больше безопасного лимита снимка; журналы не удаляй.')
        return [identifier(x) for x in values]

    def record_visit(self,peer,navigation):
        # Base record is already phone-namespaced. Another phone can visit it.
        super().record_visit(peer,navigation)

    def skip_recovery_peer(self,who):
        from one_chat_probe import identity
        who=identity(who)
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO profile_recovery_skips(peer) VALUES(?)',(who['peer'],))
