"""New release checks do not depend on or change either old pinned helper."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from control_release import PACKAGES

ROOT=Path(__file__).resolve().parents[1]/'control-android'
spec=importlib.util.spec_from_file_location('control_pack',ROOT/'pack-control.py');pin=importlib.util.module_from_spec(spec);spec.loader.exec_module(pin)

class ControlReleaseTests(unittest.TestCase):
    def test_pinned_source_and_binary_checksums_agree(self):
        raw=pin.verified(ROOT,False)
        self.assertEqual(set(raw),set(PACKAGES))
        for name,data in raw.items():self.assertEqual(hashlib.sha256(data).hexdigest(),PACKAGES[name])
    def test_source_mutation_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'control';shutil.copytree(ROOT,root,ignore=shutil.ignore_patterns('out','__pycache__'))
            (root/'src/com/dvk/control/ControlPolicy.java').write_text('changed')
            with self.assertRaises(ValueError):pin.verified(root,False)
    def test_new_packages_have_no_network_permission_and_signature_protected_receiver(self):
        a=(ROOT/'AndroidManifest.xml').read_text();b=(ROOT/'KeyboardManifest.xml').read_text()
        self.assertNotIn('android.permission.INTERNET',a+b);self.assertIn('android:protectionLevel="signature"',b)
        self.assertIn('android:permission="com.dvk.keyboard.CONTROL"',b);self.assertIn('android.permission.BIND_INPUT_METHOD',b)
    def test_native_uses_committext_not_accessibility_settext(self):
        source=(ROOT/'keyboard/com/dvk/keyboard/ImeCommandReceiver.java').read_text()
        self.assertIn('c.commitText(letter,1)',source);self.assertNotIn('ACTION_SET_TEXT',source)
        self.assertIn('ime.generation==g',source);self.assertIn('prefix.equals(text(c))',source)
    def test_stop_does_not_expose_root_or_shell_as_protocol(self):
        policy=(ROOT/'src/com/dvk/control/ControlPolicy.java').read_text()
        self.assertNotIn('Runtime.getRuntime',policy)
    def test_pure_java_unicode_and_input_policy(self):
        if not shutil.which('javac') or not shutil.which('java'):self.skipTest('JDK needed')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);runner=p/'PolicyTest.java'
            runner.write_text('''import com.dvk.control.ControlPolicy;
public class PolicyTest {static void ck(boolean v){if(!v)throw new AssertionError();}
 public static void main(String[] args){
 ck(ControlPolicy.point(0,48));ck(ControlPolicy.point(899,1599));ck(!ControlPolicy.point(900,100));ck(!ControlPolicy.point(400,47));
 ck(ControlPolicy.key(4));ck(ControlPolicy.key(66));ck(!ControlPolicy.key(3));ck(!ControlPolicy.key(187));
 ck(ControlPolicy.plain("Нальчик 🙂"));ck(!ControlPolicy.plain("a\\nb"));ck(!ControlPolicy.plain("\\uD800"));
 System.out.println("CONTROL_POLICY_PASS");}}''',encoding='utf-8')
            c=subprocess.run(['javac','-encoding','UTF-8','-d',str(p),str(ROOT/'src/com/dvk/control/ControlPolicy.java'),str(runner)],capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr)
            r=subprocess.run(['java','-cp',str(p),'PolicyTest'],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr);self.assertIn('CONTROL_POLICY_PASS',r.stdout)

    def test_ci_builds_tests_and_stages_both_new_packages_without_write_permission(self):
        root=ROOT.parents[1]
        workflow=(root/'.github/workflows/mumu-navigation.yml').read_text()
        self.assertIn('contents: read',workflow);self.assertNotIn('contents: write',workflow)
        self.assertIn('CONTROL_VERIFY_ONLY=1',workflow)
        self.assertIn('python3 mumu-navigation/control-android/test-emulator.py',workflow)
        for name in PACKAGES:self.assertGreaterEqual(workflow.count(name),3)
        self.assertIn("bridge_version='1.5.0-control-preview.1'",workflow)
    def test_native_runner_refuses_user_device_and_restores_ime(self):
        source=(ROOT/'test-emulator.py').read_text()
        self.assertIn("os.environ.get('GITHUB_ACTIONS')!='true'",source)
        self.assertIn('emulator-',source);self.assertNotIn('127.0.0.1:5555',source)
        self.assertIn('finally:',source);self.assertIn("'ime','set',previous",source)
        self.assertIn('changes=7',source)
    def test_gui_stop_remains_outside_scrollable_body(self):
        source=(ROOT.parent/'mumu_bridge.py').read_text()
        self.assertIn("footer=tk.Frame(root);footer.pack(side='bottom'",source)
        self.assertIn('buttons = footer',source)
        self.assertIn("text='Остановить доступ', command=stop",source)

if __name__=='__main__':unittest.main()
