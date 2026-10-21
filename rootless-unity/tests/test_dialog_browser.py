import copy,json,unittest
import dialog_browser as b
from test_dialog_navigation import ready_route
WHO=dict(account='100',peer='200',chat='300')
TARGET=dict(WHO,chat='-1')


def raw_open():
    value=ready_route();n=value['navigation']
    for k in ('search_verified','dialogs_verified','return_verified','open_attempted','open_completed','back_attempted','back_completed'):n.pop(k)
    n.update(entry_verified=True,list_verified=True,chat_verified=True,destination_verified=True,action_attempted=True,action_completed=True,selection_verified=True,exhausted=False,private_identity=dict(WHO),metadata_checkpoint='ready',selection_checkpoint='verify-chat',rows_scanned=2,scan_batches=1)
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
        for text in ('OnCellDidClicked','OnBackButton','dialogSignature','cell-binding','get_DialogOpponent','permitted(again.who)','selectedChat','class_get_parent','for(let batch=0;batch<4'):
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

    def test_back_requires_exact_binding_and_has_no_cell_selection(self):
        for op,expected in [('back',None),('return',WHO),('open',WHO)]:
            with self.assertRaises(ValueError):b.build(op,expected=expected)
        b.build('back',expected=WHO)

if __name__=='__main__':unittest.main()
