import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chat_batch as b
import diagnose_device as d
from test_profile_batch import good,exhausted
from test_chat_state_probe import ready as chat_ready
from test_profile_navigation import ProfileFake

def cycle(friends=13,count=0):
    r=good(friends);n=r['navigation'];n.update(copy.deepcopy(b.DEFAULTS))
    if friends<50:
        c=chat_ready(count)['navigation']
        for k in b.DEFAULTS:
            if k in c:n[k]=c[k]
        n.update(chat_metadata_checkpoint='ready',chat_open_attempted=True,chat_open_completed=True,chat_verified=True,chat_back_attempted=True,chat_back_completed=True,chat_return_verified=True,chat_return_route='profile')
        if count==0:n.update(send_attempted=True,send_handler_returned=True,messages_sent=None,greeting_variant=3)
    return r

def empty_search():
    r=exhausted();r['navigation'].update(copy.deepcopy(b.DEFAULTS));return r

class Automatic(unittest.TestCase):
    def test_full_pass_limit_and_skip(self):
        calls=[]
        def root():calls.append(1);return cycle((0,49,50,97)[(len(calls)-1)%4])
        out=b.run(root)
        self.assertEqual(len(calls),10);self.assertEqual(out['status'],'batch-completed')
        self.assertEqual((out['checked'],out['eligible'],out['skipped'],out['chats_checked'],out['send_attempts'],out['handlers_returned']),(10,6,4,6,6,6))
        self.assertIsNone(out['messages_sent']);self.assertFalse(out['delivery_confirmed']);self.assertFalse(out['profile_may_remain_open'])
    def test_nonempty_and_97_never_send(self):
        for friends,count,checked in ((97,0,0),(13,1,10)):
            out=b.run(lambda:cycle(friends,count));self.assertEqual(out['send_attempts'],0);self.assertEqual(out['messages_sent'],0);self.assertEqual(out['chats_checked'],checked)
    def test_visible_exhaustion(self):
        values=iter([cycle(),empty_search()]);out=b.run(lambda:next(values))
        self.assertEqual(out['status'],'batch-exhausted');self.assertEqual(out['checked'],1);self.assertEqual(out['handlers_returned'],1)
    def test_direct_search_return_without_extra_profile_close(self):
        r=cycle();n=r['navigation'];n.update(chat_return_route='search',close_attempted=False,close_completed=False,controller_path=['root','dv-navigation','main-tabs','search'])
        b.validate(r);self.assertFalse(n['close_attempted']);self.assertFalse(n['close_completed'])
        out=b.run(lambda:r);self.assertEqual(out['status'],'batch-completed');self.assertEqual(out['handlers_returned'],10)
        self.assertTrue(all(i['chat_return_route']=='search' for i in out['items']))
    def test_invalid_direct_search_return_rejected(self):
        for key,value in [('return_verified',False),('chat_return_verified',False),('chat_back_completed',False),('chat_return_route','not-checked'),('close_attempted',True),('close_completed',True),('controller_path',['root','dv-navigation','main-tabs','profile']),('phase','wait-chat-back')]:
            r=cycle();r['navigation'].update(chat_return_route='search',close_attempted=False,close_completed=False,controller_path=['root','dv-navigation','main-tabs','search']);r['navigation'][key]=value
            with self.assertRaises(ValueError,msg=key):b.validate(r)
    def test_rpc_unknown_counters_not_false_zero(self):
        calls=[]
        def root():calls.append(1);raise RuntimeError('PRIVATE 0x123')
        out=b.run(root)
        for key in ('messages_sent','send_attempts','handlers_returned'):self.assertIsNone(out[key])
        self.assertEqual(len(calls),1);self.assertTrue(out['profile_may_remain_open']);self.assertNotIn('PRIVATE',json.dumps(out))
    def test_handler_exception_not_retry(self):
        r=cycle();n=r['navigation'];n.update(stage='navigation-stopped',phase='check-chat',error='managed-exception',chat_back_attempted=False,chat_back_completed=False,chat_return_verified=False,chat_return_route='not-checked',send_handler_returned=False,close_attempted=False,close_completed=False,return_verified=False)
        calls=[]
        def root():calls.append(1);return r
        out=b.run(root)
        self.assertEqual(len(calls),1);self.assertEqual(out['send_attempts'],1);self.assertEqual(out['handlers_returned'],0);self.assertIsNone(out['messages_sent'])
    def test_cancel_never_calls_next_profile(self):
        calls=[]
        def root():calls.append(1);return cycle()
        out=b.run(root,lambda:len(calls)>0)
        self.assertEqual(out['status'],'batch-cancelled');self.assertEqual(len(calls),1)
    def test_send_and_history_validation(self):
        for key,value in [('friends_eligible',False),('chat_open_attempted',False),('chat_verified',False),('chat_identity_verified',False),('chat_return_verified',False),('messages_sent',0),('send_attempted',False),('send_handler_returned',False),('history_loading',True),('history_fully_loaded',False),('model_actual',False),('samples',1),('sample_interval_ms',0),('greeting_variant',30),('greeting_variant',True),('last_message_present',True),('message_count',1),('loaded_value_owner_scope',False),('loaded_value_static',True)]:
            r=cycle();r['navigation'][key]=value
            with self.assertRaises(ValueError,msg=key):b.validate(r)
    def test_unknown_count_and_extra_private_fields_rejected(self):
        for key,value in [('message_count',None),('user_id','PRIVATE'),('history_status','unknown')]:
            r=cycle();r['navigation'][key]=value
            with self.assertRaises(ValueError,msg=key):b.validate(r)
    def test_random_choices_each_new_script(self):
        with patch.object(b,'choose_index',side_effect=list(range(10))+list(range(10,20))) as random:
            a=b.build_random();c=b.build_random()
        self.assertEqual(random.call_count,20);self.assertNotEqual(a,c)
        self.assertIn('batchVariants=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]',a)
        for variants in ([0]*9,[0]*11,[True]*10,[30]*10):
            with self.assertRaises(ValueError):b.build(variants)
    def test_source_latches_before_invocation_and_delays_actions(self):
        s=b.FUNCTION
        self.assertLess(s.index('batchSent.add(batchCandidateKey)'),s.index('call(s.send,current,args)'))
        for text in ('state.nextActionAt=Date.now()+1000','batchSeen.has(identityKey)','batchHalted=true','m_OverlayView','OnMessageButton','OnBackButton','OnSendText','get_IsInputEnabled','first!==third','state.sample.draft!==sample.draft'):
            self.assertIn(text,s)
        for text in ('Memory.scan','input tap','get_Name','get_PhoneNumber','get_Text','set_Text'):self.assertNotIn(text,s)
    def test_atomic_lock_retained_after_any_possible_submission(self):
        for summary in (b.run(cycle),{},dict(send_attempts=None,messages_sent=None,reason='probe-failed')):
            with tempfile.TemporaryDirectory() as t:
                folder=Path(t);r={'gadget':{'batch':summary}}
                with patch.object(d,'diagnose',return_value=(r,folder/'report')) as run:
                    b.start(None,folder)
                    with self.assertRaises(d.TestError):b.start(None,folder)
                self.assertEqual(run.call_count,1);self.assertTrue((folder/'.dvk-ten-profile-pass.lock').exists())
    def test_lock_retained_after_transport_exception(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)
            with patch.object(d,'diagnose',side_effect=RuntimeError):
                with self.assertRaises(RuntimeError):b.start(None,folder)
            self.assertTrue((folder/'.dvk-ten-profile-pass.lock').exists())
    def test_lock_released_only_validated_no_attempt(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);r={'gadget':{'batch':b.run(lambda:cycle(97))}}
            with patch.object(d,'diagnose',return_value=(r,folder/'report')):b.start(None,folder)
            self.assertFalse((folder/'.dvk-ten-profile-pass.lock').exists())

class AutoFake(ProfileFake):
    def create_script(self,source,name):
        super().create_script(source,name);self.roots=0
        def root():self.roots+=1;return cycle()
        self.exports_sync.root=root;return self

class Integration(unittest.TestCase):
    def test_ten_cycles_same_connection_fixed_rpc(self):
        f=AutoFake();out=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,automatic_probe=True)
        self.assertEqual(out['stage'],'batch-completed');self.assertEqual(f.roots,10)
        self.assertEqual(f.script_name,'dvk-automatic-pass-0.3.27');self.assertIn('rpc.exports.root = () => probeBatchProfile();',f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_conflicting_modes(self):
        for key in ('chat_send_probe','chat_state_probe','chat_runtime_probe','profile_metadata_probe','uikit_tree_probe'):
            with self.assertRaises(d.TestError):d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=AutoFake(),automatic_probe=True,**{key:True})
    def test_gui_manual_start_and_parallel_block(self):
        import navigate_profile_device as gui
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk;tk.Tk.return_value.winfo_height.return_value=300
        ttk.Frame.return_value.winfo_reqheight.return_value=260
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}),patch.object(gui.threading,'Thread') as thread:
            gui.launch_gui();thread.assert_not_called()
            commands={c.kwargs.get('text'):c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Новая десятка · сохранить привязки']();self.assertIs(thread.call_args.kwargs['args'][8],True)
            commands['Новая десятка · сохранить привязки']();commands['Случайное приветствие — один раз']()
            thread.return_value.start.assert_called_once()
        ttk.Checkbutton.assert_not_called()
    def test_report_filename_and_delivery_not_claimed(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):
                assert args[:2]==['-s','127.0.0.1:5563'];return '37149' if args[-2:]==['tcp:0','tcp:27042'] else ''
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)/'test-apks';folder.mkdir();summary=b.run(cycle)
            gadget={'stage':summary['status'],'batch':summary,'uikit_root':cycle()}
            with patch.object(d,'bundle_token',return_value='a'*64),patch.object(d,'preflight',return_value=('PRIVATE1','PRIVATE2')),patch.object(d,'recheck'):
                result,path=d.diagnose(Adb(),folder,inspector=lambda *a:gadget,automatic_probe=True)
            self.assertEqual(result['mode'],'automatic-profile-chat-pass');self.assertEqual(path.name,'rootless-automatic-pass-0.3.27.json')
            self.assertIsNone(result['messages_sent']);self.assertEqual(result['send_attempts'],10);self.assertEqual(result['handlers_returned'],10)
            self.assertFalse(result['delivery_confirmed']);self.assertFalse(result['message_text_read'])
            for text in ('PRIVATE','a'*64,'user_id','identityKey'):self.assertNotIn(text,path.read_text())
