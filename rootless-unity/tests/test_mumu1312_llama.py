"""Selectable Llama preset and explicit missing-model errors; synthetic only."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock,patch
import assistant_ai as ai
import assistant_settings as settings
import assistant_key_pool as pool
import groq_reply as g
from test_guided_chain import snapshot

MODEL='llama-3.1-8b-instant'
class Llama(unittest.TestCase):
    def test_preset_is_selectable_but_not_default(self):
        self.assertIn(MODEL,ai.PRESETS['groq']);self.assertEqual(ai.PRESETS['groq'][0],g.MODEL)
        self.assertEqual(settings.Settings().groq_model,g.MODEL);self.assertNotEqual(g.MODEL,MODEL)
    def test_choice_persists_and_restores_without_overwriting_other_settings(self):
        s=settings.Settings(groq_enabled=True,groq_model=MODEL,errors_enabled=True)
        with tempfile.TemporaryDirectory() as p:
            settings.save(s,p);loaded=settings.load(p)
            self.assertEqual(loaded,s);self.assertEqual(loaded.ai_model,MODEL)
    def test_payload_uses_explicit_llama_id_with_same_structured_gates(self):
        r=g.Responder(model=MODEL,rules_loader=lambda:'Правила')
        body=r.payload('question',snapshot())
        self.assertEqual(body['model'],MODEL)
        self.assertEqual(body['response_format'],{'type':'json_object'})
        self.assertEqual(body['max_completion_tokens'],1024)
        self.assertIn('history',json.loads(body['messages'][-1]['content']))
    def test_model_not_found_is_not_invalid_key(self):
        client=MagicMock();client.open.side_effect=urllib.error.HTTPError('https://SECRET',404,'SECRET',{},
            io.BytesIO(b'{"error":{"code":"model_not_found","message":"SECRET"}}'))
        r=g.Responder(model=MODEL,opener=client,key_loader=lambda:'synthetic',rules_loader=lambda:'Rules')
        with self.assertRaises(g.GroqError) as e:r('question',snapshot())
        self.assertEqual(str(e.exception),'groq-model-unavailable');self.assertNotIn('SECRET',repr(e.exception))
        self.assertIn('модель недоступна',ai.explain(str(e.exception)));self.assertNotIn('бесплатную',ai.explain(str(e.exception)))
    def test_model_cooldown_does_not_poison_another_model(self):
        pool._CACHE.clear()
        a=pool.Responder('groq',MODEL,['synthetic'],factory=lambda **kw:MagicMock(calls=0))
        b=pool.Responder('groq',g.MODEL,['synthetic'],factory=lambda **kw:MagicMock(calls=0))
        a.state['blocked'][0]=100
        self.assertNotIn(0,b.state['blocked']);self.assertIsNot(a.state,b.state)
    def test_groq_specific_errors_have_settings_explanation(self):
        self.assertIn('организации',ai.explain('groq-organization-restricted'))
        self.assertIn('бесплатную',ai.explain('openrouter-model-unavailable'))
