import base64,hashlib,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import mumu_bridge as b

class DraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);exe=self.base/'adb.exe';exe.touch()
        self.reader=b.AdbReader(exe);self.reader.helper_ready=True
        self.png=b'\x89PNG\r\n\x1a\nsynthetic';self.hash=hashlib.sha256(self.png).hexdigest();self.reader.screen=lambda:self.png
    def tearDown(self):self.tmp.cleanup()
    def test_exact_draft_not_send(self):
        self.reader._run=Mock(return_value=b'INSTRUMENTATION_RESULT: draft_status=draft_set_verified\n')
        r=self.reader.put_draft(self.hash,'TEST_RECIPIENT')
        self.assertEqual(r['text'],'Как настроение?)');self.assertEqual(r['messages_sent'],0)
        args=self.reader._run.call_args.args[0];self.assertEqual(args[-1],b.HELPER_COMPONENT)
        self.assertEqual(base64.b64decode(args[-2]).decode(),'TEST_RECIPIENT')
        self.assertNotIn('input',args);self.assertNotIn('keyevent',args)
    def test_changed_screen_does_not_write(self):
        self.reader._run=Mock()
        with self.assertRaises(b.BridgeError):self.reader.put_draft('0'*64,'TEST_RECIPIENT')
        self.reader._run.assert_not_called();self.assertFalse(self.reader.draft_attempted)
    def test_refusal_consumes_attempt_no_retry(self):
        self.reader._run=Mock(return_value=b'INSTRUMENTATION_RESULT: draft_status=denied_nonempty_draft\n')
        for _ in range(2):
            with self.assertRaises(b.BridgeError):self.reader.put_draft(self.hash,'TEST_RECIPIENT')
        self.assertEqual(self.reader._run.call_count,1)
    def test_success_is_one_attempt(self):
        self.reader._run=Mock(return_value=b'INSTRUMENTATION_RESULT: draft_status=draft_set_verified\n')
        self.reader.put_draft(self.hash,'TEST_RECIPIENT')
        with self.assertRaises(b.BridgeError):self.reader.put_draft(self.hash,'TEST_RECIPIENT')
        self.assertEqual(self.reader._run.call_count,1)
    def test_no_helper_no_write(self):
        self.reader.helper_ready=False
        with self.assertRaises(b.BridgeError):self.reader.put_draft(self.hash,'TEST_RECIPIENT')
    def test_bad_name(self):
        self.reader._run=Mock()
        for name in ['', 'TEST\nX', 'x'*81]:
            with self.assertRaises(b.BridgeError):self.reader.put_draft(self.hash,name)
        self.reader._run.assert_not_called()
    def test_allowlist_rejects_control_commands(self):
        for cmd in [['shell','input','keyevent','66'],['shell','input','text','abc'],['shell','am','start','com.other'],['uninstall','com.other'],['install','/tmp/other.apk']]:
            with self.subTest(cmd=cmd),patch('subprocess.run') as runner:
                with self.assertRaises(b.BridgeError):self.reader._run(['-s',b.SERIAL,*cmd])
                runner.assert_not_called()
    def test_helper_hash_required(self):
        (self.base/'helper.apk').write_bytes(b'fake-apk-for-unit-test-only')
        (self.base/'helper-manifest.json').write_text(json.dumps({'helper_sha256':'0'*64}))
        self.reader._run=Mock()
        with self.assertRaises(b.BridgeError):self.reader.install_helper(self.base)
        self.reader._run.assert_not_called()
    def test_verified_helper_install(self):
        data=b'fake-apk-for-unit-test-only';(self.base/'helper.apk').write_bytes(data)
        (self.base/'helper-manifest.json').write_text(json.dumps({'helper_sha256':hashlib.sha256(data).hexdigest()}))
        self.reader._run=Mock(return_value=b'Success\n');self.reader.install_helper(self.base)
        self.assertTrue(self.reader.helper_ready)
        self.assertEqual(self.reader._run.call_args.args[0],['-s',b.SERIAL,'install','-t','-r',str(self.base/'helper.apk')])
    def test_java_has_no_send_input_or_network(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'android/src/com/dvk/drafthelper/DraftInstrumentation.java').read_text()
        for forbidden in ['ACTION_CLICK','performEditorAction','sendKey','KEYCODE_ENTER','executeShellCommand','ACTION_IME_ENTER']:
            self.assertNotIn(forbidden,source)
        self.assertIn('ACTION_SET_TEXT',source)
        self.assertNotIn('uses-permission',(root/'android/AndroidManifest.xml').read_text())

if __name__=='__main__':unittest.main()
