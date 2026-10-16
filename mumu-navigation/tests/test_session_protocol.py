import json
import threading
import unittest
from urllib.request import Request, urlopen
from mumu_bridge import BridgeServer, TOOLS

class SessionProtocolTests(unittest.TestCase):
    def setUp(self):
        class Reader:
            def begin_profile(self,**kw):return {'called':'begin_profile',**kw}
            def check_new_chat(self,**kw):return {'called':'check_new_chat'}
            def send_prepared(self,**kw):return {'called':'send_prepared'}
            def review_visit(self,**kw):return {'called':'review_visit'}
            def return_to_grid(self,**kw):return {'called':'return_to_grid'}
        self.server=BridgeServer(Reader(),'test-only-key')
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,name,args):
        data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}}).encode()
        req=Request(f'http://127.0.0.1:{self.server.server_port}/mcp',data,headers={'Content-Type':'application/json','Authorization':'Bearer test-only-key'})
        with urlopen(req) as response:return json.load(response)
    def test_new_scoped_tools_route_correctly(self):
        for name in ('mumu_begin_profile','mumu_check_new_chat','mumu_send_prepared_greeting','mumu_review_visit','mumu_return_to_grid'):
            with self.subTest(name=name):
                args={'expected_content_sha256':'a'*64}
                if name=='mumu_begin_profile':args.update(x=100,y=200)
                if name=='mumu_review_visit':args.update(outcome='skipped')
                result=self.request(name,args)
                self.assertIn('result',result);self.assertNotIn('isError',result['result'])
    def test_extra_fields_and_invalid_hashes_refused(self):
        for args in ({'expected_content_sha256':'a'*64,'reset':True},{'expected_content_sha256':'wrong'},{}):
            self.assertEqual(self.request('mumu_send_prepared_greeting',args)['error']['code'],-32602)
    def test_profile_boolean_coordinate_refused(self):
        self.assertEqual(self.request('mumu_begin_profile',{'expected_content_sha256':'a'*64,'x':True,'y':200})['error']['code'],-32602)
    def test_invalid_review_outcome_refused(self):
        self.assertEqual(self.request('mumu_review_visit',{'expected_content_sha256':'a'*64,'outcome':'retry'})['error']['code'],-32602)
    def test_no_remote_start_reset_or_clear_history(self):
        names={tool['name'] for tool in TOOLS}
        for name in ('mumu_start_test','mumu_reset','mumu_clear_history'):
            self.assertNotIn(name,names)
            self.assertEqual(self.request(name,{})['error']['code'],-32602)
    def test_all_new_tools_have_strict_schemas(self):
        for tool in TOOLS:
            self.assertFalse(tool['inputSchema'].get('additionalProperties',True))

if __name__=='__main__':unittest.main()
