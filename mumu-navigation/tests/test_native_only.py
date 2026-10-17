"""Strict release entry points cannot reach pixels, OCR, CV, IME or XY injection."""
import base64,copy,json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from urllib.request import Request,urlopen
from mumu_bridge import BridgeServer,AdbReader,BridgeError
from control_protocol import SERIAL,COMPONENT
from native_policy import allowed_adb
from ui_model import UnsupportedUI,UIError
from ui_diagnostics import validate
from ui_workflow import UIWorkflow
from ui_backend import NativeBackend
from ui_runtime import Element
from test_ui_runtime import tree,node
from test_session import TestSession

def instrument(payload):
    return ['-s',SERIAL,'shell','am','instrument','-w','-r','-e','request_b64',base64.b64encode(json.dumps(payload).encode()).decode(),COMPONENT]

def diagnostic():
    n=dict(index=0,parent=-1,window_id=2,package='drug.vokrug',resource_id='drug.vokrug:id/unitySurfaceView',class_name='android.view.View',text='',description='Game view',password=False,visible=True,enabled=True,editable=False,action_click=False,action_set_text=False,child_count=0)
    return dict(diagnostics_version=1,package='drug.vokrug',complete=True,unity_surface=True,flags_restored_after_scan=True,identity_verified=False,empty_chat_verified=False,flags_requested=82,flags_applied=82,flags_original=16,window_count=1,foreign_windows_skipped=1,actionable_nodes=0,editable_nodes=0,images_captured=0,actions_attempted=0,windows=[dict(window_id=2,package='drug.vokrug')],nodes=[n],blocker='unity_surface_without_exposed_controls')

class TransportTests(unittest.TestCase):
    def setUp(self):self.reader=SimpleNamespace(_local_control_setup=False,control_install_paths=set(),control_enabled=True)
    def test_native_read_and_back_are_allowed(self):
        for p in ({'op':'ui_dump'},{'op':'ui_diagnostics'},{'op':'ui_back','expected_tree_sha256':'a'*64}):self.assertTrue(allowed_adb(instrument(p),self.reader))
    def test_native_click_requires_exact_false(self):
        p=dict(op='ui_click',selector={'text':'Написать'},expected_tree_sha256='a'*64,allow_coordinate_fallback=False)
        self.assertTrue(allowed_adb(instrument(p),self.reader))
        for v in (True,0,None):
            p['allow_coordinate_fallback']=v;self.assertFalse(allowed_adb(instrument(p),self.reader))
    def test_all_visual_and_legacy_operations_are_blocked(self):
        for p in ({'op':'inspect'},{'op':'find_profile_chat'},{'op':'click_profile_chat','expected_target_sha256':'a'*64},{'op':'ui_visual_click','expected_tree_sha256':'a'*64,'expected_frame_sha256':'b'*64,'bounds':[1,2,3,4]}):self.assertFalse(allowed_adb(instrument(p),self.reader))
        for args in (['-s',SERIAL,'exec-out','screencap','-p'],['-s',SERIAL,'shell','ime','set','anything'],['-s',SERIAL,'shell','input','tap','10','20']):self.assertFalse(allowed_adb(args,self.reader))
    def test_only_one_pinned_install_during_local_setup(self):
        self.reader._local_control_setup=True
        for n,allowed in (('control-helper.apk',True),('keyboard-helper.apk',False),('helper.apk',False)):
            p='/tmp/'+n;self.reader.control_install_paths.add(p)
            self.assertEqual(allowed_adb(['-s',SERIAL,'install','-t','-r',p],self.reader),allowed)
    def test_adb_defense_before_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            adb=Path(tmp)/'adb.exe';adb.touch();reader=AdbReader(adb,native_only=True)
            with patch('subprocess.run') as run:
                with self.assertRaises(BridgeError):reader._run(['-s',SERIAL,'exec-out','screencap','-p'])
                with self.assertRaises(BridgeError):reader.screen()
                run.assert_not_called()

class StrictWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ledger=TestSession(Path(self.tmp.name)/'journal.sqlite')
        self.reader=SimpleNamespace(native_only=True,control_enabled=True,screen=Mock(side_effect=AssertionError('pixels forbidden')))
        self.supervised=SimpleNamespace(inner=self.reader,ledger=self.ledger,_run_ready=Mock())
        self.ui=UIWorkflow(self.supervised)
    def tearDown(self):self.ledger.close();self.tmp.cleanup()
    def test_no_visual_providers_constructed(self):
        self.assertIsNone(self.ui.ui.ocr);self.assertIsNone(self.ui.ui.vision);self.reader.screen.assert_not_called()
    def test_find_fallback_rejected_before_read(self):
        self.ui.backend.snapshot=Mock()
        with self.assertRaises(UnsupportedUI):self.ui.find({'text':'Написать'},allow_fallback=True)
        self.ui.backend.snapshot.assert_not_called()
    def test_action_fallback_rejected_before_journal_or_device(self):
        with self.assertRaises(UnsupportedUI):self.ui.action_call(dict(action='focus_editor',action_id='a'*32,target='',city_index=-1,allow_fallback=True))
        self.supervised._run_ready.assert_not_called()
    def test_backend_never_requests_coordinate_fallback(self):
        self.ui.backend.control.instrument=Mock(return_value=('input_injected',''))
        e=Element(self.ui.ui,{'text':'Написать'},{},'a'*64)
        self.ui.backend.perform(e,'click')
        self.assertIs(self.ui.backend.control.instrument.call_args.args[0]['allow_coordinate_fallback'],False)
    def test_non_native_element_rejected_before_transport(self):
        self.ui.backend.control.instrument=Mock()
        for method in ('ocr','profile_cv'):
            with self.assertRaises(UnsupportedUI):self.ui.backend.perform(Element(self.ui.ui,{}, {},'a'*64,method),'click')
        self.ui.backend.control.instrument.assert_not_called()
    def test_native_inspection_does_not_capture(self):
        self.ui.backend.snapshot=Mock(return_value=tree([node(text='Поиск города')]))
        self.assertIn('native only',self.ui.inspect()['fallback_policy']);self.reader.screen.assert_not_called()
    def test_diagnostics_read_only_not_an_action_tree(self):
        data=diagnostic();encoded=base64.b64encode(json.dumps(data).encode()).decode()
        self.ui.backend.control.instrument=Mock(return_value=('inspection_ok','INSTRUMENTATION_RESULT: report_b64='+encoded))
        self.assertEqual(self.ui.backend.diagnostics()['blocker'],'unity_surface_without_exposed_controls')
        self.assertEqual(self.ui.backend.control.instrument.call_args.args[0],{'op':'ui_diagnostics'})
        self.assertEqual(self.ledger.status()['visited'],0);self.reader.screen.assert_not_called()

class DiagnosticTests(unittest.TestCase):
    def test_valid_unity_report(self):self.assertEqual(validate(diagnostic())['images_captured'],0)
    def test_incomplete_does_not_claim_absence(self):
        d=diagnostic();d['complete']=False
        with self.assertRaises(UIError):validate(d)
        d['blocker']='incomplete_scan';validate(d)
    def test_wrong_counts_password_leaks_foreign_nodes_and_fake_identity_rejected(self):
        variants=[]
        for k,v in [('actionable_nodes',1),('images_captured',1),('actions_attempted',1),('identity_verified',True),('flags_restored_after_scan',False),('flags_applied',16)]:
            d=diagnostic();d[k]=v;variants.append(d)
        for k,v in [('package','other.app'),('password',True),('parent',0),('action_click',True)]:
            d=diagnostic();d['nodes'][0][k]=v;variants.append(d)
        for d in variants:
            with self.assertRaises(UIError):validate(d)

class StrictStartupTests(unittest.TestCase):
    def test_startup_and_stop_do_not_touch_pixels_ime_or_legacy_helpers(self):
        from bridge_startup import prepare_device
        from universal_control import stop_locally
        reader=SimpleNamespace(native_only=True,control_enabled=True,_foreground=Mock(),screen=Mock(side_effect=AssertionError('pixels')),_run=Mock(side_effect=AssertionError('extra command')))
        facade=SimpleNamespace(inner=reader,ledger=Mock(),connect=Mock())
        with patch('universal_control.enable_native_locally') as enable,patch('ui_backend.NativeBackend.unity_diagnostics',return_value={}) as diag,patch('universal_control.enable_locally') as legacy,patch('bridge_startup.install_helper_with_local_consent') as install:
            prepare_device(facade,Path('.'),threading.Event(),Mock(),consent=True)
            enable.assert_called_once();diag.assert_called_once();legacy.assert_not_called();install.assert_not_called()
            reader.screen.assert_not_called();reader._run.assert_not_called();facade.ledger.start.assert_not_called()
            stop_locally(reader,facade.ledger);self.assertFalse(reader.control_enabled);reader._run.assert_not_called()

class StrictProtocolTests(unittest.TestCase):
    def test_default_server_inventory_and_pre_device_refusals(self):
        reader=SimpleNamespace(status=Mock(return_value={'ok':True}),screen=Mock())
        server=BridgeServer(reader,'test-secret');thread=threading.Thread(target=server.serve_forever);thread.start()
        def rpc(method,params):
            req=Request(f'http://127.0.0.1:{server.server_port}/mcp',json.dumps(dict(jsonrpc='2.0',id=1,method=method,params=params)).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer test-secret'})
            with urlopen(req) as f:return json.load(f)
        try:
            tools=rpc('tools/list',{})['result']['tools'];self.assertEqual({t['name'] for t in tools},{'mumu_status','mumu_ui_inspect','mumu_ui_diagnostics','mumu_ui_find','mumu_ui_action','mumu_ui_unity_diagnostics'})
            for name,args in [('mumu_read_screen',{}),('mumu_control_inspect',{}),('mumu_find_profile_chat',{}),('mumu_ui_find',dict(selector={'text':'Написать'},timeout_ms=0,allow_fallback=True))]:self.assertIn('error',rpc('tools/call',dict(name=name,arguments=args)))
            reader.screen.assert_not_called();reader.status.assert_not_called()
            for t in tools:
                if 'allow_fallback' in t['inputSchema']['properties']:self.assertEqual(t['inputSchema']['properties']['allow_fallback']['enum'],[False])
        finally:server.shutdown();server.server_close();thread.join()
