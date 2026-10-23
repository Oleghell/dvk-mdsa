"""Continuous MuMu work, immediate greetings and zero post-send idle; synthetic."""
import threading,unittest
from unittest.mock import MagicMock,patch
import assistant_authorization as auth
import test_guided_chain as gf
import test_assistant_monitor as mf
import test_inbox_profiles as inf
import dialog_models as models
from assistant_store import StateError

class Greeting(unittest.TestCase):
 def test_mumu_greeting_never_sleeps_but_other_stages_keep_typing(self):
  stop=threading.Event();wait=MagicMock(return_value=False)
  approve=auth.RunAuthorization(stop,wait=wait,immediate_greeting=True)
  for _ in range(3):self.assertTrue(approve('greeting','Привет, как настроение?',lambda:False))
  wait.assert_not_called()
  for kind in ('question','contact','clarify','followup'):
   wait.reset_mock();self.assertTrue(approve(kind,' '.join(['слово']*35),lambda:False))
   self.assertAlmostEqual(sum(c.args[0] for c in wait.call_args_list),60)
 def test_default_pacing_and_cancellation_unchanged(self):
  stop=threading.Event();wait=MagicMock(return_value=False)
  self.assertTrue(auth.RunAuthorization(stop,wait=wait)('greeting','Привет',lambda:False));wait.assert_called()
  wait.reset_mock();fast=auth.RunAuthorization(stop,wait=wait,immediate_greeting=True)
  for kind,text,cancelled in [('greeting','',lambda:False),('bad','Привет',lambda:False),('greeting','Привет',lambda:True)]:
   self.assertFalse(fast(kind,text,cancelled))
  stop.set();self.assertFalse(fast('greeting','Привет',lambda:False));wait.assert_not_called()
 def test_typing_countdown_is_visible_without_exposing_message_text(self):
  stop=threading.Event();progress=MagicMock();wait=MagicMock(return_value=False)
  approve=auth.RunAuthorization(stop,wait=wait,immediate_greeting=True,progress=progress)
  self.assertTrue(approve('greeting','Личный текст',lambda:False));wait.assert_not_called()
  progress.reset_mock();self.assertTrue(approve('question','Личный текст',lambda:False))
  self.assertTrue(all('Печатаю ответ' in c.args[0] for c in progress.call_args_list))
  self.assertNotIn('Личный',str(progress.call_args_list))
 def test_worker_explicitly_enables_fast_mode_only_in_mumu(self):
  from pathlib import Path
  text=(Path(__file__).resolve().parents[1]/'mumu_worker.py').read_text(encoding='utf-8')
  self.assertIn('RunAuthorization(stopped,immediate_greeting=True,progress=progress)',text)
  self.assertIn('write=write,continuous=True',text)

class FastChain(gf.WholeChain):
 def setUp(self):
  super().setUp();self.chain.bind(gf.snapshot(),(gf.GREETING,),approved=True)
 def test_visible_outgoing_advances_without_any_five_second_sleep(self):
  pause=MagicMock(return_value=False)
  out=self.walk(gf.sequence()[1:],until_waiting=True,pause=pause)
  self.assertEqual(out['submission_calls'],1);self.assertTrue(out['diagnostics']['post_send_checked'])
  self.assertEqual(len(self.sent),1);pause.assert_not_called()
 def test_missing_outgoing_is_bounded_and_never_repeats_send(self):
  before=gf.snapshot(('Привет',False));pause=MagicMock(return_value=False)
  out=self.walk([before],until_waiting=True,pause=pause)
  self.assertEqual(out['reason'],'outgoing-not-observed');self.assertEqual(out['submission_calls'],1)
  self.assertEqual(len(self.sent),1);pause.assert_not_called()
  again=self.walk([before],until_waiting=True,pause=pause)
  self.assertEqual(again['submission_calls'],0);self.assertEqual(len(self.sent),1)
 def test_wrong_identity_still_stops_before_send(self):
  before=gf.snapshot(('Привет',False));bad=gf.snapshot(('Привет',False));bad['identity']['peer']='999'
  out=self.walk([before,bad],until_waiting=True)
  self.assertEqual(out['submission_calls'],0);self.assertFalse(self.sent)

class Continuous(mf.Monitor):
 def run_fast(self,**kwargs):
  def repeat(*a,**kw):self.stop.set();return dict(status='completed',report_name='last-run.json')
  self.repeat=MagicMock(side_effect=repeat);self.fast_wait=MagicMock(side_effect=AssertionError('No full-mode idle allowed'))
  return self.run_monitor(continuous=True,clock=lambda:0,repeat=kwargs.pop('repeat',self.repeat),wait=kwargs.pop('wait',self.fast_wait),**kwargs)
 def test_empty_inbox_immediately_starts_search_before_two_minutes(self):
  out=self.run_fast();self.repeat.assert_called_once();self.fast_wait.assert_not_called()
  self.assertEqual(self.repeat.call_args.kwargs['mode'],'profiles');self.assertEqual(out['early_profile_batches'],1)
  self.assertTrue(out['continuous_work']);self.assertEqual(self.inbox.call_count,1)
 def test_productive_pass_gets_one_fresh_drain_then_search(self):
  self.inbox.side_effect=[mf.inbox_result(dialogs_processed=2,submission_calls=2,handler_returns=2,outgoing_observed=2),mf.inbox_result()]
  out=self.run_fast();self.assertEqual(self.inbox.call_count,2);self.assertEqual(out['immediate_rechecks'],1)
  self.repeat.assert_called_once();self.fast_wait.assert_not_called()
 def test_deferred_and_review_chats_do_not_hold_search_or_become_answered(self):
  self.inbox.return_value=mf.inbox_result(history_deferred=2,review_pending=3,isolated_dialogs=1,outcomes={'isolated:send-outcome-unknown':1})
  out=self.run_fast();self.repeat.assert_called_once();self.assertEqual(out['last_pass']['history_deferred'],2)
  self.assertEqual(out['last_pass']['review_pending'],3);self.assertEqual(out['totals']['submission_calls'],0)
 def test_deadline_does_not_trigger_an_extra_drain(self):
  now=iter([0,121,121]);self.inbox.return_value=mf.inbox_result(dialogs_processed=1)
  def repeat(*a,**kw):self.stop.set();return dict(status='completed',report_name='last-run.json')
  repeat=MagicMock(side_effect=repeat)
  out=self.run_monitor(continuous=True,clock=lambda:next(now,121),repeat=repeat,wait=MagicMock(side_effect=AssertionError()))
  self.assertEqual(out['immediate_rechecks'],0);repeat.assert_called_once()
 def test_inbox_only_keeps_its_poller_and_never_opens_search(self):
  out=self.run_fast(mode='inbox',wait=self.wait_stop)
  self.repeat.assert_not_called();self.assertFalse(out['automatic_profile_repeat'])
 def test_report_failure_stops_before_any_new_profile_action(self):
  out=self.run_fast(write=MagicMock(side_effect=OSError('PRIVATE')))
  self.repeat.assert_not_called();self.assertEqual(out['reason'],'report-write-failed')
 def test_unknown_profile_send_still_stops_without_retry(self):
  repeat=MagicMock(return_value=dict(status='stopped',reason='send-outcome-unknown'))
  out=self.run_fast(repeat=repeat);repeat.assert_called_once();self.assertEqual(out['reason'],'profile-pass-stopped')

class Scan(unittest.TestCase):
 def test_four_rows_yield_before_budget_and_keep_all_selection_checks(self):
  source=models.build(allowed=[inf.WHO],needs_reply_only=True)
  self.assertIn('batch<4&&',source);self.assertIn('Date.now()<deadline-40',source)
  for text in ('stableModels(current,manager,cm,count,state.scanIndex,chat)','selection-unread-changed','selection-last-message-changed','!n.action_attempted&&!n.action_completed','state.rowBudgetYields<3','budget_yields<12'):
   self.assertIn(text,source)
 def test_scan_progress_uses_only_logical_offsets_not_names(self):
  first=inf.nav('exhausted');first['diagnostic']['header_rows_skipped']=0
  final=inf.nav('opened',inf.WHO);final['diagnostic']['header_rows_skipped']=0
  progress=MagicMock()
  with patch('one_chat_device.capture',side_effect=[(first,64),(final,None)]),patch.object(models,'build',return_value='SOURCE'):
   out=models.perform('open','adb','folder',allowed=[inf.WHO],progress=progress)
  self.assertEqual(out['state'],'opened');self.assertEqual(progress.call_count,2)
  self.assertIn('65',progress.call_args.args[0]);self.assertNotIn('Анна',str(progress.call_args_list))

for cls,base in ((FastChain,gf.WholeChain),(Continuous,mf.Monitor)):
 for name in dir(base):
  if name.startswith('test_') and name not in cls.__dict__:setattr(cls,name,None)
del cls,base
