import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uikit_tree as t
import diagnose_device as d
from test_uikit_root import ready_root,UIFake


def ready_tree():
    r=ready_root();r['tree']={'stage':'tree-ready','complete':True,'error':'none',
        'nodes':[{'id':0,'parent':None,'depth':0,'kind':'UIWindow','effectively_hidden':False,
                  'user_interaction_enabled':True,'control_enabled':None,'child_count':0}],
        'managed_calls':4,'handles_acquired':2,'handles_released':2,'cleanup_failed':False,
        'truncated_reasons':[],'repeated_references':0}
    return r

class TreeFake(UIFake):
    def create_script(self,source,name):
        super().create_script(source,name);self.exports_sync.root=ready_tree;return self

class TreeSchema(unittest.TestCase):
    def test_valid(self):t.validate(ready_tree())
    def test_extraneous_data_rejected(self):
        for key in ('text','name','bounds','token','address','children'):
            v=ready_tree();v['tree']['nodes'][0][key]='PRIVATE'
            with self.assertRaises(ValueError):t.validate(v)
    def test_fixed_kinds_only(self):
        v=ready_tree();v['tree']['nodes'][0]['kind']='private runtime class'
        with self.assertRaises(ValueError):t.validate(v)
    def test_invalid_edges(self):
        for parent in (0,1,False,'0'):
            v=ready_tree();v['tree']['nodes'][0]['parent']=parent
            with self.assertRaises(ValueError):t.validate(v)
    def test_child_coverage_required(self):
        v=ready_tree();v['tree']['nodes'][0]['child_count']=1
        with self.assertRaises(ValueError):t.validate(v)
    def test_tree_needs_confirmed_root_and_thread(self):
        v=ready_tree();v['stage']='off-main-thread';v['main_thread_confirmed']=False
        with self.assertRaises(ValueError):t.validate(v)
    def test_tree_counts_bounded(self):
        for key,bad in (('managed_calls',513),('managed_calls',True),('handles_acquired',129),('handles_released',3)):
            v=ready_tree();v['tree'][key]=bad
            with self.assertRaises(ValueError):t.validate(v)
    def test_unreported_leak_rejected(self):
        v=ready_tree();v['tree'].update(stage='tree-error',complete=False,error='native-call-failed',handles_released=1)
        with self.assertRaises(ValueError):t.validate(v)
    def test_limit_requires_fixed_reason(self):
        v=ready_tree();v['tree'].update(stage='tree-limited',complete=False)
        with self.assertRaises(ValueError):t.validate(v)
        v['tree']['truncated_reasons']=['time-budget'];t.validate(v)
    def test_no_content_getters_or_actions(self):
        for bad in ('get_Text','set_Text','get_Name','get_Position','OnDidClicked','sendMessage','screencap','input tap','Interceptor.replace','Memory.scan','il2cpp_field_','NativeCallback'):
            self.assertNotIn(bad,t.FUNCTION)
        for required in ('get_Subviews','get_EffectivelyHidden','get_UserInteractionEnabled','get_Enabled','get_Count','get_Item','gchandle_get_target','f.keep(obj,1)','f.isValueType(klass)'):
            self.assertIn(required,t.FUNCTION)
        self.assertNotIn('__BODY_EXTENSION__',t.FUNCTION)

class Integration(unittest.TestCase):
    def test_opt_in_routes_tree_stage(self):
        f=TreeFake();v=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,uikit_tree_probe=True)
        self.assertEqual(v['stage'],'tree-ready');self.assertTrue(v['rpc_root_ok'])
        self.assertIn('readUIKitTree',f.script_source);self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_tree_failure_not_masked_as_root_success(self):
        v=ready_tree();v['tree'].update(stage='tree-error',complete=False,error='unsupported-collection')
        with patch(__name__+'.ready_tree',return_value=v):
            result=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=TreeFake(),uikit_tree_probe=True)
        self.assertEqual(result['stage'],'tree-error')
    def test_invalid_tree_no_retry_or_private_error(self):
        with patch(__name__+'.ready_tree',side_effect=RuntimeError('PRIVATE TEXT')) as call:
            result=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=TreeFake(),uikit_tree_probe=True)
        self.assertEqual(call.call_count,1);self.assertNotIn('PRIVATE',json.dumps(result))
    def test_separate_filename_and_no_modification_flags(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):
                if args[-2:]==['tcp:0','tcp:27042']:return '37149'
                return ''
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir()
            old=folder.parent/'rootless-diagnostics-0.1.5.json';old.write_text('keep')
            with patch.object(d,'bundle_token',return_value='a'*64),patch.object(d,'preflight',return_value=('PRIVATE1','PRIVATE2')),patch.object(d,'recheck'):
                result,path=d.diagnose(Adb(),folder,inspector=lambda *a:{'stage':'tree-ready'},uikit_tree_probe=True)
            self.assertEqual(path.name,'rootless-diagnostics-0.1.6.json');self.assertEqual(old.read_text(),'keep')
            self.assertEqual(result['unity_object_access'],'structure-snapshot');self.assertEqual(result['mode'],'uikit-structure-only')
            for k in ('ui_actions_performed','ui_text_read','working_device_modified','app_installation_modified','root_used','ocr_used'):
                self.assertFalse(result[k])

if __name__=='__main__':unittest.main()
