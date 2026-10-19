import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uikit_profile_navigation as p
import diagnose_device as d
from test_uikit_navigation import ready_navigation
from test_diagnose_device import FakeFrida
from test_uikit_root import ready_uikit


def ready_profile():
    value=ready_navigation();n=value['navigation']
    for old,new in [('filters_verified','profile_verified'),('cancel_attempted','close_attempted'),('cancel_completed','close_completed')]:n[new]=n.pop(old)
    n['selection_counts']=dict.fromkeys(p.SELECTION_COUNTERS,0);n['selection_counts'].update(passes=1,rows=1,cells=1)
    n.update(temporary_handles_peak=20,selection_check='selected',selection_retries=0,metadata_checkpoint='ready',selection_status='selected',target_user_verified=True,profile_content_verified=True)
    return value

class ProfileFake(FakeFrida):
    def create_script(self,source,name):
        super().create_script(source,name);self.script_name=name
        self.exports_sync.native=ready_uikit;self.exports_sync.root=ready_profile;self.exports_sync.cancel=lambda:None
        return self

class ProfileSchema(unittest.TestCase):
    def test_valid(self):p.validate(ready_profile())
    def test_required_identity_and_selection(self):
        for k,v in [('profile_content_verified',False),('target_user_verified',False),('selection_status','no-eligible-cell')]:
            x=ready_profile();x['navigation'][k]=v
            with self.assertRaises(ValueError):p.validate(x)
    def test_no_mixed_old_report_or_private_fields(self):
        for k,v in [('filters_verified',True),('user_id','private'),('selection_status','Private name'),('phase','wait-filters'),('last_presented_kind','filters')]:
            x=ready_profile();x['navigation'][k]=v
            with self.assertRaises(ValueError):p.validate(x)
    def test_fixed_selection_errors(self):
        for error in ('selection-limit','selection-changed'):
            x=ready_profile();x['navigation'].update(stage='navigation-stopped',error=error);p.validate(x)
    def test_source_without_sensitive_or_generic_actions(self):
        for name in ('get_Text','get_Name','get_Id','get_Profile','set_Text','OnFriendButtonClick','OnYouSuperPressed','SendMessage','input tap','NativeCallback','Interceptor.replace','Memory.scan','OnTouchesEnded','rpc.exports'):
            self.assertNotIn(name,p.FUNCTION)
        for name in ('get_VisibleCells','IsPromoEntry','get_IsCurrentUser','get_CurrentProfileController','get_Subviews','get_Entry','get_AvatarView','OnUserSelected','OnCloseRequested','class_get_nested_types','selected.entry,promotion,selected.avatar'):
            self.assertIn(name,p.FUNCTION)
    def test_no_guessed_offsets_and_closed_receiver_types(self):
        self.assertNotIn('.add(0x',p.FUNCTION)
        self.assertIn('params.writePointer(index)',p.FUNCTION) # inherited typed modal index
        self.assertIn('args([entry])',p.FUNCTION)
        self.assertIn('member<0',p.FUNCTION)
        self.assertIn('f.objectClass(table).equals(s.searchTable)',p.FUNCTION)
        self.assertIn('f.objectClass(content).equals(s.content)',p.FUNCTION)
        self.assertIn('content.equals(target(state.content))',p.FUNCTION)
        self.assertIn('user.equals(target(state.targetUser))',p.FUNCTION)
    def test_keep_proven_cancellation_and_release_guards(self):
        for name in ('frameBusy','pendingFinish','fixedCancellationRequested',"['content','targetUser','card','origin']",'heldByObject',"f.keep(obj,1)"):
            self.assertIn(name,p.FUNCTION)

    def test_ref_returns_only_for_two_typed_indexers(self):
        self.assertEqual(p.FUNCTION.count('false,true,true);'),2)
        self.assertIn('byref&&!(allowReferenceReturn&&kind===18&&result!==null&&!f.isValueType(result))',p.FUNCTION)
        self.assertIn('!!f.byref(f.returnType(m))!==!!entry.byref',p.FUNCTION)
        self.assertIn("if(entry.byref&&!out.isNull()&&!f.assignable(entry.result,f.objectClass(out)))",p.FUNCTION)
        self.assertNotIn('out.readPointer()',p.FUNCTION)
    def test_metadata_checkpoint_closed(self):
        for v in ('private-user',None,123):
            x=ready_profile();x['navigation']['metadata_checkpoint']=v
            with self.assertRaises(ValueError):p.validate(x)

    def test_promotion_checked_before_membership_and_again_before_open(self):
        source=p.TICK
        self.assertLess(source.index("if(promoted(record,entry)){n.selection_counts.promoted++"),source.index('call(s.recordEntries,record)'))
        self.assertIn("promotion-stability';if(promoted(record,entry))",source)
        self.assertIn("n.phase==='search'&&!n.open_attempted&&n.selection_retries<2",p.FUNCTION)
    def test_selection_report_is_closed_and_bounded(self):
        for k,v in [('selection_check','private-user'),('selection_retries',True),('selection_retries',3),('selection_retries',-1),('temporary_handles_peak',65),('temporary_handles_peak',True),('temporary_handles_peak',-1),('handles_acquired',None),('handles_acquired',0)]:
            x=ready_profile();x['navigation'][k]=v
            with self.assertRaises(ValueError):p.validate(x)

    def test_scopes_transfer_pinned_handles_and_keep_limit(self):
        for fragment in ('scopes[scopes.length-1].push({key,h})','held.length>=64||n.handles_acquired>=180*64',
                         "heldByObject.delete(key)","if(broken)fail('cleanup-failed')",'return escaping({entry,user,avatar})',
                         'const attached=(view,required,needsInteraction=true)=>scoped','const childViews=view=>scoped',
                         'const selected=scoped','const candidate=scoped','visited+queue.length+children.length>16'):
            self.assertIn(fragment,p.FUNCTION)
        self.assertNotIn('held.length>=128',p.FUNCTION)

    def test_selection_counter_schema_and_limits(self):
        for key in p.SELECTION_COUNTERS:
            for invalid in (-1,True,1.5,p.SELECTION_COUNTERS[key]+1):
                value=ready_profile();value['navigation']['selection_counts'][key]=invalid
                with self.assertRaises(ValueError):p.validate(value)
        for mutation in ('extra','missing','inconsistent','skips','exhausted-after-open'):
            value=ready_profile();n=value['navigation'];c=n['selection_counts']
            if mutation=='extra':c['private-name']=1
            elif mutation=='missing':c.pop('passes')
            elif mutation=='inconsistent':c['rows']=25
            elif mutation=='skips':c.update(user_missing=1,self_user=1)
            else:n['error']='selection-unavailable';c['passes']=3
            with self.assertRaises(ValueError):p.validate(value)
    def test_avatar_anchor_need_not_receive_clicks(self):
        self.assertIn('attached(avatar,cell,false)',p.FUNCTION)
        self.assertIn('if(needsInteraction)return false',p.FUNCTION)
        self.assertIn('avatar_hidden++',p.FUNCTION)
        self.assertIn("if(!call(s.avatarUser,avatar).equals(user))fail('selection-changed')",p.FUNCTION)
    def test_one_row_per_frame_and_no_cross_frame_object_pointer(self):
        self.assertIn('Math.min(count,rowIndex+1)',p.FUNCTION)
        self.assertIn('selectionRow:0',p.FUNCTION)
        self.assertIn('state.selectionRow=i+1',p.FUNCTION)

    def test_selection_pass_budget_is_separate_from_call_limit(self):
        self.assertIn("if(n.selection_counts.passes>=3)fail('selection-unavailable')",p.FUNCTION)
        self.assertIn("n.managed_calls>=6000",p.FUNCTION)
        self.assertEqual(p.MAX_SELECTION_PASSES,3)

class ProfileTransport(unittest.TestCase):
    def test_fixed_profile_script_and_cleanup(self):
        f=ProfileFake();result=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,profile_probe=True)
        self.assertEqual(result['stage'],'navigation-ready');self.assertTrue(result['rpc_root_ok'])
        self.assertEqual(f.script_name,'dvk-uikit-profile-navigation-0.3.6')
        self.assertIn('rpc.exports.cancel',f.script_source);self.assertNotIn('rpc.exports.click',f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_no_retry_after_possible_profile_action(self):
        f=ProfileFake();original=f.create_script
        def create(*a,**kw):
            original(*a,**kw)
            def bad():raise RuntimeError('PRIVATE')
            f.exports_sync.root=bad;return f
        f.create_script=create
        result=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,profile_probe=True)
        self.assertEqual(result['attempts'],1);self.assertFalse(result['rpc_root_ok']);self.assertNotIn('PRIVATE',json.dumps(result))
    def test_version_filename_warning_and_protected_device(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):
                assert args[:2]==['-s','127.0.0.1:5563']
                return '37149' if args[-2:]==['tcp:0','tcp:27042'] else ''
        for success,unknown in ((True,False),(False,False),(False,True)):
            value=ready_profile()
            if not success:value['navigation'].update(stage='navigation-stopped',error='frame-limit',return_verified=False)
            gadget={'stage':'uikit-root-rpc'} if unknown else {'stage':'navigation-ready' if success else 'navigation-stopped','uikit_root':value}
            with tempfile.TemporaryDirectory() as temp:
                folder=Path(temp)/'test-apks';folder.mkdir();old=folder.parent/'rootless-navigation-0.2.3.json';old.write_text('keep')
                with patch.object(d,'bundle_token',return_value='a'*64),patch.object(d,'preflight',return_value=('PRIVATE1','PRIVATE2')),patch.object(d,'recheck'):
                    result,path=d.diagnose(Adb(),folder,inspector=lambda *a:gadget,profile_probe=True)
                self.assertEqual(path.name,'rootless-profile-navigation-0.3.6.json');self.assertEqual(old.read_text(),'keep')
                self.assertEqual(result['mode'],'uikit-search-profile-return');self.assertEqual(result['profile_may_remain_open'],not success)
                self.assertNotIn('filters_may_remain_open',result)
                self.assertEqual(result['target'],'127.0.0.1:5563');self.assertEqual(result['working_instance'],'127.0.0.1:5555')
                for k in ('working_device_modified','app_installation_modified','root_used','ocr_used','ui_text_read'):self.assertFalse(result[k])
                self.assertEqual(result['messages_sent'],0)
                if unknown:self.assertIsNone(result['ui_actions_attempted']);self.assertIsNone(result['ui_actions_performed'])
                self.assertNotIn('PRIVATE',path.read_text());self.assertNotIn('a'*64,path.read_text())
