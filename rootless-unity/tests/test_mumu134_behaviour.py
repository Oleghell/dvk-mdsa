"""Synthetic regressions: no accounts, keys, network or device."""
import unittest
from unittest.mock import MagicMock
import mumu_ai as ai
import groq_reply as g
import assistant_contact_clarify as clarify
import assistant_reply_audit as audit
import one_chat_send as send
import one_chat_probe as probe
from test_mumu_ai_failover import Failover
import test_guided_chain as guide

class GreetingFallback(unittest.TestCase):
 def value(self,*texts):
  s=guide.snapshot(*[(t,False) for t in texts]);s['_reply_ids']=[m['id'] for m in s['messages'] if m['sender']==guide.WHO['peer']];return s
 def test_all_keys_tried_before_simple_greeting_fallback(self):
  a,trace=Failover().make({'g1':'groq-rate-limit','g2':'groq-timeout','o1':'openrouter-rate-limit','o2':'openrouter-timeout'})
  out=a('question',self.value('😉','Здравствуйте'))
  self.assertEqual(trace,['g1','g2','o1','o2']);self.assertEqual(out,dict(decision='reply',text='Как настроение?'))
  self.assertEqual(a.safe_greeting_fallbacks,1)
 def test_no_fallback_for_objection_question_or_refusal(self):
  for text in ['Привет, кто ты?','Не пиши мне','Нормально','Напиши номер','Расскажи о себе','Не хочу общаться','Привет мой номер +79991234567']:
   self.assertIsNone(ai.safe_greeting_reply('question',self.value(text)))
  self.assertIsNone(ai.safe_greeting_reply('followup',self.value('Здравствуйте')))
 def test_messenger_list_is_choice_not_question_or_refusal(self):
  for text in ['Ватсап макс','Вацап','Давай ватсап','Тг лучше']:
   self.assertTrue(clarify.chosen([dict(text=text)]),text)
  for text in ['Что такое ватсап?','Ватсап не работает','Нет ватсапа','Не хочу ватсап','Мой номер +79991234567']:
   self.assertFalse(clarify.chosen([dict(text=text)]),text)
 def test_full_long_context_is_not_clipped(self):
  s=guide.snapshot(*[('длинная реплика '+str(i)+' я'*100,False) for i in range(65)])
  core={k:s[k] for k in ('identity','messages')};self.assertEqual(send.checked(core),core)
  self.assertEqual(len(g.public_context(s)),66)
  source=probe.build(guide.WHO)
  self.assertIn('first>128',source);self.assertIn('n.managed_calls>=60000',source)
  self.assertIn('const chunkSize=8;',source)
  self.assertIn('+chunkSize)',source)

class Receipts(guide.WholeChain):
 def test_initial_batch_answer_receipt_requires_observed_outgoing(self):
  before=guide.snapshot(('Здравствуйте',False),('😉',False))
  self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
  _,action=self.chain.proposal(before)
  self.assertEqual(set(audit.pending(self.chain,guide.WHO)),{'1002','1003'})
  self.chain.reserve_confirmed(guide.WHO,action);self.chain.finish(guide.WHO,action,True)
  audit.synchronize(self.chain,before)
  self.assertEqual(len(audit.pending(self.chain,guide.WHO)),2)
  after=guide.snapshot(('Здравствуйте',False),('😉',False),(action['text'],True))
  self.chain.proposal(after);audit.synchronize(self.chain,after)
  self.assertEqual(audit.pending(self.chain,guide.WHO),[])
 def test_arrival_after_observed_send_is_answered_on_next_pass(self):
  self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
  h=[('Привет',False),(guide.QUESTIONS[0],True)]
  first=guide.snapshot(*h[:1]);sent=guide.snapshot(*h)
  fresh=guide.snapshot(*h,('Отлично',False));after=guide.snapshot(*h,('Отлично',False),(guide.CONTACT_TEXT,True))
  out=self.walk([first,first,sent],until_waiting=True)
  self.assertEqual(out['status'],'chain-waiting');self.assertEqual(out['submission_calls'],1)
  self.assertTrue(out['diagnostics']['post_send_checked'])
  out=self.walk([fresh,fresh,after],until_waiting=True)
  self.assertEqual(out['status'],'chain-waiting');self.assertEqual(out['submission_calls'],1)
  self.assertEqual(len(self.sent),2)
  self.assertTrue(out['diagnostics']['post_send_checked'])
  self.assertEqual(audit.pending(self.chain,guide.WHO),[])

 def test_multiple_followups_only_after_previous_outgoing_is_observed(self):
  self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
  h=[('Привет',False),(guide.QUESTIONS[0],True),('Отлично',False),(guide.CONTACT_TEXT,True)]
  for i in range(1,5):
   _,action=self.chain.proposal(guide.snapshot(*h[:i]))
   if action:self.chain.reserve_confirmed(guide.WHO,action);self.chain.finish(guide.WHO,action,True)
  replies=['Можем общаться здесь, если тебе удобнее.','Я ИИ-помощник, личной биографии у меня нет.']
  self.chain.responder=MagicMock(side_effect=[dict(decision='reply',text=t) for t in replies])
  self.send=MagicMock(return_value=dict(attempted=True,handler_returned=True))
  for incoming,text in zip(['Наверное','Расскажи о себе'],replies):
   h.append((incoming,False));before=guide.snapshot(*h);after=guide.snapshot(*h,(text,True))
   out=self.walk([before,before,after],until_waiting=True)
   self.assertEqual(out['status'],'chain-waiting');self.assertEqual(out['submission_calls'],1)
   self.assertEqual(audit.pending(self.chain,guide.WHO),[])
   h.append((text,True))
  self.assertEqual(self.send.call_count,2)
  with self.store.connection() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_followup_archive').fetchone()[0],1)

for name in dir(guide.WholeChain):
 if name.startswith('test_') and name not in Receipts.__dict__:setattr(Receipts,name,None)
