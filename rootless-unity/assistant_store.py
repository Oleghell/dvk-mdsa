"""Durable per-recipient manual authorization; no message bodies or token storage."""
from contextlib import contextmanager, closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from assistant_config import check_text
from cohort_pass import Store as LegacyStore


class StateError(RuntimeError):
    pass


def data_directory():
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise StateError('Не найдена папка данных Windows.')
    if os.environ.get('DVK_MORELOGIN') == '1':
        from morelogin_common import root_directory, phone_directory
        cloud_id = os.environ.get('DVK_MORELOGIN_PHONE_ID')
        return phone_directory(cloud_id) if cloud_id else root_directory()
    return Path(base) / 'DvkAssistant'


class Store:
    def __init__(self, path=None, legacy_directory=None):
        self.path = Path(path) if path is not None else data_directory() / 'assistant.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.legacy = (Path(legacy_directory) if legacy_directory is not None
                       else self.path.parent.parent / 'DvkRootless')
        with self.connection() as db:
            from assistant_statistics import initialize
            initialize(db)
            db.execute('''CREATE TABLE IF NOT EXISTS manual_actions(
              id INTEGER PRIMARY KEY, account TEXT NOT NULL, peer TEXT NOT NULL,
              initial_chat TEXT NOT NULL, text_hash TEXT NOT NULL,
              confirmed INTEGER NOT NULL CHECK(confirmed=1),
              status TEXT NOT NULL CHECK(status IN ('reserved-unknown','not-invoked',
                'attempted-unknown','handler-returned-unconfirmed')),
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(account,peer))''')
            from assistant_statistics import greeting_backfill
            greeting_backfill(db)

    def visited_peers(self):
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS profile_visits(peer TEXT PRIMARY KEY, friends_count INTEGER, history_status TEXT NOT NULL, checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            peers = [row[0] for row in db.execute('SELECT peer FROM profile_visits UNION SELECT peer FROM manual_actions')]
        if len(peers) > 10000:
            raise StateError('Журнал анкет слишком большой. Нужна проверка архива, не удаление резервов отправки.')
        from conversation_engine import identifier
        for peer in peers:
            identifier(peer)
        return peers

    def record_visit(self, peer, navigation):
        from conversation_engine import identifier
        identifier(peer)
        # A selected row alone is not proof the profile was actually opened.
        if navigation['profile_verified'] is not True:
            return
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS profile_visits(peer TEXT PRIMARY KEY, friends_count INTEGER, history_status TEXT NOT NULL, checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            db.execute('INSERT OR IGNORE INTO profile_visits(peer,friends_count,history_status) VALUES(?,?,?)',
                       (peer, navigation['friends_count'], navigation['history_status']))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
        finally:
            db.close()

    def check_legacy(self, account, peer):
        # Never erase or migrate the old journals. Any unreadable existing journal
        # fails closed; a new application is not a reset of an old send limit.
        path = self.legacy / 'new-ten.sqlite3'
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute('SELECT 1 FROM bindings WHERE account=? AND peer=?', (account, peer)).fetchone():
                    raise StateError('Этому собеседнику уже выделялась попытка в старом журнале.')
        path = self.legacy / 'one-chat-check.sqlite3'
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='test_manual_send'").fetchone()
                if exists and db.execute('SELECT 1 FROM test_manual_send').fetchone():
                    row = db.execute("SELECT value FROM test_meta WHERE key='identity'").fetchone()
                    if not row:
                        raise StateError('Не удалось проверить старую привязку.')
                    who = json.loads(row[0])
                    if who['account'] == account and who['peer'] == peer:
                        raise StateError('Для этого чата уже использован прежний лимит отправки.')

    def reserve(self, pending, text, *, approved=False):
        pending = LegacyStore.check(pending)
        check_text(text)
        if approved is not True:
            raise StateError('Нужно отдельное подтверждение этого сообщения.')
        self.check_legacy(pending['account'], pending['peer'])
        with self.connection() as db:
            if db.execute('SELECT 1 FROM manual_actions WHERE account=? AND peer=?',
                          (pending['account'], pending['peer'])).fetchone():
                raise StateError('Повторная отправка заблокирована. Не удаляй журнал.')
            cur = db.execute('''INSERT INTO manual_actions
              (account,peer,initial_chat,text_hash,confirmed,status) VALUES(?,?,?,?,1,'reserved-unknown')''',
              (pending['account'], pending['peer'], pending['chat'], hashlib.sha256(text.encode()).hexdigest()))
            from assistant_statistics import remember_city
            remember_city(db,pending['account'],pending['peer'])
            from assistant_statistics import greeting_reserved
            greeting_reserved(db,pending['account'],pending['peer'])
            return cur.lastrowid

    def finish(self, action_id, navigation):
        attempted = navigation['send_attempted']
        returned = navigation['send_handler_returned']
        if type(attempted) is not bool or type(returned) is not bool or (returned and not attempted):
            raise StateError('Недостоверный результат отправки.')
        status = ('handler-returned-unconfirmed' if returned else
                  'attempted-unknown' if attempted else 'not-invoked')
        with self.connection() as db:
            owner=db.execute('SELECT account,peer FROM manual_actions WHERE id=?',(action_id,)).fetchone()
            cur = db.execute("UPDATE manual_actions SET status=? WHERE id=? AND status='reserved-unknown'",
                             (status, action_id))
            if cur.rowcount != 1:
                raise StateError('Резерв отправки не найден или уже завершён.')
            from assistant_statistics import greeting_finished
            greeting_finished(db,owner[0],owner[1],status)
        return status

    def summary(self):
        with self.connection() as db:
            rows = db.execute('SELECT status,COUNT(*) FROM manual_actions GROUP BY status').fetchall()
        return dict(reserved=sum(n for _, n in rows), statuses=dict(rows), delivery_confirmed=False)


def credential_directory():
    if os.environ.get('DVK_MORELOGIN') == '1':
        from morelogin_common import root_directory
        return root_directory()
    return data_directory()
