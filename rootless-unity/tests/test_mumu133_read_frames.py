"""Report regressions: full-context batches and no duplicate actions. Synthetic only."""
import unittest
from unittest.mock import MagicMock
import assistant_history_wait as wait
import one_chat_probe as probe
import search_city as city
import test_guided_chain as guide
from test_1214_read_budget import budget
from one_chat_device import safe_read_failure,ReadStopped

class ReadFrames(unittest.TestCase):
 def test_user_5565_final_recheck_is_read_only_retryable(self):
  failure=budget(read_checkpoint='recheck',scalar_checkpoint='chat-id',message_slot=7,message_direction='own',managed_calls=175)
  self.assertTrue(wait.verified_read_budget(safe_read_failure(failure)))
  for change in ({'scalar_state':'negative'},{'identity_checkpoint':'saved-binding'},{'wait_reason':'history-loading'},{'scalar_checkpoint':'message-chat-id'}):
   bad=ReadStopped('frame-budget',failure.diagnostic|change)
   self.assertFalse(wait.verified_read_budget(safe_read_failure(bad)))
 def test_native_reader_yields_headers_then_bodies_then_final_checks(self):
  s=probe.build(guide.WHO,scoped_traversal=True)
  self.assertIn("+4)",s)
  self.assertIn("chunk.phase='bodies';if(first>0){verifyWho();return;}",s)
  self.assertIn("if(chunk.messages.length===first)chunk.phase='complete';",s)
  self.assertIn("state.historyChunk=null;verifyWho();",s)
  self.assertIn('JSON.stringify(state.sample)!==JSON.stringify(sample)',s)
  self.assertLess(s.index('if(chunk.localOwn>0&&chunk.peerAnchors===0)'),s.index('const value=call(s.messageText,message)'))
  self.assertIn("state.historyChunk=null;n.wait_reason=reason",s)
 def test_city_text_handler_returns_before_query_and_never_repeats(self):
  s=city.build('Псков')
  self.assertIn('if(!state.cityTextCommitted)',s)
  self.assertIn('state.cityTextCommitted=true;n.city_query_text_completed=true;return;',s)
  self.assertIn("(n.phase==='query-city'&&state.cityTextCommitted)",s)
  self.assertIn("if(!ex.readPointer().isNull())fail('managed-exception');if(fixedCancellationRequested)",s)

class ContextBatch(guide.WholeChain):
 def test_three_incoming_after_retry_reach_ai_with_whole_dialog(self):
  self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
  self.chain.responder=MagicMock(return_value=dict(decision='reply',text='У меня тоже всё хорошо. Как настроение?'))
  before=guide.snapshot(('Привет',False),('Нормально',False),('А у тебя как?',False))
  after=guide.snapshot(('Привет',False),('Нормально',False),('А у тебя как?',False),('У меня тоже всё хорошо. Как настроение?',True))
  fail=budget(read_checkpoint='recheck',scalar_checkpoint='chat-id',message_slot=7,message_direction='own')
  out=self.walk([fail,before,before,after],until_waiting=True)
  self.assertEqual(out['submission_calls'],1);self.assertEqual(len(self.sent),1)
  self.assertEqual(out['diagnostics']['read_retries'],1)
  args=self.chain.responder.call_args.args
  self.assertEqual(args[0],'question');self.assertEqual(args[1]['messages'],before['messages'])
  self.assertEqual(set(args[1]['_reply_ids']),{'1002','1003','1004'})
 def test_new_message_before_send_refreshes_draft_with_all_messages(self):
  self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
  replies=['Как настроение?','У меня всё хорошо. Как дела?']
  self.chain.responder=MagicMock(side_effect=[dict(decision='reply',text=t) for t in replies])
  first=guide.snapshot(('Привет',False),('Нормально',False))
  newer=guide.snapshot(('Привет',False),('Нормально',False),('А у тебя?',False))
  after=guide.snapshot(('Привет',False),('Нормально',False),('А у тебя?',False),(replies[-1],True))
  out=self.walk([first,newer,newer,after],until_waiting=True)
  self.assertEqual(out['submission_calls'],1);self.assertEqual(self.sent,[replies[-1]])
  self.assertEqual(out['diagnostics']['incoming_draft_refreshes'],1)
  self.assertEqual(self.chain.responder.call_args.args[1]['messages'],newer['messages'])

for name in dir(guide.WholeChain):
 if name.startswith('test_') and name not in ContextBatch.__dict__:setattr(ContextBatch,name,None)
