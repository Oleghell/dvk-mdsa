import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import profile_metadata as p
import diagnose_device as d
from test_diagnose_device import FakeFrida
from test_uikit_root import ready_root,ready_uikit


def ready_preflight():
    value=ready_root()
    for k,v in list(value.items()):
        if type(v) is bool:value[k]=False
    value.update(stage='profile-metadata-ready',step='metadata',api_available=True,metadata_ready=True,
        observed_calls=0,managed_calls=0,frame_source='not-observed',metadata_thread_attached=True,metadata_thread_detached=True)
    value['profile_metadata']={k:None for k in p.DETAILS}
    value['profile_metadata'].update(checkpoint='ready',failure='none',nested_types_found=7)
    return value

class MetadataFake(FakeFrida):
    def create_script(self,source,name):
        super().create_script(source,name);self.script_name=name
        self.exports_sync.native=ready_uikit;self.exports_sync.root=ready_preflight
        return self

class ProfileMetadata(unittest.TestCase):
    def test_success(self):p.validate(ready_preflight())
    def test_closed_report_and_categories(self):
        for key,value in [('checkpoint','private-name'),('failure','private-error'),('method_found',1),('actual_arity',True),('actual_return_kind',-1),('nested_types_found',8),('address','0x123')]:
            x=ready_preflight();x['profile_metadata'][key]=value
            with self.assertRaises(ValueError):p.validate(x)
    def test_failure_keeps_safe_details(self):
        x=ready_preflight();x.update(stage='native-call-failed',metadata_ready=False)
        x['profile_metadata'].update(checkpoint='profile-method:next',failure='signature',method_found=True,expected_return_kind=2,actual_return_kind=1)
        p.validate(x)
    def test_no_object_or_observer_access(self):
        for k in ('observer_installed','observed_callback','main_thread_confirmed','runtime_available','window_available','object_classes_validated','runtime_handle_acquired','window_handle_acquired'):
            x=ready_preflight();x[k]=True
            with self.assertRaises(ValueError):p.validate(x)
        for k in ('managed_calls','observed_calls'):
            x=ready_preflight();x[k]=1
            with self.assertRaises(ValueError):p.validate(x)
    def test_thread_cleanup_required(self):
        x=ready_preflight();x['metadata_thread_detached']=False
        with self.assertRaises(ValueError):p.validate(x)
    def test_no_action_execution_in_source(self):
        for forbidden in ('Interceptor','navigationTick','f.invoke(','f.keep(','NativeCallback','rpc.exports','readUtf8String','get_Text','get_Id','set_Text'):
            self.assertNotIn(forbidden,p.FUNCTION)
        self.assertIn("mark('profile-method:open')",p.FUNCTION)
        self.assertIn('return Promise.resolve(r);',p.FUNCTION)
    def test_transport_is_metadata_only(self):
        f=MetadataFake();r=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,profile_metadata_probe=True)
        self.assertEqual(r['stage'],'profile-metadata-ready');self.assertTrue(r['rpc_root_ok'])
        self.assertEqual(f.script_name,'dvk-profile-metadata-0.3.1')
        self.assertNotIn('rpc.exports.cancel',f.script_source);self.assertNotIn('Interceptor',f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_conflicting_modes_rejected_before_connect(self):
        for kw in ({'profile_probe':True},{'navigation_probe':True},{'uikit_tree_probe':True}):
            with self.assertRaises(d.TestError):d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=MetadataFake(),profile_metadata_probe=True,**kw)
    def test_filename_version_device_and_no_actions(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):
                assert args[:2]==['-s','127.0.0.1:5563']
                return '37149' if args[-2:]==['tcp:0','tcp:27042'] else ''
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir()
            old=folder.parent/'rootless-profile-navigation-0.3.0.json';old.write_text('keep')
            with patch.object(d,'bundle_token',return_value='a'*64),patch.object(d,'preflight',return_value=('PRIVATE1','PRIVATE2')),patch.object(d,'recheck'):
                result,path=d.diagnose(Adb(),folder,inspector=lambda *a:{'stage':'profile-metadata-ready','uikit_root':ready_preflight()},profile_metadata_probe=True)
            self.assertEqual(path.name,'rootless-profile-metadata-0.3.1.json');self.assertEqual(old.read_text(),'keep')
            self.assertEqual(result['tool_version'],'0.3.1');self.assertEqual(result['mode'],'profile-metadata-only')
            self.assertEqual(result['action_backend'],'metadata-only');self.assertEqual(result['target'],'127.0.0.1:5563')
            for k in ('ui_actions_attempted','ui_actions_performed','profile_may_remain_open','root_used','ocr_used','working_device_modified','app_installation_modified'):self.assertIs(result[k],False)
            self.assertNotIn('PRIVATE',path.read_text());self.assertNotIn('a'*64,path.read_text())
    def test_rpc_failure_never_retries(self):
        f=MetadataFake();original=f.create_script
        def create(*a,**kw):
            original(*a,**kw)
            def bad():raise RuntimeError('PRIVATE')
            f.exports_sync.root=bad;return f
        f.create_script=create
        r=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,profile_metadata_probe=True)
        self.assertEqual(r['attempts'],1);self.assertFalse(r['rpc_root_ok']);self.assertNotIn('PRIVATE',json.dumps(r))
