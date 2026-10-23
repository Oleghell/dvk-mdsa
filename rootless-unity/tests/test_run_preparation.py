"""Lost first-pass cause regression; no device, secrets or network."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock,patch
import assistant_inbox
import assistant_run
import assistant_monitor
import run_preparation as prep
from assistant_config import ConfigError,load
from assistant_settings import Settings
from groq_reply import GroqError
from test_assistant_monitor import list_result

PRIVATE='PRIVATE_TOKEN_phone_message_path'

class Evidence(unittest.TestCase):
    def test_closed_schema(self):
        safe=prep.record(RuntimeError(PRIVATE),'inbox-ai')
        self.assertEqual(safe,dict(stage='inbox-ai',error='prepare-inbox-ai-failed',error_type='RuntimeError'))
        self.assertNotIn(PRIVATE,json.dumps(safe))
        for bad in (dict(safe,body=PRIVATE),dict(safe,stage=[]),dict(safe,error=PRIVATE),
                    dict(safe,database_code=PRIVATE),dict(safe,config_field='cities'),
                    dict(safe,error_type=PRIVATE)):
            self.assertIsNone(prep.clean(bad))

    def test_nested_checkpoint_keeps_innermost(self):
        with self.assertRaises(RuntimeError) as caught:
            with prep.checkpoint('run-inbox'):
                with prep.checkpoint('inbox-ai'):raise RuntimeError(PRIVATE)
        self.assertEqual(prep.record(caught.exception,'run-inbox')['stage'],'inbox-ai')

    def test_known_ai_code_only(self):
        v=prep.record(GroqError('groq-key-pool-invalid'),'inbox-ai')
        self.assertEqual(v['error'],'groq-key-pool-invalid')
        v=prep.record(GroqError(PRIVATE),'inbox-ai')
        self.assertNotIn(PRIVATE,json.dumps(v))

    def test_database_error_code_only(self):
        error=sqlite3.OperationalError(PRIVATE);error.sqlite_errorname='SQLITE_AUTH'
        v=prep.record(error,'inbox-chain')
        self.assertEqual(v['database_code'],'SQLITE_AUTH')
        self.assertNotIn(PRIVATE,prep.message(dict(preparation_failure=v)))

    def test_actual_config_errors_have_file_and_category(self):
        for data,reason in ((b'{','invalid-json'),(b'{"cities":[],"cities":[]}','invalid-structure'),
                            (b'{"cities":["A","A"]}','duplicate-text')):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as d:
                Path(d,'cities.json').write_bytes(data)
                with self.assertRaises(ConfigError) as c:load(d)
                v=prep.record(c.exception,'inbox-config')
                self.assertEqual((v['config_field'],v['config_reason']),('cities',reason))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ConfigError) as c:load(d)
            self.assertEqual(prep.record(c.exception,'inbox-config')['config_reason'],'file-unavailable')

class Propagation(unittest.TestCase):
    def inbox(self,settings=None):
        return assistant_inbox.run(settings or Settings(errors_enabled=False),threading.Event(),MagicMock())

    def full(self,call):
        return assistant_run.start(Settings(errors_enabled=False),threading.Event(),MagicMock(),
              inbox=call,profiles=MagicMock(),lock=nullcontext,write=lambda _: 'last-run.json')

    def test_key_pool_failure_reaches_first_report(self):
        profiles=MagicMock()
        with patch('assistant_ai.responder',side_effect=GroqError('groq-key-pool-invalid')):
            out=self.full(lambda *a,**k:self.inbox(Settings(groq_enabled=True,errors_enabled=False)))
        self.assertEqual(out['reason'],'initialization-failed')
        self.assertEqual(out['preparation_failure']['stage'],'inbox-ai')
        self.assertIn('groq-key-pool-invalid',assistant_run.summary(out))
        self.assertIsNone(out['inbox'])

    def test_lazy_import_failure_is_caught_before_first_inbox(self):
        import builtins
        original=builtins.__import__
        def importing(name,*args,**kwargs):
            if name=='assistant_profiles':raise ModuleNotFoundError(PRIVATE)
            return original(name,*args,**kwargs)
        inbox=MagicMock()
        with patch('builtins.__import__',side_effect=importing):
            out=assistant_run.start(Settings(),threading.Event(),MagicMock(),
                inbox=inbox,lock=nullcontext,write=lambda _: 'last-run.json')
        self.assertEqual(out['preparation_failure']['stage'],'run-imports')
        self.assertEqual(out['preparation_failure']['error_type'],'ModuleNotFoundError')
        self.assertNotIn(PRIVATE,json.dumps(out))
        inbox.assert_not_called()

    def test_contacts_failure_is_not_generic_busy(self):
        import telegram_notify
        with patch('telegram_notify.load',side_effect=telegram_notify.TelegramError(PRIVATE)):
            out=self.full(lambda *a,**k:self.inbox(Settings(contacts_enabled=True,errors_enabled=False)))
        self.assertEqual(out['preparation_failure']['stage'],'inbox-contacts')
        self.assertNotIn(PRIVATE,json.dumps(out)+assistant_run.summary(out))

    def test_database_creation_failure_is_explicit(self):
        with patch('assistant_store.Store',side_effect=sqlite3.OperationalError(PRIVATE)):
            out=self.full(lambda *a,**k:self.inbox())
        self.assertEqual(out['preparation_failure']['stage'],'inbox-database')
        self.assertNotIn(PRIVATE,json.dumps(out))

    def test_lock_and_cancel_not_retried(self):
        inbox=MagicMock()
        def badlock():raise RuntimeError(PRIVATE)
        out=assistant_run.start(Settings(),threading.Event(),MagicMock(),inbox=inbox,
              profiles=MagicMock(),lock=badlock,write=lambda _: 'last-run.json')
        self.assertEqual(out['preparation_failure']['stage'],'run-lock');inbox.assert_not_called()
        stop=threading.Event();stop.set()
        out=assistant_run.start(Settings(),stop,MagicMock(),inbox=inbox,profiles=MagicMock(),
              lock=nullcontext,write=lambda _: 'last-run.json')
        self.assertEqual(out['status'],'cancelled');self.assertIsNone(out['preparation_failure'])
        inbox.assert_not_called()

    def test_full_and_reply_only_monitor_and_telegram(self):
        import assistant_error_notify
        def broken(*a,**k):
            with prep.checkpoint('inbox-chain'):raise sqlite3.OperationalError(PRIVATE)
        for mode in ('full','inbox'):
            with self.subTest(mode=mode):
                def first(*a,**k):return self.full(broken)
                nav=MagicMock(side_effect=lambda op,*a,**k:dict(list_result(),state='search-ready') if op=='return' else list_result())
                out=assistant_monitor.run(Settings(errors_enabled=False),threading.Event(),MagicMock(),
                     mode=mode,initial=first,inbox=broken,navigator=nav,lock=nullcontext,
                     write=lambda _: 'last-monitor.json')
                self.assertEqual(out['last_preparation_failure']['stage'],'inbox-chain')
                self.assertNotIn(PRIVATE,json.dumps(out)+assistant_monitor.summary(out))
                self.assertEqual(out['totals']['submission_calls'],0)
                with patch('telegram_notify.load',return_value=('TOKEN','ID')),patch('telegram_notify.send',return_value='accepted') as send:
                    assistant_error_notify.notify(out,loader=lambda:('TOKEN','ID'),sender=send)
                self.assertIn('prepare-inbox-chain-failed',str(send.call_args))
                self.assertNotIn(PRIVATE,str(send.call_args))

import importlib.util
@unittest.skipIf(importlib.util.find_spec('morelogin_preparation_check') is None,'Cloud preflight not in MuMu')
class PackagedPreflight(unittest.TestCase):
    def test_disposable_shared_database_no_credentials_or_network(self):
        from morelogin_preparation_check import check
        keys=('LOCALAPPDATA','DVK_MORELOGIN','DVK_MORELOGIN_PHONE_ID')
        before={k:os.environ.get(k) for k in keys}
        with patch('telegram_notify.load',side_effect=AssertionError('credentials')),patch('assistant_ai.responder',side_effect=AssertionError('AI')):
            self.assertTrue(check())
        self.assertEqual(before,{k:os.environ.get(k) for k in keys})

    def test_environment_restored_on_failure(self):
        import morelogin_preparation_check as check
        before=dict(os.environ)
        with patch.object(check,'run',side_effect=RuntimeError(PRIVATE)):
            with self.assertRaises(RuntimeError):check.check()
        self.assertEqual(before,dict(os.environ))
