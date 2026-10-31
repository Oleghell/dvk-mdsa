"""ONE MuMu SQLite file: terminal peer outcomes + phone-isolated send journals.

The unchanged engine has chat-only primary keys. A finite identifier adapter gives
those internal tables a device namespace in the SAME database; chat IDs are never
assumed unique across accounts/phones. Only authored SQL uses this adapter; bound
message/key values are not rewritten. Initial greetings are globally deduplicated
with a 24-hour cross-port window (v1.3.87 «можно через сутки»), independently of
the permanent terminal communication bans in mumu_peer_blocks.
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
from cloud_database import connect,journal_initialization

TABLES = frozenset(('manual_actions profile_visits search_session city_rotation_used '
    'chain_send_authorizations chain_send_attempts chain_contact_media chain_contact_outbox chain_dialogs chain_review_reasons '
    'chain_seen chain_actions chain_notifications guided_bindings ai_drafts ai_draft_inputs chain_unknown_reply_retries chain_selection_recovery '
    'profile_recovery_skips inbox_reply_policy inbox_reply_exclusions inbox_read_round inbox_history_deferrals inbox_reported_inputs chain_exit_notices chain_exit_payloads read_only_bindings guided_notices chain_reply_receipts chain_followup_archive chain_recovered_anchors chain_legacy_probes').split())
TOKENS = re.compile(r'\b(' + '|'.join(sorted(TABLES, key=len, reverse=True)) + r')\b')

class SharedPeerClaimed(StateError):
    """A global greeting claim or terminal outcome prevents a new greeting."""

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
    @journal_initialization()
    def __init__(self,path=None,legacy_directory=None,*,device_port=None,installation_id=None):
        self.device_port=port(device_port if device_port is not None else os.environ.get('DVK_MUMU_PORT','5563'))
        legacy_prefix='' if self.device_port==5563 else 'm'+str(self.device_port)+'__'
        from mumu_installation import checked,load
        # Explicit offline paths retain the legacy API. Every normal GUI/worker
        # store has a machine-bound installation ID; exported DB config has none.
        if installation_id is None and path is None:installation_id=load()
        if installation_id is None and os.environ.get('DVK_MUMU_MULTI')=='1':
            installation_id=checked(os.environ.get('DVK_INSTALLATION_ID'))
        self.installation_id=None if installation_id is None else checked(installation_id)
        self.device_owner=(self.installation_id+':'+str(self.device_port)
                           if self.installation_id else str(self.device_port))
        self.prefix=('i'+self.installation_id[:20]+'_m'+str(self.device_port)+'__'
                     if self.installation_id else legacy_prefix)
        path=Path(path) if path is not None else root_directory()/'assistant.sqlite3'
        path.parent.mkdir(parents=True,exist_ok=True)
        self.path=path
        self.legacy=Path(legacy_directory) if legacy_directory is not None else path.parent.parent/'DvkRootless'
        with closing(connect(path,timeout=30,isolation_level=None)) as db:
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
                # Greeting claims have their own registry, not terminal communication bans.
                from mumu_peer_policy import initialize, backfill_contacts
                initialize(db)
                backfill_contacts(db)
                import mumu_greetings, mumu_cities
                mumu_greetings.initialize(db)
                mumu_cities.initialize(db)
                if self.installation_id:
                    from mumu_namespace import initialize as initialize_namespace
                    initialize_namespace(db,self.device_owner,self.prefix,legacy_prefix,TABLES)
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
            db.execute('CREATE TABLE IF NOT EXISTS profile_visits(peer TEXT PRIMARY KEY,friends_count INTEGER,history_status TEXT NOT NULL,checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')

    @contextmanager
    def connection(self):
        db=connect(self.path,timeout=30,isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield Connection(db,self.prefix)
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()

    @contextmanager
    def read_connection(self):
        db=connect(self.path,timeout=30,isolation_level=None)
        try:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
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
    def blocked(db,peer,*,claim_cutoff=None):
        # v1.3.85: a guided or operator-adoption binding is live tracked work
        # exactly like a journal greeting; a peer with ANY existing binding must
        # not be greeted anew by the profile pass. Both tables are engine-
        # created, so their absence on a fresh store is simply "none yet".
        for table in ('guided_bindings','operator_bindings'):
            if (db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is not None
                    and db.execute('SELECT 1 FROM '+table+' WHERE peer=?',(peer,)).fetchone() is not None):
                return True
        # v1.3.87 (user rule «можно через сутки»): a greeting claim denies every
        # OTHER port's new greeting for 24 hours only; after the window the peer
        # is eligible for another анкета again. The claiming port keeps its
        # permanent protection through its own namespaced journal below, and
        # terminal contact outcomes (number received / explicit refusal /
        # manual /num) never expire on any port.
        from mumu_greetings import claim_cutoff as greeting_claim_cutoff
        if claim_cutoff is None: claim_cutoff = greeting_claim_cutoff()
        return (db.execute('SELECT 1 FROM mumu_greeting_claims WHERE peer=? AND created_at>=?',
                           (peer,claim_cutoff)).fetchone() is not None
            or db.execute('SELECT 1 FROM mumu_peer_blocks WHERE peer=?',(peer,)).fetchone() is not None
            or db.execute('SELECT 1 FROM manual_actions WHERE peer=?',(peer,)).fetchone() is not None
            or db.execute('SELECT 1 FROM profile_recovery_skips WHERE peer=?',(peer,)).fetchone() is not None)

    def peer_claimed(self,pending):
        # This check only authorizes a NEW greeting, never an existing reply.
        pending=LegacyStore.check(pending)
        with self.read_connection() as db:return self.blocked(db,pending['peer'])

    def peer_terminal(self,pending):
        pending=LegacyStore.check(pending)
        with self.read_connection() as db:
            return db.execute('SELECT 1 FROM mumu_peer_blocks WHERE peer=?',(pending['peer'],)).fetchone() is not None

    def record_peer_outcome(self,db,who,reason):
        from one_chat_probe import identity
        from mumu_peer_policy import record
        who=identity(who)
        record(db,who,reason,self.device_owner)

    def reserve(self,pending,text,*,approved=False):
        pending=LegacyStore.check(pending);check_text(text)
        if approved is not True:raise StateError('Нужно разрешение запуска.')
        self.check_legacy(pending['account'],pending['peer'])
        with self.connection() as db:
            from mumu_namespace import ensure_account
            ensure_account(self,{k:pending[k] for k in ('account','peer','chat')},db)
            # Outcome and reservation serialize in the SAME SQLite transaction.
            # Claim and local journal commit atomically; replies use terminal bans only.
            if self.blocked(db,pending['peer']):
                raise SharedPeerClaimed('Приветствие уже зарезервировано или контакт/отказ получен на одном из MuMu.')
            # v1.3.87: greeting the same peer again after the 24-hour window
            # (always from another анкета; this port's own journal denies its
            # own repeat forever) REPLACES the stale claim row, so the shield
            # window restarts from THIS port's greeting and every other port is
            # denied again for the next 24 hours.
            from mumu_greetings import claim_stamp
            db.execute('INSERT OR REPLACE INTO mumu_greeting_claims(peer,device,account,created_at) VALUES(?,?,?,?)',
                       (pending['peer'],self.device_owner,pending['account'],claim_stamp()))
            cur=db.execute("""INSERT INTO manual_actions
              (account,peer,initial_chat,text_hash,confirmed,status) VALUES(?,?,?,?,1,'reserved-unknown')""",
              (pending['account'],pending['peer'],pending['chat'],hashlib.sha256(text.encode()).hexdigest()))
            from assistant_statistics import remember_city,greeting_reserved
            remember_city(db,pending['account'],pending['peer'])
            greeting_reserved(db,pending['account'],pending['peer'])
            return cur.lastrowid

    def release_reservation(self,pending):
        """v1.3.81: return a committed-but-never-ACKed reservation to the pool.

        Only THIS device's own claim row is deleted (device filter), so another
        port's reservation is never touched and a retry after a lost COMMIT
        re-runs the same idempotent delete. The journal row keeps its audit
        trail with the pre-existing 'not-invoked' status, so deployed databases
        need no schema migration. No send latch was ever opened for this
        reservation (the release is only reached before any ACK), which is what
        makes returning the peer to the eligible pool safe. The row is matched
        by account+peer rather than by the insert's rowid: a lost COMMIT may
        have landed BOTH rows on the server while the client never saw the id.
        """
        pending=LegacyStore.check(pending)
        with self.connection() as db:
            row=db.execute("SELECT id,account FROM manual_actions WHERE account=? AND peer=? AND status='reserved-unknown'"
                           " ORDER BY id DESC LIMIT 1",(pending['account'],pending['peer'])).fetchone()
            # The claim delete runs even when the journal row is already
            # finished/released: a leftover claim of THIS device must never
            # outlive the release, and an uncommitted reservation matches
            # nothing at all.
            db.execute('DELETE FROM mumu_greeting_claims WHERE peer=? AND device=?',
                       (pending['peer'],self.device_owner))
            if row is None:
                return False
            db.execute("UPDATE manual_actions SET status='not-invoked' WHERE id=? AND status='reserved-unknown'",
                       (row[0],))
            from assistant_statistics import greeting_finished
            greeting_finished(db,row[1],pending['peer'],'not-invoked')
            return True

    # 1.3.67: shared greeting claims and peer blocks are rechecked against the
    # FULL cloud registry by reserve()/peer_claimed() before any send, so the
    # native pre-filter only needs their recent slice; a stale shared peer may
    # cost one verified no-send skip, never a duplicate greeting. The port's own
    # journal sources stay complete because only the native filter prevents
    # reopening a previously visited profile.
    # 1.3.78 (user report: «заходит в профиль, потом в личку и ничего не пишет,
    # хотя 20 анкет просмотрел»): the live registry had grown to 12,220 claims
    # (plus ~1,000/day across two installations), so the 2,000-row recency
    # slice left ~84% of claimed peers INVISIBLE to the native pre-filter.
    # Every such peer cost a full open-profile / open-chat / host peer-check /
    # verified-Back cycle before being skipped as shared - the pass reported
    # «просмотрено N» while zero greetings were sent, because the feed keeps
    # re-serving peers some port had already greeted. The snapshot now uploads
    # the FULL shared registries: the native selection-time check (batchSeen)
    # skips an already-greeted peer WITHOUT opening its profile or chat, and
    # cycles reach genuinely new peers. Only when the combined snapshot would
    # exceed the safety limit do the shared sources degrade to the freshest
    # rows that still fit; own journals always stay complete, and
    # reserve()/peer_claimed() keep checking the full registry as the dedup
    # authority, so a duplicate greeting remains impossible.
    # 1.3.87: "already greeted" now means "greeted inside the last 24 hours"
    # (shared_visited_sources applies the same claim cutoff as blocked());
    # an older claim leaves the snapshot exactly when reserve() stops denying
    # it, so the pre-filter never hides a peer another анкета may greet again.
    VISITED_SNAPSHOT_LIMIT = 100000
    VISITED_JOURNAL_SOURCES = (
        'SELECT peer FROM profile_visits',
        'SELECT peer FROM manual_actions',
        'SELECT peer FROM guided_bindings',
        'SELECT peer FROM operator_bindings',
        'SELECT peer FROM profile_recovery_skips')

    def shared_visited_sources(self,claim_cutoff):
        """v1.3.87: shared greeting claims enter the native pre-filter ONLY
        inside their 24-hour cross-port window - an expired claim must not
        hide an eligible peer from selection (the native batchSeen check and
        reserve() agree through the same cutoff). Terminal contact outcomes
        stay in the snapshot forever: «если анкета оставила номер или
        отказалась его давать, то уже на других анкетах никогда ей не пишем».

        v1.3.100 («одна анкета — один просмотр», user report: «все также
        проходится в холостую по новым анкетам… не набивало просмотры
        анкет, такого быть не должно»): shared profile VISITS join the same
        snapshot with the same 24-hour window. A profile that ANY port
        opened is skipped by EVERY port's native selection without opening
        anything, so one anketa costs at most ONE view per day across the
        whole fleet instead of one per port - and a released no-send claim
        (1.3.81/1.3.99) no longer feeds an immediate re-open carousel. A
        visit row is pure view protection: blocked()/reserve() never
        consult it, so greeting eligibility keeps its own claim/journal/
        block semantics exactly as before («можно через сутки»).
        """
        return (('SELECT peer FROM mumu_greeting_claims WHERE created_at>=? ORDER BY created_at DESC',
                 (claim_cutoff,)),
                ('SELECT peer FROM mumu_profile_visits WHERE checked_at>=? ORDER BY checked_at DESC',
                 (claim_cutoff,)),
                ('SELECT peer FROM mumu_peer_blocks ORDER BY created_at DESC', ()))

    def visited_peers(self,*,claim_cutoff=None):
        from conversation_engine import identifier
        from mumu_greetings import claim_cutoff as greeting_claim_cutoff
        if claim_cutoff is None: claim_cutoff = greeting_claim_cutoff()
        # One consistent, read-only snapshot; no global writer/advisory lock.
        # Tables were initialized at startup, not on every native compilation.
        # Own journals upload COMPLETE (only the native filter prevents
        # reopening the port's own visited profiles); shared registries take
        # everything that still fits, freshest first, so the snapshot never
        # exceeds the contract limit instead of ever stopping the port.
        # v1.3.85: guided/operator bindings (manual adoption) join the visited
        # sources; an engine-created table a fresh store has not built yet is
        # simply absent from the snapshot, never a startup failure.
        values=[];seen=set()
        with self.read_connection() as db:
            for sql in self.VISITED_JOURNAL_SOURCES:
                table=sql.split(' FROM ')[1].split(' ')[0]
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is None:continue
                for row in db.execute(sql):
                    peer=row[0]
                    if peer in seen:continue
                    seen.add(peer);values.append(peer)
            if len(values)>self.VISITED_SNAPSHOT_LIMIT:
                raise StateError('История больше безопасного лимита снимка; журналы не удаляй.')
            for sql,params in self.shared_visited_sources(claim_cutoff):
                remaining=self.VISITED_SNAPSHOT_LIMIT-len(values)
                if remaining<=0:break
                for row in db.execute(sql+' LIMIT ?',(*params,remaining)):
                    peer=row[0]
                    if peer in seen:continue
                    seen.add(peer);values.append(peer)
        return [identifier(x) for x in values]

    def record_visit(self,peer,navigation):
        # v1.3.100 («одна анкета — один просмотр»): the own-port row and the
        # shared window row commit in ONE transaction, so a profile opened by
        # any port is never re-OPENED by another port inside the 24-hour
        # window (the native selection pre-filter skips her without a view).
        # The namespaced row is byte-for-byte the engine's original write
        # (INSERT OR IGNORE, permanent per-port verdict); the shared row is
        # pure view protection with a refreshed window stamp and is NEVER a
        # greeting ban - blocked()/reserve()/peer_claimed() do not consult it.
        # The base implementation is reproduced instead of super()'s so both
        # writes share one BEGIN IMMEDIATE/COMMIT: a failure writes neither
        # (the pre-existing deferred-visit hole is unchanged, never widened).
        from conversation_engine import identifier
        from mumu_greetings import claim_stamp
        who=identifier(peer)
        if navigation['profile_verified'] is not True:
            return
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS profile_visits(peer TEXT PRIMARY KEY, friends_count INTEGER, history_status TEXT NOT NULL, checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            db.execute('INSERT OR IGNORE INTO profile_visits(peer,friends_count,history_status) VALUES(?,?,?)',
                       (who, navigation['friends_count'], navigation['history_status']))
            db.execute('INSERT OR REPLACE INTO mumu_profile_visits(peer,checked_at) VALUES(?,?)',
                       (who, claim_stamp()))

    def skip_recovery_peer(self,who):
        from one_chat_probe import identity
        who=identity(who)
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO profile_recovery_skips(peer) VALUES(?)',(who['peer'],))
