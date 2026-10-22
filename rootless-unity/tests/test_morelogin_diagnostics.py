"""Offline regression tests: no credentials, live API or Android."""
import ast
import io
import json
from pathlib import Path
import queue
import socket
import ssl
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from morelogin_common import CloudError
from morelogin_client import Client
from morelogin_diagnostics import diagnostic, describe, save_failure, completion_text

class Opener:
    def __init__(self, *results): self.results=list(results);self.calls=0
    def open(self, request, timeout):
        self.calls+=1
        value=self.results.pop(0)
        if isinstance(value,Exception):raise value
        return io.BytesIO(value)

def response(value):return json.dumps(value).encode()

class Diagnostics(unittest.TestCase):
    def invoke(self, opener):
        with patch('morelogin_client.time.sleep'):
            return Client('app','synthetic-secret',opener=opener).post('/oauth2/token',{})
    def test_http_auth_status_is_safe_and_not_retried(self):
        for code in (400,401,403,404):
            with self.subTest(code=code):
                op=Opener(urllib.error.HTTPError('SECRET-URL',code,'SECRET-MSG',{'SECRET':'HEADER'},io.BytesIO(b'SECRET-BODY')))
                with self.assertRaises(CloudError) as ctx:self.invoke(op)
                self.assertEqual(op.calls,1)
                self.assertEqual(diagnostic(ctx.exception),dict(code='api-http',stage='auth',http_status=code,service_code=None))
                self.assertNotIn('SECRET',describe(ctx.exception))
    def test_temporary_http_retries_bounded(self):
        for status in (429,500,502,503,504):
            errors=[urllib.error.HTTPError('secret',status,'secret',{},io.BytesIO(b'secret')) for _ in range(3)]
            op=Opener(*errors)
            with self.assertRaises(CloudError) as ctx:self.invoke(op)
            self.assertEqual(op.calls,3)
            self.assertEqual(ctx.exception.http_status,status)
    def test_network_recovers_without_changing_endpoint(self):
        op=Opener(urllib.error.URLError(socket.gaierror('secret')),response({'code':0,'data':{}}))
        self.assertEqual(self.invoke(op),{})
        self.assertEqual(op.calls,2)
    def test_network_errors_classified(self):
        for reason,code,attempts in [(socket.gaierror('SECRET'),'api-dns',3),(TimeoutError('SECRET'),'api-timeout',3),(ConnectionRefusedError('SECRET'),'api-network',3),(ssl.SSLCertVerificationError('SECRET'),'api-tls',1)]:
            op=Opener(*[urllib.error.URLError(reason) for _ in range(attempts)])
            with self.assertRaises(CloudError) as ctx:self.invoke(op)
            self.assertEqual(ctx.exception.code,code)
            self.assertEqual(op.calls,attempts)
            self.assertNotIn('SECRET',describe(ctx.exception))
    def test_business_error_numeric_only(self):
        op=Opener(response({'code':35002,'msg':'SYNTHETIC-SECRET'}))
        with self.assertRaises(CloudError) as ctx:self.invoke(op)
        self.assertEqual(ctx.exception.service_code,35002)
        self.assertEqual(op.calls,1)
        self.assertNotIn('SYNTHETIC-SECRET',json.dumps(diagnostic(ctx.exception)))
    def test_invalid_response_no_retry(self):
        for value in (b'<html>SECRET</html>', b'[]',b'{"code":true,"data":{}}',b'{"code":0}',b'\xff'):
            op=Opener(value)
            with self.assertRaises(CloudError) as ctx:self.invoke(op)
            self.assertEqual(ctx.exception.code,'api-response')
            self.assertEqual(op.calls,1)
    def test_adb_stage(self):
        op=Opener(response({'code':0,'data':{'access_token':'synthetic-token-0123456789'}}),urllib.error.HTTPError('secret',403,'secret',{},io.BytesIO()))
        with self.assertRaises(CloudError) as ctx:Client('app','synthetic-secret',opener=op).query(['101'])
        self.assertEqual(ctx.exception.stage,'adb-info')
    def test_shape_error_stage(self):
        op=Opener(response({'code':0,'data':{'access_token':'synthetic-token-0123456789'}}),response({'code':0,'data':{}}))
        with self.assertRaises(CloudError) as ctx:Client('app','synthetic-secret',opener=op).query(['101'])
        self.assertEqual(ctx.exception.stage,'adb-info')
    def test_unexpected_error_not_exported(self):
        op=Opener(RuntimeError('APP-ID SECRET TOKEN password'))
        with self.assertRaises(CloudError) as ctx:self.invoke(op)
        self.assertEqual(ctx.exception.code,'api-unavailable')
        self.assertNotIn('SECRET',describe(ctx.exception))
    def test_diagnostic_report_contains_only_allowlisted_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'report.json'
            self.assertTrue(save_failure(['101','202'],RuntimeError('SECRET'),path=p))
            data=json.loads(p.read_text())
            self.assertEqual(set(data),{'status','phone_ids','code','stage','http_status','service_code'})
            self.assertNotIn('SECRET',p.read_text())
    def test_invalid_diagnostic_metadata_discarded(self):
        e=CloudError('api-http',stage='SECRET',http_status='SECRET',service_code='SECRET')
        self.assertEqual(diagnostic(e),dict(code='api-http',stage=None,http_status=None,service_code=None))
    def test_unwritable_report_does_not_mask_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'file';p.write_text('x')
            self.assertFalse(save_failure(['101'],CloudError('api-http'),path=p/'report.json'))
    def test_error_completion_never_claims_success(self):
        self.assertIn('ошибкой',completion_text(True))
        self.assertNotEqual(completion_text(False),completion_text(True))
    def test_actual_gui_event_loop_preserves_failure_and_marks_phone(self):
        # Execute actual poll body without launching Tk or importing the engine.
        path=Path(__file__).resolve().parents[1]/'morelogin_app.py'
        tree=ast.parse(path.read_text())
        launch=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='launch')
        poll=next(n for n in launch.body if isinstance(n,ast.FunctionDef) and n.name=='poll')
        poll.body=[ast.Global(names=n.names) if isinstance(n,ast.Nonlocal) else n for n in poll.body]
        mod=ast.fix_missing_locations(ast.Module(body=[poll],type_ignores=[]))
        class Status:
            def set(self,value):self.value=value
        class Root:
            def after(self,*_):pass
        events=queue.Queue();rows={};status=Status()
        events.put(('phone',('101','error','Авторизация API: HTTP 403')))
        events.put(('error','Авторизация API: HTTP 403'))
        events.put(('check-done',True))
        scope=dict(events=events,status=status,busy=True,set_phone=lambda k,v:rows.update({k:v}),completion_text=completion_text,refresh=lambda:None,root=Root())
        exec(compile(mod,str(path),'exec'),scope)
        scope['poll']()
        self.assertIn('HTTP 403',rows['101'])
        self.assertIn('ошибкой',status.value)
        self.assertFalse(scope['busy'])

if __name__=='__main__':unittest.main()
