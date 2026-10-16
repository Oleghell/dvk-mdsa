"""Regression: opening a new chat is NOT focusing its native message editor.

Synthetic transport only: no account, device, real chat or message is used.
"""
import unittest
from unittest.mock import patch
from mumu_bridge import BridgeError, GREETINGS, TOOLS, input_context_sha256
import test_session_bridge as helpers

class MessageFocusTests(unittest.TestCase):
    setUp = helpers.SessionBridgeTests.setUp
    tearDown = helpers.SessionBridgeTests.tearDown
    sha = helpers.SessionBridgeTests.sha
    authorize_online = helpers.SessionBridgeTests.authorize_online
    enter = helpers.SessionBridgeTests.enter

    def start_chat(self):
        self.ledger.start(4)
        self.assertTrue(self.enter()['eligible'])
        base = self.transport.inspect
        def inspect():
            result = base()
            for n in result['nodes']:
                if not self.transport.focused:
                    n['bounds'] = [216,1488,748,1544]
            return result
        self.transport.reader.inspect_layout = inspect

    def prepare(self, variant=0):
        return self.r.prepare_greeting(input_context_sha256(self.transport.frame),variant)

    def focus(self):
        return self.r.navigate('tap',self.sha(),400,1515)

    def assert_no_input(self, events, actions):
        self.assertEqual(self.transport.events,events)
        self.assertEqual(self.transport.reader.action_attempts,actions)
        s=self.ledger.status()
        self.assertEqual(s['input_attempts'],0)
        self.assertEqual(s['send_attempts'],0)
        self.assertFalse(s['manual_review_required'])
        self.assertEqual(s['current_step'],'empty_checked')

    def test_unfocused_field_refuses_before_reservation_with_clear_instruction(self):
        self.start_chat();events=list(self.transport.events);actions=self.transport.reader.action_attempts
        with self.assertRaisesRegex(BridgeError,'Сначала нажмите «Сообщение'):
            self.prepare()
        self.assert_no_input(events,actions)
        self.assertEqual(self.transport.native,'')

    def test_readonly_preflight_refusal_can_be_followed_by_first_real_input(self):
        self.start_chat()
        with self.assertRaises(BridgeError):self.prepare()
        self.focus();result=self.prepare()
        self.assertTrue(result['native_field_text_verified'])
        self.assertEqual(self.transport.native,'Привет')
        self.assertEqual(self.ledger.status()['input_attempts'],1)
        self.assertEqual([e[0] for e in self.transport.events][-2:],['tap','greeting'])
        self.assertEqual(self.ledger.status()['send_attempts'],0)

    def test_focus_only_does_not_type_or_send(self):
        self.start_chat();result=self.focus()
        self.assertTrue(result['input_injected'])
        self.assertFalse(result['ui_transition_verified'])
        self.assertTrue(self.transport.focused)
        self.assertEqual(self.transport.native,'')
        self.assertEqual(self.ledger.status()['input_attempts'],0)
        self.assertEqual(self.ledger.status()['send_attempts'],0)

    def test_failed_focus_tap_cannot_unlock_typing(self):
        self.start_chat()
        original=self.transport.reader._instrument
        def tap_without_focus(*args):
            result=original(*args);self.transport.focused=False;return result
        self.transport.reader._instrument=tap_without_focus
        self.focus()
        events=list(self.transport.events);actions=self.transport.reader.action_attempts
        with self.assertRaises(BridgeError):self.prepare()
        self.assert_no_input(events,actions)

    def test_wrong_focused_bounds_refuse_without_consuming_input(self):
        self.start_chat();self.focus();original=self.transport.reader.inspect_layout
        def wrong():
            d=original();d['nodes'][0]['bounds']=[152,1400,748,1456];return d
        with patch.object(self.transport.reader,'inspect_layout',side_effect=wrong):
            events=list(self.transport.events);actions=self.transport.reader.action_attempts
            with self.assertRaises(BridgeError):self.prepare()
            self.assert_no_input(events,actions)

    def test_changed_recipient_blocks_focus_and_input(self):
        self.start_chat();self.transport.person=2;self.transport.render()
        events=list(self.transport.events);actions=self.transport.reader.action_attempts
        with self.assertRaises(BridgeError):self.focus()
        with self.assertRaises(BridgeError):self.prepare()
        self.assert_no_input(events,actions)

    def test_existing_messages_invitation_missing_blocks_focus_and_input(self):
        self.start_chat();self.transport.mode='sent';self.transport.render()
        events=list(self.transport.events);actions=self.transport.reader.action_attempts
        with self.assertRaises(BridgeError):self.focus()
        with self.assertRaises(BridgeError):self.prepare()
        self.assert_no_input(events,actions)

    def test_draft_appearing_after_check_is_never_overwritten(self):
        self.start_chat();self.transport.native='Existing draft';self.transport.render()
        events=list(self.transport.events);actions=self.transport.reader.action_attempts
        with self.assertRaises(BridgeError):self.focus()
        with self.assertRaises(BridgeError):self.prepare()
        self.assert_no_input(events,actions)
        self.assertEqual(self.transport.native,'Existing draft')

    def test_invalid_layouts_block_both_focus_and_input(self):
        self.start_chat();original=self.transport.reader.inspect_layout
        def truncated(d):d['truncated']=True
        def stale(d):d['content_sha256']='0'*64
        def absent(d):d['nodes']=[]
        def multiple(d):d['nodes']*=2
        def disabled(d):d['nodes'][0]['enabled']=False
        def wrong_class(d):d['nodes'][0]['class']='android.widget.TextView'
        for modify in [truncated,stale,absent,multiple,disabled,wrong_class]:
            with self.subTest(case=modify.__name__):
                def inspect():
                    d=original();modify(d);return d
                with patch.object(self.transport.reader,'inspect_layout',side_effect=inspect):
                    events=list(self.transport.events);actions=self.transport.reader.action_attempts
                    with self.assertRaises(BridgeError):self.focus()
                    with self.assertRaises(BridgeError):self.prepare()
                    self.assert_no_input(events,actions)

    def test_focus_point_must_be_inside_native_editor(self):
        self.start_chat();events=list(self.transport.events);actions=self.transport.reader.action_attempts
        with self.assertRaises(BridgeError):self.r.navigate('tap',self.sha(),200,1515)
        self.assert_no_input(events,actions)

    def test_focus_disallows_plus_send_and_back(self):
        self.start_chat();events=list(self.transport.events);actions=self.transport.reader.action_attempts
        for action,x,y in [('tap',825,1515),('back',0,0),('tap',True,1515)]:
            with self.subTest(action=action,x=x),self.assertRaises(BridgeError):
                self.r.navigate(action,self.sha(),x,y)
        self.assert_no_input(events,actions)

    def test_stale_hash_blocks_focus_without_mutation(self):
        self.start_chat();events=list(self.transport.events);actions=self.transport.reader.action_attempts
        with self.assertRaises(BridgeError):self.r.navigate('tap','0'*64,400,1515)
        self.assert_no_input(events,actions)

    def test_stale_input_hash_blocks_before_reservation(self):
        self.start_chat();self.focus();events=list(self.transport.events);actions=self.transport.reader.action_attempts
        with self.assertRaises(BridgeError):self.r.prepare_greeting('0'*64,0)
        self.assert_no_input(events,actions)

    def test_lost_focus_blocks_before_reservation(self):
        self.start_chat();self.focus();self.transport.focused=False
        events=list(self.transport.events);actions=self.transport.reader.action_attempts
        with self.assertRaises(BridgeError):self.prepare()
        self.assert_no_input(events,actions)

    def test_native_refusal_stays_one_shot_not_reclassified_as_focus_preflight(self):
        self.start_chat();self.focus()
        with patch.object(self.transport.reader,'_instrument',return_value=('denied_field','')):
            with self.assertRaisesRegex(BridgeError,'Android отказал'):self.prepare()
        self.assertEqual(self.ledger.status()['input_attempts'],1)
        with self.assertRaises(BridgeError):self.prepare()
        self.assertEqual(self.ledger.status()['input_attempts'],1)

    def test_unknown_focus_result_stops_run(self):
        self.start_chat();self.transport.fail=True
        with self.assertRaises(BridgeError):self.focus()
        self.assertTrue(self.ledger.status()['manual_review_required'])
        self.assertEqual(self.ledger.status()['input_attempts'],0)
        with self.assertRaises(BridgeError):self.prepare()

    def test_tool_descriptions_make_focus_step_explicit(self):
        for name in ['mumu_navigate','mumu_prepare_greeting']:
            text=next(t['description'] for t in TOOLS if t['name']==name)
            self.assertIn('FIRST',text);self.assertIn('400,1515',text)
            self.assertIn('focused=true',text)

if __name__=='__main__':unittest.main()
