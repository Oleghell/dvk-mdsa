"""Synthetic-only provider/key/UI regressions. Never uses real keys or the network."""
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

import assistant_ai as ai
import assistant_settings as cfg
import groq_reply as g
import openrouter_reply as o
import test_groq_reply as groq_tests
from test_groq_reply import reply, QUESTION, CONTACT
from test_guided_chain import snapshot

KEY = 'sk-or-v1-' + 'x' * 64


class OpenRouter(unittest.TestCase):
    def client(self, result=None):
        return groq_tests.Adapter().client(result)

    def test_free_request_fixed_endpoint_price_privacy_no_paid_fallback(self):
        client=self.client(); responder=o.Responder(key_loader=lambda:KEY,opener=client)
        self.assertEqual(responder('question',snapshot(('Взаимно',False))),reply())
        request=client.open.call_args.args[0];body=json.loads(request.data)
        self.assertEqual(request.full_url,o.ENDPOINT)
        self.assertEqual(client.open.call_args.kwargs['timeout'],30)
        self.assertTrue(body['model'].endswith(':free'))
        self.assertEqual(body['provider']['max_price'],dict(prompt=0,completion=0))
        self.assertEqual(body['provider']['data_collection'],'deny')
        self.assertTrue(body['provider']['require_parameters'])
        self.assertEqual(body['reasoning'],dict(effort='low',exclude=True))
        self.assertEqual(body['max_tokens'],2048)
        for unsupported in ('models','plugins','tools','max_completion_tokens'):
            self.assertNotIn(unsupported,body)
        self.assertEqual(responder.calls,1)

    def test_paid_auto_router_and_url_models_are_blocked_before_http(self):
        for model in ('openai/gpt-4o','openrouter/auto','openrouter/free','https://PRIVATE',o.MODEL+'?paid=1','x/y:free\n'):
            with self.assertRaises(g.GroqError) as error:o.Responder(model=model)
            self.assertEqual(str(error.exception),'openrouter-paid-model-blocked')

    def test_all_auth_credit_policy_rate_and_server_errors_are_sanitized(self):
        for status,code in ((401,'unauthorized'),(402,'credits-required'),(403,'access-denied'),
                            (404,'model-unavailable'),(429,'rate-limit'),(503,'service-error'),(400,'request-rejected')):
            client=self.client();client.open.side_effect=urllib.error.HTTPError('https://PRIVATE',status,KEY,{},io.BytesIO(KEY.encode()))
            with self.assertRaises(g.GroqError) as error:o.Responder(key_loader=lambda:KEY,opener=client)('question',snapshot())
            self.assertEqual(str(error.exception),'openrouter-'+code)
            self.assertEqual(client.open.call_count,1)

    def test_timeout_malformed_response_and_unsafe_reply_never_fall_back(self):
        for client,code in ((self.client(),'timeout'),(self.client(reply('Как дела? @secret')),'unsafe-reply')):
            if code=='timeout':client.open.side_effect=TimeoutError(KEY)
            with self.assertRaises(g.GroqError) as error:o.Responder(key_loader=lambda:KEY,opener=client)('question',snapshot())
            self.assertEqual(str(error.exception),'openrouter-'+code)
            self.assertEqual(client.open.call_count,1)
        client=self.client();client.open.return_value.__enter__.return_value.read.return_value=b'{"error":{"message":"PRIVATE"}}'
        with self.assertRaises(g.GroqError) as error:o.Responder(key_loader=lambda:KEY,opener=client)('question',snapshot())
        self.assertEqual(str(error.exception),'openrouter-invalid-response')

    def test_cancelled_before_http_and_missing_key(self):
        client=self.client()
        with self.assertRaises(g.GroqError) as error:o.Responder(cancelled=lambda:True,opener=client)('question',snapshot())
        self.assertEqual(str(error.exception),'openrouter-cancelled');client.open.assert_not_called()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(g.GroqError) as error:o.load_key(Path(temp)/'missing')
            self.assertEqual(str(error.exception),'openrouter-key-unavailable')

    def test_separate_encrypted_key_roundtrip_and_crypto_failure_no_plaintext(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'openrouter.dpapi'
            o.save_key(KEY,path,encoder=lambda b:b'E'+b[::-1])
            self.assertNotIn(KEY.encode(),path.read_bytes())
            self.assertEqual(o.load_key(path,decoder=lambda b:b[1:][::-1]),KEY)
            self.assertFalse(path.with_suffix('.tmp').exists())
            with self.assertRaises(g.GroqError):o.save_key('gsk_'+('x'*32),path)
            fresh=Path(temp)/'fresh'
            with self.assertRaises(g.GroqError):o.save_key(KEY,fresh,encoder=lambda b:None)
            self.assertFalse(fresh.exists())


class ConnectionAndSettings(unittest.TestCase):
    def test_entered_key_is_used_without_loading_saved_key_or_persisting(self):
        client=groq_tests.Adapter().client()
        with patch.object(g,'Responder',wraps=g.Responder) as cls,patch.object(g,'load_key') as stored,patch.object(g,'save_key') as saved:
            responder=ai.responder('groq',g.MODEL,entered_key='  gsk_'+('x'*32)+'  ')
            # Capture the loader passed by the UI helper, not a nonexistent DPAPI file.
            self.assertEqual(cls.call_args.kwargs['key_loader'](),'gsk_'+('x'*32))
            stored.assert_not_called();saved.assert_not_called()
        with patch.object(o,'Responder',wraps=o.Responder) as cls:
            ai.responder('openrouter',o.MODEL,entered_key=KEY)
            self.assertEqual(cls.call_args.kwargs['key_loader'](),KEY)

    def test_empty_field_preserves_default_saved_key_loader(self):
        with patch.object(g,'Responder') as cls:
            ai.responder('groq',g.MODEL)
            self.assertNotIn('key_loader',cls.call_args.kwargs)

    def test_test_connection_checks_both_stages_and_explicit_refusal(self):
        for provider,adapter,model in (('groq',g,g.MODEL),('openrouter',o,o.MODEL)):
            fake=MagicMock(side_effect=[reply(),reply(CONTACT),dict(decision='decline',text='')]);fake.calls=3
            with patch.object(adapter,'Responder',return_value=fake):
                self.assertEqual(ai.test_connection(provider,model),3)
            self.assertEqual([c.args[0] for c in fake.call_args_list],['question','contact','question'])
            self.assertEqual([c.args[1]['_reply_ids'] for c in fake.call_args_list],[['2'],['4'],['2']])
            fake=MagicMock(return_value=dict(decision='review',text=''))
            with patch.object(adapter,'Responder',return_value=fake),self.assertRaises(g.GroqError) as error:
                ai.test_connection(provider,model)
            self.assertEqual(str(error.exception),provider+'-self-test-failed')
            self.assertEqual(fake.call_count,1)

    def test_save_load_schema4_and_migrate_old_default_without_touching_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            value=cfg.Settings(groq_enabled=True,ai_provider='openrouter',openrouter_model=o.MODELS[1])
            cfg.save(value,temp);self.assertEqual(cfg.load(temp),value)
            self.assertEqual(cfg.load(temp).ai_model,o.MODELS[1])
            path=Path(temp)/'workflow-settings.json'
            body=json.loads(path.read_text());body.update(settings_version=3,groq_model='llama-3.3-70b-versatile')
            body.pop('profile_interval');body.pop('ai_provider');body.pop('openrouter_model');path.write_text(json.dumps(body))
            migrated=cfg.load(temp)
            self.assertEqual(migrated.groq_model,g.MODEL);self.assertEqual(migrated.ai_provider,'groq')
            self.assertTrue(migrated.groq_enabled)
            self.assertNotIn('key',path.read_text())
        for changes in (dict(ai_provider='unknown'),dict(openrouter_model='openai/gpt-4o')):
            with self.assertRaises(Exception):cfg.Settings(**changes).check()

    def test_reason_codes_show_in_telegram_without_private_text(self):
        from assistant_error_notify import reasons
        self.assertIn('openrouter-rate-limit',reasons(dict(reason='chat-openrouter-rate-limit',PRIVATE=KEY)))
        self.assertIn('Вставь ключ',ai.explain('groq-key-unavailable'))
        self.assertNotIn(KEY,ai.explain('openrouter-rate-limit'))




class SettingsWindowRegression(unittest.TestCase):
    def test_ui_test_uses_unsaved_entry_and_key_save_is_independent_of_telegram(self):
        import sys
        import assistant_app as app
        class Var:
            def __init__(self, value=''): self.value=value
            def get(self): return self.value
            def set(self, value): self.value=value
        tk,ttk=MagicMock(),MagicMock();tk.ttk=ttk
        tk.StringVar.side_effect=lambda value='':Var(value)
        tk.BooleanVar.side_effect=lambda value=False:Var(value)
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog}), \
             patch.object(app,'load',return_value=cfg.Settings()), \
             patch.object(app,'save') as settings_saved, \
             patch.object(app.telegram_notify,'load',return_value=('token','chat')), \
             patch.object(g,'load_key') as stored, patch.object(g,'save_key') as saved, \
             patch.object(ai,'test_connection',return_value=3) as tested, \
             patch.object(app.threading,'Thread') as thread:
            app.launch()
            commands={c.kwargs['text']:c.kwargs['command'] for c in ttk.Button.call_args_list}
            commands['Настройки']()
            commands={c.kwargs['text']:c.kwargs['command'] for c in ttk.Button.call_args_list}
            key_var=next(c.kwargs['textvariable'] for c in ttk.Entry.call_args_list if c.kwargs.get('show')=='*')
            typed='gsk_'+('x'*32);key_var.set(typed)
            commands['Тест ИИ (введённый или сохранённый ключ)']()
            thread.call_args.kwargs['target']()
            self.assertEqual(tested.call_args.args[:3],('groq',g.MODEL,typed))
            stored.assert_not_called();saved.assert_not_called();settings_saved.assert_not_called()
            commands['Сохранить ключ ИИ']()
            saved.assert_called_once_with(typed)
            self.assertEqual(key_var.get(),'')
            settings_saved.assert_not_called()

    @unittest.skipUnless(__import__('os').name=='nt','Windows DPAPI only')
    def test_real_windows_dpapi_roundtrip_is_not_plaintext(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'openrouter.dpapi'
            o.save_key(KEY,path)
            self.assertNotIn(KEY.encode(),path.read_bytes())
            self.assertEqual(o.load_key(path),KEY)

if __name__=='__main__':unittest.main()
