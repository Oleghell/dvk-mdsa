"""Synthetic direct-ADB tests: no cloud, credentials or Android device."""
from contextlib import contextmanager
import io,json,os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from morelogin_client import DirectPlan,plan
from morelogin_common import CloudError
import morelogin_direct as direct
from assistant_settings import Settings

BOOT='12345678-1234-1234-1234-123456789abc'
def entry(id='101',**changes):
    value=dict(id=id,supportAdb=True,enableAdb=True,envStatus=4,remark='',command=None,
        adbIp='8.8.8.8',adbPort='12345',adbPassword='123456')
    value.update(changes);return value

class PlanTests(unittest.TestCase):
    def test_direct_api_fields_and_password_not_in_repr(self):
        p=plan(entry(),'101')
        self.assertIsInstance(p,DirectPlan)
        self.assertEqual((p.host,p.adb_port,p.password),('8.8.8.8',12345,'123456'))
        self.assertNotIn('123456',repr(p))
    def test_exact_direct_command_optional_never_executed(self):
        for command in ('',None,'adb connect 8.8.8.8:12345','adb.exe connect 8.8.8.8:12345'):
            self.assertIsInstance(plan(entry(command=command),'101'),DirectPlan)
    def test_malformed_ssh_never_falls_back_to_direct(self):
        for c in ('ssh broken','ssh user@host -p 22','adb connect 8.8.8.8:12345; whoami','adb connect 8.8.4.4:12345'):
            with self.assertRaises(CloudError):plan(entry(command=c),'101')
    def test_no_implicit_device_private_target_or_shell_injection(self):
        for values in ({'adbIp':'127.0.0.1'},{'adbIp':'192.168.1.2'},{'adbIp':'0.0.0.0'},{'adbIp':'224.0.0.1'},{'adbIp':'example.test'},
            {'adbPort':'0'},{'adbPort':'65536'},{'adbPassword':None},{'adbPassword':'123456; rm -rf /'},
            {'adbPassword':'reboot'},{'adbPassword':'1234\n5678'},{'adbPassword':'1'*33}):
            with self.subTest(value=values),self.assertRaises(CloudError):plan(entry(**values),'101')
    def test_wrong_id_and_offline_stay_rejected(self):
        with self.assertRaises(CloudError):plan(entry(),'202')
        for v in ({'enableAdb':False},{'envStatus':2},{'remark':'offline'}):
            with self.assertRaises(CloudError):plan(entry(**v),'101')

class SocketProtocol(unittest.TestCase):
    def fake(self,commands,*,failed=False):
        class Sock:
            def __init__(self):self.buf=b'';self.steps=0
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def settimeout(self,_):pass
            def sendall(self,value):
                if value==b'exit\n':return
                size=int(value[:4],16);text=value[4:].decode()
                assert size==len(value[4:]);commands.append(text)
                if text.startswith('host:transport:'):
                    self.buf+=b'OKAY';return
                if failed:self.buf+=b'FAIL0006SECRET';return
                self.buf+=b'OKAY'
                if text=='shell:cat /proc/sys/kernel/random/boot_id':self.buf+=(BOOT+'\n').encode()
                elif text=='shell:getprop sys.boot_completed':self.buf+=b'1\n'
            def recv(self,n):v=self.buf[:n];self.buf=self.buf[n:];return v
        def factory(address,timeout):
            self.assertEqual(address,('127.0.0.1',5037));return Sock()
        return factory
    def test_exact_adb_transport_and_shell_code_frames_no_implicit_target(self):
        commands=[]
        factory=self.fake(commands)
        direct._shell('127.0.0.1:23456','authenticate',code='123456',socket_factory=factory)
        boot=direct._shell('127.0.0.1:23456','boot-id',socket_factory=factory)
        self.assertEqual(boot,BOOT)
        self.assertEqual(commands[:2],['host:transport:127.0.0.1:23456','shell:123456'])
    def test_fail_body_not_exposed(self):
        with self.assertRaises(CloudError) as ctx:
            direct._shell('127.0.0.1:23456','authenticate',code='123456',socket_factory=self.fake([],failed=True))
        self.assertEqual(str(ctx.exception),'adb-auth-failed')
    def test_code_rejects_shell_commands_before_socket(self):
        with patch('morelogin_direct.socket.create_connection') as connect:
            with self.assertRaises(CloudError):direct._shell('127.0.0.1:23456','authenticate',code='reboot')
            connect.assert_not_called()
    def test_authentication_requires_boot_identity_and_completed_android(self):
        with patch('morelogin_direct._shell',side_effect=[None,BOOT,'1']):
            self.assertEqual(direct.authenticate('127.0.0.1:23456','123456'),BOOT)
        with patch('morelogin_direct._shell',side_effect=[None,'wrong-device-response']),self.assertRaises(CloudError):
            direct.authenticate('127.0.0.1:23456','123456')
        with patch('morelogin_direct._shell',side_effect=[None,BOOT,'0']),self.assertRaisesRegex(CloudError,'device-not-ready'):
            direct.authenticate('127.0.0.1:23456','123456')
    def test_cancelled_does_not_open_socket(self):
        def fail(*a,**kw):raise AssertionError('Must not open socket')
        with self.assertRaisesRegex(CloudError,'cancelled'):
            direct._shell('127.0.0.1:23456','boot-id',cancelled=lambda:True,socket_factory=fail)

class DirectLifecycle(unittest.TestCase):
    def test_only_owned_serial_disconnects_after_auth_failure(self):
        @contextmanager
        def fake_relay(*_):yield '127.0.0.1:23456'
        with patch('morelogin_direct.relay',fake_relay),patch('morelogin_direct._adb') as adb,patch('morelogin_direct.authenticate',side_effect=CloudError('adb-auth-failed')):
            with self.assertRaises(CloudError):
                with direct.connection(plan(entry(),'101'),'fake-adb'):pass
            self.assertEqual([x.args[1:] for x in adb.call_args_list],[('connect','127.0.0.1:23456'),('disconnect','127.0.0.1:23456')])
    def test_adb_arguments_do_not_contain_connection_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'adb';p.write_text('synthetic',encoding='utf-8')
            with patch('morelogin_direct.subprocess.run',return_value=type('Result',(),{'returncode':0})()) as run:
                direct._adb(str(p),'connect','127.0.0.1:23456')
                args=run.call_args
                self.assertEqual(args.args[0],[str(p),'connect','127.0.0.1:23456'])
                self.assertNotIn('123456',repr(args))
                self.assertFalse(args.kwargs['shell'])
                self.assertEqual(args.kwargs['stdout'],subprocess.DEVNULL)
                self.assertEqual(args.kwargs['env']['ADB_SERVER_SOCKET'],'tcp:localhost:5037')
    def test_adb_global_or_arbitrary_operation_refused(self):
        for operation,serial in [('kill-server','127.0.0.1:23456'),('disconnect',''),('connect','8.8.8.8:12345')]:
            with self.assertRaises(CloudError):direct._adb('none',operation,serial)
    def test_two_relays_are_separate_loopback_and_forward_only_selected_endpoint(self):
        class Echo(socketserver.BaseRequestHandler):
            def handle(self):self.request.sendall(self.request.recv(100))
        server=socketserver.ThreadingTCPServer(('127.0.0.1',0),Echo)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        selected=[]
        def factory(address,timeout):
            selected.append(address)
            return socket.create_connection(server.server_address,timeout=timeout)
        p=DirectPlan('8.8.8.8',12345,'123456')
        try:
            with direct.relay(p,socket_factory=factory) as a,direct.relay(p,socket_factory=factory) as b:
                self.assertNotEqual(a,b)
                for serial in (a,b):
                    host,port=serial.split(':');self.assertEqual(host,'127.0.0.1')
                    with socket.create_connection((host,int(port)),timeout=3) as sock:
                        sock.sendall(b'hello');self.assertEqual(sock.recv(5),b'hello')
            self.assertEqual(selected,[('8.8.8.8',12345)]*2)
        finally:server.shutdown();server.server_close();t.join(timeout=2)
    def test_supervisor_direct_has_no_ssh_pin_but_ssh_still_requires_one(self):
        from morelogin_supervisor import run
        spawned=[];events=[]
        run(Settings(),['101'],{}, {'101':entry()},'inbox',threading.Event(),lambda *x:events.append(x),target=lambda spec,*_:spawned.append(spec))
        self.assertEqual(len(spawned),1);self.assertIsNone(spawned[0]['fingerprint'])
        self.assertEqual(events,[])
        self.assertEqual(spawned[0]['id'],'101')
    def test_worker_direct_chooses_direct_not_ssh_and_still_binds_loopback(self):
        import morelogin_worker as worker
        @contextmanager
        def direct_context(*args):yield '127.0.0.1:23456'
        spec={'id':'101','entry':entry(),'fingerprint':None,'settings':{'adb':'test-adb'}}
        with patch('morelogin_direct.connection',direct_context),patch('morelogin_worker.configure_target',side_effect=CloudError('cancelled')) as bind,patch('morelogin_ssh.tunnel') as ssh:
            with self.assertRaisesRegex(CloudError,'cancelled'):worker.run(spec,threading.Event(),lambda _:None)
            bind.assert_called_once_with('127.0.0.1:23456','101');ssh.assert_not_called()

if __name__=='__main__':unittest.main()
