"""Synthetic smart-socket transport/boot recovery; no device or credentials."""
import os,tempfile,threading,unittest,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
import mumu_fast_adb as fast
from mumu_worker import check_recovery_device
from target_only import TargetOnlyAdb
from test_device import TARGET,TestError
from startup_failure import checkpoint,recoverable_adb
from mumu_recovery import Repair,run
from assistant_store import StateError
from assistant_settings import Settings
from assistant_monitor import REPORT
from assistant_error_notify import diagnostic_json
from test_mumu_fast_adb import Sock,BOOT,packet

class FailSock(Sock):
    def __init__(self,body):super().__init__();self.body=body
    def sendall(self,value):self.sent.append(value);self.buffer=b'FAIL'+('%04x'%len(self.body)).encode()+self.body

class Transport(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.folder=Path(t.name)
        self.exe=str(self.folder/'adb.exe');Path(self.exe).write_text('synthetic')
        env=patch.dict(os.environ,{'DVK_MUMU_MULTI':'1'});env.start();self.addCleanup(env.stop)
    def check(self,factory,boot=BOOT):
        with patch.object(TargetOnlyAdb,'run',MagicMock(return_value='already connected')) as cli:
            with fast.transport(TARGET,socket_factory=factory):check_recovery_device(self.exe,self.folder,TARGET,boot)
            self.assertEqual(cli.call_count,1);self.assertEqual(cli.call_args.args[1],['connect',TARGET])
    def test_reconnect_same_endpoint_before_same_boot_check(self):
        self.check(lambda *a,**kw:Sock())
    def test_socket_failure_retains_retryable_closed_reason(self):
        def socket(*a,**kw):raise ConnectionRefusedError('PRIVATE IP PATH')
        with self.assertRaises(TestError) as err:self.check(socket)
        e=err.exception._dvk_failure
        self.assertEqual(e['stage'],'device-recheck');self.assertEqual(e['adb_check'],'test-identity')
        self.assertEqual(e['adb_reason'],'connection-failed');self.assertTrue(recoverable_adb(e))
        self.assertNotIn('PRIVATE',json.dumps(e))
    def test_service_failure_categories_not_raw_body(self):
        for body,expected,retry in [(b'device offline','device-offline',True),
                                    (b'device not found','device-not-found',True),
                                    (b'unauthorized PRIVATE TOKEN','device-unauthorized',False),
                                    (b'permission denied PRIVATE','permission-denied',False),
                                    (b'PRIVATE UNKNOWN','command-failed',False)]:
            with self.subTest(reason=expected),self.assertRaises(TestError) as err:
                self.check(lambda *a,body=body,**kw:FailSock(body))
            e=err.exception._dvk_failure
            self.assertEqual(e['adb_reason'],expected);self.assertEqual(recoverable_adb(e),retry)
            self.assertNotIn('PRIVATE',json.dumps(e))
    def test_valid_different_boot_is_fatal_never_adopted(self):
        with self.assertRaises(TestError) as err:
            self.check(lambda *a,**kw:Sock(reply=packet(1,b'87654321-1234-1234-1234-123456789abc\n')+packet(3,b'\0')))
        self.assertFalse(recoverable_adb(err.exception._dvk_failure))
    def test_repair_backoff_not_fatal_for_socket_loss(self):
        def socket(*a,**kw):raise ConnectionRefusedError('PRIVATE')
        repair=Repair(SimpleNamespace(),threading.Event(),None,reader=MagicMock(),navigator=MagicMock(),
                      recheck=lambda:self.check(socket))
        with self.assertRaises(ConnectionError):repair()
        repair.reader.assert_not_called();repair.navigator.assert_not_called()
    def test_blocked_recheck_keeps_evidence_in_final_json(self):
        def denied():self.check(lambda *a,**kw:FailSock(b'unauthorized PRIVATE'))
        repair=Repair(SimpleNamespace(),threading.Event(),None,recheck=denied)
        with self.assertRaises(StateError) as err:repair()
        self.assertEqual(err.exception._dvk_failure['adb_reason'],'device-unauthorized')
        out=json.loads(diagnostic_json(dict(recovery_failure=dict(last_preparation_failure=err.exception._dvk_failure))))
        self.assertNotIn('PRIVATE',json.dumps(out))
