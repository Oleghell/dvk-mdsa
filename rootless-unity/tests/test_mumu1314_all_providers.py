"""Only synthetic adapters. Exhaust every available pool, never replay sends."""
import unittest
from unittest.mock import patch
import mumu_ai as ai
import assistant_key_pool as pool
import groq_reply as g
from test_guided_chain import snapshot

REPLY={'decision':'reply','text':'Всё спокойно. Как настроение?'}

class AllProviders(unittest.TestCase):
    def setUp(self):pool._CACHE.clear()
    def make(self, selected='groq', good='zai2', cancel_at=None):
        trace=[];stopped=[False]
        class Adapter:
            def __init__(self, **kw):self.key=kw['key_loader']();self.calls=0
            def __call__(self,*args):
                self.calls+=1;trace.append(self.key)
                if self.key==cancel_at:stopped[0]=True
                if self.key==good:return REPLY.copy()
                raise g.GroqError(self.key[:-1]+'-unauthorized')
        def factory(provider,model,keys,cancelled):
            return pool.Responder(provider,model,keys,cancelled,factory=Adapter,clock=lambda:0)
        r=ai.Responder(selected,{'groq':ai.g,'openrouter':ai.o,'gemini':ai.google,'zai':ai.z}[selected].MODEL,
            cancelled=lambda:stopped[0],collector=lambda p:[p+'1',p+'2'],factory=factory)
        return r,trace
    def test_all_keys_before_each_next_provider(self):
        r,t=self.make()
        self.assertEqual(r('question',snapshot()),REPLY)
        self.assertEqual(t,[p+str(i) for p in ai.PROVIDERS for i in (1,2)])
        self.assertEqual(r.provider_calls,dict.fromkeys(ai.PROVIDERS,2))
        self.assertEqual(len(ai.safe_failures(r)),7)
    def test_every_selected_provider_can_reach_every_other_provider(self):
        for selected in ai.PROVIDERS:
            with self.subTest(selected=selected):
                pool._CACHE.clear();last=ai.provider_order(selected)[-1];r,t=self.make(selected,good=last+'2')
                self.assertEqual(r('question',snapshot()),REPLY)
                self.assertEqual(t,[p+str(i) for p in ai.provider_order(selected) for i in (1,2)])
    def test_all_fail_stop_after_exactly_one_pass(self):
        r,t=self.make(good=None)
        with self.assertRaisesRegex(g.GroqError,'^groq-key-pool-exhausted$'):r('question',snapshot())
        self.assertEqual(len(t),8)
        self.assertEqual(len(set(t)),8)
        with self.assertRaises(g.GroqError):r('question',snapshot())
        self.assertEqual(len(t),8) # cooldown keys skipped; no sleep/retry storm
    def test_cancel_stops_before_remaining_keys_or_providers(self):
        r,t=self.make(cancel_at='groq1')
        with self.assertRaisesRegex(g.GroqError,'cancelled'):r('question',snapshot())
        self.assertEqual(t,['groq1'])
    def test_bad_local_rules_are_not_a_key_failure(self):
        r,t=self.make()
        class BadRules:
            calls=0;failures=[]
            def __call__(self,*args):raise g.GroqError('groq-rules-unavailable')
        r.pools['groq']=BadRules()
        with self.assertRaisesRegex(g.GroqError,'rules-unavailable'):r('question',snapshot())
        self.assertEqual(t,[]);self.assertEqual(set(r.pools),{'groq'})
    def test_explicit_key_check_never_uses_production_pool(self):
        import assistant_ai
        for provider in ai.PROVIDERS:
            adapter=assistant_ai.module(provider)
            with patch.object(adapter,'key_value',return_value='synthetic'),patch.object(adapter,'Responder') as factory,patch.object(pool,'load',side_effect=AssertionError('must not read pool')):
                responder=factory.return_value;responder.calls=1;responder.return_value=REPLY.copy()
                out=assistant_ai.check_entered_key(provider,adapter.MODEL,'synthetic')
                self.assertTrue(out['answer_verified']);self.assertEqual(out['requests'],1)
                self.assertEqual(factory.call_args.kwargs['key_loader'](),'synthetic')
                self.assertNotIn('text',out)

    def test_setup_accepts_reserve_key_when_selected_provider_has_none(self):
        import assistant_ai
        with patch.object(ai.Responder,'collect',side_effect=lambda p:['synthetic'] if p=='zai' else []):
            self.assertEqual(assistant_ai.check_configured_keys('groq'),1)
    def test_setup_without_any_key_rejected_without_network(self):
        import assistant_ai
        from assistant_store import StateError
        with patch.object(ai.Responder,'collect',return_value=[]):
            with self.assertRaises(StateError):assistant_ai.check_configured_keys('groq')
