"""Finite business journal remains shared with the compatibility workflow."""
from pathlib import Path
from types import SimpleNamespace
import tempfile,unittest
from unittest.mock import Mock
from ui_workflow import UIWorkflow
from ui_model import UIError,UnsupportedUI,ElementNotFound
from test_ui_runtime import tree,node
from test_session import TestSession,SessionError
from universal_control import UniversalControl

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.ledger=TestSession(self.root/'run.sqlite');self.ledger.start(5)
        self.reader=SimpleNamespace(control_enabled=True,action_attempts=0,action_uncertain=False,screen=Mock())
        self.supervised=SimpleNamespace(inner=self.reader,ledger=self.ledger,online_confirmed=False,_run_ready=self.ready)
        self.workflow=UIWorkflow(self.supervised);self.backend=self.workflow.backend
        self.backend.snapshot=Mock(return_value=tree([node(description='Открыть чат',clickable=True)]))
        self.calls=[];self.native_state='input_injected'
        def perform(element,op,**args):
            self.assertEqual(self.ledger.db.execute('SELECT state FROM control_actions').fetchone()[0],'reserved')
            self.calls.append((element.query,op,args))
            if self.native_state=='timeout':raise UIError('unknown')
            return self.native_state,{}
        self.backend.perform=perform
    def ready(self):
        self.ledger._no_hold();self.ledger._active()
        if self.reader.action_attempts>=50 or self.reader.action_uncertain:raise UnsupportedUI('Stop')
    def tearDown(self):self.ledger.close();self.tmp.cleanup()
    def action(self,kind='open_chat',ident='b'*32,**extra):
        return self.workflow.action_call(dict(action=kind,action_id=ident,target='',city_index=-1,allow_fallback=False)|extra)
    def test_counted_profile_before_open_chat_and_no_screenshot(self):
        self.ledger.begin_visit();result=self.action()
        self.assertFalse(result['message_sent']);self.assertEqual(self.ledger.status()['visited'],1)
        self.assertEqual(self.ledger.status()['current_step'],'chat_opening');self.reader.screen.assert_not_called()
        with self.assertRaises(UnsupportedUI):self.action(ident='c'*32)
        self.assertEqual(len(self.calls),1)
    def test_cannot_open_uncounted_or_skipped_profile(self):
        with self.assertRaises(SessionError):self.action()
        self.ledger.begin_visit();self.ledger.skip()
        with self.assertRaises(SessionError):self.action()
        self.assertEqual(self.calls,[])
    def test_unknown_holds_shared_journal_across_restart(self):
        self.ledger.begin_visit();self.native_state='timeout'
        with self.assertRaises(UIError):self.action()
        self.assertTrue(self.reader.action_uncertain);self.assertEqual(self.ledger.status()['state'],'stopped')
        self.ledger.close();self.ledger=TestSession(self.root/'run.sqlite');self.assertTrue(self.ledger.status()['manual_review_required'])
    def test_known_stale_refusal_consumes_receipt_not_retry(self):
        self.ledger.begin_visit();self.native_state='denied_screen_changed'
        with self.assertRaises(UIError):self.action()
        self.assertFalse(self.reader.action_uncertain);self.assertFalse(self.ledger.status()['manual_review_required'])
        with self.assertRaises(UnsupportedUI):self.action(ident='c'*32)
        self.assertEqual(len(self.calls),1)
    def test_compatibility_and_modern_open_chat_share_attempt_key(self):
        self.ledger.begin_visit();visit=self.ledger.current()
        self.ledger.db.execute('INSERT INTO control_config VALUES (?,?)',('semantic-profile:'+visit['id'],'a'*64))
        with self.assertRaises(UnsupportedUI):self.action()
        self.assertEqual(self.calls,[])
    def test_search_cannot_change_during_profile(self):
        self.ledger.begin_visit()
        with self.assertRaises(UnsupportedUI):self.action('open_city')
        self.assertEqual(self.calls,[])
    def test_generic_field_does_not_authorize_city_query(self):
        self.backend.snapshot.return_value=tree([node(class_name='android.widget.EditText',editable=True)])
        with self.assertRaises(UnsupportedUI):self.action('input_city',city_index=0)
        self.assertEqual(self.calls,[])
    def test_city_settext_uses_shared_city_journal(self):
        self.backend.snapshot.return_value=tree([node(text='Поиск города'),node(1,class_name='android.widget.EditText',editable=True)])
        self.native_state='text_verified';result=self.action('input_city',city_index=0)
        self.assertEqual(self.calls[0][1],'set_text');self.assertEqual(self.calls[0][2]['text'],'Нальчик')
        self.assertEqual(self.ledger.db.execute('SELECT state FROM city_actions').fetchone()[0],'verified')
        with self.assertRaises(SessionError):self.action('input_city',ident='c'*32,city_index=0)
        self.assertEqual(len(self.calls),1)
    def test_online_label_without_native_checkable_does_not_authorize(self):
        self.backend.snapshot.return_value=tree([node(text='Только онлайн')])
        with self.assertRaises(ElementNotFound):self.action('enable_online')
        self.assertEqual(self.calls,[])
    def test_already_checked_online_is_idempotent_no_action(self):
        self.backend.snapshot.return_value=tree([node(text='Только онлайн',checkable=True,checked=True)])
        result=self.action('enable_online');self.assertTrue(result['already_enabled']);self.assertEqual(self.calls,[])
    def test_no_open_profile_without_confirmed_filter_and_grid(self):
        args=dict(action='open_profile',action_id='b'*32,target='Profile',city_index=-1,allow_fallback=False)
        with self.assertRaises(UnsupportedUI):self.workflow.action_call(args)
        self.assertEqual(self.ledger.status()['visited'],0)
    def test_shared_action_cap(self):
        self.ledger.begin_visit();self.reader.action_attempts=50
        with self.assertRaises(UnsupportedUI):self.action()
        self.assertEqual(self.calls,[])
    def test_no_public_generic_mutation_selector(self):
        args=dict(action='send',action_id='b'*32,target='',city_index=-1,allow_fallback=False)
        with self.assertRaises(UIError):self.workflow.action_call(args)
        self.assertEqual(self.calls,[])

    def test_wrong_native_ack_is_unknown_not_success(self):
        self.ledger.begin_visit();self.native_state='text_verified'
        with self.assertRaises(UIError):self.action()
        self.assertTrue(self.ledger.status()['manual_review_required'])
