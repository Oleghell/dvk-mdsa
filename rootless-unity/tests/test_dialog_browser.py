import copy,json,unittest
import dialog_browser as b
from test_dialog_navigation import ready_route
WHO=dict(account='100',peer='200',chat='300')
TARGET=dict(WHO,chat='-1')


def raw_open():
    value=ready_route();n=value['navigation']
    for k in ('search_verified','dialogs_verified','return_verified','open_attempted','open_completed','back_attempted','back_completed'):n.pop(k)
    n.update(entry_verified=True,list_verified=True,chat_verified=True,destination_verified=True,action_attempted=True,action_completed=True,selection_verified=True,exhausted=False,private_identity=dict(WHO),metadata_checkpoint='ready',selection_checkpoint='verify-chat',rows_scanned=2,scan_batches=1,unread_filter_applied=False,unread_verified=False,read_rows_skipped=0,back_budget_retries=0,observation_budget_retries=0,entry_read_budget_retries=0,entry_search_recovered=False,reply_filter_applied=False,reply_needed_verified=False,waiting_rows_skipped=0,handled_rows_skipped=0,profile_closed=False)
    n['controller_path']=['chat'];n['root_top_kind']='chat'
    return value


class BrowserSchema(unittest.TestCase):
    def test_only_tracked_binding_leaves_private_transport(self):
        v=raw_open();r=b.validate(v,'open',allowed=[TARGET])
        self.assertEqual(r['identity'],WHO);self.assertEqual(r['state'],'opened')
        self.assertNotIn('100',json.dumps(r['diagnostic']))
        self.assertEqual(v['navigation']['private_identity'],WHO)

    def test_untracked_wrong_account_and_wrong_positive_chat_rejected(self):
        for target in (dict(TARGET,peer='201'),dict(TARGET,account='101'),dict(TARGET,chat='301')):
            with self.assertRaises(ValueError):b.validate(raw_open(),'open',allowed=[target])

    def test_no_extras_or_missing_destination_evidence(self):
        for change in (lambda n:n.update(text='PRIVATE'),lambda n:n.update(chat_verified=False),lambda n:n.update(selection_verified=False),lambda n:n.update(ui_text_read=True),lambda n:n.update(handles_released=0),lambda n:n.update(metadata_checkpoint='PRIVATE'),lambda n:n.update(rows_scanned=129)):
            v=raw_open();change(v['navigation'])
            with self.assertRaises(ValueError):b.validate(v,'open',allowed=[TARGET])

    def test_exhaustion_never_claims_whole_inbox_or_private_binding(self):
        v=raw_open();v['navigation'].update(exhausted=True,selection_verified=False,chat_verified=False,private_identity=None,selection_checkpoint='exhausted')
        r=b.validate(v,'open',allowed=[TARGET]);self.assertEqual(r['state'],'exhausted');self.assertIsNone(r['identity'])
        v['navigation']['private_identity']=WHO
        with self.assertRaises(ValueError):b.validate(v,'open',allowed=[TARGET])

    def test_journal_inputs_are_strict_bounded_decimal_literals(self):
        for values in ([dict(TARGET,peer='200;evil()')],[dict(TARGET,chat='-9223372036854775809')],[dict(TARGET,account='200')],[TARGET,TARGET],[TARGET]*1001):
            with self.assertRaises(ValueError):b.build('open',allowed=values)
        b.build('open',allowed=[dict(TARGET,account='9007199254740993',peer='9007199254740994',chat='9223372036854775807')])

    def test_fixed_actions_and_no_body_read_send_or_scroll(self):
        s=b.build('open',allowed=[TARGET])
        for text in ('OnCellDidClicked','OnBackButton','dialogSignature','cell-binding','get_DialogOpponent','permitted(again.who)','selectedChat','class_get_parent','for(let batch=0;batch<(needsReplyOnly?2:4)'):
            self.assertIn(text,s)
        for text in ('OnSend','get_Text','get_Name','set_Text','ShowChat','input tap','scrollTo','Memory.scan','il2cpp_field_', 'rpc.exports'):
            self.assertNotIn(text,s)
        self.assertLess(s.index('if(!permitted(model.who))'),s.index('call(s.openCell,current,args)'))
        self.assertIn('if(!bound.chat.equals(target(state.selectedChat))',s)

    def test_stability_guards_all_have_body_free_fixed_categories(self):
        source=b.build('open',allowed=[TARGET])
        for error in b.SELECTION_ERRORS:
            self.assertIn("fail('"+error+"')",source)
        self.assertNotIn("fail('selection-changed')",source)
        self.assertLess(source.index("fail('selection-chat-changed')"),source.index('call(s.openCell,current,args)'))
        self.assertLess(source.index("fail('selection-detached')"),source.index('call(s.openCell,current,args)'))
        self.assertIn('const stableList=(table,count,index,cell)=>{',source)
        self.assertIn('stableList(table,count,state.scanIndex,cell);',source)
        self.assertIn('stableList(table,count,null,null);',source)
        self.assertNotIn("if(!call(s.visible,table).equals(list))fail('selection-list-changed');",source)

    def test_traversal_handles_are_scoped_without_relaxing_live_limit(self):
        source=b.build('open',allowed=[TARGET])
        for text in ('const scope=(body,retainResult=false)=>{',
                     'const current=scope(()=>resolve(candidate),true);',
                     'scope(()=>checkView(current))',
                     'scope(()=>resolve(candidate).equals(current))',
                     'if(retained!==null)held.push(retained);',
                     "if(held.length>=64)fail('handle-limit')"):
            self.assertIn(text,source)
        self.assertNotIn('if(!checkView(current))',source)
        self.assertNotIn('if(!resolve(candidate).equals(current))',source)

    def test_unread_filter_requires_evidence_and_rechecks_before_open(self):
        source=b.build('open',allowed=[TARGET],unread_only=True)
        self.assertIn('unreadOnly=true',source)
        self.assertIn("s.unreadCount=checked(s.chatModel,'get_UnreadCount',8)",source)
        self.assertIn("if(unreadOnly&&unread===0){n.read_rows_skipped++;return false;}",source)
        first=source.index('unread=unreadCount(chat)')
        again=source.index('if(unreadCount(chat)!==unread)')
        self.assertLess(first,source.index("fail('selection-chat-changed')"))
        self.assertGreater(again,source.index("fail('selection-detached')"))
        self.assertLess(again,source.index('call(s.openCell,current,args)'))
        self.assertNotIn('get_UnreadUnmutedChatsCount',source)
        for option in (None,1,'true'):
            with self.assertRaises(ValueError):b.build('open',allowed=[TARGET],unread_only=option)
        for operation in ('back','return'):
            with self.assertRaises(ValueError):b.build(operation,expected=WHO if operation=='back' else None,unread_only=True)
        with self.assertRaises(ValueError):b.validate(raw_open(),'open',allowed=[TARGET],unread_only=True)
        value=raw_open();value['navigation'].update(unread_filter_applied=True,unread_verified=True,read_rows_skipped=1)
        result=b.validate(value,'open',allowed=[TARGET],unread_only=True)
        self.assertTrue(result['diagnostic']['unread_verified'])
        self.assertEqual(result['diagnostic']['read_rows_skipped'],1)
        with self.assertRaises(ValueError):b.validate(value,'open',allowed=[TARGET])
        for field,bad in [('unread_filter_applied',False),('unread_verified',False),('read_rows_skipped',3),('read_rows_skipped',True)]:
            value=raw_open();value['navigation'].update(unread_filter_applied=True,unread_verified=True,read_rows_skipped=1)
            value['navigation'][field]=bad
            with self.assertRaises(ValueError):b.validate(value,'open',allowed=[TARGET],unread_only=True)

    def test_unread_exhaustion_requires_filter_but_no_selected_chat(self):
        value=raw_open();value['navigation'].update(exhausted=True,selection_verified=False,chat_verified=False,private_identity=None,
            selection_checkpoint='exhausted',unread_filter_applied=True,unread_verified=False,read_rows_skipped=2)
        out=b.validate(value,'open',allowed=[TARGET],unread_only=True)
        self.assertEqual(out['state'],'exhausted')
        value['navigation']['unread_verified']=True
        with self.assertRaises(ValueError):b.validate(value,'open',allowed=[TARGET],unread_only=True)

    def test_dialog_list_verification_never_selects_or_exposes_a_chat(self):
        for acted in (False, True):
            value = raw_open()
            n = value['navigation']
            n.update(chat_verified=False, private_identity=None, selection_verified=False,
                     rows_scanned=0, scan_batches=0, selection_checkpoint='not-checked',
                     action_attempted=acted, action_completed=acted,
                     root_top_kind='dialogs', controller_path=['dialogs'])
            result = b.validate(value, 'list')
            self.assertEqual(result['state'], 'dialogs-ready')
            self.assertIsNone(result['identity'])
            for field, bad in (('rows_scanned', 1), ('scan_batches', 1),
                               ('chat_verified', True), ('list_verified', False),
                               ('private_identity', WHO), ('selection_verified', True)):
                invalid = copy.deepcopy(value)
                invalid['navigation'][field] = bad
                with self.assertRaises(ValueError):
                    b.validate(invalid, 'list')
        for entry in ('search', 'dialogs', 'either'):
            source = b.build('list', entry=entry)
            self.assertIn("if(operation==='list'&&k==='dialogs')", source)
            self.assertIn("if(operation!=='open'){finish();return;}", source)
            # The bounded Esc press: a stuck profile card is closed once via the
            # verified handler, then the navigation continues to the list.
            self.assertIn("if(operation==='list'&&k==='profile')", source)
            self.assertIn("call(s.closeProfile,current)", source)
        with self.assertRaises(ValueError):
            b.build('open', allowed=[TARGET], entry='either')
        for options in ({'allowed': [TARGET]}, {'expected': WHO}, {'unread_only': True}):
            with self.assertRaises(ValueError):
                b.build('list', **options)

    def test_back_requires_exact_binding_and_has_no_cell_selection(self):
        for op,expected in [('back',None),('return',WHO),('open',WHO)]:
            with self.assertRaises(ValueError):b.build(op,expected=expected)
        b.build('back',expected=WHO)

if __name__=='__main__':unittest.main()


class BackBudgetRecovery(unittest.TestCase):
    def test_retry_is_only_after_completed_bound_back_and_remains_observation(self):
        source=b.build('back',expected=WHO)
        self.assertIn("e==='frame-budget'&&operation==='back'&&n.phase==='wait-back'",source)
        self.assertIn('same(n.private_identity,expectedIdentity)&&state.stop===null',source)
        self.assertIn('!fixedCancellationRequested&&!n.cleanup_failed&&n.back_budget_retries<3',source)
        self.assertIn('n.back_budget_retries++;return;',source)
        self.assertEqual(source.count('call(s.closeChat,current)'),2)  # mutually exclusive explicit back / startup list
        wait=source.split("if(n.phase==='wait-back'){")[1].split('if(n.phase===')[0]
        self.assertNotIn('call(s.closeChat',wait)
        self.assertIn("if(k!=='dialogs')fail('unexpected-screen')",wait)
        self.assertIn("operation==='list'?state.startupReturnIdentity:expectedIdentity",wait)
        self.assertIn('const deadline=Date.now()+100',source)
        self.assertIn('r.navigation.frames>=180',source)

    def test_recovery_evidence_rejected_for_open_or_uncompleted_back(self):
        v=raw_open();v['navigation']['back_budget_retries']=1
        with self.assertRaises(ValueError):b.validate(v,'open',allowed=[TARGET])
        for bad in (-1,4,True,'1'):
            v=raw_open();v['navigation']['back_budget_retries']=bad
            with self.assertRaises(ValueError):b.validate(v,'open',allowed=[TARGET])

    def test_diagnostic_counter_is_optional_for_legacy_and_bounded(self):
        from assistant_navigation_check import safe_diagnostic
        diagnostic=b.validate(raw_open(),'open',allowed=[TARGET])['diagnostic']
        safe_diagnostic(diagnostic)
        diagnostic.pop('back_budget_retries');safe_diagnostic(diagnostic)
        for bad in (-1,4,True,'1'):
            with self.assertRaises(ValueError):safe_diagnostic(dict(diagnostic,back_budget_retries=bad))
        for change in (dict(phase='entry'),dict(action_completed=False)):
            with self.assertRaises(ValueError):safe_diagnostic(dict(diagnostic,back_budget_retries=1,**change))


class StartupChatReturn(unittest.TestCase):
 def test_list_recovery_has_double_binding_no_body_and_one_action(self):
  source=b.build('list',entry='either')
  part=source.split("if(operation==='list'&&entryScreen==='either'&&k==='chat'){")[1].split("if(operation==='open'&&entryScreen==='dialogs'&&k==='search'){")[0]
  self.assertEqual(part.count('currentIdentity(current)'),2)
  self.assertIn('resolve(candidate).equals(current)',part)
  self.assertIn('same(currentIdentity(current).who,bound.who)',part)
  self.assertEqual(part.count('call(s.closeChat,current)'),1)
  self.assertIn("n.phase='wait-back';return;",part)
  self.assertNotIn('private_identity=',part)
  self.assertNotIn('message',part)
  self.assertIn("k!=='search'&&k!=='dialogs'",source)
