"""Fault-injected unloaded navigation setup. No real devices or credentials."""
import itertools,json,subprocess,shutil,sys,unittest,copy
from unittest.mock import MagicMock,patch
import dialog_browser as browser
import dialog_models as models
import search_online as online
import one_chat_device as transport
from startup_failure import record
import test_one_chat as read_harness
from test_search_online import OnlineFake
from test_dialog_browser import raw_open,TARGET
from test_target_only import BOOT,OTHER_BOOT
from test_device import TestError
PRIVATE='PRIVATE BODY TOKEN HOST'

class Data(unittest.TestCase):
    def test_compiled_source_size_is_independent_of_private_targets(self):
        values=[dict(account='123456789012345678',peer=str(100000+i),chat='-1',seen_ids=list(map(str,range(200000,200128)))) for i in range(1000)]
        large=models.build(allowed=values,needs_reply_only=True,recent_limit=50,reverse=True)
        prepared=browser.PreparedNavigation(models.build(allowed=(),needs_reply_only=True,recent_limit=50,reverse=True),values,lambda x:x)
        self.assertLess(len(prepared.source),len(large)//4)
        self.assertNotIn('123456789012345678',prepared.source)
        self.assertIn('allowedTargets=navigationTargets',prepared.source)
        self.assertNotIn('eval(',prepared.source)
        self.assertEqual(prepared.allowed,values)
    @unittest.skipUnless(shutil.which('node'),'Node needed for isolated data parser')
    def test_bootstrap_strict_atomic_and_one_shot(self):
        # Test the actual authored JS without Frida or native UI.
        js=browser.TARGET_BOOTSTRAP+r'''
const bad=[null,{},[null],[{account:'1',peer:'2',chat:'3',body:'PRIVATE'}],
 [{account:'01',peer:'2',chat:'3'}],[{account:'1',peer:'2',chat:'9223372036854775808'}],
 [{account:'1',peer:'2',chat:'-9223372036854775809'}],
 [{account:'1',peer:'2',chat:'3',seen_ids:['4','4']}],
 [{account:'1',peer:'2',chat:'3'},{account:'1',peer:'2',chat:'4'}]];
for(const x of bad){let failed=false;try{prepareNavigationTargets(x);}catch(_){failed=true;}
 if(!failed||navigationTargets!==null)throw Error('bad value accepted or partial state');}
const x=[{account:'1',peer:'2',chat:'-9223372036854775808',seen_ids:['4']}];
if(prepareNavigationTargets(x)!==true)throw Error('no ACK');
x[0].seen_ids.push('5');if(navigationTargets[0].seen_ids.length!==1)throw Error('not copied');
if(!Object.isFrozen(navigationTargets)||!Object.isFrozen(navigationTargets[0]))throw Error('not frozen');
let failed=false;try{prepareNavigationTargets([]);}catch(_){failed=true;}if(!failed)throw Error('second upload');
console.log('PASS');
'''
        out=subprocess.run([shutil.which('node'),'-e',js],capture_output=True,text=True,check=True,timeout=60)
        self.assertEqual(out.stdout.strip(),'PASS')

class Upload(unittest.TestCase):
    def fake(self,ack=True):
        f=OnlineFake();original=f.create_script;self.calls=[]
        def create(*a,**kw):
            value=original(*a,**kw)
            f.exports_sync.preparetargets=lambda targets:self.calls.append(('targets',targets)) or ack
            f.exports_sync.root=lambda:self.calls.append(('root',None)) or 'validated'
            return value
        f.create_script=create;return f
    def test_upload_ack_precedes_root(self):
        f=self.fake()
        value=online.inspect(37149,PRIVATE,lambda:False,frida_api=f,source_function='FIXED',validator=lambda x:x,navigation_targets=[TARGET])
        self.assertEqual(value,'validated');self.assertEqual(self.calls,[('targets',[TARGET]),('root',None)])
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_rejected_or_unknown_upload_does_not_call_root_or_borrow_no_load_proof(self):
        for ack in (False,None,1):
            f=self.fake(ack)
            with self.assertRaises(Exception) as raised:
                online.inspect(37149,PRIVATE,lambda:False,frida_api=f,source_function='FIXED',navigation_targets=[TARGET])
            self.assertEqual(self.calls,[('targets',[TARGET])]);self.assertFalse(raised.exception._dvk_navigation_not_loaded)
            self.assertEqual(raised.exception._dvk_failure['stage'],'navigation-targets-upload')
    def test_only_script_create_transport_gets_unloaded_proof(self):
        for stage in ('create_script','load'):
            f=self.fake();setattr(f,stage,MagicMock(side_effect=type('TransportError',(Exception,),{})(PRIVATE)))
            with self.assertRaises(Exception) as raised:
                online.inspect(37149,PRIVATE,lambda:False,frida_api=f,source_function='FIXED',navigation_targets=[])
            self.assertEqual(raised.exception._dvk_navigation_not_loaded,stage=='create_script')
            self.assertNotIn(PRIVATE,json.dumps(raised.exception._dvk_failure))

class Reconnect(read_harness.ReadTransport):
    def call_navigation(self,f,*,model=False,cancelled=lambda:False):
        with self.patched(),patch.object(transport,'TargetOnlyAdb',return_value=self.adb),patch.object(transport,'bundle_token',return_value=PRIVATE),patch.dict(sys.modules,frida=f):
            return (models.perform if model else browser.perform)('open','adb',self.folder,cancelled,allowed=[TARGET])
    def fake(self,failures=1,stage='create_script'):
        f=OnlineFake();create=f.create_script;self.attempts=0;self.roots=0;self.uploads=0
        def failure():raise type('TransportError',(Exception,),{})(PRIVATE)
        def root():
            self.roots+=1
            if stage=='root':failure()
            return raw_open()
        def prepare(values):self.uploads+=1;self.assertEqual(values,[TARGET]);return True
        def created(*a,**kw):
            self.attempts+=1
            if stage=='create_script' and self.attempts<=failures:failure()
            result=create(*a,**kw);f.exports_sync.preparetargets=prepare;f.exports_sync.root=root
            return result
        f.create_script=created
        if stage=='load':f.load=failure
        return f
    def test_two_unloaded_failures_refresh_forward_then_open_once(self):
        self.identities=itertools.repeat(BOOT);f=self.fake(2)
        self.assertEqual(self.call_navigation(f)['state'],'opened')
        self.assertEqual((self.attempts,self.uploads,self.roots),(3,1,1))
        self.assertEqual(sum('tcp:0' in x for x in self.calls),3)
        self.assertEqual(sum('--remove' in x for x in self.calls),3)
    def test_persistent_failure_is_bounded_and_executes_nothing(self):
        self.identities=itertools.repeat(BOOT);f=self.fake(9)
        with self.assertRaises(Exception):self.call_navigation(f)
        self.assertEqual((self.attempts,self.uploads,self.roots),(3,0,0))
    def test_changed_boot_never_loads_second_script(self):
        self.identities=iter([BOOT,BOOT,OTHER_BOOT]);f=self.fake()
        with self.assertRaises(TestError):self.call_navigation(f)
        self.assertEqual((self.attempts,self.roots),(1,0))
    def test_load_or_root_unknown_never_replayed(self):
        for stage in ('load','root'):
            self.identities=itertools.repeat(BOOT);f=self.fake(stage=stage)
            with self.assertRaises(Exception):self.call_navigation(f)
            self.assertEqual(self.attempts,1);self.assertEqual(self.roots,int(stage=='root'))
    def test_actual_cached_model_adapter_reconnects_before_root(self):
        self.identities=itertools.repeat(BOOT);f=self.fake(1);created=f.create_script
        def create(*a,**kw):
            value=created(*a,**kw)
            def root():
                self.roots+=1;raw=raw_open()
                raw['navigation']['private_model_scan']=dict(next=None,count=2,skipped_headers=0)
                return raw
            f.exports_sync.root=root;return value
        f.create_script=create
        self.assertEqual(self.call_navigation(f,model=True)['state'],'opened')
        self.assertEqual((self.attempts,self.uploads,self.roots),(2,1,1))
    def test_cancel_after_failed_create_does_not_retry_or_open(self):
        self.identities=itertools.repeat(BOOT);f=self.fake();create=f.create_script;stopped=[]
        def created(*a,**kw):
            try:return create(*a,**kw)
            finally:stopped.append(True)
        f.create_script=created
        with self.assertRaises(Exception):self.call_navigation(f,cancelled=lambda:bool(stopped))
        self.assertEqual((self.attempts,self.uploads,self.roots),(1,0,0))
        self.assertEqual(sum('tcp:0' in x for x in self.calls),1)
    def test_non_open_target_input_rejected_before_transport(self):
        with patch.object(transport,'capture') as capture,self.assertRaises(ValueError):
            browser.perform('list','adb','folder',allowed=[TARGET])
        capture.assert_not_called()
    def test_custom_inspector_cannot_borrow_navigation_proof(self):
        error=type('TransportError',(Exception,),{})(PRIVATE);record(error,'script-create');error._dvk_navigation_not_loaded=True
        custom=MagicMock(side_effect=error)
        with self.assertRaises(Exception):self.run_capture(custom)
        custom.assert_called_once()

for name in dir(read_harness.ReadTransport):
    if name.startswith('test_') and name not in Reconnect.__dict__:setattr(Reconnect,name,None)
