import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import adb_evidence as e
import diagnose_device as d
from test_device import TestError,TARGET,WORKING,BOOT_ID,PACKAGE


class Evidence(unittest.TestCase):
    def test_fixed_labels_not_arbitrary_arguments(self):
        cases=[(['version'],'adb-version'),(['connect',WORKING],'working-connect'),
               (['connect',TARGET],'test-connect'),(['-s',TARGET,'get-state'],'test-state'),
               (['-s',WORKING,'shell','cat',BOOT_ID],'working-identity'),
               (['-s',TARGET,'shell','pm','list','packages',PACKAGE],'test-package-presence')]
        for args,label in cases:self.assertEqual(e.check_label(args),label)
        self.assertEqual(e.check_label(['PRIVATE TOKEN']),'unrecognized-check')
    def test_fixed_error_categories(self):
        cases={'connection-refused':'cannot connect to PRIVATE: No connection could be made because the target machine actively refused it. (10061)',
          'connection-timeout':'failed to connect to PRIVATE (10060)',
          'device-not-found':"error: device 'PRIVATE SERIAL' not found",
          'device-offline':'error: device offline',
          'device-unauthorized':'error: device unauthorized',
          'adb-version-mismatch':"adb server version (41) doesn't match this client (39)",
          'adb-server-unavailable':"ADB server didn't ACK PRIVATE",'permission-denied':'cat: PRIVATE Permission denied',
          'no-device':'error: no devices/emulators found','ambiguous-device':'more than one device/emulator',
          'unsupported-command':'unknown command PRIVATE','connection-failed':'cannot connect to PRIVATE'}
        for reason,text in cases.items():
            with self.subTest(reason=reason):
                v=e.event(['connect',TARGET],1,text)
                self.assertEqual(v['reason'],reason);self.assertEqual(v['status'],'failed')
                self.assertNotIn('PRIVATE',json.dumps(v))
    def test_connect_failure_detected_even_on_exit_zero(self):
        v=e.event(['connect',TARGET],0,'cannot connect to PRIVATE (10061)')
        self.assertEqual(v['status'],'failed');self.assertEqual(v['return_code'],0)
    def test_unknown_failure_has_no_output(self):
        v=e.event(['version'],1,'PRIVATE TOKEN C:\\private\\adb.exe 0123456789')
        self.assertEqual(v,{'check':'adb-version','status':'failed','reason':'command-failed','return_code':1})
    def test_identity_only_returns_category(self):
        for text in ('11111111-1111-1111-1111-111111111111','PRIVATE ID'):
            v=e.event(['-s',TARGET,'shell','cat',BOOT_ID],0,text)
            self.assertNotIn(text,json.dumps(v))
            self.assertEqual(v['status'],'passed' if text.startswith('1111') else 'failed')
    def test_states_and_exception_categories(self):
        for text,reason in [('device','none'),('offline','device-offline'),('unauthorized','device-unauthorized'),('PRIVATE','unexpected-response')]:
            self.assertEqual(e.event(['-s',TARGET,'get-state'],0,text)['reason'],reason)
        for outcome,reason in [('timeout','command-timeout'),('launch-failed','executable-launch-failed'),('oversized-output','oversized-output')]:
            self.assertEqual(e.event(['version'],None,'',outcome)['reason'],reason)

class Transport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'adb.exe').touch()
        self.adb=d.DiagnosticAdb(str(self.root/'adb.exe'),self.root)
    def test_nonzero_process_records_only_fixed_evidence(self):
        def fake(command,**kw):
            kw['stdout'].write(b"error: device 'PRIVATE SERIAL' not found");return subprocess.CompletedProcess(command,1)
        with patch('test_device.subprocess.run',fake):
            with self.assertRaises(TestError):self.adb.run(['-s',TARGET,'get-state'])
        self.assertEqual(self.adb.adb_events[-1]['check'],'test-state')
        self.assertEqual(self.adb.adb_events[-1]['reason'],'device-not-found')
        self.assertNotIn('PRIVATE',json.dumps(self.adb.adb_events))
    def test_timeout_and_launch_failure_never_store_exception(self):
        for error,reason in [(subprocess.TimeoutExpired(['PRIVATE'],30,output=b'PRIVATE TOKEN'),'command-timeout'),(OSError('PRIVATE PATH'),'executable-launch-failed')]:
            with patch('test_device.subprocess.run',side_effect=error):
                with self.assertRaises(TestError):self.adb.run(['version'])
            self.assertEqual(self.adb.adb_events[-1]['reason'],reason)
        self.assertNotIn('PRIVATE',json.dumps(self.adb.adb_events))
    def test_output_limit_is_explicit(self):
        def fake(command,**kw):
            kw['stdout'].write(b'x'*65537);return subprocess.CompletedProcess(command,1)
        with patch('test_device.subprocess.run',fake):
            with self.assertRaises(TestError):self.adb.run(['version'])
        self.assertEqual(self.adb.adb_events[-1]['reason'],'oversized-output')
    def test_evidence_bounded_and_guards_still_block(self):
        for _ in range(100):self.adb.observe_result(['version'],0,'PRIVATE ignored')
        self.assertEqual(len(self.adb.adb_events),40)
        for args in (['devices'],['kill-server'],['-s',WORKING,'shell','input','tap','1','1'],['-s',TARGET,'root']):
            with patch('test_device.subprocess.run',side_effect=AssertionError('must not execute')):
                with self.assertRaises(TestError):self.adb.run(args)
    def test_saved_report_identifies_preflight_operation(self):
        def fake(command,**kw):
            if command[-1]=='version':text=b'Android Debug Bridge version 1.0.41';code=0
            else:text=b'cannot connect to PRIVATE (10061)';code=1
            kw['stdout'].write(text);return subprocess.CompletedProcess(command,code)
        with patch('test_device.subprocess.run',fake),patch.object(d,'bundle_token',return_value='a'*64):
            result,path=d.diagnose(self.adb,self.root,uikit_tree_probe=True)
        self.addCleanup(path.unlink)
        self.assertEqual(result['failure_stage'],'device-preflight');self.assertEqual(result['adb_last_check'],'working-connect')
        self.assertEqual(result['adb_failure']['reason'],'connection-refused')
        self.assertNotIn('PRIVATE',path.read_text(encoding='utf-8'));self.assertNotIn('a'*64,path.read_text(encoding='utf-8'))
        self.assertFalse(result['working_device_modified']);self.assertFalse(result['ocr_used'])

if __name__=='__main__':unittest.main()
