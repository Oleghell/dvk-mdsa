import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import profile_batch as b
import diagnose_device as d
from test_profile_navigation import ready_profile,ProfileFake


def good(count=13):
    value=ready_profile();value['navigation'].update(friends_source='Profile.get_FriendsCount',friends_status='read',friends_count=count,friends_eligible=count<50)
    return value


def exhausted():
    value=ready_profile();n=value['navigation']
    n.update(stage='navigation-stopped',phase='search',error='selection-unavailable',
             open_attempted=False,open_completed=False,close_attempted=False,close_completed=False,
             profile_verified=False,return_verified=False,target_user_verified=False,profile_content_verified=False,
             selection_status='no-eligible-cell',friends_status='not-read')
    n['selection_counts'].update(passes=3)
    return value


class Batch(unittest.TestCase):
    def test_limit_and_thresholds(self):
        calls=[]
        def root():calls.append(1);return good((0,49,50,97)[(len(calls)-1)%4])
        out=b.run(root)
        self.assertEqual(len(calls),10);self.assertEqual(out['status'],'batch-completed')
        self.assertEqual((out['checked'],out['eligible'],out['skipped']),(10,6,4))
        self.assertFalse(out['profile_may_remain_open']);self.assertEqual(out['messages_sent'],0)
    def test_partial_visible_exhaustion(self):
        values=iter([good(),good(97),exhausted()]);out=b.run(lambda:next(values))
        self.assertEqual(out['status'],'batch-exhausted');self.assertEqual(out['checked'],2)
        self.assertEqual(out['errors'],0);self.assertFalse(out['profile_may_remain_open'])
    def test_empty_search_is_not_ten_completed(self):
        out=b.run(exhausted)
        self.assertEqual(out['status'],'batch-exhausted');self.assertEqual(out['visited'],0)
    def test_cancellation_between_profiles_never_opens_next(self):
        calls=[]
        def root():calls.append(1);return good()
        out=b.run(root,lambda:len(calls)>=2)
        self.assertEqual(out['status'],'batch-cancelled');self.assertEqual(len(calls),2)
    def test_rpc_exception_is_sanitized_and_potentially_open(self):
        def root():raise ValueError('PRIVATE TOKEN 0x123')
        out=b.run(root)
        self.assertTrue(out['profile_may_remain_open']);self.assertEqual(out['errors'],1)
        self.assertNotIn('PRIVATE',json.dumps(out));self.assertEqual(out['attempts'],1)
    def test_invalid_result_stops_without_retry(self):
        calls=[]
        def root():calls.append(1);value=good();value['navigation']['user_id']='PRIVATE';return value
        out=b.run(root);self.assertEqual(len(calls),1);self.assertEqual(out['reason'],'probe-failed')
        self.assertNotIn('PRIVATE',json.dumps(out))
    def test_unknown_count_is_not_zero_or_eligible(self):
        out=b.run(ready_profile)
        self.assertEqual((out['visited'],out['checked'],out['unknown'],out['errors']),(1,0,1,1))
        self.assertEqual(out['reason'],'count-unavailable');self.assertEqual(out['eligible'],0)
    def test_fixed_actions_and_in_memory_identity(self):
        for text in ("checked(s.user,'get_Id',10)",'batchSeen.has(identityKey)','batchSeen.add(identityKey)',
                     'identity.compare(0)<=0','batchAttempts>=10','batchSeen.size>=10','batchHalted=true'):
            self.assertIn(text,b.FUNCTION)
        for text in ('get_Name','get_PhoneNumber','get_ExternalLink','SendMessage','input tap','Memory.scan','readS32().toString'):
            self.assertNotIn(text,b.FUNCTION)
        self.assertNotIn('get_Id',b.single.FUNCTION) # Single-profile behavior remains private and unchanged.


class BatchFake(ProfileFake):
    def create_script(self,source,name):
        super().create_script(source,name);self.roots=0
        def root():self.roots+=1;return good()
        self.exports_sync.root=root
        return self


class BatchTransport(unittest.TestCase):
    def test_same_script_and_connection_for_whole_batch(self):
        f=BatchFake();out=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,batch_probe=True)
        self.assertEqual(out['stage'],'batch-completed');self.assertEqual(f.roots,10)
        self.assertEqual(f.script_name,'dvk-profile-batch-0.3.26')
        self.assertIn('rpc.exports.root = () => probeBatchProfile();',f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
        self.assertEqual(out['batch']['checked'],10)
    def test_metadata_only_mode_cannot_start_batch(self):
        with self.assertRaises(d.TestError):d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=BatchFake(),batch_probe=True,profile_metadata_probe=True)


class BatchGUI(unittest.TestCase):
    def test_button_uses_batch_and_prevents_double_start(self):
        import navigate_profile_device as gui
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk;tk.Tk.return_value.winfo_height.return_value=300
        ttk.Frame.return_value.winfo_reqheight.return_value=260
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}),patch.object(gui.threading,'Thread') as thread:
            gui.launch_gui();thread.assert_not_called()
            commands={c.kwargs.get('text'):c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Проверить 10']();self.assertIs(thread.call_args.kwargs['args'][2],True)
            commands['Проверить 10']();thread.return_value.start.assert_called_once()
        ttk.Checkbutton.assert_not_called()
    def test_short_final_summary(self):
        import navigate_profile_device as gui
        result={'gadget':{'batch':b.run(good)}}
        text=gui.result_status(result)
        self.assertIn('Проверено: 10',text);self.assertIn('<50: 10',text);self.assertLess(len(text),160)

class BatchReport(unittest.TestCase):
    def test_batch_filename_privacy_and_uncertain_rpc(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):
                assert args[:2]==['-s','127.0.0.1:5563']
                return '37149' if args[-2:]==['tcp:0','tcp:27042'] else ''
        for uncertain in (False,True):
            if uncertain:
                calls=[]
                def root():
                    calls.append(1)
                    if len(calls)>1:raise RuntimeError('PRIVATE TOKEN')
                    return good()
                summary=b.run(root)
            else:summary=b.run(good)
            gadget={'stage':summary['status'],'batch':summary,'uikit_root':{} if uncertain else good()}
            with tempfile.TemporaryDirectory() as temp:
                folder=Path(temp)/'test-apks';folder.mkdir()
                with patch.object(d,'bundle_token',return_value='a'*64),patch.object(d,'preflight',return_value=('PRIVATE1','PRIVATE2')),patch.object(d,'recheck'):
                    result,path=d.diagnose(Adb(),folder,inspector=lambda *a:gadget,batch_probe=True)
                self.assertEqual(path.name,'rootless-profile-batch-0.3.26.json')
                self.assertEqual(result['mode'],'uikit-search-ten-profiles')
                self.assertEqual(result['profile_may_remain_open'],uncertain)
                self.assertTrue(result['ui_actions_attempted'])
                self.assertEqual(result['messages_sent'],0)
                for text in ('PRIVATE','a'*64,'user_id','identityKey'):self.assertNotIn(text,path.read_text())
    def test_rpc_failure_after_one_profile_is_not_masked_by_previous_success(self):
        f=BatchFake();original=f.create_script
        def create(*a,**kw):
            original(*a,**kw)
            def root():
                f.roots+=1
                if f.roots>1:raise RuntimeError('PRIVATE TOKEN')
                return good()
            f.exports_sync.root=root;return f
        f.create_script=create
        out=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,batch_probe=True)
        self.assertEqual(out['stage'],'batch-stopped');self.assertEqual(f.roots,2)
        self.assertEqual(out['uikit_root'],{});self.assertTrue(out['batch']['profile_may_remain_open'])
        self.assertEqual(out['batch']['checked'],1);self.assertNotIn('PRIVATE',json.dumps(out))
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_identity_change_is_checked_before_transferring_permanent_handles(self):
        self.assertLess(b.FUNCTION.index("identityKey!==batchCandidateKey"),b.FUNCTION.index('state.targetUser=own(selected.user)'))
