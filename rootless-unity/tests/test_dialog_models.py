"""Cached model navigation, private evidence and production wiring; no device."""
from pathlib import Path
import copy,json,threading,unittest
from unittest.mock import patch
import dialog_models as models
import assistant_inbox as inbox
from assistant_settings import Settings
from assistant_store import StateError
from assistant_navigation_check import safe_diagnostic
from test_inbox_profiles import Base,WHO,GREETING,nav

class Models(unittest.TestCase):
 def test_fixed_route_no_visible_cells_or_screen_paging(self):
  source=models.build(allowed=[WHO],needs_reply_only=True)
  for text in ('m_MessagesManager','get_Chats','get_MessagesRouter','ShowChat','EventSourcesContext','OpenChatMethod','modelOffset=0','headerOrSkip','stableModels','DV.Analytics','MESSAGES','LIST_ITEM_CLICK'):
   self.assertIn(text,source)
  for text in ('get_VisibleCells','OnCellDidClicked','input swipe','get_Text','GetLoadCommand'):
   self.assertNotIn(text,source)
  self.assertIn('fieldFlags(s.managerField)&16',source)
  self.assertIn('f.fieldOwner(s.managerField).equals(s.filters)',source)
  self.assertIn("enumType(s.contextClass,'EventSourcesContext')",source)
  self.assertIn("enumType(s.methodClass,'OpenChatMethod')",source)
  self.assertIn('f.declaring(klass).equals(s.statClass)',source)
  self.assertNotIn("getClass('DV.dll','','EventSourcesContext')",source)
  self.assertIn('if(error!==\'identity-not-bound\')throw error',source)
  self.assertLess(source.index('const model=modelIdentity(chat)'),source.index('header=headerOrSkip(chat'))
  self.assertLess(source.index('stableModels(current,manager,cm,count,state.scanIndex,chat)'),source.index('n.action_attempted=true;call(s.openModel'))
 def test_offset_strict(self):
  for value in (-1,True,1.5,'64',100001):
   with self.assertRaises(ValueError):models.build(offset=value)
  self.assertIn('modelOffset=64',models.build(offset=64))
 def test_scan_evidence_is_private_and_cursor_checked(self):
  raw=dict(navigation=dict(private_model_scan=dict(next=64,count=130,skipped_headers=2)))
  expected=nav('exhausted');before=copy.deepcopy(raw)
  with patch.object(models.browser,'validate',return_value=expected) as v:
   out,nxt=models.validate(raw)
   self.assertEqual(nxt,64);self.assertEqual(out['diagnostic']['header_rows_skipped'],2)
   self.assertNotIn('private_model_scan',v.call_args.args[0]['navigation'])
   self.assertEqual(raw,before)
  for scan in (dict(next=0,count=130,skipped_headers=0),dict(next=True,count=130,skipped_headers=0),dict(next=64,count=64,skipped_headers=0),dict(next=None,count=100001,skipped_headers=0),dict(next=None,count=2,skipped_headers=65),dict(next=None,count=2,skipped_headers=True)):
   with self.assertRaises(ValueError):models.validate(dict(navigation=dict(private_model_scan=scan)))
 def test_no_continuation_after_action(self):
  raw=dict(navigation=dict(private_model_scan=dict(next=64,count=130,skipped_headers=0)))
  with patch.object(models.browser,'validate',return_value=nav('opened',WHO)):
   with self.assertRaises(ValueError):models.validate(raw)
 def test_logical_slices_use_no_device_gestures(self):
  first=nav('exhausted');first['diagnostic']['header_rows_skipped']=2
  last=nav('opened',WHO);last['diagnostic']['header_rows_skipped']=1
  with patch('one_chat_device.capture',side_effect=[(first,64),(last,None)]) as capture,patch.object(models,'build',return_value='function probeUIKitRoot() { const allowedTargets=[];}') as build:
   out=models.perform('open','adb','folder',allowed=[WHO],needs_reply_only=True)
   self.assertEqual(out['state'],'opened');self.assertEqual(out['diagnostic']['header_rows_skipped'],3)
   self.assertEqual(capture.call_count,2)
   self.assertEqual([call.kwargs['offset'] for call in build.call_args_list],[0,64])
   self.assertEqual(build.call_args_list[-1].kwargs['entry'],'dialogs')
 def test_stopped_action_never_retried(self):
  result=nav('stopped');result['diagnostic']['header_rows_skipped']=0
  with patch('one_chat_device.capture',return_value=(result,None)) as capture:
   self.assertEqual(models.perform('open','adb','folder')['state'],'stopped');capture.assert_called_once()
 def test_cancellation_no_probe(self):
  with patch('one_chat_device.capture') as capture:
   with self.assertRaises(StateError):models.perform('open','adb','folder',lambda:True)
   capture.assert_not_called()
 def test_non_open_keeps_verified_back(self):
  with patch.object(models.browser,'perform',return_value=nav('returned',WHO)) as call:
   self.assertEqual(models.perform('back','adb','folder',expected=WHO)['state'],'returned')
   self.assertEqual(call.call_args.kwargs['expected'],WHO)
 def test_public_counter_bounded_and_no_identity(self):
  good=nav('exhausted')['diagnostic'];good['header_rows_skipped']=100000
  self.assertEqual(safe_diagnostic(good)['header_rows_skipped'],100000)
  for n in (-1,True,100001):
   with self.assertRaises(ValueError):safe_diagnostic(dict(good,header_rows_skipped=n))

class Production(Base):
 def test_default_inbox_uses_cached_navigation_not_pager(self):
  self.journal()
  settings=Settings(contacts_enabled=False,errors_enabled=False)
  with patch('dialog_models.perform',side_effect=[nav('exhausted'),nav('exhausted'),nav('search-ready')]) as navigator,patch('assistant_dialog_pages.Pager') as pager:
   out=inbox.run(settings,self.stop,self.approve,store=self.store,greetings=(GREETING,),pause=lambda _:False)
  self.assertEqual(out['status'],'inbox-completed');pager.assert_not_called()
  self.assertGreater(navigator.call_count,0)
 def test_production_source_does_not_instantiate_scroll_backend(self):
  source=(Path(__file__).resolve().parents[1]/'assistant_inbox.py').read_text(encoding='utf-8')
  self.assertNotIn('Pager(',source);self.assertNotIn('from assistant_dialog_pages',source)

class NestedRouteRegression(unittest.TestCase):
 def test_apk_evidence_and_no_default_zero(self):
  path=Path(__file__).resolve().parents[1]/'DIALOG-ROUTE-APK-EVIDENCE.json'
  evidence=json.loads(path.read_text(encoding='utf-8'))
  self.assertEqual(evidence['declaring_namespace'],'DV.Analytics')
  self.assertEqual(evidence['declaring_type'],'Stat')
  self.assertEqual([p['value'] for p in evidence['parameters']],[58,4])
  source=models.build(allowed=[WHO],needs_reply_only=True)
  for p in evidence['parameters']:
   self.assertIn(p['literal'],source)
   self.assertNotIn("getClass('DV.dll','','"+p['type']+"')",source)
  self.assertIn("s.contextClass=f.classFromType(ct)",source)
  self.assertIn('context.writeS32(s.contextValue)',source)
  self.assertIn('method.writeS32(s.methodValue)',source)
  self.assertNotIn('method.writeS32(0)',source)
 def test_enum_owner_in_offline_catalog_roots(self):
  from dialog_catalog import ROOTS
  for root in (('DV.dll','DV.Analytics','Stat'),('DV.dll','','EventSourcesContext'),('DV.dll','','OpenChatMethod')):
   self.assertIn(root,ROOTS)
