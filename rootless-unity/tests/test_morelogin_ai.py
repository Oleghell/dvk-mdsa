"""Synthetic credentials/responses only: no keys, provider traffic or chat sends."""
import os,unittest
from unittest.mock import patch,MagicMock
import assistant_ai as ai
import assistant_key_pool as pool
import groq_reply as g
import openrouter_reply as o
import morelogin_ai as runtime
from morelogin_fast_adb import Timings
from morelogin_common import CloudError

REPLY=dict(decision='reply',text='Как настроение?')
class Failover(unittest.TestCase):
 def setUp(self):pool._CACHE.clear()
 def setup_keys(self):
  self.loads=patch.object(pool,'load',side_effect=lambda p:['g1','g2'] if p=='groq' else ['o1','o2']);self.loads.start();self.addCleanup(self.loads.stop)
  for mod in (g,o):
   p=patch.object(mod,'load_key',side_effect=g.GroqError(('groq' if mod is g else 'openrouter')+'-key-unavailable'));p.start();self.addCleanup(p.stop)
 def factory(self,provider,failures):
  def make(**kw):
   key=kw['key_loader']();self.models.append((provider,kw['model']))
   client=MagicMock(calls=0)
   def call(*args):
    self.order.append(key);client.calls+=1
    if key in failures:raise g.GroqError(provider+'-'+failures[key])
    return dict(REPLY)
   client.side_effect=call;return client
  return make
 def run_with(self,failures,provider='openrouter'):
  self.setup_keys();self.order=[];self.models=[]
  self.metrics=Timings()
  client=runtime.Responder(provider,o.MODEL if provider=='openrouter' else g.MODEL,metrics=self.metrics)
  a=patch.object(g,'Responder',side_effect=self.factory('groq',failures));b=patch.object(o,'Responder',side_effect=self.factory('openrouter',failures))
  a.start();b.start();self.addCleanup(a.stop);self.addCleanup(b.stop)
  return client
 def test_groq_priority_even_when_ui_selected_openrouter(self):
  c=self.run_with({});self.assertEqual(c('question',{}),REPLY)
  self.assertEqual(self.order,['g1']);self.assertEqual(c.calls,1)
  self.assertTrue(all(value==('groq',g.MODEL) for value in self.models))
  self.assertEqual(self.metrics.snapshot()['ai_openrouter']['calls'],0)
 def test_second_groq_key_before_any_openrouter(self):
  c=self.run_with({'g1':'rate-limit'});self.assertEqual(c('question',{}),REPLY)
  self.assertEqual(self.order,['g1','g2']);self.assertEqual(c.calls,2)
 def test_all_groq_then_second_free_openrouter(self):
  c=self.run_with({'g1':'network-error','g2':'timeout','o1':'rate-limit'})
  self.assertEqual(c('question',{}),REPLY);self.assertEqual(self.order,['g1','g2','o1','o2'])
  self.assertTrue(all(m.endswith(':free') for p,m in self.models if p=='openrouter'))
 def test_skip_only_after_all_available_keys_fail(self):
  c=self.run_with(dict(g1='unauthorized',g2='timeout',o1='credits-required',o2='service-error'))
  with self.assertRaisesRegex(g.GroqError,'^groq-key-pool-exhausted$'):c('question',{})
  self.assertEqual(self.order,['g1','g2','o1','o2']);self.assertEqual(c.calls,4)
  # Known failed keys cool down; no hammering requests on each poll.
  with self.assertRaises(g.GroqError):c('question',{})
  self.assertEqual(len(self.order),4)
 def test_saved_key_appended_and_duplicates_not_retried(self):
  c=self.run_with({'g1':'unauthorized','g2':'timeout'})
  with patch.object(g,'load_key',return_value='saved-groq'):
   self.assertEqual(c('question',{}),REPLY)
  self.assertEqual(self.order,['g1','g2','saved-groq'])
 def test_cancellation_does_not_try_backup(self):
  c=self.run_with({});c.cancelled=lambda:True
  with self.assertRaisesRegex(g.GroqError,'groq-cancelled'):c('question',{})
  self.assertEqual(self.order,[])
 def test_local_rules_failure_is_not_misreported_as_service_down(self):
  c=self.run_with({'g1':'rules-unavailable'})
  with self.assertRaisesRegex(g.GroqError,'groq-rules-unavailable'):c('question',{})
  self.assertEqual(self.order,['g1'])
 def test_review_or_decline_not_overridden_by_backup(self):
  for decision in ('review','decline'):
   with self.subTest(decision=decision),patch.object(pool,'load',return_value=['synthetic']),patch.object(g,'load_key',side_effect=g.GroqError('groq-key-unavailable')),patch.object(g,'Responder',return_value=MagicMock(calls=1,return_value=dict(decision=decision,text=''))),patch.object(o,'Responder') as backup:
    self.assertEqual(runtime.Responder('groq',g.MODEL)('question',{})['decision'],decision);backup.assert_not_called()
 def test_no_credentials_no_network_and_no_raw_key_export(self):
  with patch.object(pool,'load',return_value=[]),patch.object(g,'load_key',side_effect=g.GroqError('groq-key-unavailable')),patch.object(o,'load_key',side_effect=g.GroqError('openrouter-key-unavailable')):
   with self.assertRaisesRegex(g.GroqError,'^groq-key-pool-exhausted$'):runtime.Responder('groq',g.MODEL)('question',{})
 def test_scope_restores_and_never_patches_mumu_or_ui_entered_test(self):
  original=ai.responder
  with patch.dict(os.environ,{'DVK_MORELOGIN':'0'}),self.assertRaises(CloudError):
   with runtime.runtime():pass
  with patch.dict(os.environ,{'DVK_MORELOGIN':'1'}):
   with runtime.runtime():
    self.assertIsInstance(ai.responder('groq',g.MODEL),runtime.Responder)
    with patch.object(g,'Responder') as ctor:
     ai.responder('groq',g.MODEL,entered_key='gsk_'+'x'*32);ctor.assert_called_once()
    with self.assertRaises(CloudError):
     with runtime.runtime():pass
  self.assertIs(ai.responder,original)
 def test_models_and_actual_request_totals_honor_both_settings(self):
  c=self.run_with({'g1':'rate-limit','g2':'service-error'},provider='groq')
  c.models={'groq':'synthetic-groq','openrouter':'synthetic/free:free'};c.totals=dict(groq=0,openrouter=0)
  c('question',{})
  self.assertEqual(c.totals,dict(groq=2,openrouter=1))
  self.assertIn(('groq','synthetic-groq'),self.models);self.assertIn(('openrouter','synthetic/free:free'),self.models)
 def test_inbox_report_counts_actual_providers_and_restores_scope(self):
  import assistant_inbox
  from assistant_settings import Settings
  original=assistant_inbox.run
  def fake_inbox(settings,*args,**kwargs):
   ai.responder(settings.ai_provider,settings.ai_model)('question',{})
   return dict(ai_requests=999,groq_requests=999,openrouter_requests=999)
  self.setup_keys();self.order=[];self.models=[]
  with patch.dict(os.environ,{'DVK_MORELOGIN':'1'}),patch.object(assistant_inbox,'run',side_effect=fake_inbox),patch.object(g,'Responder',side_effect=self.factory('groq',{'g1':'timeout','g2':'service-error'})),patch.object(o,'Responder',side_effect=self.factory('openrouter',{})):
   with runtime.runtime() as totals:
    out=assistant_inbox.run(Settings(groq_enabled=True))
    self.assertEqual((out['groq_requests'],out['openrouter_requests'],out['ai_requests']),(2,1,3))
    self.assertEqual(totals,dict(groq=2,openrouter=1));self.assertEqual(out['ai_provider_order'],['groq','openrouter'])
  self.assertIs(assistant_inbox.run,original)
