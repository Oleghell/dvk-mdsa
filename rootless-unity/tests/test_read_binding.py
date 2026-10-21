"""Synthetic read-only enrollment; no real device, account or network."""
from contextlib import closing, nullcontext
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from assistant_read_binding import ReadBindings, bind_open_chat, read_bindings
from assistant_store import Store, StateError
from assistant_chain import Chain
from assistant_settings import Settings
import assistant_read_check as read
from test_read_check import nav_result

WHO=dict(account='100', peer='200', chat='300')


class ReadBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'assistant.sqlite3'
        self.bindings=ReadBindings(self.path)
        self.stop=threading.Event()

    def test_consent_required_before_device_or_database(self):
        reader=MagicMock()
        with self.assertRaises(StateError):
            bind_open_chat(Settings(), self.stop, reader=reader, journal_path=self.path)
        reader.assert_not_called(); self.assertFalse(self.path.exists())
        with self.assertRaises(StateError): self.bindings.bind(WHO)
        self.assertFalse(self.path.exists())

    def test_binding_reads_only_identity_and_never_creates_send_journal(self):
        reader=MagicMock(return_value=dict(identity=WHO,messages=None))
        with patch('assistant_read_binding.operation_lock',return_value=nullcontext()):
            out=bind_open_chat(Settings(),self.stop,approved=True,reader=reader,journal_path=self.path)
        self.assertFalse(out['send_authorization_granted']); self.assertFalse(out['chat_content_read'])
        self.assertIsNone(reader.call_args.args[3])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(read_bindings(db),[WHO])
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[('read_only_bindings',)])

    def test_duplicate_is_idempotent_and_different_chat_never_overwrites(self):
        self.assertEqual(self.bindings.bind(WHO,approved=True),'bound')
        self.assertEqual(self.bindings.bind(WHO,approved=True),'already-bound')
        with self.assertRaises(StateError): self.bindings.bind(dict(WHO,chat='301'),approved=True)
        with closing(sqlite3.connect(self.path)) as db: self.assertEqual(read_bindings(db),[WHO])

    def test_invalid_or_cancelled_binding_not_saved(self):
        for who in (dict(WHO,chat='-1'),dict(WHO,peer='100'),dict(WHO,chat='0')):
            with self.assertRaises(ValueError): self.bindings.bind(who,approved=True)
        with self.assertRaises(StateError): self.bindings.bind(WHO,approved=True,cancelled=lambda:True)
        self.assertFalse(self.path.exists())

    def test_stop_and_body_results_are_not_saved(self):
        for value in (dict(identity=WHO,messages=[]),dict(identity=WHO,messages=None,extra='private')):
            with patch('assistant_read_binding.operation_lock',return_value=nullcontext()):
                with self.assertRaises(StateError):
                    bind_open_chat(Settings(),self.stop,approved=True,reader=MagicMock(return_value=value),journal_path=self.path)
            self.assertFalse(self.path.exists())
        def reader(*args): self.stop.set(); return dict(identity=WHO,messages=None)
        with patch('assistant_read_binding.operation_lock',return_value=nullcontext()):
            with self.assertRaises(StateError): bind_open_chat(Settings(),self.stop,approved=True,reader=reader,journal_path=self.path)
        self.assertFalse(self.path.exists())

    def test_read_binding_does_not_authorize_chain_or_modify_manual_actions(self):
        store=Store(self.path,Path(self.tmp.name)/'old')
        self.bindings.bind(WHO,approved=True)
        chain=Chain(store)
        with self.assertRaises(StateError): chain.authorized(WHO)
        with store.connection() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM manual_actions').fetchone()[0],0)

    def test_manual_journal_is_preserved(self):
        store=Store(self.path,Path(self.tmp.name)/'old')
        store.reserve(dict(attempt=1,account='100',peer='201',chat='-1',variant=0),'Привет 🙂',approved=True)
        with store.connection() as db: before=db.execute('SELECT * FROM manual_actions').fetchall()
        self.bindings.bind(WHO,approved=True)
        with store.connection() as db: self.assertEqual(db.execute('SELECT * FROM manual_actions').fetchall(),before)

    def test_read_only_chat_is_read_without_chain_analysis_or_disk_mutation(self):
        self.bindings.bind(WHO,approved=True); before=self.path.read_bytes()
        navigator=MagicMock(side_effect=[nav_result('opened',WHO),nav_result('returned',WHO),nav_result('search-ready')])
        reader=MagicMock(return_value=dict(identity=WHO,messages=[dict(id='1001',sender='200',text='PRIVATE')]))
        with patch.object(Chain,'consume',side_effect=AssertionError('No chain for read binding')) as consume, \
             patch.object(Chain,'authorized',side_effect=AssertionError('No send authorization')) as authorize:
            out=read.walk(Settings(),self.stop,navigator=navigator,reader=reader,journal_path=self.path)
        self.assertEqual(out['status'],'dialogs-completed'); self.assertEqual(out['dialogs_read'],1)
        self.assertEqual(out['preview_actions'],dict(question=0,contact=0,none=1))
        self.assertEqual(out['messages_sent'],0); self.assertEqual(self.path.read_bytes(),before)
        consume.assert_not_called(); authorize.assert_not_called()

    def test_changed_chat_is_not_read(self):
        self.bindings.bind(WHO,approved=True)
        reader=MagicMock(); navigator=MagicMock(return_value=nav_result('opened',dict(WHO,chat='301')))
        out=read.walk(Settings(),self.stop,navigator=navigator,reader=reader,journal_path=self.path)
        self.assertEqual(out['status'],'dialogs-stopped'); reader.assert_not_called()
