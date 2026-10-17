"""Candidate cursor-stable gesture protocol; no device, private data or sending."""
import base64
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from control_protocol import valid_call,native_request,args_allowed,COMPONENT,SERIAL
from universal_control import UniversalControl
from mumu_bridge import BridgeError
import test_universal_control as previous
from test_universal_control import gesture,SHA,ID

class EditorGuardProtocolTests(unittest.TestCase):
    def action(self,**kw):
        return gesture(editor_guard={'bounds':[118,196,786,276],'expected_text':'Нижнекамск'},**kw)
    def test_optional_explicit_guard_and_legacy_default(self):
        self.assertTrue(valid_call('mumu_control_gesture',self.action()))
        self.assertTrue(valid_call('mumu_control_gesture',gesture()))
    def test_guard_native_round_trip(self):
        req=native_request('mumu_control_gesture',self.action())
        raw=base64.b64encode(json.dumps(req).encode()).decode()
        self.assertTrue(args_allowed(['-s',SERIAL,'shell','am','instrument','-w','-r','-e','request_b64',raw,COMPONENT],True))
    def test_no_arbitrary_mask_or_large_rectangle(self):
        for bounds in ([0,48,900,1600],[118,196,786,500],[True,196,786,276],[0,0,500,80],[10,100,899,150]):
            a=self.action();a['editor_guard']['bounds']=bounds
            self.assertFalse(valid_call('mumu_control_gesture',a))
    def test_guard_malformed_or_missing_exact_text_rejected(self):
        for value in (None,{},[],{'bounds':[118,196,786,276]}, {'bounds':[118,196,786,276],'expected_text':None}, {'bounds':[118,196,786,276],'expected_text':'x','disable_guard':True}):
            a=self.action();a['editor_guard']=value
            self.assertFalse(valid_call('mumu_control_gesture',a))
    def test_only_gesture_supports_editor_guard(self):
        a={'action_id':ID,'expected_content_sha256':SHA,'key':'ENTER','editor_guard':self.action()['editor_guard']}
        self.assertFalse(valid_call('mumu_control_key',a))
    def test_any_app_coordinate_but_no_status_bar_or_outside_screen(self):
        for x,y in ((0,48),(899,1599),(320,403)):
            self.assertTrue(valid_call('mumu_control_gesture',self.action(x=x,y=y)))
        for x,y in ((0,47),(900,100),(10,1600)):
            self.assertFalse(valid_call('mumu_control_gesture',self.action(x=x,y=y)))
    def test_swipe_and_hold_preserve_their_validation(self):
        self.assertTrue(valid_call('mumu_control_gesture',self.action(action='hold',duration_ms=500)))
        self.assertTrue(valid_call('mumu_control_gesture',self.action(action='swipe',x2=500,y2=1000,duration_ms=400)))

# Reuse setup, not test inheritance: do not count existing tests twice.
class EditorGuardTransportTests(unittest.TestCase):
    setUp=previous.ControlJournalTests.setUp
    tearDown=previous.ControlJournalTests.tearDown
    def action(self):
        return gesture(expected_content_sha256=SHA,editor_guard={'bounds':[118,196,786,276],'expected_text':'Нижнекамск'})
    def inspect_value(self,**kw):
        return {'gesture_editor_guard_supported':True,'focused':True,'bounds':[118,196,786,276], 'text':'Нижнекамск','field_context_sha256':SHA,**kw}
    def test_candidate_capability_accepts_guarded_action(self):
        self.control.inspect=lambda:self.inspect_value()
        with patch.object(self.reader,'screen',side_effect=AssertionError('Unmasked image path must not be used')):
            d=self.control.execute('mumu_control_gesture',self.action())
        self.assertFalse(d['message_sent_verified']);self.assertEqual(self.calls[0]['editor_guard']['expected_text'],'Нижнекамск')
    def test_old_helper_refused_before_reservation_or_dispatch(self):
        self.control.inspect=lambda:self.inspect_value(gesture_editor_guard_supported=False)
        with self.assertRaisesRegex(BridgeError,'новая подписанная'):self.control.execute('mumu_control_gesture',self.action())
        self.assertEqual(self.calls,[])
        self.assertEqual(self.ledger.db.execute('SELECT COUNT(*) FROM control_actions').fetchone()[0],0)
    def test_missing_capability_never_falls_back_to_unguarded_action(self):
        d=self.inspect_value();d.pop('gesture_editor_guard_supported');self.control.inspect=lambda:d
        with self.assertRaises(BridgeError):self.control.execute('mumu_control_gesture',self.action())
        self.assertEqual(self.calls,[])
    def test_changed_text_bounds_focus_or_context_refuses(self):
        for change in ({'text':'другой текст'},{'bounds':[120,196,786,276]},{'focused':False},{'field_context_sha256':'c'*64}):
            self.control.inspect=lambda change=change:self.inspect_value(**change)
            with self.assertRaises(BridgeError):self.control.execute('mumu_control_gesture',self.action())
        self.assertEqual(self.calls,[])
    def test_unknown_outcome_still_persistently_stops(self):
        self.control.inspect=lambda:self.inspect_value();self.state='timeout'
        with self.assertRaises(BridgeError):self.control.execute('mumu_control_gesture',self.action())
        self.assertTrue(self.ledger.status()['manual_review_required'])
    def test_native_refusal_does_not_retry(self):
        self.control.inspect=lambda:self.inspect_value();self.state='denied_screen_changed'
        with self.assertRaises(BridgeError):self.control.execute('mumu_control_gesture',self.action())
        self.assertEqual(len(self.calls),1);self.assertFalse(self.reader.action_uncertain)

class CandidateSourceTests(unittest.TestCase):
    def test_candidate_keeps_native_editor_and_outside_pixels_guard(self):
        p=Path(__file__).resolve().parents[1]/'control-android-next/src/com/dvk/control/ControlInstrumentation.java'
        s=p.read_text(encoding='utf-8')
        self.assertIn('Rect mask=gestureEditor(guard)',s)
        self.assertIn('expected.equals(current.sha)',s)
        self.assertIn('ScreenSnapshot current=snapshot(mask)',s)
        self.assertIn('check<2',s)
        self.assertIn('actual.width()>800 || actual.height()>160',s)
        self.assertIn('!text.equals(value(n))',s)
        self.assertIn('if("key".equals(op)){done("denied_arguments",null);return;}',s)
        self.assertIn('else if(!expected.equals(hash(null)) || !expected.equals(hash(null)))',s)
        self.assertIn('n.isPassword()',s)
        self.assertIn('"drug.vokrug".contentEquals',s)
    def test_candidate_is_not_substituted_for_pinned_release(self):
        r=Path(__file__).resolve().parents[1]
        legacy=(r/'control-android/src/com/dvk/control/ControlInstrumentation.java').read_text(encoding='utf-8')
        self.assertNotIn('gesture_editor_guard_supported',legacy)

if __name__=='__main__':unittest.main()
