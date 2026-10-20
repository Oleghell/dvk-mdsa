"""Separate one-chat test state: IDs and salted fingerprints, never bodies."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import re

from one_chat_probe import identity


def default_path():
    if not os.environ.get('LOCALAPPDATA'):
        raise ValueError('Windows LOCALAPPDATA required')
    return Path(os.environ['LOCALAPPDATA']) / 'DvkRootless' / 'one-chat-check.sqlite3'


class TestChatStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()
        # Never reuse enrollment/review DB, including their WAL/SHM files.
        if self.path.name != 'one-chat-check.sqlite3':
            raise ValueError('Separate test database required')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS test_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS test_seen(message_key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS test_preview(singleton INTEGER PRIMARY KEY CHECK(singleton=1),code TEXT NOT NULL,snapshot_key TEXT NOT NULL);
        ''')
        self.db.execute("INSERT OR IGNORE INTO test_meta VALUES('salt',?)", (secrets.token_hex(32),))
        self.salt = bytes.fromhex(self.db.execute("SELECT value FROM test_meta WHERE key='salt'").fetchone()[0])

    def close(self):
        self.db.close()

    def bound(self):
        row = self.db.execute("SELECT value FROM test_meta WHERE key='identity'").fetchone()
        return identity(json.loads(row[0])) if row else None

    def bind(self, who):
        who = identity(who)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old = self.bound()
            if old is not None and old != who:
                raise ValueError('Another chat is already bound; no automatic rebind')
            self.db.execute("INSERT OR IGNORE INTO test_meta VALUES('identity',?)", (json.dumps(who, sort_keys=True),))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _hash(self, value):
        return hmac.new(self.salt, json.dumps(value, ensure_ascii=False, sort_keys=True).encode(), hashlib.sha256).hexdigest()

    def consume(self, snapshot, *, preview=False):
        who = identity(snapshot['identity'])
        messages = snapshot['messages']
        if not isinstance(messages, list) or len(messages) > 20:
            raise ValueError('Invalid test snapshot')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.bound() != who:
                raise ValueError('Different test dialog')
            old = dict(self.db.execute('SELECT message_key,fingerprint FROM test_seen'))
            records = {}
            incoming = set()
            for m in messages:
                if not isinstance(m, dict) or set(m) != {'id','sender','text'}:
                    raise ValueError('Invalid test message')
                identity(dict(account=who['account'], peer=who['peer'], chat=m['id']))
                if m['sender'] not in (who['account'],who['peer']):
                    raise ValueError('Invalid sender')
                if m['text'] is not None and (not isinstance(m['text'],str) or len(m['text'])>2048 or '\x00' in m['text']):
                    raise ValueError('Invalid text')
                key = self._hash(m['id'])
                if key in records:
                    raise ValueError('Duplicate message')
                records[key] = self._hash(m)
                if m['sender'] == who['peer']:
                    incoming.add(key)
            if sum(len(m['text'] or '') for m in messages) > 16384:
                raise ValueError('Too much text')
            if not set(old) <= set(records) or any(records[k] != v for k,v in old.items()):
                raise ValueError('History changed; nothing consumed')
            baseline = self.db.execute("SELECT 1 FROM test_meta WHERE key='baseline'").fetchone() is None
            new_incoming = 0 if baseline else len(incoming - set(old))
            preview_fields = None
            if preview:
                from one_chat_preview import CODE, decide
                saved = self.db.execute('SELECT code,snapshot_key FROM test_preview WHERE singleton=1').fetchone()
                if saved and (saved[0] != CODE or not re.fullmatch('[0-9a-f]{64}', saved[1])):
                    raise ValueError('Invalid saved preview')
                snapshot_key = self._hash(sorted(records.items()))
                expired = bool(saved and saved[1] != snapshot_key)
                new_messages = [m for m in messages if self._hash(m['id']) not in old]
                preview_fields = decide(baseline, new_messages, who['account'],
                                        saved=bool(saved), expired=expired)
                self.db.execute('DELETE FROM test_preview')
                if preview_fields['preview_available']:
                    self.db.execute('INSERT INTO test_preview VALUES(1,?,?)', (CODE, snapshot_key))
            elif set(records) != set(old):
                # Reading without preview must not leave an obsolete suggestion.
                self.db.execute('DELETE FROM test_preview')
            self.db.executemany('INSERT OR IGNORE INTO test_seen VALUES(?,?)', records.items())
            self.db.execute("INSERT OR IGNORE INTO test_meta VALUES('baseline','1')")
            self.db.execute('COMMIT')
            result = dict(status='baseline-recorded' if baseline else 'read-complete',
                        observed_messages=len(records), incoming_messages=len(incoming),
                        new_incoming=new_incoming, baseline_recorded=True)
            if preview_fields is not None:
                result.update(preview_fields)
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
