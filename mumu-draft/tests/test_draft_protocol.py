import http.client,json,threading,unittest
import mumu_bridge as b
class Backend:
    def __init__(self):self.calls=[]
    def put_draft(self,**args):self.calls.append(args);return {'text':b.DRAFT_TEXT,'messages_sent':0}
class DraftProtocolTests(unittest.TestCase):
    def setUp(self):
        self.backend=Backend();self.server=b.BridgeServer(self.backend,'synthetic-key')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def call(self,args):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        req={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'mumu_put_approved_draft','arguments':args}}
        conn.request('POST','/mcp',json.dumps(req),{'Content-Type':'application/json','Authorization':'Bearer synthetic-key'})
        response=conn.getresponse();data=json.loads(response.read());conn.close();return data
    def test_valid_draft_dispatch(self):
        args={'expected_screen_sha256':'a'*64,'expected_name':'TEST_RECIPIENT'}
        r=self.call(args);self.assertNotIn('error',r);self.assertEqual(self.backend.calls,[args])
        self.assertIn('Как настроение?)',r['result']['content'][0]['text'])
    def test_arbitrary_text_argument_rejected(self):
        r=self.call({'expected_screen_sha256':'a'*64,'expected_name':'TEST_RECIPIENT','text':'OTHER'})
        self.assertIn('error',r);self.assertEqual(self.backend.calls,[])
    def test_missing_guard_rejected(self):
        r=self.call({'expected_name':'TEST_RECIPIENT'});self.assertIn('error',r);self.assertEqual(self.backend.calls,[])
    def test_bad_name_type_rejected(self):
        r=self.call({'expected_screen_sha256':'a'*64,'expected_name':[]});self.assertIn('error',r);self.assertEqual(self.backend.calls,[])
if __name__=='__main__':unittest.main()
