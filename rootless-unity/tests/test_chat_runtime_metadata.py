import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chat_runtime_metadata as p
import diagnose_device as d
from test_diagnose_device import FakeFrida


def ready():
    return {'stage':'chat-runtime-ready','step':'done','reason':'none','api_available':True,
            'thread_attach_performed':True,'thread_detach_confirmed':True,'current_thread_initially_attached':False,
            'cleanup_failed':False,'native_calls':100,'assemblies_scanned':5,'limited':False,
            'ui_actions_attempted':False,'method_values_read':False,'chat_opened':False,'history_read':False,'messages_sent':0,
            'roots':[dict(image=im,namespace=ns,type=n,found=False,class_index=None) for im,ns,n in p.ROOTS],'types':[]}


def graph():
    r=ready();root=r['roots'][1];root.update(found=True,class_index=0)
    identity={k:root[k] for k in ('image','namespace','type')}
    desc={'kind':1,'byref':False,'target':{'image':'mscorlib.dll','namespace':'System','type':'Void'}}
    method={'method':'OnMessageButton','arity':0,'static':False,'abstract':False,'virtual':False,'owner':identity.copy(),'owner_matches':True,'return_type':desc,'parameters':[],'parameters_truncated':False}
    r['types']=[{'index':0,'identity':identity,'depth':0,'parent':None,'parent_index':None,'methods':[method],'fields':[],'truncated':False}]
    return r


class RuntimeFake(FakeFrida):
    def create_script(self,source,name):
        super().create_script(source,name);self.script_name=name;self.exports_sync.native=graph;return self


class RuntimeMetadata(unittest.TestCase):
    def test_ready_and_typed_route(self):self.assertEqual(p.validate(graph()),graph())
    def test_source_has_no_app_or_ui_access(self):
        for word in ('Interceptor','runtime_invoke','field_get_value','gchandle','NativeCallback','object_get','readUtf8String','rpc.exports','set_Text','get_Text'):
            self.assertNotIn(word,p.FUNCTION)
        self.assertIn('class_get_parent',p.FUNCTION);self.assertIn('class_get_fields',p.FUNCTION)
    def test_unknown_fields_bad_flags_and_counts_rejected(self):
        for key,v in [('address','0x123'),('native_calls',True),('native_calls',50001),('ui_actions_attempted',True),('method_values_read',True),('chat_opened',True),('history_read',True),('messages_sent',1),('messages_sent',False),('reason','PRIVATE'),('step','PRIVATE')]:
            r=ready();r[key]=v
            with self.assertRaises(ValueError,msg=key):p.validate(r)
    def test_thread_ownership_and_cleanup(self):
        for changes in ({'thread_detach_confirmed':False},{'current_thread_initially_attached':True},{'thread_attach_performed':False},{'cleanup_failed':True}):
            r=ready();r.update(changes)
            with self.assertRaises(ValueError):p.validate(r)
        r=ready();r.update(stage='chat-runtime-stopped',reason='cleanup-failed',cleanup_failed=True,thread_detach_confirmed=False);p.validate(r)
    def test_signature_and_root_graph_validation(self):
        changes=[lambda r:r['roots'][1].update(class_index=63),lambda r:r['types'][0].update(parent_index=0,parent=r['types'][0]['identity']),
                 lambda r:r['types'][0]['methods'][0].update(parameters_truncated=True),lambda r:r['types'][0]['methods'][0].update(owner=None),
                 lambda r:r['types'][0]['methods'][0]['return_type'].update(kind=-1),lambda r:r['types'][0]['identity'].update(type='BAD\nVALUE'),
                 lambda r:r['types'][0].update(truncated=True),lambda r:r['types'][0]['methods'][0].update(address='0x123')]
        for change in changes:
            r=graph();change(r)
            with self.assertRaises(ValueError):p.validate(r)
    def test_transport_uses_native_rpc_only_and_cleans_up(self):
        f=RuntimeFake();r=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,chat_runtime_probe=True)
        self.assertEqual(r['stage'],'chat-runtime-ready');self.assertEqual(f.script_name,'dvk-chat-runtime-metadata-0.3.20')
        self.assertNotIn('rpc.exports.root',f.script_source);self.assertNotIn('rpc.exports.cancel',f.script_source);self.assertNotIn('Interceptor',f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_modes_cannot_mix(self):
        for key in ('profile_probe','batch_probe','profile_metadata_probe','navigation_probe','uikit_tree_probe','uikit_root_probe'):
            with self.assertRaises(d.TestError):d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=RuntimeFake(),chat_runtime_probe=True,**{key:True})
    def test_rpc_failure_not_retried_and_private_error_not_recorded(self):
        f=RuntimeFake();original=f.create_script
        def create(*a,**kw):
            original(*a,**kw)
            def bad():raise RuntimeError('PRIVATE')
            f.exports_sync.native=bad;return f
        f.create_script=create
        r=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,chat_runtime_probe=True)
        self.assertEqual(r['attempts'],1);self.assertNotIn('PRIVATE',json.dumps(r))
    def test_filename_and_no_actions(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):
                assert args[:2]==['-s','127.0.0.1:5563']
                return '37149' if args[-2:]==['tcp:0','tcp:27042'] else ''
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir()
            with patch.object(d,'bundle_token',return_value='a'*64),patch.object(d,'preflight',return_value=('PRIVATE1','PRIVATE2')),patch.object(d,'recheck'):
                result,path=d.diagnose(Adb(),folder,inspector=lambda *a:{'stage':'chat-runtime-ready','native_metadata':graph()},chat_runtime_probe=True)
            self.assertEqual(path.name,'rootless-chat-runtime-metadata-0.3.20.json');self.assertEqual(result['mode'],'chat-runtime-metadata-only')
            for key in ('ui_actions_attempted','ui_actions_performed','chat_opened','history_read','method_values_read','profile_may_remain_open','working_device_modified'):self.assertIs(result[key],False)
            self.assertEqual(result['messages_sent'],0);self.assertNotIn('PRIVATE',path.read_text());self.assertNotIn('a'*64,path.read_text())
    def test_default_inspector_forwarding_keeps_ui_modes_off(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):return '37149' if args[-2:]==['tcp:0','tcp:27042'] else ''
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir()
            with patch.object(d,'bundle_token',return_value='a'*64),patch.object(d,'preflight',return_value=('A','B')),patch.object(d,'recheck'),patch.object(d,'inspect_gadget',return_value={'stage':'chat-runtime-ready','native_metadata':graph()}) as inspect:
                d.diagnose(Adb(),folder,inspector=inspect,chat_runtime_probe=True)
                kw=inspect.call_args.kwargs
                self.assertIs(kw['chat_runtime_probe'],True)
                for key in ('uikit_root_probe','uikit_tree_probe','profile_probe','navigation_probe','batch_probe','profile_metadata_probe'):self.assertIs(kw[key],False)
    def test_cancellation_before_native_rpc(self):
        calls=[0]
        def cancelled():calls[0]+=1;return calls[0]>1
        f=RuntimeFake();r=d.inspect_gadget(37149,'a'*64,cancelled,frida_api=f,chat_runtime_probe=True)
        self.assertEqual(r['stage'],'cancelled');self.assertFalse(r['rpc_native_ok']);self.assertTrue(f.script_unloaded and f.detached and f.removed)

    def test_button_starts_only_runtime_metadata_and_busy_blocks_other_buttons(self):
        import navigate_profile_device as gui
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk;tk.Tk.return_value.winfo_height.return_value=300;ttk.Frame.return_value.winfo_reqheight.return_value=260
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}),patch.object(gui.threading,'Thread') as thread:
            gui.launch_gui();thread.assert_not_called()
            commands={c.kwargs.get('text'):c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Типы чата']();self.assertEqual(thread.call_args.kwargs['args'][2:],(False,True));thread.return_value.start.assert_called_once()
            commands['Проверить 10']();thread.return_value.start.assert_called_once()
        ttk.Checkbutton.assert_not_called();self.assertIn('Типы чата проверены',gui.result_status({'mode':'chat-runtime-metadata-only','status':'chat-runtime-ready'}))
