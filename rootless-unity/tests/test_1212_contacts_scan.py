"""1.2.12: user examples, bounded read-only scan, durable isolation. Synthetic only."""
import copy, struct, unittest, zlib
from unittest.mock import patch
import test_1210_context_loading as old
import test_guided_chain as guide
import test_inbox_profiles as ih
import shared_contact as contacts
import assistant_contact_clarify as clarify
import dialog_models as models

class Parsing(unittest.TestCase):
 def test_labelled_handle_after_request(self):
  for s in ('Love_1712 телега','Love\\_1712 телега','телега Love_1712','тг: Love_1712','Love_1712 Telegram'):
   with self.subTest(s=s):self.assertEqual(contacts.self_shared(s,requested=True),['@Love_1712'])
 def test_label_is_not_ownership_without_request(self):
  self.assertEqual(contacts.self_shared('Love_1712 телега'),[])
 def test_no_guessing_arbitrary_names(self):
  for s in ('Telegram','телега','тг','Макс.','Вацап есть. Макс.','12345 телега','ab телега','a'*33+' телега','телега мой друг Love_1712','«Love_1712 телега»','не мой Love_1712 телега','Love_1712 телега?','Love_1712 hello','Love_1712, спасибо'):
   with self.subTest(s=s):self.assertEqual(contacts.self_shared(s,requested=True),[])
 def test_bare_latin_word_after_request_is_telegram(self):
  # Reports y8zZxWkA (v1.3.73): «Ptaha3112» answered the contact request and
  # must be saved; app names and ordinary English/romanized words stay excluded.
  for s,want in (('Love_1712',['@Love_1712']),('Ptaha3112',['@Ptaha3112']),('.Ptaha3112',['@Ptaha3112']),('Ptaha3112.',['@Ptaha3112']),('hello',[]),('thanks',[]),('privet',[]),('whatsapp',[]),('Telegram',[]),('ab',[]),('12345',[])):
   with self.subTest(s=s):
    self.assertEqual(contacts.self_shared(s,requested=True),want)
    self.assertEqual(contacts.self_shared(s,requested=False),[])
 def test_punctuated_handle_is_contact(self):
  self.assertEqual(contacts.self_shared('.@MER19820',requested=True),['@MER19820'])
 def test_messenger_spelling_availability(self):
  for s in ('Вацап есть. Макс.','Хотя тг лучше / Давай ватсап','ватсап есть','ватцап есть','whatsapp есть','телега лучше'):
   with self.subTest(s=s):self.assertTrue(clarify.chosen([dict(text=s)]))
 def test_refusal_not_an_invitation(self):
  for s in ('Не пиши мне, давай тг','не хочу общаться, тг лучше','Вацап не работает','Не пользуюсь ватсап'):
   with self.subTest(s=s):self.assertFalse(clarify.chosen([dict(text=s)]))
 def test_whole_invitation_packet_must_not_be_third_party_or_refusal(self):
  for text in ('ник моей подруги','не передавай никому','«Давай тг»','не хочу общаться'):
   self.assertFalse(contacts.voluntary_batch([dict(text='.@MER19820'),dict(text='Давай тг'),dict(text=text)]))
 def test_explicit_choice_packet_is_voluntary(self):
  self.assertTrue(contacts.voluntary_batch([dict(text=t) for t in ('Попробуй','.@MER19820','Ты оч далеко','А смысл','Давай тг')]))

def png():
 def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',300,600,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\0'*900)*600))+chunk(b'IEND',b'')

class Chain(old.Context):
 def test_bare_labelled_contact_goes_to_photo_and_one_notification(self):
  h=self.seed_contact();self.chain.media_required=True
  sample=guide.snapshot(*h,('Love_1712 телега',False));image=png();photo=[]
  def capture(who):photo.append(who);return image
  out=self.walk([sample],contact_photo=capture)
  self.assertEqual(out['reason'],'contact-forwarded');self.assertEqual(self.sent,[])
  self.notifier.assert_called_once_with(dict(name=guide.PEER_NAME,contacts=['@Love_1712'],photo=image))
  self.assertEqual(photo,[guide.WHO]);self.walk([sample]);self.notifier.assert_called_once()
 def test_available_whatsapp_sends_one_clarification(self):
  h=self.seed_contact()+[('Вацап есть. Макс.',False)]
  first=guide.snapshot(*h);seen=guide.snapshot(*h,(clarify.WHATSAPP_TEXT,True))
  out=self.walk([first,first,seen],until_waiting=True)
  self.assertEqual(self.sent,[clarify.WHATSAPP_TEXT]);self.assertEqual(out['reason'],'contact-clarification-sent');self.notifier.assert_not_called()
 def pending_question(self,returned=False):
  self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
  h=[('Привет',False)];stage,action=self.chain.proposal(guide.snapshot(*h));self.chain.reserve_confirmed(guide.WHO,action)
  if returned:self.chain.finish(guide.WHO,action,True)
  return h
 def test_voluntary_contact_does_not_prove_pending_send(self):
  h=self.pending_question()+[(t,False) for t in ('Попробуй','.@MER19820','Ты оч далеко','А смысл','Давай тг')]
  self.chain.media_required=True;image=png();sample=guide.snapshot(*h)
  out=self.walk([sample],contact_photo=lambda who:image)
  self.assertEqual(out['reason'],'contact-forwarded');self.assertEqual(self.sent,[])
  self.notifier.assert_called_once_with(dict(name=guide.PEER_NAME,contacts=['@MER19820'],photo=image))
  with self.store.connection() as db:
   self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='question'").fetchone()[0],'reserved-unknown')
   self.assertIsNone(db.execute("SELECT status FROM chain_actions WHERE kind='contact'").fetchone())
  out=self.walk([sample]);self.notifier.assert_called_once();self.assertEqual(out['submission_calls'],0)
 def test_voluntary_contact_preserves_returned_unobserved_status(self):
  h=self.pending_question(True)+[('.@MER19820',False),('Давай тг',False)]
  out=self.walk([guide.snapshot(*h)]);self.assertEqual(out['reason'],'contact-forwarded')
  with self.store.connection() as db:self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='question'").fetchone()[0],'handler-returned-unconfirmed')
 def test_old_manual_review_is_not_cleared_by_contact(self):
  h=self.pending_question();self.chain.mark_review(guide.WHO)
  out=self.walk([guide.snapshot(*h,('.@MER19820',False),('Давай тг',False))])
  self.assertEqual(out['reason'],'manual-review');self.notifier.assert_not_called();self.assertFalse(self.sent)
 def test_unrequested_bare_handle_without_invitation_does_not_bypass_pending(self):
  h=self.pending_question();out=self.walk([guide.snapshot(*h,('.@MER19820',False))])
  self.assertNotEqual(out['reason'],'contact-forwarded');self.notifier.assert_not_called();self.assertFalse(self.sent)
for name in dir(old.Context):
 if name.startswith('test_') and name not in Chain.__dict__:setattr(Chain,name,None)

class Navigation(unittest.TestCase):
 def raw(self,nxt,count=130):return dict(navigation=dict(private_model_scan=dict(next=nxt,count=count,skipped_headers=0)))
 def test_partial_completed_scan_cursor_accepted(self):
  with patch.object(models.browser,'validate',return_value=ih.nav('exhausted')):
   for nxt in (1,18,52,64):self.assertEqual(models.validate(self.raw(nxt))[1],nxt)
 def test_cursor_must_progress_and_stay_bounded(self):
  with patch.object(models.browser,'validate',return_value=ih.nav('exhausted')):
   for nxt in (-1,0,65,130,True,'18'):
    with self.subTest(nxt=nxt),self.assertRaises(ValueError):models.validate(self.raw(nxt))
   for nxt in (18,19,82,83):
    if nxt in (19,82):self.assertEqual(models.validate(self.raw(nxt),offset=18)[1],nxt)
    else:
     with self.assertRaises(ValueError):models.validate(self.raw(nxt),offset=18)
 def test_no_continuation_from_opened_or_failed_probe(self):
  for state in ('opened','stopped'):
   with patch.object(models.browser,'validate',return_value=ih.nav(state,guide.WHO)):
    with self.assertRaises(ValueError):models.validate(self.raw(18))
 def test_partial_slices_progress_without_scroll_or_open_retry(self):
  end=ih.nav('opened',guide.WHO);end['diagnostic']['header_rows_skipped']=0
  empty=ih.nav('exhausted');empty['diagnostic']['header_rows_skipped']=0
  with patch('one_chat_device.capture',side_effect=[(copy.deepcopy(empty),18),(copy.deepcopy(empty),39),(end,None)]) as capture,patch.object(models,'build',return_value='function probeUIKitRoot() { const allowedTargets=[],hiddenPeers=new Set([]);}') as build:
   result=models.perform('open','adb','folder',allowed=[guide.WHO],needs_reply_only=True)
   self.assertEqual(result['state'],'opened');self.assertEqual(capture.call_count,3)
   self.assertEqual([c.kwargs['offset'] for c in build.call_args_list],[0,18,39])
   self.assertEqual([c.kwargs['entry'] for c in build.call_args_list],['search','dialogs','dialogs'])
 def test_time_budget_does_not_expand_global_transition_deadline(self):
  source=models.build();self.assertIn('Date.now()-state.scanStarted<4000',source)
  self.assertIn('stableModels(current,manager,cm,count,null,null)',source)
  self.assertNotIn('get_VisibleCells',source);self.assertNotIn('input swipe',source)

class Isolation(ih.Base):
 def test_bad_greeting_is_durable_local_only_after_verified_return(self):
  self.journal();self.journal(ih.OTHER);chain=self.chain()
  wrong=ih.snap(ih.msg(1002,'Привет'));wrong['messages'][0]['text']='Не то приветствие'
  good=ih.snap(ih.msg(1002,'Привет',who=ih.OTHER),who=ih.OTHER)
  observed=ih.snap(ih.msg(1002,'Привет',who=ih.OTHER),ih.msg(1003,ih.QUESTIONS[0],True,ih.OTHER),who=ih.OTHER)
  out=self.walk([ih.nav('opened',ih.WHO),ih.nav('returned',ih.WHO),ih.nav('opened',ih.OTHER),ih.nav('returned',ih.OTHER),ih.nav('search-ready')],[wrong,good,good,observed],chain=chain)
  self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['isolated_reasons'],{'greeting-not-verified':1})
  self.assertEqual(self.sent,[ih.QUESTIONS[0]])
  with self.store.connection() as db:self.assertEqual(db.execute("SELECT stage,greeting FROM chain_dialogs WHERE chat='300'").fetchone(),('manual-review',None))
  out=self.walk([ih.nav('exhausted'),ih.nav('exhausted'),ih.nav('search-ready')],[],chain=chain)
  self.assertEqual(out['status'],'inbox-completed')
  for c in self.nav.call_args_list:
   if c.args[0]=='open':self.assertNotIn(ih.WHO,c.kwargs['allowed'])
 def test_failed_back_is_still_global_stop(self):
  self.journal();wrong=ih.snap(ih.msg(1002,'Привет'));wrong['messages'][0]['text']='Не то приветствие'
  out=self.walk([ih.nav('opened',ih.WHO),ih.nav('stopped')],[wrong])
  self.assertEqual(out['status'],'inbox-stopped');self.assertEqual(out['isolated_dialogs'],0);self.assertFalse(self.sent)
