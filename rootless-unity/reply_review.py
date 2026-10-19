"""Durable, human-confirmed replies for the existing cohort only.

This module has no native/Android implementation. ReviewSession requires a
verified reader/sender adapter; ingest never sends. The enrollment database is
opened read-only, and draft-chat IDs are never turned into server chat IDs.
"""
from contextlib import contextmanager, closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Protocol

from conversation_engine import (Snapshot, PolicyError, identifier, contacts,
                                 normalized, REFUSAL, NEGATIVE, QUESTIONS)
from greetings import get_greeting
from telegram_notify import protect

CONTACT_DRAFT = ('Если тебе удобно, можем продолжить в Telegram или WhatsApp. '
                 'Хочешь поделиться контактом?')
MAX_DIALOGS = 10
TERMINAL = {'done', 'declined', 'manual_review'}


class ReviewError(PolicyError):
    pass


@dataclass(frozen=True)
class Binding:
    attempt: int
    account: str
    peer: str
    initial_chat: str
    variant: int
    status: str


@dataclass(frozen=True)
class Identity:
    account: str
    peer: str
    chat: str

    def check(self):
        for value in (self.account, self.peer, self.chat):
            identifier(value)
        if self.account == self.peer:
            raise ReviewError('Self dialog')
        return self


@dataclass(frozen=True)
class Draft:
    id: int
    identity: Identity
    kind: str
    text: str
    snapshot_digest: str


class VerifiedBackend(Protocol):
    """identity must not read bodies; snapshot must verify chronological history.

    submit_reply must revalidate identity, trigger and snapshot_digest on the
    actual UI thread immediately before a single OnSendText invocation. A True
    result means handler return, not delivery. No automatic retry is permitted.
    """
    def identity(self) -> Identity: ...
    def snapshot(self, identity: Identity) -> Snapshot: ...
    def submit_reply(self, identity: Identity, text: str, trigger: str,
                     snapshot_digest: str) -> bool: ...


def default_path():
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise ReviewError('Нужна папка LOCALAPPDATA текущего пользователя Windows.')
    return Path(base) / 'DvkRootless' / 'reply-review.sqlite3'


def load_bindings(path):
    """No Store.create/finish, migrations, checkpoints or enrollment writes."""
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        cohort = db.execute('SELECT singleton,state FROM cohort').fetchall()
        if cohort != [(1, 'closed')]:
            raise ReviewError('Сначала нужен завершённый журнал; повторять проход нельзя.')
        rows = db.execute('SELECT attempt,account,peer,initial_chat,variant,status '
                          'FROM bindings ORDER BY attempt').fetchall()
    if not 1 <= len(rows) <= MAX_DIALOGS:
        raise ReviewError('Invalid cohort size')
    result = []
    attempts, peers, accounts = set(), set(), set()
    # Reuse enrollment's exact signed-Int64 validator, without opening its store.
    from cohort_pass import Store
    for attempt, account, peer, chat, variant, status in rows:
        Store.check(dict(attempt=attempt, account=account, peer=peer,
                         chat=chat, variant=variant))
        if status not in ('reserved-unknown', 'handler-returned-unconfirmed'):
            raise ReviewError('Unknown enrollment outcome')
        if attempt in attempts or peer in peers:
            raise ReviewError('Duplicate cohort binding')
        attempts.add(attempt)
        peers.add(peer)
        accounts.add(account)
        result.append(Binding(attempt, account, peer, chat, variant, status))
    if len(accounts) != 1:
        raise ReviewError('Different cohort accounts')
    return tuple(result)


def digest(snapshot):
    snapshot.check()
    value = [snapshot.account, snapshot.peer, snapshot.chat,
             [[m.id, m.sender, m.text] for m in snapshot.messages]]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


class ReviewStore:
    def __init__(self, cohort_path, path=None, *, choose=lambda: secrets.randbelow(2),
                 seal=protect, unseal=lambda b: protect(b, decrypt=True)):
        self.bindings = load_bindings(cohort_path)
        self.allowed = {(b.account, b.peer): b for b in self.bindings}
        path = Path(path) if path is not None else default_path()
        source = Path(cohort_path).resolve(strict=True)
        protected = {source, Path(str(source) + '-wal'), Path(str(source) + '-shm')}
        if path.resolve() in protected or (path.exists() and os.path.samefile(path, source)):
            raise ReviewError('Review database must be separate from enrollment')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.choose, self.seal, self.unseal = choose, seal, unseal
        try:
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS review_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS review_dialogs(
              peer TEXT PRIMARY KEY,account TEXT NOT NULL,chat TEXT UNIQUE,
              greeting TEXT,anchor TEXT,stage TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS review_drafts(
              id INTEGER PRIMARY KEY,peer TEXT NOT NULL,kind TEXT NOT NULL,
              trigger TEXT NOT NULL,digest TEXT NOT NULL,text TEXT NOT NULL,status TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS review_one_open_draft
              ON review_drafts(peer) WHERE status='draft';
            CREATE TABLE IF NOT EXISTS review_outbox(
              peer TEXT PRIMARY KEY,payload BLOB NOT NULL,status TEXT NOT NULL);
            ''')
            fingerprint = hashlib.sha256(json.dumps([b.__dict__ for b in self.bindings],
                                                    sort_keys=True).encode()).hexdigest()
            with self.tx():
                old = self.db.execute("SELECT value FROM review_meta WHERE key='cohort'").fetchone()
                if old and old[0] != fingerprint:
                    raise ReviewError('Enrollment changed; no automatic rebind')
                self.db.execute("INSERT OR IGNORE INTO review_meta VALUES('cohort',?)", (fingerprint,))
                for b in self.bindings:
                    self.db.execute("INSERT OR IGNORE INTO review_dialogs VALUES(?,?,NULL,NULL,NULL,'wait_reply')",
                                    (b.peer, b.account))
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def authorize(self, identity):
        if not isinstance(identity, Identity):
            raise ReviewError('Invalid identity')
        identity.check()
        if (identity.account, identity.peer) not in self.allowed:
            raise ReviewError('Dialog is not in the saved cohort')
        row = self.db.execute('SELECT chat FROM review_dialogs WHERE peer=?', (identity.peer,)).fetchone()
        b = self.allowed[identity.account, identity.peer]
        if row['chat'] is not None and row['chat'] != identity.chat:
            raise ReviewError('Bound server chat changed')
        if int(b.initial_chat) > 0 and b.initial_chat != identity.chat:
            raise ReviewError('Different enrolled chat')
        return b

    def _snapshot(self, snapshot):
        if not isinstance(snapshot, Snapshot):
            raise ReviewError('Invalid snapshot')
        s = snapshot.check()
        binding = self.authorize(Identity(s.account, s.peer, s.chat))
        first = s.messages[0]
        if first.sender != s.account or first.text != get_greeting(binding.variant):
            raise ReviewError('Enrolled outgoing greeting not verified')
        row = self.db.execute('SELECT * FROM review_dialogs WHERE peer=?', (s.peer,)).fetchone()
        if row['greeting'] is not None and row['greeting'] != first.id:
            raise ReviewError('Greeting identity changed')
        return s, row

    def _stop(self, peer, stage):
        self.db.execute('UPDATE review_dialogs SET stage=? WHERE peer=?', (stage, peer))
        self.db.execute("UPDATE review_drafts SET status='cancelled' WHERE peer=? AND status='draft'", (peer,))

    def ingest(self, snapshot):
        """Consume a verified snapshot; prepare at most one draft, never send."""
        with self.tx():
            s, row = self._snapshot(snapshot)
            if row['stage'] in TERMINAL:
                return row['stage']
            if row['stage'] not in ('wait_reply', 'wait_mood', 'wait_contact', 'pending_question', 'pending_contact'):
                raise ReviewError('Invalid dialog stage')
            first = s.messages[0]
            self.db.execute('UPDATE review_dialogs SET chat=?,greeting=?,anchor=COALESCE(anchor,?) WHERE peer=?',
                            (s.chat, first.id, first.id, s.peer))
            anchor_id = row['anchor'] or first.id
            positions = {m.id: i for i, m in enumerate(s.messages)}
            if anchor_id not in positions:
                raise ReviewError('History anchor is missing')
            after = s.messages[positions[anchor_id] + 1:]
            incoming = [m for m in after if m.sender == s.peer]
            joined = '\n'.join(m.text for m in incoming if m.text is not None)
            if REFUSAL.search(normalized(joined)):
                self._stop(s.peer, 'declined')
                return 'declined'
            found = contacts(joined)
            if found:
                self._stop(s.peer, 'done')
                payload = json.dumps({'name': s.name, 'contacts': found}, ensure_ascii=False).encode()
                try:
                    sealed = self.seal(payload)
                    if not isinstance(sealed, bytes) or not 1 <= len(sealed) <= 16384:
                        raise ReviewError('Invalid sealed payload')
                except Exception:
                    # Stop even when private contact storage is unavailable.
                    # No plaintext fallback and no contact in the error/report.
                    self.db.execute("INSERT OR IGNORE INTO review_outbox VALUES(?,?,'blocked')", (s.peer, b''))
                    return 'contact_storage_unavailable'
                self.db.execute("INSERT OR IGNORE INTO review_outbox VALUES(?,?,'pending')", (s.peer, sealed))
                return 'contact_saved'
            stage = row['stage']
            if stage.startswith('pending_'):
                action = self.db.execute('SELECT * FROM review_drafts WHERE peer=? AND kind=? '
                                         "AND status IN ('attempted','handler_returned','unknown') ORDER BY id DESC LIMIT 1",
                                         (s.peer, stage[8:])).fetchone()
                if action is None:
                    raise ReviewError('Missing attempted action')
                own = [m for m in after if m.sender == s.account]
                if not own:
                    return 'await_outgoing_observation'
                if len(own) != 1 or own[0].text != action['text']:
                    self._stop(s.peer, 'manual_review')
                    return 'manual_review'
                stage = 'wait_mood' if action['kind'] == 'question' else 'wait_contact'
                self.db.execute("UPDATE review_drafts SET status='observed' WHERE id=?", (action['id'],))
                self.db.execute('UPDATE review_dialogs SET stage=?,anchor=? WHERE peer=?', (stage, own[0].id, s.peer))
                after = s.messages[positions[own[0].id] + 1:]
                incoming = [m for m in after if m.sender == s.peer]
                joined = '\n'.join(m.text for m in incoming if m.text is not None)
            if any(m.sender == s.account for m in after):
                self._stop(s.peer, 'manual_review')
                return 'manual_review'
            if not incoming:
                return 'waiting'
            if any(m.text is None or not m.text.strip() for m in incoming) or NEGATIVE.search(normalized(joined)):
                self._stop(s.peer, 'manual_review')
                return 'manual_review'
            if stage == 'wait_contact':
                return 'waiting_contact'
            kind = 'question' if stage == 'wait_reply' else 'contact'
            fingerprint = digest(s)
            old = self.db.execute("SELECT * FROM review_drafts WHERE peer=? AND status='draft'", (s.peer,)).fetchone()
            if old and old['digest'] == fingerprint:
                return 'draft_ready'
            if old:
                self.db.execute("UPDATE review_drafts SET status='superseded' WHERE id=?", (old['id'],))
            if kind == 'question':
                choice = self.choose()
                if type(choice) is not int or choice not in (0, 1):
                    raise ReviewError('Invalid question choice')
                text = QUESTIONS[choice]
            else:
                text = CONTACT_DRAFT
            self.db.execute("INSERT INTO review_drafts(peer,kind,trigger,digest,text,status) VALUES(?,?,?,?,?,'draft')",
                            (s.peer, kind, incoming[-1].id, fingerprint, text))
            return 'draft_ready'

    def drafts(self):
        """Private local UI data. Never include this result in diagnostics."""
        rows = self.db.execute("SELECT d.*,b.account,b.chat FROM review_drafts d JOIN review_dialogs b USING(peer) "
                               "WHERE d.status='draft' ORDER BY d.id").fetchall()
        return tuple(Draft(r['id'], Identity(r['account'], r['peer'], r['chat']),
                           r['kind'], r['text'], r['digest']) for r in rows)

    def edit(self, draft_id, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 4096 or '\x00' in text:
            raise ReviewError('Invalid draft text')
        with self.tx():
            if self.db.execute("UPDATE review_drafts SET text=? WHERE id=? AND status='draft'", (text, draft_id)).rowcount != 1:
                raise ReviewError('Draft is no longer available')

    def reject(self, draft_id):
        with self.tx():
            r = self.db.execute("SELECT peer FROM review_drafts WHERE id=? AND status='draft'", (draft_id,)).fetchone()
            if r is None:
                raise ReviewError('Draft is no longer available')
            self._stop(r['peer'], 'manual_review')

    def confirm(self, draft, snapshot, sender, *, approved=False):
        if approved is not True or not isinstance(draft, Draft):
            raise ReviewError('Explicit confirmation of the displayed draft is required')
        # No side effects before the entire confirmation and reservation commits.
        with self.tx():
            s, dialog = self._snapshot(snapshot)
            row = self.db.execute('SELECT * FROM review_drafts WHERE id=?', (draft.id,)).fetchone()
            if row is None or row['status'] != 'draft' or dialog['stage'] not in ('wait_reply', 'wait_mood'):
                raise ReviewError('Draft is no longer available')
            expected_kind = 'question' if dialog['stage'] == 'wait_reply' else 'contact'
            identity = Identity(s.account, s.peer, s.chat)
            if (draft.identity != identity or row['peer'] != s.peer or row['kind'] != draft.kind
                    or row['kind'] != expected_kind or row['text'] != draft.text
                    or row['digest'] != draft.snapshot_digest or digest(s) != row['digest']):
                raise ReviewError('Draft or incoming history changed; refresh before confirming')
            trigger = row['trigger']
            self.db.execute("UPDATE review_drafts SET status='attempted' WHERE id=?", (draft.id,))
            self.db.execute('UPDATE review_dialogs SET stage=?,anchor=? WHERE peer=?',
                            ('pending_' + draft.kind, trigger, s.peer))
        try:
            accepted = sender(identity, draft.text, trigger, draft.snapshot_digest)
            status = 'handler_returned' if accepted is True else 'unknown'
        except Exception:
            status = 'unknown'
        with self.tx():
            self.db.execute('UPDATE review_drafts SET status=? WHERE id=?', (status, draft.id))
        return status

    def notify_one(self, notifier):
        if notifier is None:
            return 'not_configured'
        with self.tx():
            row = self.db.execute("SELECT * FROM review_outbox WHERE status='pending' ORDER BY rowid LIMIT 1").fetchone()
            if row is None:
                return 'nothing_pending'
            try:
                payload = json.loads(self.unseal(row['payload']))
                if not isinstance(payload, dict) or set(payload) != {'name', 'contacts'}:
                    raise ReviewError('Invalid private payload')
            except Exception:
                self.db.execute("UPDATE review_outbox SET status='blocked' WHERE peer=?", (row['peer'],))
                return 'private_storage_unavailable'
            self.db.execute("UPDATE review_outbox SET status='attempted' WHERE peer=?", (row['peer'],))
        try:
            status = 'accepted' if notifier(payload) is True else 'unknown'
        except Exception:
            status = 'unknown'
        with self.tx():
            self.db.execute('UPDATE review_outbox SET status=? WHERE peer=?', (status, row['peer']))
        return status

    def summary(self):
        """Counts only; not a claim of Android integration or delivery."""
        stages = dict(self.db.execute('SELECT stage,COUNT(*) FROM review_dialogs GROUP BY stage'))
        notifications = dict(self.db.execute('SELECT status,COUNT(*) FROM review_outbox GROUP BY status'))
        drafts = self.db.execute("SELECT COUNT(*) FROM review_drafts WHERE status='draft'").fetchone()[0]
        return dict(bound_dialogs=len(self.bindings), stages=stages, drafts=drafts,
                    notifications=notifications, confirmation_required=True,
                    live_backend_available=False, delivery_confirmed=False)


class ReviewSession:
    """Orchestration boundary: reject untracked identity before reading bodies."""
    def __init__(self, store, backend):
        self.store, self.backend = store, backend

    def capture(self):
        identity = self.backend.identity()
        self.store.authorize(identity)
        s = self.backend.snapshot(identity)
        if not isinstance(s, Snapshot) or Identity(s.account, s.peer, s.chat) != identity:
            raise ReviewError('Identity changed during snapshot')
        s.check()
        return s

    def read_once(self):
        return self.store.ingest(self.capture())

    def confirm(self, draft, *, approved=False):
        if approved is not True:
            raise ReviewError('Explicit confirmation required')
        # Do not read a different tracked dialog just to reject it later.
        if self.backend.identity() != draft.identity:
            raise ReviewError('The displayed draft is for a different dialog')
        return self.store.confirm(draft, self.capture(), self.backend.submit_reply, approved=True)


def main(argv=None):
    """Explicit local counts command. No ADB, Frida, network or sending."""
    import argparse
    from cohort_pass import default_path as enrollment_path
    parser = argparse.ArgumentParser(description='Счётчики ручного ревью; не подключает Android.')
    parser.add_argument('--summary', action='store_true', required=True)
    parser.add_argument('--cohort', type=Path)
    parser.add_argument('--state', type=Path)
    args = parser.parse_args(argv)
    try:
        store = ReviewStore(args.cohort if args.cohort is not None else enrollment_path(), args.state)
        try:
            print(json.dumps(store.summary(), ensure_ascii=False))
        finally:
            store.close()
        return 0
    except (PolicyError, OSError, sqlite3.Error):
        print(json.dumps({'status': 'review-storage-unavailable', 'live_backend_available': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
