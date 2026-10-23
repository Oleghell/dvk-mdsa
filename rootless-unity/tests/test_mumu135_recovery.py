"""Exact report shapes for 5559/5561/5565; no live accounts or keys."""
import copy,json,unittest
from unittest.mock import MagicMock
import assistant_history_wait as wait
import dialog_browser as browser
from assistant_exit_notify import notify_exit
from one_chat_device import safe_read_failure,ReadStopped
from test_1214_read_budget import budget,ReadRecovery
from test_inbox_profiles import Base,WHO,OTHER,nav,msg,snap,GREETING
from test_dialog_browser import raw_open,TARGET
from mumu_worker import telegram_device_label


def sample_budget(**changes):
 return budget(read_checkpoint='sample',scalar_checkpoint='chat-id',message_slot=1,
               message_direction='own',frames=3,managed_calls=272,**changes)

class SampleBudget(ReadRecovery):
 def test_exact_5565_shape_retries_full_read_before_send(self):
  import test_guided_chain as guide
  out=self.walk([sample_budget()]+guide.sequence())
  self.assertEqual(out['status'],'chain-completed');self.assertEqual(out['diagnostics']['read_retries'],1)
  self.assertEqual(out['submission_calls'],2);self.assertEqual(len(self.sent),2)
 def test_all_fixed_read_stages_retry_only_by_starting_full_read_again(self):
  original=sample_budget().diagnostic
  for phase in ('identity','model','manager','loaded-flag','count','last-message','recheck','sample'):
   for scalar_state in ('positive','not-read'):
    d=dict(original,read_checkpoint=phase,scalar_state=scalar_state,message_slot=-1,wait_reason='not-checked')
    self.assertTrue(wait.verified_read_budget(safe_read_failure(ReadStopped('frame-budget',d))))
  for error in ('identity-changed','identity-not-bound','wrong-screen','signature-mismatch','message-invalid'):
   self.assertFalse(wait.verified_read_budget(safe_read_failure(ReadStopped(error,original))))
 def test_persistent_sample_after_handler_never_replays_send(self):
  import test_guided_chain as guide
  values=guide.sequence()
  out=self.walk(values[:3]+[sample_budget()]*4)
  self.assertEqual(out['reason'],'history-read-budget-timeout');self.assertEqual(out['submission_calls'],1)
  with self.store.connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'handler-returned-unconfirmed')
  later=self.walk(values[3:]);self.assertEqual(later['status'],'chain-completed');self.assertEqual(len(self.sent),2)
 def test_sample_does_not_authorize_identity_or_incomplete_evidence(self):
  self.assertTrue(wait.verified_read_budget(safe_read_failure(sample_budget())))
  original=sample_budget().diagnostic
  for key,bad in [('scalar_state','negative'),('identity_checkpoint','saved-binding'),('metadata_checkpoint','base'),('wait_reason','history-loading'),('message_slot',128)]:
   self.assertFalse(wait.verified_read_budget(safe_read_failure(ReadStopped('frame-budget',dict(original,**{key:bad})))))
for name in dir(ReadRecovery):
 if name.startswith('test_') and name not in SampleBudget.__dict__:setattr(SampleBudget,name,None)

class InboxSample(Base):
 def test_exhausted_read_leaves_same_chat_and_continues_next(self):
  from conversation_engine import QUESTIONS
  self.journal();self.journal(OTHER)
  hello=msg(1002,'Привет',who=OTHER);answer=msg(1003,QUESTIONS[0],True,who=OTHER)
  out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('opened',OTHER),nav('returned',OTHER),nav('search-ready')],
      [sample_budget()]*4+[snap(hello,who=OTHER),snap(hello,who=OTHER),snap(hello,answer,who=OTHER)])
  self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['dialogs_processed'],2)
  self.assertEqual(out['history_deferred'],1);self.assertEqual(self.sent,[QUESTIONS[0]])
  with self.store.connection() as db:
   self.assertEqual(db.execute('SELECT peer FROM inbox_history_deferrals').fetchall(),[(WHO['peer'],)])
   self.assertEqual(db.execute('SELECT COUNT(*) FROM inbox_read_round WHERE peer=?',(WHO['peer'],)).fetchone()[0],0)
 def test_changed_chat_on_back_still_stops(self):
  self.journal();notice=MagicMock()
  out=self.walk([nav('opened',WHO),nav('returned',OTHER)],[sample_budget()]*4,exit_notifier=notice)
  self.assertEqual(out['status'],'inbox-stopped');self.assertEqual(out['history_deferred'],0);notice.assert_not_called();self.assertFalse(self.sent)
 def test_caption_does_not_call_missing_excerpt_a_read_failure(self):
  self.journal();notice=MagicMock(return_value=True)
  notify_exit(self.chain(),WHO,dict(reason='ai-temporarily-unavailable'),sender=notice)
  self.assertNotIn('прочитать не удалось',notice.call_args.args[0]);self.assertIn('Текст сообщения не включён',notice.call_args.args[0])
 def test_read_pending_incoming_reappears_in_ai_failure_caption(self):
  import groq_reply as g
  self.journal();chain=self.chain();model=MagicMock(side_effect=g.GroqError('groq-key-pool-exhausted'));chain.responder=model
  before=snap(msg(1002,'Спасибо за цветы'))
  first=MagicMock(return_value=True)
  out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[before],chain=chain,exit_notifier=first)
  self.assertEqual(out['status'],'inbox-completed');self.assertIn('Спасибо за цветы',first.call_args.args[0])

class NavigationRecovery(unittest.TestCase):
 def test_observation_never_replays_handlers(self):
  source=browser.build('return');part=source.split("if(e==='frame-budget'&&['wait-list'")[1].split("if(e==='frame-budget'&&operation==='list'")[0]
  self.assertIn('n.action_completed',part);self.assertIn('n.observation_budget_retries<3',part)
  for text in ('switchTab(', 'call(s.closeChat','n.phase='):self.assertNotIn(text,part)
  self.assertIn('stableDestination(current)',source)
  self.assertIn("(!state.tabs||state.tabs.isNull()))scope(()=>resolve(root))",source)
 def test_search_reentry_does_not_allow_unknown_chat_or_screen(self):
  source=browser.build('open',allowed=[TARGET],entry='dialogs')
  part=source.split("if(operation==='open'&&entryScreen==='dialogs'&&k==='search'){")[1].split("if(required==='either'?")[0]
  self.assertIn('resolve(candidate).equals(current)',part);self.assertEqual(part.count('switchTab(s.messageTab)'),1)
  self.assertNotIn('closeChat',part);self.assertIn("fail('wrong-screen')",source)
 def test_counters_and_body_free_categories_are_validated(self):
  value=raw_open();value['navigation'].update(observation_budget_retries=1,entry_search_recovered=True)
  out=browser.validate(value,'open',allowed=[TARGET]);self.assertEqual(out['state'],'opened')
  self.assertNotIn('100',json.dumps(out['diagnostic']))
  for key,bad in [('observation_budget_retries',4),('observation_budget_retries',True),('entry_search_recovered',1),('controller_path',['PRIVATE'])]:
   v=copy.deepcopy(value);v['navigation'][key]=bad
   with self.assertRaises(ValueError):browser.validate(v,'open',allowed=[TARGET])
 def test_cached_model_builder_preserves_destination_helpers(self):
  import dialog_models
  source=dialog_models.build(allowed=[TARGET],entry='search',needs_reply_only=True)
  for name in ('const stableDestination=', 'const resetDestination='):
   self.assertEqual(source.count(name),1)
  self.assertIn('stableDestination(current)',source)
 def test_all_requested_telegram_numbers_and_unknown_port(self):
  for port,n in [(5563,1),(5557,2),(5559,3),(5561,4),(5565,5)]:
   self.assertEqual(telegram_device_label(port),f'MuMu ADB {port} ({n})')
  self.assertEqual(telegram_device_label(5567),'MuMu ADB 5567')
 def test_mixed_ai_failures_are_not_misreported_as_read_failure(self):
  from mumu_ai import failure_explanation
  values=[dict(provider='groq',key_index=1,code='groq-unsafe-reply',cooldown=False),dict(provider='openrouter',key_index=1,code='openrouter-rate-limit',cooldown=False)]
  text=failure_explanation(values);self.assertIn('проверку',text);self.assertIn('лимиты',text)

class TelegramWorkerLabels(unittest.TestCase):
 def test_fresh_workers_label_both_text_and_photo_without_network(self):
  import subprocess,sys
  from pathlib import Path
  code='''import json,sys
from mumu_worker import configure,telegram_device_label
n=configure(int(sys.argv[1]))
import telegram_notify as tg
from test_extensions126 import png
class Response:
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self,*args):return b'{"ok":true,"result":{"message_id":1}}'
class Client:
 def __init__(self):self.requests=[]
 def open(self,request,**kwargs):self.requests.append(request);return Response()
a=Client();token='123456:'+'a'*24
assert tg.send(token,'42','Тест',opener=a)
assert tg.send_photo(token,'42','Тест',png(),opener=a)
from urllib.parse import parse_qs
label=telegram_device_label(n)
assert parse_qs(a.requests[0].data.decode())['text']==[label+'\\nТест']
assert (label+'\\nТест').encode() in a.requests[1].data
assert len(a.requests)==2
print('ok')
'''
  root=Path(__file__).resolve().parents[1]
  import os
  env=dict(os.environ,PYTHONPATH=str(root)+os.pathsep+str(root/'tests'))
  for port in (5563,5557,5559,5561,5565):
   out=subprocess.run([sys.executable,'-c',code,str(port)],capture_output=True,text=True,env=env,timeout=20)
   self.assertEqual(out.returncode,0,out.stderr[-1000:]);self.assertEqual(out.stdout.strip(),'ok')
