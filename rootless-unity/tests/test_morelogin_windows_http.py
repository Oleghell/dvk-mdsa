"""Offline Windows bridge, private-pipe and saved-key auth regression tests."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from morelogin_client import Client
from morelogin_common import CloudError
from morelogin_windows_http import WindowsOpener, SCRIPT, command
from morelogin_auth_check import check_saved

class Child:
    returncode=0
    def __init__(self,value):self.value=value;self.input=None;self.killed=False
    def communicate(self,payload=None,timeout=None):self.input=payload;return self.value,None
    def kill(self):self.killed=True

class WindowsTransport(unittest.TestCase):
    def request(self,path='/oauth2/token',data=b'{"client_secret":"SYNTHETIC-SECRET"}'):
        return urllib.request.Request('https://api.morelogin.com'+path,data=data,method='POST')
    def run_reply(self,reply,request=None):
        child=Child(json.dumps(reply).encode())
        with patch('morelogin_windows_http.command',return_value=['SYSTEM-POWERSHELL','FIXED-CODE']),patch('morelogin_windows_http.subprocess.Popen',return_value=child) as popen:
            value=WindowsOpener().open(request or self.request(),25)
        return value,child,popen
    def test_secret_only_goes_to_stdin_not_arguments_or_environment(self):
        value,child,popen=self.run_reply(dict(status=200,body=base64.b64encode(b'{"code":0}').decode()))
        self.assertEqual(value.read(),b'{"code":0}')
        self.assertIn(b'SYNTHETIC-SECRET',child.input)
        self.assertNotIn('SYNTHETIC-SECRET',repr(popen.call_args))
        self.assertEqual(popen.call_args.kwargs['stderr'],subprocess.DEVNULL)
        self.assertNotIn('shell',popen.call_args.kwargs)
        self.assertNotIn('env',popen.call_args.kwargs)
    def test_fixed_origin_and_endpoints(self):
        for u in ('http://api.morelogin.com/oauth2/token','https://other.test/oauth2/token','https://api.morelogin.com/cloudphone/updateAdb','https://api.morelogin.com/oauth2/token?secret=x'):
            with self.subTest(url=u),patch('morelogin_windows_http.subprocess.Popen') as popen,self.assertRaises(CloudError):
                WindowsOpener().open(urllib.request.Request(u,data=b'{}'),25)
            popen.assert_not_called()
    def test_redirect_is_error_never_followed(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:self.run_reply(dict(status=302,body='SECRET'))
        self.assertEqual(ctx.exception.code,302)
        self.assertEqual(ctx.exception.read(),b'')
    def test_native_http_error_keeps_status_without_server_text(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:self.run_reply(dict(status=403,body='SECRET'))
        self.assertEqual(ctx.exception.code,403)
        self.assertNotIn('SECRET',str(ctx.exception))
    def test_native_errors_allowlist(self):
        for code in ('api-tls','api-dns','api-timeout','api-network','api-response'):
            with self.assertRaisesRegex(CloudError,'^'+code+'$'):self.run_reply(dict(error=code))
        with self.assertRaisesRegex(CloudError,'^api-transport$'):self.run_reply(dict(error='SECRET'))
    def test_response_validation(self):
        for obj in ({'status':True,'body':''},{'status':200,'body':'INVALID BASE64'},{'status':200}):
            with self.assertRaises(CloudError):self.run_reply(obj)
    def test_timeout_kills_only_owned_process(self):
        child=Child(b'');calls=[]
        def communicate(payload=None,timeout=None):
            calls.append(payload)
            if len(calls)==1:raise subprocess.TimeoutExpired('fixed-command',35)
            return b'',None
        child.communicate=communicate
        with patch('morelogin_windows_http.command',return_value=['FIXED']),patch('morelogin_windows_http.subprocess.Popen',return_value=child),self.assertRaisesRegex(CloudError,'api-timeout'):
            WindowsOpener().open(self.request(),25)
        self.assertTrue(child.killed)
        self.assertEqual(len(calls),2)
    def test_authorization_header_is_data_not_code(self):
        req=self.request('/cloudphone/batchAdbInfo',b'{"envIds":["101"]}')
        req.add_header('Authorization','Bearer synthetic-token-123456789')
        _,child,popen=self.run_reply(dict(status=200,body='e30='),req)
        self.assertEqual(json.loads(child.input)['token'],'synthetic-token-123456789')
        self.assertNotIn('synthetic-token',repr(popen.call_args))
    def test_windows_platform_selects_native_no_urllib_fallback(self):
        with patch('morelogin_client.sys.platform','win32'):
            self.assertIsInstance(Client('app','synthetic-secret').opener,WindowsOpener)
    def test_script_security_invariants(self):
        for text in ('$request.Proxy=$null','$request.AllowAutoRedirect=$false','https://api.morelogin.com','[Console]::In.ReadToEnd()'):
            self.assertIn(text,SCRIPT)
        for text in ('ServerCertificateValidationCallback','Invoke-Expression','Start-Transcript','Set-Content','Write-Host','Write-Output'):
            self.assertNotIn(text,SCRIPT)
    def test_native_network_retry_bounded_and_staged(self):
        class Opener:
            calls=0
            def open(self,*_,**__):self.calls+=1;raise CloudError('api-network')
        op=Opener()
        with patch('morelogin_client.time.sleep'),self.assertRaises(CloudError) as ctx:
            Client('app','synthetic-secret',opener=op).authorize()
        self.assertEqual(op.calls,3)
        self.assertEqual(ctx.exception.stage,'auth')
    def test_authorize_only_never_queries_phones(self):
        calls=[]
        class Opener:
            def open(self,request,**_):
                calls.append(request.full_url)
                return io.BytesIO(b'{"code":0,"data":{"access_token":"synthetic-token-123456789"}}')
        self.assertEqual(Client('app','synthetic-secret',opener=Opener()).authorize(),'synthetic-token-123456789')
        self.assertEqual(calls,['https://api.morelogin.com/oauth2/token'])
    @unittest.skipUnless(sys.platform=='win32','Requires system Windows PowerShell')
    def test_actual_windows_helper_private_pipe_offline(self):
        # Invalid endpoint is rejected before any HTTP operation, no account needed.
        payload=json.dumps({'path':'/not-allowed','body':'{}','token':None}).encode()
        p=subprocess.run(command(),input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        self.assertEqual(p.returncode,0)
        self.assertEqual(json.loads(p.stdout.decode('utf-8-sig')),{'error':'api-unavailable'})
    @unittest.skipUnless(sys.platform=='win32','Requires system Windows PowerShell')
    def test_actual_system_powershell_parses_fixed_script_offline(self):
        cmd=command()
        parser="$ErrorActionPreference='Stop';$s=[Console]::In.ReadToEnd();$null=[ScriptBlock]::Create($s);[Console]::Out.Write('SYNTAX-OK')"
        cmd[-1]=base64.b64encode(parser.encode('utf-16-le')).decode()
        p=subprocess.run(cmd,input=SCRIPT.encode('utf-8'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        self.assertEqual(p.returncode,0)
        self.assertEqual(p.stdout,b'SYNTAX-OK')

class SavedCheck(unittest.TestCase):
    def test_saved_keys_used_success_report_never_contains_token(self):
        calls=[]
        class Fake:
            def __init__(self,a,k):calls.append((a,k))
            def authorize(self):return 'SECRET-TOKEN'
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'report.json'
            text=check_saved(loader=lambda:('saved-id','saved-secret'),factory=Fake,path=p)
            self.assertIn('успешна',text)
            self.assertEqual(calls,[('saved-id','saved-secret')])
            self.assertNotIn('SECRET',p.read_text(encoding='utf-8'))
            self.assertEqual(json.loads(p.read_text(encoding='utf-8'))['result'],'auth-ok')
    def test_failure_has_stage_status_no_secrets(self):
        class Fake:
            def __init__(self,*_):pass
            def authorize(self):raise CloudError('api-http',stage='auth',http_status=403)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'report.json'
            self.assertIn('403',check_saved(loader=lambda:('id','secret'),factory=Fake,path=p))
            self.assertEqual(json.loads(p.read_text(encoding='utf-8'))['http_status'],403)
    def test_load_failure_does_not_open_client(self):
        def loader():raise CloudError('configuration')
        def factory(*_):raise AssertionError('Must not call network')
        with tempfile.TemporaryDirectory() as temp:
            self.assertIn('настройки',check_saved(loader=loader,factory=factory,path=Path(temp)/'report.json'))

if __name__=='__main__':unittest.main()
