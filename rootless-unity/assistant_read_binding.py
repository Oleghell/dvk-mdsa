"""Explicit current-chat read consent. Never grants send/Chain authorization."""
from cloud_database import connect as primary_connect, readonly as primary_readonly, available as primary_available
from contextlib import closing
from pathlib import Path
import sqlite3

from assistant_lock import operation_lock
from assistant_store import StateError, data_directory
from one_chat_device import capture
from one_chat_probe import identity


class ReadBindings:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else data_directory() / 'assistant.sqlite3'

    def bind(self, who, *, approved=False, cancelled=lambda: False):
        who = identity(who)
        if approved is not True:
            raise StateError('Нужно подтвердить привязку открытого чата только для чтения.')
        if cancelled():
            raise StateError('Привязка отменена.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(primary_connect(self.path, timeout=5)) as db, db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS read_only_bindings(
                account TEXT NOT NULL, peer TEXT NOT NULL, chat TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(account,peer), UNIQUE(account,chat))''')
            old = db.execute('SELECT chat FROM read_only_bindings WHERE account=? AND peer=?',
                             (who['account'], who['peer'])).fetchone()
            if old is not None and old[0] != who['chat']:
                raise StateError('У собеседника уже другая привязка. Автоматическая замена запрещена.')
            if cancelled():
                raise StateError('Привязка отменена.')
            db.execute('INSERT OR IGNORE INTO read_only_bindings(account,peer,chat) VALUES(?,?,?)',
                       (who['account'], who['peer'], who['chat']))
            if cancelled():
                raise StateError('Привязка отменена.')
        return 'already-bound' if old else 'bound'


def read_bindings(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='read_only_bindings'").fetchone():
        return []
    from dialog_browser import MAX_TARGETS, targets
    rows = db.execute('SELECT account,peer,chat FROM read_only_bindings ORDER BY rowid LIMIT ?',
                      (MAX_TARGETS + 1,)).fetchall()
    return targets([identity(dict(account=a, peer=p, chat=c)) for a,p,c in rows])


def bind_open_chat(settings, stopped, *, approved=False, reader=capture, journal_path=None):
    if approved is not True:
        raise StateError('Нужно подтвердить привязку открытого чата только для чтения.')
    with operation_lock():
        if stopped.is_set():
            raise StateError('Привязка отменена.')
        # expected=None selects the existing identity-only native path: no bodies.
        value = reader(settings.adb, settings.folder, stopped.is_set, None)
        if not isinstance(value, dict) or set(value) != {'identity', 'messages'} or value['messages'] is not None:
            raise StateError('Открытый чат не подтверждён. Привязка не сохранена.')
        state = ReadBindings(journal_path).bind(value['identity'], approved=True, cancelled=stopped.is_set)
        return dict(status='read-only-bound', binding_state=state, messages_sent=0,
                    chat_content_read=False, send_authorization_granted=False)
