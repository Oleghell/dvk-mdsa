import copy,json
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uikit_navigation as n
import diagnose_device as d
from test_uikit_root import ready_root,ready_uikit
from test_diagnose_device import FakeFrida


def ready_navigation():
    root=ready_root();root['managed_calls']=12;root['observed_calls']=4
    root['navigation']={'stage':'navigation-ready','phase':'done','error':'none','frames':4,
      'managed_calls':70,'handles_acquired':26,'handles_released':26,'cleanup_failed':False,
      'search_verified':True,'filters_verified':True,'return_verified':True,
      'open_attempted':True,'open_completed':True,'cancel_attempted':True,'cancel_completed':True,
      'root_top_kind':'search','last_presented_kind':'none','controller_path':['search'],'action_backend':'semantic-controller-handlers','ui_text_read':False,
      'readiness_check':'ready','view_parent_depth':1,'readiness':{'has_view':True,'is_presented':False,'hidden':False,'interactive':True,'attached_to_main_window':True}}
    return root

class NavigationSchema(unittest.TestCase):
    def test_success(self):n.validate(ready_navigation())
    def test_rejects_extra_data(self):
        for target in ('root','nav'):
            v=ready_navigation();(v if target=='root' else v['navigation'])['private']='text'
            with self.assertRaises(ValueError):n.validate(v)
    def test_success_requires_every_step(self):
        for field in ('search_verified','filters_verified','return_verified','open_attempted','open_completed','cancel_attempted','cancel_completed'):
            v=ready_navigation();v['navigation'][field]=False
            with self.assertRaises(ValueError):n.validate(v)
    def test_no_success_with_leak_or_missing_thread(self):
        for key,val in [('handles_released',25),('managed_calls',6001),('frames',181),('ui_text_read',True),('root_top_kind','PRIVATE')]:
            v=ready_navigation();v['navigation'][key]=val
            with self.assertRaises(ValueError):n.validate(v)
        v=ready_navigation();v['main_thread_confirmed']=False
        with self.assertRaises(ValueError):n.validate(v)
    def test_no_unknown_stop_or_unfinished(self):
        for stage,error in [('navigation-stopped','none'),('navigation-running','none'),('navigation-stopped','raw private error')]:
            v=ready_navigation();v['navigation'].update(stage=stage,error=error)
            with self.assertRaises(ValueError):n.validate(v)
    def test_only_fixed_semantic_actions(self):
        for forbidden in ('get_Text','set_Text','get_Name','get_Subviews','OnApplyButton','OnResetButton','OnContactButton','DismissWithSuccess','OnDidClicked','NativeCallback','Interceptor.replace','Memory.scan','il2cpp_field_', 'input tap'):
            self.assertNotIn(forbidden,n.FUNCTION)
        for required in ('DV.Search.dll','SearchTabController','SearchSettingsCardController','ShowSearchSettings','DismissWithCancel','get_Parent','get_IsBeingPresented','get_IsBeingDismissed','virtualMethod','cancelNavigation'):
            self.assertIn(required,n.FUNCTION)
    def test_closed_fixed_rpc_and_pointer_handles(self):
        self.assertNotIn('rpc.exports',n.FUNCTION)
        self.assertIn("keep:bind('gchandle_new','pointer',['pointer','bool'])",n.FUNCTION)
        self.assertIn("f.keep(obj,1)",n.FUNCTION)
        self.assertNotIn('setInterval',n.FUNCTION)
        self.assertIn("get_CurrentViewController",n.FUNCTION)

class NavFake(FakeFrida):
    def create_script(self,source,name):
        super().create_script(source,name)
        self.exports_sync.native=ready_uikit
        self.exports_sync.root=ready_navigation
        self.exports_sync.cancel=lambda:None
        return self

class NavigationTransport(unittest.TestCase):
    def test_fixed_script_no_generic_action_rpc(self):
        f=NavFake();r=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,navigation_probe=True)
        self.assertEqual(r['stage'],'navigation-ready');self.assertTrue(r['rpc_root_ok'])
        self.assertIn('rpc.exports.cancel',f.script_source)
        self.assertNotIn('rpc.exports.click',f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_no_retry_after_attachment(self):
        f=NavFake()
        def bad(*a,**kw):raise RuntimeError('private')
        original=f.create_script
        def create(*a,**kw):
            original(*a,**kw);f.exports_sync.root=bad;return f
        f.create_script=create
        r=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,navigation_probe=True)
        self.assertEqual(r['attempts'],1);self.assertFalse(r['rpc_root_ok'])
        self.assertNotIn('private',json.dumps(r))
    def test_report_truthfully_marks_attempts_and_file_name(self):
        self.assertEqual(d.TARGET,'127.0.0.1:5563');self.assertEqual(d.WORKING,'127.0.0.1:5555')
    def test_report_filename_and_partial_action_warning(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):
                return '37149' if args[-2:]==['tcp:0','tcp:27042'] else ''
        for complete in (True,False):
            value=ready_navigation()
            if not complete:
                value['navigation'].update(stage='navigation-stopped',error='frame-limit',return_verified=False)
            gadget={'stage':'navigation-ready' if complete else 'navigation-stopped','uikit_root':value}
            with tempfile.TemporaryDirectory() as temp:
                folder=Path(temp)/'test-apks';folder.mkdir()
                previous=folder.parent/'rootless-diagnostics-0.1.8.json';previous.write_text('keep')
                with patch.object(d,'bundle_token',return_value='a'*64),patch.object(d,'preflight',return_value=('PRIVATE1','PRIVATE2')),patch.object(d,'recheck'):
                    result,path=d.diagnose(Adb(),folder,inspector=lambda *a:gadget,navigation_probe=True)
                self.assertEqual(path.name,'rootless-navigation-0.2.2.json');self.assertEqual(previous.read_text(),'keep')
                self.assertTrue(result['ui_actions_attempted'] and result['ui_actions_performed'])
                self.assertEqual(result['filters_may_remain_open'],not complete)
                for flag in ('root_used','ocr_used','working_device_modified','app_installation_modified','ui_text_read'):self.assertFalse(result[flag])
                text=path.read_text(encoding='utf-8')
                for private in ('PRIVATE','a'*64):self.assertNotIn(private,text)

class ActiveControllerRegression(unittest.TestCase):
    def test_fixed_category_path_only(self):
        v=ready_navigation();v['navigation']['controller_path']=['ui-navigation','main-tabs','search'];n.validate(v)
        for path in (['PRIVATE USER'],['search']*13,'search',[True]):
            v=ready_navigation();v['navigation']['controller_path']=path
            with self.assertRaises(ValueError):n.validate(v)
    def test_explicit_active_container_getters_not_all_children(self):
        for method in ('get_MainNavigationController','get_CurrentViewController','HasPresentedViewControllers','get_InTransition'):
            self.assertIn(method,n.FUNCTION)
        self.assertNotIn('get_ChildViewControllers',n.FUNCTION)
        self.assertNotIn('get_Subviews',n.FUNCTION)
        self.assertIn("if(k==='search'||k==='filters')return current;",n.FUNCTION)
    def test_hierarchy_limits_and_no_guessing(self):
        self.assertIn('controller-cycle',n.FUNCTION)
        self.assertIn('depth<12',n.FUNCTION)
        self.assertIn('presentation-not-resolved',n.FUNCTION)
        self.assertNotIn('get_Name',n.FUNCTION)

class ViewReadinessRegression(unittest.TestCase):
    def test_presentation_is_not_visibility(self):
        for presented in (True,False):
            v=ready_navigation();v['navigation']['readiness']['is_presented']=presented;n.validate(v)
        self.assertNotIn('get_IsEffectivelyPresented',n.FUNCTION)
        self.assertIn('cursor.equals(window)',n.FUNCTION)
    def test_no_ready_without_attached_visible_interactive_view(self):
        for key,value in [('has_view',False),('hidden',True),('interactive',False),('attached_to_main_window',False),('attached_to_main_window',None)]:
            v=ready_navigation();v['navigation']['readiness'][key]=value
            with self.assertRaises(ValueError):n.validate(v)
    def test_fixed_readiness_data_only(self):
        for key,value in [('readiness_check','PRIVATE TEXT'),('view_parent_depth',32),('view_parent_depth',True)]:
            v=ready_navigation();v['navigation'][key]=value
            with self.assertRaises(ValueError):n.validate(v)
        v=ready_navigation();v['navigation']['readiness']['private']='data'
        with self.assertRaises(ValueError):n.validate(v)
