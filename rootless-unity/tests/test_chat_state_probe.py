import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chat_state_probe as p
import diagnose_device as d
from test_uikit_navigation import ready_navigation
from test_uikit_root import ready_uikit
from test_diagnose_device import FakeFrida


def ready(count=0):
    r=ready_navigation();n=r['navigation']
    for k in ('search_verified','filters_verified','return_verified','open_attempted','open_completed','cancel_attempted','cancel_completed'):n[k]=False
    n.update(root_top_kind='ui-navigation',controller_path=['root','ui-navigation','main-tabs','chat'],action_backend='read-only-chat-state',metadata_checkpoint='ready',read_checkpoint='complete',wait_reason='none',model_actual=True,model_draft=False,model_has_cm=True,cm_present=True,loaded_field_present=True,loaded_value_method_found=True,loaded_value_return_kind=2,loaded_value_byref=False,loaded_value_owner_verified=True,loaded_value_owner_inherited=False,loaded_value_owner_scope=True,loaded_value_static=False,loaded_value_abstract=False,loaded_value_arity=0,
             history_status='empty' if count==0 else 'not-empty',message_count=count,history_fully_loaded=True,history_loading=False,last_message_present=False,samples=2,sample_interval_ms=1000,chat_identity_verified=True,app_actions_attempted=False,messages_sent=0)
    return r


class ChatFake(FakeFrida):
    def create_script(self,source,name):
        super().create_script(source,name);self.script_name=name;self.exports_sync.native=ready_uikit;self.exports_sync.root=ready;self.exports_sync.cancel=lambda:None;return self


class ChatState(unittest.TestCase):
    def test_empty_and_nonempty(self):p.validate(ready());p.validate(ready(7))
    def test_draft_is_not_an_empty_history_shortcut(self):
        for count in (0,7):
            r=ready(count);r['navigation']['model_draft']=True;p.validate(r)
            for key,value in [('history_fully_loaded',False),('history_loading',True),('model_actual',False),('model_has_cm',False),('cm_present',False),('samples',1)]:
                bad=copy.deepcopy(r);bad['navigation'][key]=value
                with self.assertRaises(ValueError,msg=key):p.validate(bad)
    def test_draft_transition_must_be_stable(self):
        self.assertIn('draftAgain!==n.model_draft',p.FUNCTION)
        self.assertIn('state.sample.draft!==sample.draft',p.FUNCTION)
    def test_diagnostics_are_closed_and_count_stays_unknown(self):
        for key in ('read_checkpoint','wait_reason','model_actual','model_draft','model_has_cm','cm_present','loaded_field_present'):
            r=ready();r['navigation'][key]='PRIVATE'
            with self.assertRaises(ValueError,msg=key):p.validate(r)
    def test_verified_inherited_owner_allowed(self):
        r=ready();r['navigation']['loaded_value_owner_inherited']=True;p.validate(r)
    def test_unknown_never_exposes_zero(self):
        v=ready();v['navigation'].update(stage='navigation-stopped',error='cancelled',history_status='unknown',message_count=None,samples=1);p.validate(v)
        v['navigation']['message_count']=0
        with self.assertRaises(ValueError):p.validate(v)
    def test_empty_requires_stable_loaded_and_verified_state(self):
        for key,value in [('samples',1),('samples',True),('sample_interval_ms',0),('history_fully_loaded',False),('history_loading',True),('last_message_present',True),('chat_identity_verified',False),('metadata_checkpoint','loaded-value'),('loaded_value_method_found',False),('loaded_value_return_kind',19),('loaded_value_byref',True),('loaded_value_owner_verified',False),('loaded_value_owner_scope',False),('loaded_value_owner_inherited',None),('loaded_value_static',True),('loaded_value_abstract',True),('loaded_value_arity',1),('loaded_value_arity',True),('read_checkpoint','model'),('wait_reason','chat-draft'),('model_actual',False),('model_draft',None),('model_has_cm',False),('cm_present',False),('loaded_field_present',None),('message_count',-1),('message_count',True),('message_count',1)]:
            r=ready();r['navigation'][key]=value
            with self.assertRaises(ValueError,msg=key):p.validate(r)
    def test_no_text_data_or_ui_action_flags(self):
        for key in ('app_actions_attempted','open_attempted','open_completed','cancel_attempted','cancel_completed','search_verified','filters_verified','return_verified','ui_text_read'):
            r=ready();r['navigation'][key]=True
            with self.assertRaises(ValueError,msg=key):p.validate(r)
        for key,value in [('message_text','PRIVATE'),('address','0x123'),('messages_sent',1),('messages_sent',False),('history_status','PRIVATE')]:
            r=ready();r['navigation'][key]=value
            with self.assertRaises(ValueError,msg=key):p.validate(r)
    def test_thread_visibility_lifetime_guards_still_apply(self):
        for target,key,value in [('root','main_thread_confirmed',False),('root','hooks_detached',False),('nav','handles_released',0),('nav','managed_calls',6001),('nav','frames',181),('nav','root_top_kind','filters')]:
            r=ready();(r if target=='root' else r['navigation'])[key]=value
            with self.assertRaises(ValueError,msg=key):p.validate(r)
        r=ready();r['navigation']['readiness']['attached_to_main_window']=False
        with self.assertRaises(ValueError):p.validate(r)
    def test_source_is_fixed_and_has_no_ui_mutators(self):
        for text in ('ShowSearchSettings','DismissWithCancel','OnMessageButton','OnSend','set_Text','get_Text','get_Name','get_Id','field_get_value','call(s.open','call(s.cancel','NativeCallback','Interceptor.replace','rpc.exports'):
            self.assertNotIn(text,p.FUNCTION)
        for text in ('get_LoadInProgress','get_AllIsLoaded','get_Value','get_Count','state.nextActionAt=Date.now()+1000','first!==third','lastAgain.equals(lastMessage)','get_Parent','main-thread-check','frameBusy'):
            self.assertIn(text,p.FUNCTION)
    def test_fixed_transport_no_retry_and_cleanup(self):
        f=ChatFake();r=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,chat_state_probe=True)
        self.assertEqual(r['stage'],'navigation-ready');self.assertEqual(f.script_name,'dvk-open-chat-state-0.3.21')
        self.assertIn('rpc.exports.cancel',f.script_source);self.assertNotIn('OnSendText',f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_modes_cannot_mix(self):
        for key in ('profile_probe','batch_probe','profile_metadata_probe','navigation_probe','uikit_tree_probe','chat_runtime_probe'):
            with self.assertRaises(d.TestError):d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=ChatFake(),chat_state_probe=True,**{key:True})
    def test_file_name_and_truthful_read_only_flags(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):
                assert args[:2]==['-s','127.0.0.1:5563'];return '37149' if args[-2:]==['tcp:0','tcp:27042'] else ''
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir()
            with patch.object(d,'bundle_token',return_value='a'*64),patch.object(d,'preflight',return_value=('PRIVATE1','PRIVATE2')),patch.object(d,'recheck'):
                out,path=d.diagnose(Adb(),folder,inspector=lambda *a:{'stage':'navigation-ready','uikit_root':ready()},chat_state_probe=True)
            self.assertEqual(path.name,'rootless-open-chat-state-0.3.21.json');self.assertEqual(out['mode'],'open-chat-state-read-only')
            for key in ('ui_actions_attempted','ui_actions_performed','chat_opened','message_text_read','history_read','working_device_modified','app_installation_modified'):self.assertIs(out[key],False)
            self.assertIs(out['history_state_read'],True);self.assertIs(out['method_values_read'],True);self.assertEqual(out['messages_sent'],0)
            self.assertNotIn('PRIVATE',path.read_text());self.assertNotIn('a'*64,path.read_text())
    def test_compact_button_has_no_autostart_and_blocks_parallel_run(self):
        import navigate_profile_device as gui
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk;tk.Tk.return_value.winfo_height.return_value=300;ttk.Frame.return_value.winfo_reqheight.return_value=260
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}),patch.object(gui.threading,'Thread') as thread:
            gui.launch_gui();thread.assert_not_called();commands={c.kwargs.get('text'):c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Проверить чат']();self.assertEqual(thread.call_args.kwargs['args'][2:],(False,False,True));thread.return_value.start.assert_called_once()
            commands['Проверить 10']();thread.return_value.start.assert_called_once()
        ttk.Checkbutton.assert_not_called()
        self.assertIn('Доступная история пуста',gui.result_status({'mode':'open-chat-state-read-only','status':'navigation-ready','gadget':{'uikit_root':ready()}}))
