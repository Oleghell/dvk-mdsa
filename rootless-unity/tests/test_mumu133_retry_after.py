"""Synthetic quota scheduling; never credentials, live providers or send retries."""
import io, unittest, urllib.error
from email.message import Message
from unittest.mock import MagicMock
import assistant_key_pool as pool
import groq_reply as g
from test_groq_reply import KEY, snapshot

class RetryAfter(unittest.TestCase):
 def setUp(self):pool._CACHE.clear()
 def test_numeric_bounded_header(self):
  for raw,want in [('445',445),('0.2',1),(' 152 ',152),('999999',86400),('nan',None),('-2',None),('secret',None),('1e9',None),('2026-10-23',None)]:
   h=Message();h['Retry-After']=raw;self.assertEqual(g.retry_after_seconds(h),want)
 def test_http_error_keeps_only_closed_code_and_numeric_delay(self):
  h=Message();h['Retry-After']='422';client=MagicMock()
  client.open.side_effect=urllib.error.HTTPError('https://PRIVATE',429,'PRIVATE',h,io.BytesIO(b'PRIVATE KEY BODY'))
  r=g.Responder(key_loader=lambda:KEY,opener=client)
  with self.assertRaises(g.GroqError) as got:r('question',snapshot())
  self.assertEqual(str(got.exception),'groq-rate-limit');self.assertEqual(got.exception.retry_after,422)
  self.assertNotIn('PRIVATE',repr(got.exception.__dict__))
 def test_pool_waits_for_provider_delay_but_tries_other_keys_now(self):
  now=[0];trace=[]
  class Adapter:
   def __init__(self,**kw):self.key=kw['key_loader']();self.calls=0
   def __call__(self,*_):
    self.calls+=1;trace.append(self.key);raise g.GroqError('groq-rate-limit',retry_after=422)
  p=pool.Responder('groq',g.MODEL,['one','two'],factory=Adapter,clock=lambda:now[0])
  for instant,want in [(0,2),(61,2),(421,2),(423,4)]:
   now[0]=instant
   with self.assertRaisesRegex(g.GroqError,'groq-key-pool-exhausted'):p('question',{})
   self.assertEqual(len(trace),want)
 def test_short_or_invalid_delay_does_not_remove_minimum_backoff(self):
  for delay,want in [(2,2),(86401,None),('secret',None),(float('nan'),None),(True,None)]:
   self.assertEqual(g.GroqError('groq-rate-limit',retry_after=delay).retry_after,want)

if __name__=='__main__':unittest.main()
