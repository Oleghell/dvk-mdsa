import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from PIL import Image
from mumu_bridge import AdbReader, BridgeError, BridgeServer, content_pixel_sha256, TOOLS, SERIAL, HELPER_COMPONENT

def png(color='white',size=(900,1600)):
    b=BytesIO();Image.new('RGB',size,color).save(b,format='PNG');return b.getvalue()

class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.adb=Path(self.temp.name)/'adb.exe';self.adb.touch()
        self.r=AdbReader(self.adb);self.r.helper_ready=True
        self.image=png();self.sha=content_pixel_sha256(self.image)
    def tearDown(self): self.temp.cleanup()
    def test_hash_ignores_status_clock_only(self):
        im=Image.new('RGB',(900,1600),'white');im.paste('black',(0,0,900,48));b=BytesIO();im.save(b,format='PNG')
        self.assertEqual(content_pixel_sha256(b.getvalue()),self.sha)
        im.putpixel((0,48),(0,0,0));b=BytesIO();im.save(b,format='PNG')
        self.assertNotEqual(content_pixel_sha256(b.getvalue()),self.sha)
    def test_wrong_size_refused(self):
        with self.assertRaises(BridgeError): content_pixel_sha256(png(size=(450,800)))
    def test_invalid_png_refused(self):
        with self.assertRaises(BridgeError): content_pixel_sha256(b'not png')
    def test_success_injection_not_transition_proof(self):
        with patch.object(self.r,'screen',return_value=self.image),patch.object(self.r,'_instrument',return_value=('input_injected','')) as action:
            result=self.r.navigate('tap',self.sha,100,200)
        action.assert_called_once_with('tap',self.sha,100,200)
        self.assertFalse(result['ui_transition_verified']);self.assertEqual(self.r.action_attempts,1)
    def test_stale_screen_no_instrumentation(self):
        with patch.object(self.r,'screen',return_value=self.image),patch.object(self.r,'_instrument') as action:
            with self.assertRaises(BridgeError): self.r.navigate('tap','0'*64,100,200)
        action.assert_not_called();self.assertEqual(self.r.action_attempts,0)
    def test_unknown_outcome_latches_stop(self):
        with patch.object(self.r,'screen',return_value=self.image),patch.object(self.r,'_instrument',side_effect=BridgeError('timeout')):
            with self.assertRaises(BridgeError): self.r.navigate('tap',self.sha,100,200)
        self.assertTrue(self.r.action_uncertain)
        with patch.object(self.r,'screen') as screen:
            with self.assertRaises(BridgeError): self.r.navigate('tap',self.sha,100,200)
        screen.assert_not_called()
    def test_android_refusal_does_not_latch_uncertainty(self):
        with patch.object(self.r,'screen',return_value=self.image),patch.object(self.r,'_instrument',return_value=('denied_screen_changed','')):
            with self.assertRaises(BridgeError): self.r.navigate('tap',self.sha,100,200)
        self.assertFalse(self.r.action_uncertain);self.assertEqual(self.r.action_attempts,1)
    def test_budget_exhausted(self):
        self.r.action_attempts=50
        with self.assertRaises(BridgeError): self.r.navigate('back',self.sha)
    def test_invalid_actions_and_coordinates(self):
        for action,x,y in [('send',1,100),('tap',1,47),('tap',900,100),('tap',1,1536),('tap',True,100),('back',1,0)]:
            with self.subTest(action=action,x=x,y=y),self.assertRaises(BridgeError): self.r.navigate(action,self.sha,x,y)
    def test_adb_arbitrary_shell_not_allowed(self):
        with patch('subprocess.run') as run:
            with self.assertRaises(BridgeError): self.r._run(['-s',SERIAL,'shell','input','tap','100','200'])
        run.assert_not_called()
    def test_adb_fixed_instrumentation_only(self):
        args=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','op','tap','-e','expected_content_sha256',self.sha,'-e','x','100','-e','y','200',HELPER_COMPONENT]
        with patch('subprocess.run') as run:
            run.return_value.returncode=0;run.return_value.stdout=b'ok'
            self.assertEqual(self.r._run(args),b'ok')
            self.assertNotIn('shell',run.call_args.kwargs)
        args[-1]='other/package'
        with self.assertRaises(BridgeError): self.r._run(args)
    def test_no_typing_or_send_loop_tool(self):
        self.assertEqual({t['name'] for t in TOOLS},{'mumu_status','mumu_read_screen','mumu_inspect_layout','mumu_navigate','mumu_open_profile_chat','mumu_leave_profile','mumu_prepare_greeting','mumu_finish_greeting_input','mumu_begin_profile','mumu_check_new_chat','mumu_send_prepared_greeting','mumu_review_visit','mumu_return_to_grid','mumu_check_city_search','mumu_focus_city_search','mumu_inspect_city_input','mumu_input_city','mumu_autotest_city','mumu_autofocus_city'})

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        class Reader:
            def navigate(self,**kwargs): return {'input_injected':True}
            def status(self): return {'test':True}
        self.server=BridgeServer(Reader(),'unit-secret')
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}/mcp'
    def tearDown(self): self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,name,args,auth='Bearer unit-secret'):
        data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}}).encode()
        req=Request(self.url,data,headers={'Content-Type':'application/json','Authorization':auth})
        with urlopen(req) as r:return json.load(r)
    def test_authentication_required(self):
        with self.assertRaises(HTTPError) as error:self.request('mumu_status',{},'')
        self.assertEqual(error.exception.code,401)
    def test_extra_arguments_refused(self):
        r=self.request('mumu_navigate',{'action':'back','expected_content_sha256':'0'*64,'x':0,'y':0,'shell':'anything'})
        self.assertEqual(r['error']['code'],-32602)
    def test_old_fixed_draft_not_exposed(self):
        self.assertEqual(self.request('mumu_put_approved_draft',{})['error']['code'],-32602)
    def test_back_requires_zero_coordinates(self):
        r=self.request('mumu_navigate',{'action':'back','expected_content_sha256':'0'*64,'x':1,'y':0})
        self.assertIn('error',r)
    def test_valid_navigation(self):
        r=self.request('mumu_navigate',{'action':'back','expected_content_sha256':'0'*64,'x':0,'y':0})
        self.assertTrue(json.loads(r['result']['content'][0]['text'])['input_injected'])
    def test_boolean_coordinate_refused(self):
        r=self.request('mumu_navigate',{'action':'tap','expected_content_sha256':'0'*64,'x':True,'y':100})
        self.assertIn('error',r)

if __name__=='__main__':unittest.main()
