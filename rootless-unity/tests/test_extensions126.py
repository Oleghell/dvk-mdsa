"""No real credentials, Telegram, Android or contacts."""
from test_guided_chain import snapshot
from pathlib import Path
import copy,json,struct,tempfile,threading,unittest,zlib
from unittest.mock import MagicMock,patch
import assistant_key_pool as pool
import groq_reply as g
import assistant_inbox as inbox
import telegram_notify as tg
from assistant_store import StateError
from assistant_contact_photo import png_size,capture_profile,profile_source
from assistant_dialog_pages import Pager,page_source
from assistant_settings import Settings
from test_inbox_profiles import Base,WHO,msg,snap,nav,GREETING
from test_inbox_reactivity import ContactFlow


def png(w=300,h=600):
 def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+b'\x00'*w*3)*h))+chunk(b'IEND',b'')

class KeyPool(unittest.TestCase):
 def setUp(self):pool._CACHE.clear()
 def test_file_scopes_provider_and_deduplicates(self):
  a='gsk_'+'a'*24;b='sk-or-v1-'+'b'*24
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'keys.txt';p.write_text('[groq]\n'+a+'\n'+a+'\n[openrouter]\n'+b,encoding='utf-8')
   self.assertEqual(pool.load('groq',p),[a]);self.assertEqual(pool.load('openrouter',p),[b])
   p.write_text('[groq]\nPRIVATE_BAD_KEY',encoding='utf-8')
   with self.assertRaises(g.GroqError) as e:pool.load('groq',p)
   self.assertNotIn('PRIVATE',str(e.exception))
 def test_failover_and_reuse_working_key_no_unsafe_send(self):
  adapters=[]
  def factory(**kw):
   a=MagicMock();a.calls=0
   def call(*args):
    a.calls+=1
    if len(adapters)>0 and a is adapters[0]:raise g.GroqError('groq-rate-limit')
    return dict(decision='reply',text='Как дела?')
   a.side_effect=call;adapters.append(a);return a
  ai=pool.Responder('groq',g.MODEL,['key1','key2'],factory=factory,clock=lambda:0)
  self.assertEqual(ai('question',snapshot())['text'],'Как дела?');self.assertEqual(ai.calls,2)
  ai('question',snapshot());self.assertEqual(ai.calls,3);self.assertEqual(adapters[0].call_count,1)
 def test_unsafe_reply_regenerated_but_not_accepted(self):
  items=[MagicMock(calls=1,return_value=dict(decision='reply',text='https://bad.invalid')),
         MagicMock(calls=1,return_value=dict(decision='reply',text='Как настроение?'))]
  ai=pool.Responder('groq',g.MODEL,['one','two'],factory=lambda **k:items.pop(0),clock=lambda:0)
  self.assertEqual(ai('question',snapshot())['text'],'Как настроение?');self.assertEqual(ai.failovers,1)
 def test_all_keys_failure_exhausts_with_cooldown_not_raw_error(self):
  model=MagicMock(calls=1,side_effect=g.GroqError('groq-unauthorized'))
  ai=pool.Responder('groq',g.MODEL,['one','two'],factory=lambda **k:model,clock=lambda:0)
  for _ in range(2):
   with self.assertRaises(g.GroqError) as e:ai('question',snapshot())
   self.assertEqual(str(e.exception),'groq-key-pool-exhausted')
  self.assertEqual(model.call_count,2)
 def test_cancelled_never_fails_over(self):
  model=MagicMock(calls=0)
  ai=pool.Responder('groq',g.MODEL,['one'],cancelled=lambda:True,factory=lambda **k:model)
  with self.assertRaises(g.GroqError):ai('question',snapshot())
  model.assert_not_called()

class FullInbox(Base):
 def test_more_than_ten_are_processed_without_opening_waiting(self):
  reads=[];moves=[]
  for i in range(15):
   who=dict(account='100',peer=str(200+i),chat=str(300+i));self.journal(who,who['chat'])
   reads.append(snap(msg(1002,'Не пиши мне',who=who),who=who))
   moves.extend([nav('opened',who),nav('returned',who)])
  moves.append(nav('search-ready'))
  out=self.walk(moves,reads)
  self.assertEqual(out['dialogs_processed'],15);self.assertIsNone(out['dialog_limit'])
 def test_short_exit_text_only_sent_to_telegram_not_report(self):
  self.journal();text='Не пиши мне';notice=MagicMock(return_value=True)
  out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[snap(msg(1002,text))],exit_notifier=notice)
  sent=notice.call_args.args[0]
  self.assertIn(text,sent);self.assertIn('отказался',sent);self.assertNotIn('Причина:',sent);self.assertNotIn('диалог ',sent)
  self.assertNotIn(text,json.dumps(out,ensure_ascii=False))
 def test_unsafe_answer_isolated_not_global_stop(self):
  self.journal();chain=self.chain();chain.responder=MagicMock(side_effect=g.GroqError('groq-unsafe-reply'))
  out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[snap(msg(1002,'Привет'))],chain=chain,exit_notifier=MagicMock(return_value=True))
  self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['isolated_dialogs'],1)
  self.assertEqual(out['submission_calls'],0)
 def test_paging_continues_after_initial_page_exhaustion(self):
  self.journal();pager=MagicMock();pager.pages=2;pager.advance.side_effect=[True,False]
  # first page has no eligible rows; second page has an incoming refusal.
  out=self.walk([nav('exhausted'),nav('exhausted'),nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
      [snap(msg(1002,'Не пиши мне'))],pager=pager)
  self.assertEqual(out['dialogs_processed'],1);self.assertEqual(out['pages_checked'],2)

class PhotoFlow(ContactFlow):
 def test_photo_and_contact_one_attempt_saved_before_notify(self):
  chain,messages=self.waiting();chain.media_required=True;image=png()
  snapshot=dict(snap(*messages,msg(1006,'791234567890')),peer_name='Тест')
  stage,_=chain.proposal(snapshot);self.assertEqual(stage,'done')
  self.assertEqual(chain.notify(WHO,self.notifier),'photo-required');self.notifier.assert_not_called()
  capture=MagicMock(return_value=image);chain.prepare_media(WHO,capture);chain.prepare_media(WHO,capture)
  self.assertEqual(capture.call_count,1)
  self.assertEqual(chain.notify(WHO,self.notifier),'accepted')
  self.assertEqual(self.notifier.call_args.args[0]['photo'],image);self.assertFalse(chain.has_media(WHO))
  self.assertEqual(chain.notify(WHO,self.notifier),'nothing-pending');self.assertEqual(self.notifier.call_count,1)
 def test_unknown_photo_is_not_retried(self):
  chain,messages=self.waiting();chain.media_required=True
  chain.proposal(dict(snap(*messages,msg(1006,'791234567890')),peer_name='Тест'))
  chain.prepare_media(WHO,lambda who:png());notifier=MagicMock(side_effect=RuntimeError('PRIVATE'))
  self.assertEqual(chain.notify(WHO,notifier),'unknown');chain.notify(WHO,notifier)
  self.assertEqual(notifier.call_count,1)
 def test_pending_photo_queue_remains_eligible_without_new_incoming(self):
  chain,messages=self.waiting();chain.media_required=True
  chain.proposal(dict(snap(*messages,msg(1006,'791234567890')),peer_name='Тест'))
  attention,_=inbox.inbox_targets(chain);self.assertEqual(attention,[WHO])
 def test_capture_failure_does_not_consume_notification(self):
  chain,messages=self.waiting();chain.media_required=True
  candidate=dict(snap(*messages,msg(1006,'791234567890')),peer_name='Тест')
  out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[candidate],chain=chain,contact_photo=MagicMock(side_effect=StateError('profile-photo-unavailable')))
  self.assertEqual(out['status'],'inbox-completed');self.notifier.assert_not_called()
  self.assertEqual(out['contact_delivery_pending'],1)
  self.assertEqual(out['history_deferred'],1)

class PhotoTransport(unittest.TestCase):
 def test_png_rejects_corruption_and_oversize_dimensions(self):
  self.assertEqual(png_size(png()),(300,600))
  for data in (png()[:-3],b'not png',png()[:-1]+b'x'):
   with self.assertRaises(StateError):png_size(data)
 def test_verify_before_and_after_photo_return_same_chat(self):
  device=MagicMock();device.screen.return_value=png();events=[]
  def reader(*a):
   events.append('chat')
   if len(events)<4 and events.count('profile')>0:raise RuntimeError()
   return snap()
  def profile(*a):events.append('profile');return True
  # first chat read, two profile reads, failed chat read while profile remains,
  # one Back then a verified chat read.
  calls=[0]
  def chat(*a):
   calls[0]+=1
   if calls[0]==2:raise RuntimeError()
   return snap()
  image=capture_profile('adb','folder',WHO,device_factory=lambda *a:device,chat_reader=chat,profile_reader=profile)
  self.assertEqual(image,png());self.assertEqual(events,['profile','profile','profile']);self.assertEqual(calls[0],3)
  self.assertIn(unittest.mock.call(['shell','input','keyevent','4']),device.run.call_args_list)
 def test_wrong_profile_never_returns_image(self):
  device=MagicMock();device.screen.return_value=png()
  with self.assertRaises(StateError):capture_profile('adb','folder',WHO,device_factory=lambda *a:device,chat_reader=lambda *a:snap(),profile_reader=MagicMock(side_effect=StateError('profile-not-verified')))
 def test_send_photo_is_one_multipart_request_caption_not_second_message(self):
  opener=MagicMock();opener.open.return_value.__enter__.return_value.read.return_value=json.dumps(dict(ok=True,result=dict(message_id=1))).encode()
  self.assertTrue(tg.send_photo('123456:'+'a'*30,'123','Имя: Тест\nКонтакт: @test',png(),opener))
  request=opener.open.call_args.args[0]
  self.assertTrue(request.full_url.endswith('/sendPhoto'));self.assertEqual(opener.open.call_count,1)
  self.assertIn(png(),request.data);self.assertIn('Контакт: @test'.encode(),request.data)
 def test_sources_build_fixed_no_message_send_or_user_code(self):
  source=profile_source(WHO)
  self.assertIn('private_profile_peer',source);self.assertIn('expectedIdentity.peer',source)
  self.assertIn('private_page',page_source())

class PageEnd(unittest.TestCase):
 def test_stable_identity_page_stops_and_no_fixed_page_limit(self):
  device=MagicMock();reader=MagicMock(side_effect=['middle','top','top','top','next','next','next'])
  pager=Pager(Settings(),lambda:False,device_factory=lambda *a:device,reader=reader)
  pager.reset();self.assertTrue(pager.advance());self.assertFalse(pager.advance());self.assertEqual(pager.pages,2)
