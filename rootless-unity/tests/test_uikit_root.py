import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uikit_root as p
import uikit_profile
import diagnose_device as d
from test_diagnose_device import FakeFrida
from test_native_metadata import ready_metadata


def ready_root():
    return {'stage':'root-ready','step':'done','api_available':True,'metadata_ready':True,
        'observer_installed':True,'observed_callback':True,'main_thread_confirmed':True,
        'runtime_available':True,'window_available':True,'object_classes_validated':True,
        'hooks_detached':True,'cleanup_failed':False,'metadata_thread_attached':True,
        'metadata_thread_detached':True,'runtime_handle_acquired':True,'window_handle_acquired':True,
        'runtime_handle_released':True,'window_handle_released':True,'observed_calls':1,'managed_calls':3,
        'watched_sources':dict.fromkeys(p.SOURCES,True),'frame_source':'uikit-component-update'}


def ready_uikit():
    v=ready_metadata()
    v['known_images']=dict.fromkeys(uikit_profile.IMAGES,True)
    v['known_types']=dict.fromkeys([t[0] for t in uikit_profile.TYPES],True)
    v['known_methods']=dict.fromkeys([f'{t}.{n}/{a}' for t,n,a in uikit_profile.METHODS],True)
    return v


class UIFake(FakeFrida):
    def create_script(self,source,name):
        super().create_script(source,name)
        self.exports_sync.native=ready_uikit
        self.exports_sync.root=ready_root
        return self


class RootSchema(unittest.TestCase):
    def test_valid(self):p.validate(ready_root())
    def test_extra_data_rejected(self):
        v=ready_root();v['text']='private'
        with self.assertRaises(ValueError):p.validate(v)
    def test_success_requires_observation_mainthread_and_cleanup(self):
        for key in ('observed_callback','main_thread_confirmed','runtime_available','window_available','hooks_detached','metadata_thread_detached','runtime_handle_released','window_handle_released'):
            v=ready_root();v[key]=False
            with self.assertRaises(ValueError):p.validate(v)
    def test_counts_bounded_and_not_booleans(self):
        for key,bad in (('managed_calls',4),('observed_calls',10001),('observed_calls',True),('managed_calls',-1)):
            v=ready_root();v[key]=bad
            with self.assertRaises(ValueError):p.validate(v)
    def test_fixed_frame_labels_only(self):
        v=ready_root();v['frame_source']='private MethodInfo address'
        with self.assertRaises(ValueError):p.validate(v)
    def test_no_native_code_offset_or_behavior_replacement(self):
        for bad in ('Interceptor.replace','Interceptor.detachAll','retval.replace','args[0] =','NativeCallback','Memory.scan','il2cpp_field_', 'il2cpp_runtime_class_init'):
            self.assertNotIn(bad,p.FUNCTION)
        self.assertIn('Interceptor.attach(addresses.il2cpp_runtime_invoke',p.FUNCTION)
        self.assertIn('setTimeout',p.FUNCTION)
        self.assertIn('8000',p.FUNCTION)
        self.assertIn('10000',p.FUNCTION)
    def test_handles_are_opaque_pointers_not_uint32(self):
        self.assertIn("keep:bind('gchandle_new','pointer',['pointer','bool'])",p.FUNCTION)
        self.assertIn("release:bind('gchandle_free','void',['pointer'])",p.FUNCTION)
        self.assertNotIn("gchandle_new','uint32'",p.FUNCTION)
        self.assertNotIn("gchandle_free','void',['uint32']",p.FUNCTION)
    def test_release_without_acquisition_rejected(self):
        v=ready_root();v['runtime_handle_acquired']=False
        with self.assertRaises(ValueError):p.validate(v)
    def test_only_three_fixed_managed_getters(self):
        for name in ('set_Text','get_Text','OnDidClicked','get_Subviews','sendMessage'):
            self.assertNotIn(name,p.FUNCTION)
        for name in ('get_IsOnMainThread','get_OptionalInstance','get_MainWindow'):
            self.assertIn(name,p.FUNCTION)


class Integration(unittest.TestCase):
    def test_opt_in_uses_profile_and_root_rpc(self):
        f=UIFake();v=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,uikit_root_probe=True)
        self.assertEqual(v['stage'],'root-ready');self.assertTrue(v['rpc_root_ok'])
        self.assertIn('probeUIKitRoot()',f.script_source)
        self.assertIn('UIKit.UIRuntime',f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_legacy_mode_never_installs_observer(self):
        f=FakeFrida();v=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f)
        self.assertEqual(v['stage'],'metadata-ready')
        self.assertNotIn('Interceptor',f.script_source);self.assertNotIn('uikit_root',v)
    def test_skip_root_when_metadata_not_ready(self):
        original=ready_uikit
        def bad_metadata():
            v=original();v['stage']='metadata-api-incomplete';return v
        with patch(__name__+'.ready_uikit',side_effect=bad_metadata),patch(__name__+'.ready_root',side_effect=AssertionError('must not call')) as root:
            v=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=UIFake(),uikit_root_probe=True)
        self.assertFalse(v['rpc_root_ok']);self.assertEqual(root.call_count,0)
    def test_root_failure_not_retried_or_exception_leaked(self):
        with patch(__name__+'.ready_root',side_effect=RuntimeError('PRIVATE POINTER')) as root:
            v=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=UIFake(),uikit_root_probe=True)
        self.assertEqual(root.call_count,1);self.assertEqual(v['stage'],'uikit-root-rpc')
        self.assertNotIn('PRIVATE',json.dumps(v))
    def test_new_report_filename_does_not_overwrite_013(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):
                if args[-2:]==['tcp:0','tcp:27042']:return '37149'
                return ''
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir()
            old=folder.parent/'rootless-diagnostics-0.1.3.json';old.write_text('keep')
            with patch.object(d,'bundle_token',return_value='a'*64),patch.object(d,'preflight',return_value=('PRIVATE1','PRIVATE2')),patch.object(d,'recheck'):
                result,path=d.diagnose(Adb(),folder,inspector=lambda *a:{'stage':'root-ready'},uikit_root_probe=True)
            self.assertEqual(old.read_text(),'keep');self.assertEqual(path.name,'rootless-diagnostics-0.1.5.json')
            self.assertEqual(result['unity_object_access'],'root-presence-confirmed')
            self.assertFalse(result['ui_actions_performed']);self.assertFalse(result['ui_text_read'])


if __name__=='__main__':unittest.main()
