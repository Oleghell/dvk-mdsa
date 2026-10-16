"""Device-free tests for universal controls: strict protocol, opt-in and receipts."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from control_protocol import (TOOLS, IME, COMPONENT, SERIAL, valid_call,native_request,args_allowed)
from universal_control import UniversalControl, enable_locally, stop_locally
from test_session import TestSession, SessionError
from mumu_bridge import AdbReader,BridgeError,content_pixel_sha256
from test_city_field import frame

SHA='a'*64
ID='b'*32

def gesture(**kw):return {'action_id':ID,'expected_content_sha256':SHA,'action':'tap','x':400,'y':236,'x2':0,'y2':0,'duration_ms':0,**kw}
def text(**kw):return {'action_id':ID,'expected_field_context_sha256':SHA,'bounds':[118,196,786,276],'expected_text':'','mode':'type','text':'Нальчик 🙂','delay_ms':343,**kw}
def native_args(r):return ['-s',SERIAL,'shell','am','instrument','-w','-r','-e','request_b64',base64.b64encode(json.dumps(r).encode()).decode(),COMPONENT]

class ControlDiagnosticTests(unittest.TestCase):
    def test_diagnostic_only_fixed_safe_enums(self):
        from universal_control import safe_diagnostic
        report='INSTRUMENTATION_RESULT: control_diagnostic_code=root_not_ready\nINSTRUMENTATION_RESULT: control_diagnostic_phase=startup_root\n'
        self.assertEqual(safe_diagnostic(report),' [code=root_not_ready, phase=startup_root]')
        self.assertEqual(safe_diagnostic('INSTRUMENTATION_RESULT: control_diagnostic_code=private_user_text\n'),'')
        self.assertEqual(safe_diagnostic(report+'INSTRUMENTATION_RESULT: control_diagnostic_code=wrong_package\n'),' [phase=startup_root]')
    def test_inspection_refusal_reports_fixed_reason_without_raw_output(self):
        from types import SimpleNamespace
        report=b'INSTRUMENTATION_RESULT: control_status=denied_context\nINSTRUMENTATION_RESULT: control_diagnostic_code=screen_dimensions\nINSTRUMENTATION_RESULT: control_diagnostic_phase=inspect_screen\nPRIVATE_APP_TEXT\n'
        reader=SimpleNamespace(control_enabled=True,_foreground=lambda:None,_run=lambda args:report)
        with self.assertRaises(BridgeError) as caught:UniversalControl(reader,None).inspect()
        message=str(caught.exception)
        self.assertIn('code=screen_dimensions',message);self.assertIn('phase=inspect_screen',message)
        self.assertNotIn('PRIVATE_APP_TEXT',message)

class ControlProtocolTests(unittest.TestCase):
    def test_four_tools_no_shell_scripts_or_remote_optin(self):
        self.assertEqual({t['name'] for t in TOOLS},{'mumu_control_inspect','mumu_control_gesture','mumu_control_key','mumu_control_text'})
        for t in TOOLS:self.assertIs(t['inputSchema']['additionalProperties'],False)
    def test_unicode_text_is_independent_of_city_catalog(self):
        for value in ('Нальчик','Комсомольск-на-Амуре','🙂👋','Привет, как дела?','X'*128):
            self.assertTrue(valid_call('mumu_control_text',text(text=value)))
    def test_no_newline_control_surrogate_or_unbounded_text(self):
        for value in ('','x\ny','x\ry','\t','\x00','\x7f','\x85','\u2028','\ud800','X'*129):
            self.assertFalse(valid_call('mumu_control_text',text(text=value)))
    def test_clear_requires_exact_expected_text_and_empty_payload(self):
        self.assertTrue(valid_call('mumu_control_text',text(mode='clear',expected_text='Нальчик',text='')))
        self.assertFalse(valid_call('mumu_control_text',text(mode='clear',text='other')))
        self.assertFalse(valid_call('mumu_control_text',text(expected_text='existing draft')))
    def test_text_strict_native_bounds_delay_and_types(self):
        for change in ({'bounds':[True,196,786,276]},{'bounds':[0,0,900,1600]},{'bounds':[118,276,786,196]}, {'delay_ms':True},{'delay_ms':19},{'delay_ms':501},{'expected_text':None}):
            self.assertFalse(valid_call('mumu_control_text',text(**change)))
    def test_gesture_shapes_and_limits(self):
        self.assertTrue(valid_call('mumu_control_gesture',gesture()))
        self.assertTrue(valid_call('mumu_control_gesture',gesture(action='hold',duration_ms=700)))
        self.assertTrue(valid_call('mumu_control_gesture',gesture(action='swipe',x2=400,y2=1200,duration_ms=500)))
        for bad in ({'x':True},{'y':47},{'x':900},{'action':'tap','duration_ms':500},{'action':'swipe','x2':900},{'duration_ms':2001},{'action':'shell'}):
            self.assertFalse(valid_call('mumu_control_gesture',gesture(**bad)))
    def test_action_ids_hashes_and_extras_strict(self):
        for bad in ({'action_id':'short'},{'expected_content_sha256':'bad'},{'reset':True},{'script':'print(1)'}):
            self.assertFalse(valid_call('mumu_control_gesture',gesture(**bad)))
    def test_keys_are_single_allowlisted_android_events(self):
        base={'action_id':ID,'expected_content_sha256':SHA}
        for key in ('BACK','ENTER','DELETE','LEFT'):self.assertTrue(valid_call('mumu_control_key',{**base,'key':key}))
        for key in ('HOME','APP_SWITCH','ENTER;am force-stop drug.vokrug','adb shell',True):self.assertFalse(valid_call('mumu_control_key',{**base,'key':key}))
    def test_native_allowlist_roundtrip_and_no_shell_expansion(self):
        for name,args in (('mumu_control_inspect',{}),('mumu_control_gesture',gesture()),('mumu_control_text',text()),('mumu_control_key',{'action_id':ID,'expected_content_sha256':SHA,'key':'ENTER'})):
            r=native_request(name,args);a=native_args(r);self.assertTrue(args_allowed(a,True));self.assertFalse(args_allowed(a,False))
            r['shell']='anything';self.assertFalse(args_allowed(native_args(r),True))
    def test_native_extra_keys_and_noncanonical_parameters_refused(self):
        r=native_request('mumu_control_gesture',gesture());r['x2']=99
        self.assertFalse(args_allowed(native_args(r),True))
        for malformed in (None,[],{},['shell','input','text','a']):self.assertFalse(args_allowed(malformed,True))

class ControlJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'adb.exe').touch()
        self.reader=AdbReader(self.root/'adb.exe');self.reader.control_enabled=True;self.reader.screen=lambda:frame()
        self.ledger=TestSession(self.root/'run.sqlite');self.control=UniversalControl(self.reader,self.ledger)
        self.sha=content_pixel_sha256(frame());self.calls=[];self.state='input_injected'
        def instrument(r):
            self.calls.append(r)
            self.assertEqual(self.ledger.db.execute('SELECT state FROM control_actions WHERE id=?',(ID,)).fetchone()[0],'reserved')
            if self.state=='timeout':raise BridgeError('Private timeout data')
            return self.state,''
        self.control.instrument=instrument
    def tearDown(self):self.ledger.close();self.tmp.cleanup()
    def run_tap(self,**kw):return self.control.execute('mumu_control_gesture',gesture(**{'expected_content_sha256':self.sha,**kw}))
    def test_local_optin_required_no_device_call_or_receipt(self):
        self.reader.control_enabled=False
        with self.assertRaises(BridgeError):self.run_tap()
        self.assertEqual(self.calls,[])
    def test_reserve_before_dispatch_no_text_or_images_in_journal(self):
        before=self.ledger.status();d=self.run_tap();self.assertFalse(d['result_screen_verified'])
        self.assertEqual(self.ledger.status(),before)
        self.assertEqual(self.ledger.db.execute('SELECT * FROM control_actions').fetchone()['state'],'succeeded')
        self.assertEqual([r[1] for r in self.ledger.db.execute('PRAGMA table_info(control_actions)')],['id','state'])
    def test_same_action_id_cannot_replay_after_success(self):
        self.run_tap()
        with self.assertRaises(BridgeError):self.run_tap()
        self.assertEqual(len(self.calls),1)
    def test_unknown_outcome_holds_without_active_profile_run(self):
        self.state='timeout'
        with self.assertRaises(BridgeError):self.run_tap()
        self.assertTrue(self.ledger.status()['manual_review_required']);self.assertTrue(self.reader.action_uncertain)
        self.ledger.close();self.ledger=TestSession(self.root/'run.sqlite')
        self.assertTrue(self.ledger.status()['manual_review_required'])
    def test_unknown_outcome_stops_existing_run_preserves_target(self):
        self.ledger.start(4);self.state='timeout'
        with self.assertRaises(BridgeError):self.run_tap()
        d=self.ledger.status();self.assertEqual(d['target'],4);self.assertEqual(d['remaining'],4);self.assertEqual(d['state'],'stopped')
    def test_wrong_operation_ack_is_unknown(self):
        self.state='text_verified'
        with self.assertRaises(BridgeError):self.run_tap()
        self.assertTrue(self.ledger.status()['manual_review_required'])
    def test_known_refusal_records_no_replay_without_global_hold(self):
        self.state='denied_screen_changed'
        with self.assertRaises(BridgeError):self.run_tap()
        self.assertFalse(self.ledger.status()['manual_review_required']);self.assertFalse(self.reader.action_uncertain)
        with self.assertRaises(BridgeError):self.run_tap()
        self.assertEqual(len(self.calls),1)
    def test_changed_screen_refuses_before_reservation(self):
        with self.assertRaises(BridgeError):self.run_tap(expected_content_sha256=SHA)
        self.assertEqual(self.calls,[])
    def test_reserved_crash_recovers_to_hold_on_reopen(self):
        self.ledger.start(4);self.ledger.db.execute('INSERT INTO control_actions VALUES (?,?)',(ID,'reserved'));self.ledger.close()
        self.ledger=TestSession(self.root/'run.sqlite');self.assertTrue(self.ledger.status()['manual_review_required']);self.assertEqual(self.ledger.status()['state'],'stopped')
    def test_changed_field_no_text_dispatch(self):
        self.control.inspect=lambda:{'focused':True,'bounds':[118,196,786,276],'text':'existing','field_context_sha256':SHA}
        with self.assertRaises(BridgeError):self.control.execute('mumu_control_text',text())
        self.assertEqual(self.calls,[])
    def test_text_native_verification_is_not_claimed_as_search_or_send(self):
        self.control.inspect=lambda:{'focused':True,'bounds':[118,196,786,276],'text':'','field_context_sha256':SHA}
        self.state='text_verified';d=self.control.execute('mumu_control_text',text())
        self.assertFalse(d['message_sent_verified']);self.assertEqual(self.calls[0]['text'],'Нальчик 🙂')
    def test_persistent_receipt_cap_is_not_reset_by_reconnect(self):
        self.ledger.db.executemany('INSERT INTO control_actions VALUES (?,?)',[(str(i),'succeeded') for i in range(500)])
        with self.assertRaises(BridgeError):self.run_tap()
        self.assertEqual(self.calls,[])

class ControlLocalSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'adb.exe').touch();self.reader=AdbReader(self.root/'adb.exe');self.ledger=TestSession(self.root/'db')
    def tearDown(self):self.ledger.close();self.tmp.cleanup()
    def test_no_remote_ime_enable_arbitrary_install_or_force_stop(self):
        for a in (['-s',SERIAL,'shell','ime','set',IME],['-s',SERIAL,'shell','am','force-stop','drug.vokrug'],['-s',SERIAL,'install','-t','-r','arbitrary.apk']):
            with patch('subprocess.run') as run:
                with self.assertRaises(BridgeError):self.reader._run(a)
                run.assert_not_called()
    def test_both_apks_validated_before_install_or_ime_change(self):
        with patch.object(self.reader,'_run') as run:
            with self.assertRaises(BridgeError):enable_locally(self.reader,self.ledger,self.root)
        run.assert_not_called();self.assertFalse(self.reader._local_control_setup)
    def test_stop_kills_only_bridge_ime_and_does_not_change_user_chosen_keyboard(self):
        self.reader.control_enabled=True;self.ledger.db.execute("INSERT INTO control_config VALUES ('previous_ime','old.keyboard/.Ime')")
        calls=[]
        def fake(a):calls.append(a);return b'new.keyboard/.Ime'
        with patch.object(self.reader,'_run',side_effect=fake):stop_locally(self.reader,self.ledger)
        self.assertEqual(calls[0],['-s',SERIAL,'shell','am','force-stop','com.dvk.keyboard.v1'])
        self.assertFalse(any('set' in c for c in calls));self.assertFalse(self.reader.control_enabled)
    def test_stop_restores_only_saved_previous_keyboard_if_ours_still_selected(self):
        self.ledger.db.execute("INSERT INTO control_config VALUES ('previous_ime','old.keyboard/.Ime')")
        with patch.object(self.reader,'_run',side_effect=[b'',IME.encode(),b'',b'old.keyboard/.Ime']) as run:stop_locally(self.reader,self.ledger)
        self.assertIn(unittest.mock.call(['-s',SERIAL,'shell','ime','set','old.keyboard/.Ime']),run.call_args_list)

    def test_failed_enable_after_ime_selection_restores_original(self):
        import hashlib
        names=('control-helper.apk','keyboard-helper.apk')
        for name in names:(self.root/name).write_bytes(b'pinned-test')
        packages={name:hashlib.sha256(b'pinned-test').hexdigest() for name in names}
        current=['old.keyboard/.Ime'];reads=[0];calls=[]
        def fake(args):
            calls.append(args)
            if args[2]=='install':return b'Success'
            if 'get' in args:
                reads[0]+=1
                if reads[0]==2:raise BridgeError('readback failed after selecting IME')
                return current[0].encode()
            if 'set' in args:current[0]=args[-1]
            return b''
        with patch('control_release.PACKAGES',packages),patch.object(self.reader,'_run',side_effect=fake):
            with self.assertRaises(BridgeError):enable_locally(self.reader,self.ledger,self.root)
        self.assertEqual(current[0],'old.keyboard/.Ime');self.assertFalse(self.reader.control_enabled)
        self.assertFalse(self.reader._local_control_setup)
        self.assertEqual(calls[0][-1],str((self.root/'keyboard-helper.apk').resolve()))
    def test_restore_verifies_readback(self):
        from universal_control import restore_keyboard_locally
        self.ledger.db.execute("INSERT INTO control_config VALUES ('previous_ime','old.keyboard/.Ime')")
        with patch.object(self.reader,'_run',side_effect=[IME.encode(),b'',IME.encode()]):
            with self.assertRaises(BridgeError):restore_keyboard_locally(self.reader,self.ledger)
        self.assertFalse(self.reader._local_control_setup)

if __name__=='__main__':unittest.main()
