"""Autotests use synthetic frames/ADB doubles only, never a user's emulator."""
import base64
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from city_autotest import (FOCUS_POINTS, observe_city, run_city_diagnostics,
                           save_diagnostic_report)
from city_field import CITY_EDITOR_BOUNDS
from city_release import CITY_CATALOG
from city_transport import CityInspectionError, city_context_sha256
from limited_scenario import CITIES
from mumu_bridge import AdbReader, BridgeError
from session_bridge import SupervisedReader
from test_session import TestSession, SessionError
from test_city_field import frame

class AutoCityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        (self.path/'adb.exe').touch();self.reader=AdbReader(self.path/'adb.exe')
        self.reader.helper_ready=True;self.reader.city_helper_ready=True
        self.png=frame();self.query=CITIES[0];self.focused=False;self.events=[]
        self.focus_on=1;self.native_refusal=None;self.tap_refusal=None;self.change_query=False
        self.change_context=False;self.after_read_failure=False
        self.reader.screen=lambda:self.png;self.reader._foreground=lambda:None
        self.reader._run=self.native_read;self.reader._instrument=self.native_tap
        self.db=TestSession(self.path/'run.sqlite');self.facade=SupervisedReader(self.reader,self.db)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def native_read(self,args):
        self.assertEqual(args[9],'inspect_city')
        if self.after_read_failure and self.events:raise BridgeError('private-secret-ADB-output')
        if self.native_refusal:
            code=self.native_refusal
            return ('INSTRUMENTATION_RESULT: navigation_status=denied_context_or_layout\nINSTRUMENTATION_RESULT: city_diagnostic_code='+code+'\nINSTRUMENTATION_RESULT: city_diagnostic_phase=startup\nINSTRUMENTATION_RESULT: actual_editor_bounds=118,197,786,277\n').encode()
        d={'catalog':CITY_CATALOG,'query':self.query,'focused':self.focused,
           'bounds':list(CITY_EDITOR_BOUNDS),'city_context_sha256':city_context_sha256(self.png),
           'result_rows_available':False,'city_selected':False,'filters_applied':False}
        return ('INSTRUMENTATION_RESULT: navigation_status=city_inspection_ok\nINSTRUMENTATION_RESULT: layout_b64='+base64.b64encode(json.dumps(d).encode()).decode()+'\n').encode()
    def native_tap(self,op,sha,x,y):
        self.assertEqual(op,'tap');self.assertIn((x,y),FOCUS_POINTS)
        self.events.append((x,y))
        if self.tap_refusal=='unknown':raise BridgeError('Synthetic timeout')
        if self.tap_refusal:return (self.tap_refusal,'')
        if len(self.events)>=self.focus_on:self.focused=True
        if self.change_query:self.query=CITIES[1]
        if self.change_context:self.mutate(450,500)
        return ('input_injected','')
    def mutate(self,x,y):
        im=Image.open(BytesIO(self.png)).convert('RGB');im.putpixel((x,y),(255,0,0))
        buf=BytesIO();im.save(buf,'PNG');self.png=buf.getvalue()
    def autofocus(self):return self.facade.autofocus_city(city_context_sha256(self.png))
    def test_readonly_without_active_run_never_changes_journal_or_device(self):
        before=self.db.status();d=run_city_diagnostics(self.reader)
        self.assertTrue(d['passed']);self.assertEqual(len(d['samples']),3)
        self.assertEqual(d['device_actions'],0);self.assertEqual(self.events,[])
        self.assertEqual(self.db.status(),before);self.assertEqual(self.reader.action_attempts,0)
    def test_readonly_report_never_contains_query_text_images_or_raw_errors(self):
        self.query='PRIVATE SEARCH QUERY'
        d=run_city_diagnostics(self.reader);text=json.dumps(d)
        self.assertNotIn(self.query,text);self.assertNotIn('layout_b64',text)
        self.native_refusal='editor_bounds';d=run_city_diagnostics(self.reader)
        self.assertFalse(d['passed']);self.assertEqual(len(d['samples']),3)
        self.assertEqual(d['samples'][0]['diagnostic']['actual_bounds'],[118,197,786,277])
    def test_wrong_package_stops_read_sweep(self):
        self.native_refusal='wrong_package';d=run_city_diagnostics(self.reader)
        self.assertFalse(d['passed']);self.assertEqual(len(d['samples']),1)
    def test_generic_read_failure_is_sanitized_and_stops_sweep(self):
        self.reader.screen=lambda:(_ for _ in ()).throw(BridgeError('PRIVATE token=password'))
        d=run_city_diagnostics(self.reader)
        self.assertNotIn('PRIVATE',json.dumps(d));self.assertEqual(len(d['samples']),1)
        self.assertEqual(d['samples'][0]['diagnostic']['code'],'read_refused')
    def test_caret_only_change_is_normalized_not_a_click(self):
        old=city_context_sha256(self.png);self.mutate(300,236)
        self.assertEqual(city_context_sha256(self.png),old)
        self.assertTrue(run_city_diagnostics(self.reader)['passed']);self.assertEqual(self.events,[])
    def test_changes_between_screenshot_and_native_read_are_refused(self):
        original=self.native_read
        def changed(args):self.mutate(500,500);return original(args)
        self.reader._run=changed
        with self.assertRaises(CityInspectionError):observe_city(self.reader)
        self.assertEqual(self.events,[])
    def test_query_or_focus_oscillation_is_not_a_passing_diagnostic(self):
        for key in ('query','focused'):
            d,_=observe_city(self.reader);observations=[]
            for i in range(3):
                one=deepcopy(d);one[key]=(CITIES[i] if key=='query' else bool(i%2));observations.append((one,'a'*64))
            with patch('city_autotest.observe_city',side_effect=observations):
                self.assertFalse(run_city_diagnostics(self.reader)['passed'])
    def test_local_report_is_atomic_and_contains_no_private_text(self):
        self.query='PRIVATE';d=run_city_diagnostics(self.reader)
        with patch.dict(os.environ,{'LOCALAPPDATA':str(self.path)}):
            self.assertTrue(save_diagnostic_report(d))
            p=self.path/'DvkMuMu/diagnostics/city-last.json'
            self.assertNotIn('PRIVATE',p.read_text(encoding='utf-8'))
            self.assertFalse(p.with_suffix('.tmp').exists());self.assertEqual(json.loads(p.read_text())['device_actions'],0)
    def test_facade_diagnostic_saves_report_without_starting_test(self):
        with patch.dict(os.environ,{'LOCALAPPDATA':str(self.path)}):d=self.facade.autotest_city()
        self.assertTrue(d['report_saved']);self.assertEqual(self.db.status()['state'],'not_started')
    def test_candidates_strictly_inside_native_editor_not_result_rows(self):
        self.assertEqual(len(set(FOCUS_POINTS)),3);l,t,r,b=CITY_EDITOR_BOUNDS
        for x,y in FOCUS_POINTS:self.assertTrue(l<x<r and t<y<b)
    def test_autofocus_needs_explicit_local_run(self):
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(self.events,[])
    def test_already_focused_does_not_reserve_or_tap(self):
        self.db.start(5);self.focused=True;before=self.db.status()
        d=self.autofocus();self.assertTrue(d['already_focused']);self.assertTrue(d['focus_verified'])
        self.assertEqual(self.events,[]);self.assertEqual(self.db.status(),before)
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM city_focus_actions').fetchone()[0],0)
    def test_first_point_success_is_native_verified_no_typing(self):
        self.db.start(5);before=self.db.status();d=self.autofocus()
        self.assertTrue(d['focus_verified']);self.assertEqual(self.events,[FOCUS_POINTS[0]])
        self.assertFalse(d['text_entered']);self.assertFalse(d['message_sent'])
        self.assertEqual(self.db.status(),before)
    def test_second_point_only_after_known_injected_no_focus(self):
        self.db.start(5);self.focus_on=2;d=self.autofocus()
        self.assertTrue(d['focus_verified']);self.assertEqual(self.events,list(FOCUS_POINTS[:2]))
        self.assertEqual([s['outcome'] for s in d['steps']],['no_focus','focused'])
    def test_three_known_no_focus_attempts_exhaust_across_calls_and_restart(self):
        self.db.start(5);self.focus_on=99;d=self.autofocus()
        self.assertFalse(d['focus_verified']);self.assertEqual(len(self.events),3)
        self.assertFalse(self.autofocus()['focus_verified']);self.assertEqual(len(self.events),3)
        self.db.close();self.db=TestSession(self.path/'run.sqlite');self.facade=SupervisedReader(self.reader,self.db)
        self.assertFalse(self.autofocus()['focus_verified']);self.assertEqual(len(self.events),3)
    def test_native_known_refusal_does_not_try_another_point(self):
        self.db.start(5);self.tap_refusal='denied_screen_changed'
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(len(self.events),1);self.assertFalse(self.reader.action_uncertain)
        self.assertEqual(self.db.db.execute('SELECT state FROM city_focus_actions').fetchone()[0],'refused')
    def test_known_refusal_cannot_be_bypassed_by_another_call_or_restart(self):
        self.db.start(5);self.tap_refusal='denied_screen_changed'
        with self.assertRaises(BridgeError):self.autofocus()
        self.tap_refusal=None
        with self.assertRaises(BridgeError):self.autofocus()
        self.db.close();self.db=TestSession(self.path/'run.sqlite');self.facade=SupervisedReader(self.reader,self.db)
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(len(self.events),1)
    def test_migration_adds_focus_table_without_resetting_old_run(self):
        self.db.start(4);self.db.begin_visit();self.db.skip();self.db.returned()
        before=self.db.status()
        self.db.db.execute('DROP TABLE city_focus_actions');self.db.close()
        self.db=TestSession(self.path/'run.sqlite')
        self.assertEqual(self.db.status(),before)
        self.assertEqual(self.db.city_focus_points_used(),[])
    def test_report_save_failure_never_changes_device(self):
        d=run_city_diagnostics(self.reader)
        with patch('city_autotest.Path.mkdir',side_effect=PermissionError('private path')):
            self.assertFalse(save_diagnostic_report(d))
        self.assertEqual(self.events,[])

    def test_unknown_tap_halts_persistently_no_fallback(self):
        self.db.start(5);self.tap_refusal='unknown'
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(len(self.events),1);self.assertTrue(self.db.status()['manual_review_required'])
        self.db.close();self.db=TestSession(self.path/'run.sqlite');self.facade=SupervisedReader(self.reader,self.db)
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(len(self.events),1)
    def test_unreadable_post_tap_or_query_change_is_unknown_not_no_focus(self):
        self.db.start(5);self.after_read_failure=True
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(len(self.events),1);self.assertTrue(self.db.status()['manual_review_required'])
    def test_query_change_during_focus_stops_and_does_not_clear_text(self):
        self.db.start(5);self.change_query=True
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(self.query,CITIES[1]);self.assertEqual(len(self.events),1)
        self.assertTrue(self.db.status()['manual_review_required'])
    def test_context_change_during_focus_stops_no_alternate_point(self):
        self.db.start(5);self.change_context=True
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(len(self.events),1);self.assertTrue(self.reader.action_uncertain)
    def test_malformed_injection_ack_is_unknown_and_stops(self):
        self.db.start(5)
        with patch.object(self.reader,'navigate',return_value={'input_injected':False}):
            with self.assertRaises(BridgeError):self.autofocus()
        self.assertTrue(self.db.status()['manual_review_required'])
    def test_no_focus_during_visit_or_pending_city_action(self):
        self.db.start(5);a=self.db.reserve_city_input(1,0)
        with self.assertRaises(BridgeError):self.autofocus()
        self.db.finish_city_input(a,'refused');self.db.begin_visit()
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(self.events,[])
    def test_stale_expected_context_or_unsupported_bounds_never_tap(self):
        self.db.start(5)
        with self.assertRaises(BridgeError):self.facade.autofocus_city('a'*64)
        self.native_refusal='editor_bounds'
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(self.events,[]);self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM city_focus_actions').fetchone()[0],0)
    def test_action_cap_is_shared_not_renewed_per_point(self):
        self.db.start(5);self.reader.action_attempts=49;self.focus_on=99
        with self.assertRaises(BridgeError):self.autofocus()
        self.assertEqual(len(self.events),1);self.assertEqual(self.reader.action_attempts,50)
    def test_pending_focus_crash_stops_on_reopen_and_blocks_city_input(self):
        self.db.start(5);self.db.reserve_city_focus(0)
        with self.assertRaises(SessionError):self.db.reserve_city_input(1,0)
        self.db.close();self.db=TestSession(self.path/'run.sqlite')
        self.assertTrue(self.db.status()['manual_review_required']);self.assertEqual(self.db.status()['state'],'stopped')
    def test_focus_indices_strict_and_completion_not_replayable(self):
        self.db.start(5)
        for i in (-1,3,True,'0'):
            with self.assertRaises(SessionError):self.db.reserve_city_focus(i)
        a=self.db.reserve_city_focus(0);self.db.finish_city_focus(a,'no_focus')
        with self.assertRaises(SessionError):self.db.reserve_city_focus(0)
        with self.assertRaises(SessionError):self.db.finish_city_focus(a,'focused')
    def test_legacy_single_focus_point_cannot_be_reused_by_autofocus(self):
        self.db.start(5);a=self.db.reserve_city_focus(0);self.db.finish_city_focus(a,'injected')
        d=self.autofocus();self.assertTrue(d['focus_verified']);self.assertEqual(self.events,[FOCUS_POINTS[1]])

if __name__=='__main__':unittest.main()
