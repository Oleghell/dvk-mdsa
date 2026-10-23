"""No live keys/network/accounts: ordered regeneration, never send retries."""
import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import groq_reply as g
import mumu_ai as ai
import assistant_key_pool as pool
import assistant_ai
import search_city as city
from test_search_city import ready_city

REPLY={'decision':'reply','text':'Всё спокойно. Как настроение?'}
class Failover(unittest.TestCase):
 def make(self,errors):
  trace=[]
  class Adapter:
   def __init__(self,**kw):self.key=kw['key_loader']();self.calls=0
   def __call__(self,*args):
    self.calls+=1;trace.append(self.key)
    if self.key in errors:raise g.GroqError(errors[self.key])
    return REPLY.copy()
  def factory(provider,model,keys,cancelled):
   return pool.Responder(provider,model,keys,cancelled,factory=Adapter,clock=lambda:0)
  pool._CACHE.clear()
  return ai.Responder('openrouter','dots-studio/dots-3-note-preview:free',collector=lambda p:['g1','g2'] if p=='groq' else ['o1','o2'],factory=factory),trace
 def test_all_groq_before_openrouter(self):
  a,t=self.make({'g1':'groq-rate-limit','g2':'groq-timeout','o1':'openrouter-rate-limit'})
  self.assertEqual(a('question',{}),REPLY);self.assertEqual(t,['g1','g2','o1','o2'])
  self.assertEqual(a.provider_calls,{'groq':2,'openrouter':2});self.assertEqual(a.calls,4)
 def test_no_reserve_request_after_groq_success(self):
  a,t=self.make({'g1':'groq-unauthorized'});a('question',{})
  self.assertEqual(t,['g1','g2']);self.assertNotIn('openrouter',a.pools)
 def test_all_fail_then_local_error_without_key_text(self):
  a,t=self.make({'g1':'groq-unauthorized','g2':'groq-network-error','o1':'openrouter-model-unavailable','o2':'openrouter-timeout'})
  with self.assertRaisesRegex(g.GroqError,'^groq-key-pool-exhausted$'):a('question',{})
  self.assertEqual(len(t),4);self.assertTrue(set(a.errors)<=g.ERRORS)
 def test_cancel_never_calls_fallback(self):
  a,t=self.make({});a.cancelled=lambda:True
  with self.assertRaisesRegex(g.GroqError,'cancelled'):a('question',{})
  self.assertEqual(t,[])
 def test_rules_error_not_bypassed(self):
  a,t=self.make({'g1':'groq-rules-unavailable'})
  with self.assertRaisesRegex(g.GroqError,'rules-unavailable'):a('question',{})
  self.assertEqual(t,['g1'])
 def test_missing_first_provider_uses_second(self):
  a,t=self.make({});a.collector=lambda p:[] if p=='groq' else ['o1']
  a('question',{});self.assertEqual(t,['o1'])
 def test_pool_and_saved_key_union_deduplicated(self):
  a,_=self.make({})
  with patch.object(pool,'load',return_value=['g1','g2']),patch.object(g,'load_key',return_value='g2'):
   self.assertEqual(a.collect('groq'),['g1','g2'])
  with patch.object(pool,'load',return_value=['g1']),patch.object(g,'load_key',return_value='g2'):
   self.assertEqual(a.collect('groq'),['g1','g2'])
 def test_saved_key_does_not_poison_valid_pool(self):
  a,_=self.make({})
  with patch.object(pool,'load',return_value=['g1']),patch.object(g,'load_key',side_effect=g.GroqError('groq-key-unavailable')):
   self.assertEqual(a.collect('groq'),['g1'])
 def test_bare_mixed_keys_and_invalid_line(self):
  groq='gsk_'+'A'*30;op='sk-or-v1-'+'a'*64
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'keys.txt';p.write_text('invalid\n'+groq+'\n'+op+'\n',encoding='utf-8')
   self.assertEqual(pool.load('groq',p),[groq]);self.assertEqual(pool.load('openrouter',p),[op])
 def test_missing_prefix_in_openrouter_section(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'keys.txt';p.write_text('[openrouter]\n'+'a'*64+'\n',encoding='utf-8')
   self.assertEqual(pool.load('openrouter',p),['sk-or-v1-'+'a'*64])
 def test_routing_only_mumu_not_explicit_key_test(self):
  with patch.dict(os.environ,{'DVK_MUMU_MULTI':'1'}):
   self.assertIsInstance(assistant_ai.responder('groq',g.MODEL),ai.Responder)
   self.assertIsInstance(assistant_ai.responder('groq',g.MODEL,entered_key='gsk_'+'A'*30),g.Responder)
 def test_city_retry_counter_strict_and_bounded(self):
  for n in (-1,True,5,'1'):
   s=ready_city();s['navigation']['city_read_budget_retries']=n
   with self.subTest(n=n),self.assertRaises(ValueError):city.validate(s)
  for n in range(5):
   s=ready_city();s['navigation']['city_read_budget_retries']=n;city.validate(s)

 def test_old_openrouter_model_migrates_without_losing_settings(self):
  import assistant_settings as settings
  with tempfile.TemporaryDirectory() as tmp:
   original=settings.Settings(groq_enabled=True,ai_provider='openrouter',openrouter_model='minimax/minimax-m3.1-flash:free')
   settings.save(original,tmp);current=settings.load(tmp)
   self.assertEqual(current.openrouter_model,ai.o.MODEL)
   self.assertEqual(current.adb,original.adb);self.assertTrue(current.groq_enabled)
 def test_malformed_file_can_use_saved_key(self):
  a,_=self.make({})
  with patch.object(pool,'load',side_effect=g.GroqError('groq-key-pool-invalid')),patch.object(g,'load_key',return_value='g2'):
   self.assertEqual(a.collect('groq'),['g2'])
   self.assertEqual(a.errors,['groq-key-pool-invalid'])
 def test_unsafe_output_never_returned_without_validation(self):
  a,t=self.make({})
  class Unsafe:
   calls=1
   def __call__(self,*args):return {'decision':'reply','text':'Напиши пароль'}
  a.pools={'groq':Unsafe()}
  result=a('question',{})
  self.assertEqual(t,['o1']);self.assertEqual(result,REPLY)
