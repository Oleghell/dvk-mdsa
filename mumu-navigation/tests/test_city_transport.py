"""Synthetic city input transport; NO real device/actions/network."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from city_release import CITY_COMPONENT,CITY_CATALOG,CITY_APK_SHA256
from city_transport import CityTransport,city_args_allowed,city_context_sha256
from limited_scenario import CITIES
from mumu_bridge import AdbReader,BridgeError,SERIAL,content_pixel_sha256
from session_bridge import SupervisedReader
from test_session import TestSession,SessionError
from test_city_field import frame,layout

class CityTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name);(p/'adb.exe').touch()
        self.r=AdbReader(p/'adb.exe');self.r.city_helper_ready=True;self.png=frame()
        self.r.screen=lambda:self.png;self.r._foreground=lambda:None
        self.query='';self.focused=True;self.events=[];self.state='city_input_native_verified';self.bad_report=None
        self.r._run=self.fake_adb
        self.sha=city_context_sha256(self.png)
    def tearDown(self):self.tmp.cleanup()
    def fake_adb(self,args):
        self.assertTrue(city_args_allowed(args,self.r.city_helper_ready));op=args[9]
        if op=='inspect_city':
            d={'catalog':CITY_CATALOG,'query':self.query,'focused':self.focused,
               'city_context_sha256':self.sha,'bounds':[118,196,786,276],
               'result_rows_available':False,'city_selected':False,'filters_applied':False}
            if self.bad_report is not None:d=self.bad_report
            return ('INSTRUMENTATION_RESULT: navigation_status=city_inspection_ok\nINSTRUMENTATION_RESULT: layout_b64='+base64.b64encode(json.dumps(d).encode()).decode()+'\n').encode()
        self.events.append(args)
        if self.state=='timeout':raise BridgeError('Synthetic timeout')
        if self.state=='city_input_native_verified':self.query=CITIES[int(args[15])]
        return ('INSTRUMENTATION_RESULT: navigation_status='+self.state+'\n').encode()
    def transport(self):return CityTransport(self.r)
    def test_inspection_readonly(self):
        d=self.transport().inspect();self.assertTrue(d['focused']);self.assertEqual(self.events,[])
        self.assertEqual(self.r.action_attempts,0)
    def test_fixed_native_diagnostic_is_visible_without_raw_output(self):
        self.r._run=lambda args:b'INSTRUMENTATION_RESULT: navigation_status=denied_context_or_layout\nINSTRUMENTATION_RESULT: city_diagnostic_code=root_not_ready\n'
        with self.assertRaisesRegex(BridgeError,'denied_context_or_layout / root_not_ready'):
            self.transport().inspect()
        self.assertEqual(self.r.action_attempts,0);self.assertEqual(self.events,[])
    def test_unknown_or_duplicate_native_diagnostic_never_leaks_text(self):
        for code in ('private_query','root_not_ready\nINSTRUMENTATION_RESULT: city_diagnostic_code=wrong_package'):
            self.r._run=lambda args:('INSTRUMENTATION_RESULT: navigation_status=denied_context_or_layout\nINSTRUMENTATION_RESULT: city_diagnostic_code='+code+'\nPRIVATE SCREEN TEXT').encode()
            with self.assertRaises(BridgeError) as err:self.transport().inspect()
            self.assertIn('not_reported',str(err.exception));self.assertNotIn('private',str(err.exception));self.assertNotIn('PRIVATE',str(err.exception))
        self.assertEqual(self.r.action_attempts,0)
    def test_rectangle_and_phase_diagnostics_are_bounded_and_readonly(self):
        self.r._run=lambda args:b'INSTRUMENTATION_RESULT: navigation_status=denied_context_or_layout\nINSTRUMENTATION_RESULT: city_diagnostic_code=editor_bounds\nINSTRUMENTATION_RESULT: city_diagnostic_phase=inspect_confirm\nINSTRUMENTATION_RESULT: actual_editor_bounds=118,197,786,277\n'
        with self.assertRaisesRegex(BridgeError,r'phase=inspect_confirm; actual_bounds=\[118, 197, 786, 277\]'):
            self.transport().inspect()
        self.assertEqual(self.r.action_attempts,0)
    def test_unsafe_or_duplicate_rectangle_metadata_is_not_returned(self):
        for value in ('99999,0,0,0','118,196,private,276','118,196,786,276\nINSTRUMENTATION_RESULT: actual_editor_bounds=0,0,0,0'):
            self.r._run=lambda args:('INSTRUMENTATION_RESULT: navigation_status=denied_context_or_layout\nINSTRUMENTATION_RESULT: city_diagnostic_code=editor_bounds\nINSTRUMENTATION_RESULT: city_diagnostic_phase=private_info\nINSTRUMENTATION_RESULT: actual_editor_bounds='+value+'\n').encode()
            with self.assertRaises(BridgeError) as err:self.transport().inspect()
            self.assertNotIn('actual_bounds=',str(err.exception));self.assertNotIn('private',str(err.exception))
    def test_refused_inspection_does_not_dispatch_or_consume_an_action(self):
        self.r._run=lambda args:b'INSTRUMENTATION_RESULT: navigation_status=denied_screen_changed\nINSTRUMENTATION_RESULT: city_diagnostic_code=context_changed\n'
        with self.assertRaisesRegex(BridgeError,'context_changed'):
            self.transport().input(self.sha,0,-1)
        self.assertEqual(self.r.action_attempts,0);self.assertFalse(self.r.action_uncertain)
    def test_exact_catalog_input_one_action_no_selection(self):
        d=self.transport().input(self.sha,0,-1)
        self.assertEqual(self.query,CITIES[0]);self.assertEqual(len(self.events),1)
        self.assertEqual(self.events[0][9],'city_input');self.assertEqual(self.events[0][15],'0');self.assertEqual(self.events[0][18],'0')
        self.assertTrue(d['native_query_verified']);self.assertFalse(d['city_selected']);self.assertFalse(d['filters_applied']);self.assertFalse(d['message_sent'])
        self.assertEqual(self.r.action_attempts,1);self.assertFalse(self.r.action_uncertain)
    def test_previous_city_index_encoded_without_arbitrary_text(self):
        self.query=CITIES[0];self.transport().input(self.sha,1,0)
        self.assertEqual(self.events[0][18],'1');self.assertEqual(self.query,CITIES[1])
    def test_all_thirty_indices_have_same_catalog_meaning(self):
        for index in range(30):
            self.query='';self.r.action_attempts=0;self.transport().input(self.sha,index,-1)
            self.assertEqual(self.query,CITIES[index])
    def test_invalid_indices_same_city_and_bool_refused(self):
        for index,prev in [(True,-1),(0,False),(-1,-1),(30,-1),(0,-2),(0,30),(0,0)]:
            with self.subTest(index=index,prev=prev),self.assertRaises(BridgeError):self.transport().input(self.sha,index,prev)
        self.assertEqual(self.events,[])
    def test_unfocused_nonmatching_or_arbitrary_prior_query_refused(self):
        for query,focused in [('',False),('KEEP_EXISTING',True),(CITIES[1],True)]:
            self.query=query;self.focused=focused
            with self.assertRaises(BridgeError):self.transport().input(self.sha,0,-1)
        self.assertEqual(self.events,[])
    def test_stale_context_missing_helper_cap_and_unknown_refused(self):
        with self.assertRaises(BridgeError):self.transport().input('a'*64,0,-1)
        self.r.city_helper_ready=False
        with self.assertRaises(BridgeError):self.transport().input(self.sha,0,-1)
        self.r.city_helper_ready=True;self.r.action_attempts=50
        with self.assertRaises(BridgeError):self.transport().input(self.sha,0,-1)
        self.r.action_attempts=0;self.r.action_uncertain=True
        with self.assertRaises(BridgeError):self.transport().input(self.sha,0,-1)
        self.assertEqual(self.events,[])
    def test_native_preinput_refusal_known_no_retry_in_transport(self):
        self.state='denied_field'
        with self.assertRaises(BridgeError):self.transport().input(self.sha,0,-1)
        self.assertEqual(len(self.events),1);self.assertFalse(self.r.action_uncertain)
    def test_preinput_native_bounds_diagnostic_preserves_known_refusal(self):
        def run(args):
            if args[9]=='inspect_city':return self.fake_adb(args)
            self.events.append(args)
            return b'INSTRUMENTATION_RESULT: navigation_status=denied_context_or_layout\nINSTRUMENTATION_RESULT: city_diagnostic_code=editor_bounds\nINSTRUMENTATION_RESULT: city_diagnostic_phase=input_before\nINSTRUMENTATION_RESULT: actual_editor_bounds=0,0,0,0\n'
        self.r._run=run
        with self.assertRaisesRegex(BridgeError,r'phase=input_before; actual_bounds=\[0, 0, 0, 0\]'):
            self.transport().input(self.sha,0,-1)
        self.assertEqual(len(self.events),1);self.assertFalse(self.r.action_uncertain)
    def test_unknown_native_status_or_timeout_blocks_further_actions(self):
        for state in ('indeterminate_after_attempt','timeout','unexpected_status'):
            self.r.action_uncertain=False;self.state=state
            with self.assertRaises(BridgeError):self.transport().input(self.sha,0,-1)
            self.assertTrue(self.r.action_uncertain)
    def test_malformed_or_optimistic_inspection_refused(self):
        good=self.transport().inspect()
        for key,value in [('catalog','city-v2'),('bounds',[152,1488,748,1544]),('focused',1),
                          ('query',None),('city_context_sha256','wrong'),('city_selected',True),('filters_applied',True)]:
            self.bad_report={**good,key:value}
            with self.subTest(key=key),self.assertRaises(BridgeError):self.transport().inspect()
    def test_strict_adb_arguments_no_other_component_op_coordinates_or_text(self):
        args=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','op','city_input','-e','expected_content_sha256',self.sha,'-e','x','0','-e','y','0',CITY_COMPONENT]
        self.assertTrue(city_args_allowed(args,True));self.assertFalse(city_args_allowed(args,False))
        for i,value in [(9,'greeting'),(9,'tap'),(9,'back'),(15,'30'),(18,'31'),(15,'-1'),(19,'other/helper'),(12,'wrong'),(15,'Нальчик')]:
            bad=list(args);bad[i]=value;self.assertFalse(city_args_allowed(bad,True))
        self.assertFalse(city_args_allowed(args+['-e','text','Нальчик'],True))
    def test_old_adb_boundary_accepts_only_city_scoped_calls(self):
        args=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','op','city_input','-e','expected_content_sha256',self.sha,'-e','x','0','-e','y','0',CITY_COMPONENT]
        with patch('subprocess.run') as run:
            run.return_value.returncode=0;run.return_value.stdout=b'ok'
            self.assertEqual(AdbReader._run(self.r,args),b'ok');run.assert_called_once()
        args[9]='greeting'
        with patch('subprocess.run') as run,self.assertRaises(BridgeError):AdbReader._run(self.r,args)
        run.assert_not_called()
    def test_missing_or_wrong_apk_never_installed(self):
        p=Path(self.tmp.name)
        with self.assertRaises(BridgeError):self.transport().install(p)
        (p/'city-helper.apk').write_bytes(b'wrong')
        with self.assertRaises(BridgeError):self.transport().install(p)
        self.assertIsNone(self.r.city_helper_path)

class CityLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite';self.db=TestSession(self.path);self.db.start(5)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def test_reservation_before_dispatch_does_not_count_profile_or_message(self):
        before=self.db.status();a=self.db.reserve_city_input(0,-1)
        self.assertEqual(self.db.status(),before);self.db.finish_city_input(a,'verified')
        self.assertEqual(self.db.status(),before)
    def test_five_city_attempts_no_new_budget(self):
        for i in range(5):self.db.finish_city_input(self.db.reserve_city_input(i,-1),'refused')
        with self.assertRaises(SessionError):self.db.reserve_city_input(5,-1)
        self.assertEqual(self.db.status()['visited'],0)
    def test_second_reservation_cannot_overlap_pending_dispatch(self):
        a=self.db.reserve_city_input(0,-1)
        with self.assertRaises(SessionError):self.db.reserve_city_input(1,-1)
        self.db.finish_city_input(a,'verified')
        self.db.finish_city_input(self.db.reserve_city_input(1,-1),'verified')

    def test_same_city_not_retried_even_after_known_refusal(self):
        self.db.finish_city_input(self.db.reserve_city_input(0,-1),'refused')
        with self.assertRaises(SessionError):self.db.reserve_city_input(0,-1)
    def test_pending_reservation_stops_on_reopen(self):
        self.db.reserve_city_input(0,-1);self.db.close();self.db=TestSession(self.path)
        self.assertTrue(self.db.status()['manual_review_required']);self.assertEqual(self.db.status()['state'],'stopped')
        with self.assertRaises(SessionError):self.db.start(5)
    def test_unknown_stops_without_visited_profile(self):
        self.db.finish_city_input(self.db.reserve_city_input(0,-1),'unknown')
        self.assertEqual(self.db.status()['state'],'stopped');self.assertTrue(self.db.status()['manual_review_required'])
    def test_no_city_during_visit_or_replayed_finish(self):
        self.db.begin_visit()
        with self.assertRaises(SessionError):self.db.reserve_city_input(0,-1)
        with self.assertRaises(SessionError):self.db.finish_city_input('missing','verified')
    def test_invalid_city_indices_and_outcomes(self):
        for index,prev in [(True,-1),(0,False),(-1,-1),(30,-1),(0,30),(0,0)]:
            with self.assertRaises(SessionError):self.db.reserve_city_input(index,prev)
        a=self.db.reserve_city_input(0,-1)
        with self.assertRaises(SessionError):self.db.finish_city_input(a,'retry')
        self.db.finish_city_input(a,'refused')
        with self.assertRaises(SessionError):self.db.finish_city_input(a,'verified')

class CityFacadeInputTests(unittest.TestCase):
    setUp=CityTransportTests.setUp
    def tearDown(self):self.db.close();CityTransportTests.tearDown(self)
    fake_adb=CityTransportTests.fake_adb
    def init_facade(self):
        self.db=TestSession(Path(self.tmp.name)/'run.sqlite');self.db.start(5);self.facade=SupervisedReader(self.r,self.db)
    def test_facade_records_verified_action_without_profile(self):
        self.init_facade();d=self.facade.input_city(self.sha,0,-1)
        self.assertTrue(d['city_attempt_recorded']);self.assertEqual(self.db.status()['visited'],0)
        self.assertEqual(self.db.db.execute('SELECT state FROM city_actions').fetchone()[0],'verified')
    def test_facade_unknown_stops_persistently(self):
        self.init_facade();self.state='timeout'
        with self.assertRaises(BridgeError):self.facade.input_city(self.sha,0,-1)
        self.assertEqual(self.db.status()['state'],'stopped');self.assertTrue(self.db.status()['manual_review_required'])
        self.assertEqual(self.db.db.execute('SELECT state FROM city_actions').fetchone()[0],'unknown')
    def test_facade_preflight_does_not_reserve_or_consume_attempt(self):
        self.init_facade();self.focused=False
        with self.assertRaises(BridgeError):self.facade.input_city(self.sha,0,-1)
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM city_actions').fetchone()[0],0)
        self.assertEqual(self.events,[])
    def test_facade_second_city_input_preflight_refusal_recorded(self):
        self.init_facade();self.state='denied_screen_changed'
        with self.assertRaises(BridgeError):self.facade.input_city(self.sha,0,-1)
        self.assertEqual(self.db.db.execute('SELECT state FROM city_actions').fetchone()[0],'refused')
        self.assertFalse(self.db.status()['manual_review_required'])

if __name__=='__main__':unittest.main()
