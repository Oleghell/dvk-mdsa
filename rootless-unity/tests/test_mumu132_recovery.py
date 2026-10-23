"""Synthetic skip/media/key diagnostics. No keys, accounts, network or Android."""
import json,unittest
from unittest.mock import MagicMock
from test_inbox_profiles import Base,WHO,snap,msg,nav
from test_extensions126 import png
from one_chat_device import ReadStopped
import assistant_history_wait as wait
from assistant_exit_photo import capture_chat
from assistant_exit_notify import notify_exit
import mumu_ai as ai
import assistant_key_pool as pool
import groq_reply as g

def too_large(**changes):
 v=dict(stage='navigation-stopped',metadata_checkpoint='ready',read_checkpoint='last-message',identity_checkpoint='recheck',scalar_checkpoint='chat-id',scalar_state='positive',wait_reason='none',message_slot=-1,message_kind='not-read',message_direction='not-read',frames=1,managed_calls=59)
 v.update(changes);return ReadStopped('snapshot-too-large',v)

class Recovery(Base):
 def test_too_large_leaves_via_verified_back_without_blocking_inbox(self):
  self.journal();chain=self.chain()
  out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[too_large()],chain=chain)
  self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['history_deferred'],1)
  self.assertTrue(out['return_verified']);self.assertEqual(self.sent,[])
  with self.store.connection() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM inbox_history_deferrals').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM inbox_read_round').fetchone()[0],0)
 def test_bad_identity_is_not_local_deferral(self):
  self.journal();out=self.walk([nav('opened',WHO)],[too_large(identity_checkpoint='saved-binding')])
  self.assertEqual(out['status'],'inbox-stopped');self.assertEqual(out['history_deferred'],0)
 def test_failed_back_still_stops_and_does_not_notify(self):
  self.journal();notice=MagicMock()
  out=self.walk([nav('opened',WHO),RuntimeError('private')],[too_large()],exit_notifier=notice)
  self.assertEqual(out['status'],'inbox-stopped');notice.assert_not_called()
 def test_photo_before_back_caption_after_back(self):
  self.journal();chain=self.chain();chain.consume(snap());order=[];image=png()
  def photo(who):self.assertEqual(who,WHO);order.append('photo');return image
  def send_photo(text,data):
   self.assertEqual(order,['photo','back']);self.assertEqual(data,image);order.append('sendPhoto');return True
  back=nav('returned',WHO)
  def returned():order.append('back');return back
  self.nav=MagicMock(side_effect=[nav('opened',WHO),returned(),nav('search-ready')])
  # Use a navigator wrapper rather than pre-evaluating the recorded return.
  order.clear();steps=iter([nav('opened',WHO),back,nav('search-ready')])
  def navigator(op,*a,**k):
   if op=='back':order.append('back')
   return next(steps)
  import assistant_inbox as inbox
  notice=MagicMock()
  out=inbox.walk(self.settings,self.stop,self.approve,lambda _:None,chain,navigator=navigator,reader=lambda *a: snap(),sender=self.sender,exit_notifier=notice,exit_photo=photo,exit_photo_sender=send_photo,greetings=('Привет 🙂',),pause=lambda _:False)
  self.assertEqual(order,['photo','back','sendPhoto']);notice.assert_not_called()
  self.assertEqual(out['exit_events'][0]['photo'],'attached');self.assertTrue(out['chat_content_exported'])
 def test_missing_photo_sends_one_explanatory_text(self):
  self.journal();chain=self.chain();chain.consume(snap());notice=MagicMock(return_value=True)
  out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[snap()],chain=chain,exit_notifier=notice,exit_photo=MagicMock(side_effect=RuntimeError('PRIVATE')))
  self.assertEqual(notice.call_count,1);self.assertIn('Снимок',notice.call_args.args[0]);self.assertNotIn('PRIVATE',notice.call_args.args[0])
 def test_unknown_photo_never_repeated(self):
  self.journal();chain=self.chain();photo=MagicMock(side_effect=TimeoutError('PRIVATE'));notice=MagicMock()
  result=dict(reason='wait-contact',_exit_messages=['Тест'])
  a=notify_exit(chain,WHO,result,sender=notice,photo=png(),photo_sender=photo)
  b=notify_exit(chain,WHO,result,sender=notice,photo=png(),photo_sender=photo)
  self.assertEqual(a['notification'],'unknown');self.assertEqual(b['notification'],'already-attempted');self.assertEqual(photo.call_count,1);notice.assert_not_called()
 def test_ai_unavailable_deferred_without_checked_marker(self):
  self.journal();chain=self.chain();chain.responder=MagicMock(side_effect=g.GroqError('groq-key-pool-exhausted'))
  out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[snap(msg(1002,'Здравствуйте'))],chain=chain)
  self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['history_deferred'],1)
  with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM inbox_read_round').fetchone()[0],0)

class PhotosAndKeys(unittest.TestCase):
 def test_identity_checked_both_sides_of_image_without_reading_history(self):
  order=[]
  def binder(*args):self.assertIsNone(args[-1]);order.append('bind');return dict(identity=WHO,messages=None)
  class Device:
   def __init__(self,*args):pass
   def screen(self):order.append('screen');return png()
  self.assertEqual(capture_chat('adb','folder',WHO,binder=binder,device_factory=Device),png())
  self.assertEqual(order,['bind','screen','bind'])
 def test_wrong_chat_never_exported(self):
  binder=MagicMock(return_value=dict(identity=dict(account='100',peer='201',chat='301'),messages=None));factory=MagicMock()
  with self.assertRaises(Exception):capture_chat('adb','folder',WHO,binder=binder,device_factory=factory)
  factory.assert_not_called()
 def test_key_failures_closed_indexed_and_cooldown_visible(self):
  pool._CACHE.clear();adapter=MagicMock(calls=1,side_effect=g.GroqError('groq-rate-limit'))
  a=pool.Responder('groq',g.MODEL,['PRIVATE_SECRET'],factory=lambda **k:adapter,clock=lambda:0)
  for cooldown in (False,True):
   with self.assertRaises(g.GroqError):a('question',{})
   safe=ai.safe_failures(type('R',(),dict(failure_summary=a.failures))())
   self.assertEqual(safe,[dict(provider='groq',key_index=1,code='groq-rate-limit',cooldown=cooldown)])
   self.assertNotIn('PRIVATE',json.dumps(safe));self.assertIn('лимиты',ai.failure_explanation(safe))
 def test_diagnostics_drop_arbitrary_fields(self):
  bad=dict(provider='groq',key_index=1,code='PRIVATE',cooldown=False,secret='PRIVATE')
  self.assertEqual(ai.safe_failures(type('R',(),dict(failure_summary=[bad]))()),[])
 def test_short_completion_limit_raised_without_loosening_reply_gate(self):
  a=g.Responder(key_loader=lambda:'unused',rules_loader=lambda:'Тест')
  sample=dict(identity=WHO,messages=[dict(id='1001',sender='200',text='Привет')],_reply_ids=['1001'])
  self.assertEqual(a.payload('question',sample)['max_completion_tokens'],1024)
  with self.assertRaises(g.GroqError):g.decision(dict(decision='reply',text='a'*241),'question')

 def test_length_finish_is_distinguished_from_invalid_json(self):
  import io
  opener=MagicMock();opener.open.return_value.__enter__.return_value=io.BytesIO(json.dumps({'choices':[{'finish_reason':'length','message':{'content':''}}]}).encode())
  a=g.Responder(key_loader=lambda:'gsk_'+'A'*30,rules_loader=lambda:'Тест',opener=opener)
  sample=dict(identity=WHO,messages=[dict(id='1001',sender='200',text='Привет')],_reply_ids=['1001'])
  with self.assertRaisesRegex(g.GroqError,'^groq-token-limit$'):a('question',sample)
