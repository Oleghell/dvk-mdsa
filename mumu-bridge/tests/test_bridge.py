import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import mumu_bridge as b

class FakeReader:
    def status(self): return {'connected': True, 'read_only': True}
    def screen(self): return b'\x89PNG\r\n\x1a\n-test-only-not-a-real-screenshot'

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.server = b.BridgeServer(FakeReader(), 'unit-test-key-not-a-real-secret')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
    def call(self, req, auth=True, origin=None, path='/mcp', method='POST'):
        headers={'Content-Type':'application/json'}
        if auth: headers['Authorization']='Bearer unit-test-key-not-a-real-secret' if auth is True else auth
        if origin: headers['Origin']=origin
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        conn.request(method,path,json.dumps(req),headers)
        response=conn.getresponse(); data=response.read(); status=response.status; conn.close()
        return status,json.loads(data) if data else None
    def rpc(self, method, params=None):
        return self.call({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})
    def test_loopback(self): self.assertEqual(self.server.server_address[0],'127.0.0.1')
    def test_no_auth(self): self.assertEqual(self.call({},False)[0],401)
    def test_wrong_auth(self): self.assertEqual(self.call({},'Bearer wrong')[0],401)
    def test_revoke(self):
        self.server.token=''; self.assertEqual(self.call({})[0],401)
    def test_initialize(self):
        status,obj=self.rpc('initialize',{'protocolVersion':'2025-03-26'})
        self.assertEqual(status,200); self.assertEqual(obj['result']['protocolVersion'],'2025-03-26')
    def test_notification(self): self.assertEqual(self.call({'jsonrpc':'2.0','method':'notifications/initialized'})[0],202)
    def test_tools(self):
        _,obj=self.rpc('tools/list'); self.assertEqual([t['name'] for t in obj['result']['tools']],['mumu_status','mumu_read_screen'])
        self.assertTrue(all(t['annotations']['readOnlyHint'] for t in obj['result']['tools']))
    def test_status(self):
        _,obj=self.rpc('tools/call',{'name':'mumu_status'}); self.assertIn('connected',obj['result']['content'][0]['text'])
    def test_image(self):
        _,obj=self.rpc('tools/call',{'name':'mumu_read_screen'}); self.assertEqual(base64.b64decode(obj['result']['content'][1]['data']),FakeReader().screen())
    def test_no_shell(self): self.assertIn('error',self.rpc('tools/call',{'name':'shell','arguments':{'command':'id'}})[1])
    def test_no_args(self): self.assertIn('error',self.rpc('tools/call',{'name':'mumu_status','arguments':{'port':5556}})[1])
    def test_origin(self): self.assertEqual(self.call({},origin='https://evil.example')[0],403)
    def test_path(self): self.assertEqual(self.call({},path='/files')[0],404)
    def test_batch(self): self.assertEqual(self.call([])[0],400)
    def test_get(self): self.assertEqual(self.call({},method='GET')[0],405)
    def test_unknown_method(self): self.assertEqual(self.rpc('execute')[1]['error']['code'],-32601)
    def test_nonobject_params(self):
        self.assertIn('error',self.call({'jsonrpc':'2.0','id':1,'method':'tools/call','params':'bad'})[1])
    def test_busy(self):
        with self.server.device_lock:
            self.assertIn('error',self.rpc('tools/call',{'name':'mumu_read_screen'})[1])
    def test_backend_error_sanitized(self):
        self.server.reader.status=lambda: (_ for _ in ()).throw(RuntimeError('private diagnostic'))
        _,obj=self.rpc('tools/call',{'name':'mumu_status'}); self.assertNotIn('private',str(obj)); self.assertTrue(obj['result']['isError'])

class AdbTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); path=Path(self.temp.name)/'adb.exe'; path.touch(); self.reader=b.AdbReader(path)
    def tearDown(self): self.temp.cleanup()
    def test_reject_command(self):
        with patch('subprocess.run') as runner:
            with self.assertRaises(b.BridgeError): self.reader._run(['-s',b.SERIAL,'shell','input','tap','1','2'])
            runner.assert_not_called()
    def test_reject_other_target(self):
        with self.assertRaises(b.BridgeError): self.reader._run(['connect','0.0.0.0:5555'])
    def test_foreground(self):
        self.reader._run=lambda _: b'mCurrentFocus=Window{abc u0 drug.vokrug/.Main}'
        self.reader._foreground()
    def test_wrong_foreground(self):
        self.reader._run=lambda _: b'mCurrentFocus=Window{abc u0 com.android.settings/.Main}'
        with self.assertRaises(b.BridgeError): self.reader._foreground()
    def test_missing_foreground(self):
        self.reader._run=lambda _: b'mCurrentFocus=null'
        with self.assertRaises(b.BridgeError): self.reader._foreground()
    def test_screen_rechecks_foreground(self):
        self.reader.status=lambda: {}
        with patch.object(self.reader,'_foreground',side_effect=[None,b.BridgeError('changed app')]) as fg:
            self.reader._run=lambda _: FakeReader().screen()
            with self.assertRaises(b.BridgeError): self.reader.screen()
            self.assertEqual(fg.call_count,2)
    def test_invalid_png(self):
        self.reader.status=lambda: {}; self.reader._foreground=lambda: None; self.reader._run=lambda _: b'not image'
        with self.assertRaises(b.BridgeError): self.reader.screen()

if __name__=='__main__': unittest.main()
