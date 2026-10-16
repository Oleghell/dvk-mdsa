import json
import threading
import unittest
from urllib.request import Request, urlopen
from mumu_bridge import BridgeServer, TOOLS

class SessionProtocolTests(unittest.TestCase):
    def setUp(self):
        class Reader:
            def control_inspect(self):return {'called':'control_inspect'}
            def control_execute(self,name,args):return {'called':name,**args}
            def autotest_city(self):return {'called':'autotest_city'}
            def autofocus_city(self,**kw):return {'called':'autofocus_city',**kw}
            def inspect_city_input(self):return {'called':'inspect_city_input'}
            def input_city(self,**kw):return {'called':'input_city',**kw}
            def check_city_search(self,**kw):return {'called':'check_city_search'}
            def focus_city_search(self,**kw):return {'called':'focus_city_search'}
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
        for name in ('mumu_begin_profile','mumu_check_new_chat','mumu_send_prepared_greeting','mumu_review_visit','mumu_return_to_grid','mumu_check_city_search','mumu_focus_city_search'):
            with self.subTest(name=name):
                args={'expected_content_sha256':'a'*64}
                if name=='mumu_begin_profile':args.update(x=100,y=200)
                if name=='mumu_review_visit':args.update(outcome='skipped')
                result=self.request(name,args)
                self.assertIn('result',result);self.assertNotIn('isError',result['result'])
    def test_extra_fields_and_invalid_hashes_refused(self):
        for args in ({'expected_content_sha256':'a'*64,'reset':True},{'expected_content_sha256':'wrong'},{}):
            self.assertEqual(self.request('mumu_send_prepared_greeting',args)['error']['code'],-32602)
    def test_native_city_tools_route_only_strict_catalog_indices(self):
        self.assertNotIn('isError',self.request('mumu_inspect_city_input',{})['result'])
        args={'expected_city_context_sha256':'a'*64,'city_index':0,'previous_index':-1}
        self.assertNotIn('isError',self.request('mumu_input_city',args)['result'])
        for extra in ({'text':'Нальчик'},{'city_index':True},{'city_index':30},{'previous_index':False},
                      {'previous_index':-2},{'expected_city_context_sha256':'wrong'}):
            self.assertEqual(self.request('mumu_input_city',{**args,**extra})['error']['code'],-32602)
        self.assertEqual(self.request('mumu_inspect_city_input',{'city_index':0})['error']['code'],-32602)

    def test_city_tools_reject_arbitrary_text_coordinates_and_extra_args(self):
        for name in ('mumu_check_city_search','mumu_focus_city_search'):
            for extra in ({'text':'Нальчик'},{'x':400,'y':236},{'reset':True}):
                args={'expected_content_sha256':'a'*64,**extra}
                self.assertEqual(self.request(name,args)['error']['code'],-32602)
            for args in ({},{'expected_content_sha256':'bad'}):
                self.assertEqual(self.request(name,args)['error']['code'],-32602)

    def test_autotest_tools_strict_routing_and_annotations(self):
        self.assertNotIn('isError',self.request('mumu_autotest_city',{})['result'])
        args={'expected_city_context_sha256':'a'*64}
        self.assertNotIn('isError',self.request('mumu_autofocus_city',args)['result'])
        for extra in ({'text':'hello'},{'x':400,'y':236},{'script':'pass'},{'maxtries':99},{'reset':True}):
            self.assertEqual(self.request('mumu_autotest_city',extra)['error']['code'],-32602)
            self.assertEqual(self.request('mumu_autofocus_city',{**args,**extra})['error']['code'],-32602)
        for bad in ({},{'expected_city_context_sha256':'bad'},{'expected_city_context_sha256':True}):
            self.assertEqual(self.request('mumu_autofocus_city',bad)['error']['code'],-32602)
        tools={t['name']:t for t in TOOLS}
        self.assertTrue(tools['mumu_autotest_city']['annotations']['readOnlyHint'])
        self.assertFalse(tools['mumu_autofocus_city']['annotations']['readOnlyHint'])

    def test_universal_tools_route_strictly_without_remote_enable(self):
        self.assertNotIn('isError',self.request('mumu_control_inspect',{})['result'])
        args={'action_id':'b'*32,'expected_content_sha256':'a'*64,'key':'BACK'}
        self.assertNotIn('isError',self.request('mumu_control_key',args)['result'])
        for extra in ({'shell':'x'},{'enable':True},{'reset':True},{'key':'HOME'}):
            self.assertEqual(self.request('mumu_control_key',{**args,**extra})['error']['code'],-32602)
        for name in ('mumu_control_enable','mumu_install_apk','mumu_shell'):
            self.assertEqual(self.request(name,{})['error']['code'],-32602)

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
