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
            (root/'src/com/dvk/control/ControlPolicy.java').write_text('changed', encoding='utf-8')
            with self.assertRaises(ValueError):pin.verified(root,False)
    def test_new_packages_have_no_network_permission_and_signature_protected_receiver(self):
        a=(ROOT/'AndroidManifest.xml').read_text(encoding='utf-8');b=(ROOT/'KeyboardManifest.xml').read_text(encoding='utf-8')
        self.assertNotIn('android.permission.INTERNET',a+b);self.assertIn('android:protectionLevel="signature"',b)
        self.assertIn('android:permission="com.dvk.keyboard.CONTROL"',b);self.assertIn('android.permission.BIND_INPUT_METHOD',b)
    def test_native_uses_committext_not_accessibility_settext(self):
        source=(ROOT/'keyboard/com/dvk/keyboard/ImeCommandReceiver.java').read_text(encoding='utf-8')
        self.assertIn('c.commitText(letter,1)',source);self.assertNotIn('ACTION_SET_TEXT',source)
        self.assertIn('ime.generation==g',source);self.assertIn('prefix.equals(text(c))',source)
    def test_stop_does_not_expose_root_or_shell_as_protocol(self):
        policy=(ROOT/'src/com/dvk/control/ControlPolicy.java').read_text(encoding='utf-8')
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
        workflow=(root/'.github/workflows/mumu-navigation.yml').read_text(encoding='utf-8')
        self.assertIn('contents: read',workflow);self.assertNotIn('contents: write',workflow)
        self.assertIn('CONTROL_VERIFY_ONLY=1',workflow)
        self.assertIn('python3 mumu-navigation/control-android/test-emulator.py',workflow)
        for name in PACKAGES:self.assertGreaterEqual(workflow.count(name),3)
        self.assertIn("bridge_version='1.5.0-control-preview.2'",workflow)
    def test_native_runner_refuses_user_device_and_restores_ime(self):
        source=(ROOT/'test-emulator.py').read_text(encoding='utf-8')
        self.assertIn("os.environ.get('GITHUB_ACTIONS')!='true'",source)
        self.assertIn('emulator-',source);self.assertNotIn('127.0.0.1:5555',source)
        self.assertIn('finally:',source);self.assertIn("'ime','set',previous",source)
        self.assertIn('changes=7',source)
    def test_gui_stop_remains_outside_scrollable_body(self):
        source=(ROOT.parent/'mumu_bridge.py').read_text(encoding='utf-8')
        self.assertIn("footer=tk.Frame(root);footer.pack(side='bottom'",source)
        self.assertIn('buttons = footer',source)
        self.assertIn("text='Остановить доступ', command=stop",source)

    def test_startup_wait_is_readonly_once_and_does_not_relax_package_checks(self):
        source=(ROOT/'src/com/dvk/control/ControlInstrumentation.java').read_text(encoding='utf-8')
        self.assertEqual(source.count('awaitAccessibility();'),1)
        self.assertIn('"root_not_ready".equals(code) || "node_not_ready".equals(code)?0:-1',source)
        root=source[source.index(' private AccessibilityNodeInfo root()'):source.index(' private AccessibilityNodeInfo field()')]
        self.assertEqual(root.count('"drug.vokrug".contentEquals'),2)
        self.assertNotIn('SystemClock.sleep',root)
        self.assertLess(source.index('awaitAccessibility();'),source.index('phase="ime_input"'))
        self.assertIn('control_diagnostic_code',source);self.assertNotIn('e.getMessage()',source)
    def test_java_startup_wait_transient_permanent_and_deadline(self):
        if not shutil.which('javac') or not shutil.which('java'):self.skipTest('JDK needed')
        runner_source="""import com.dvk.control.ControlPolicy;
public class WaitTest {
 static void ck(boolean value){if(!value)throw new AssertionError();}
 static class Probe implements ControlPolicy.RootProbe {
  int calls=0,pauses=0,zeros,result;Probe(int zeros,int result){this.zeros=zeros;this.result=result;}
  public int state(){calls++;return calls<=zeros?0:result;}public void pause(){pauses++;}
 }
 public static void main(String[] args){
  Probe transientRoot=new Probe(3,1);ck(ControlPolicy.awaitRoot(transientRoot)==1);ck(transientRoot.calls==4);ck(transientRoot.pauses==3);
  Probe wrongPackage=new Probe(0,-1);ck(ControlPolicy.awaitRoot(wrongPackage)==-1);ck(wrongPackage.calls==1);ck(wrongPackage.pauses==0);
  Probe absent=new Probe(99,1);ck(ControlPolicy.awaitRoot(absent)==0);ck(absent.calls==40);ck(absent.pauses==39);
  Probe ready=new Probe(0,1);ck(ControlPolicy.awaitRoot(ready)==1);ck(ready.calls==1);ck(ready.pauses==0);
  System.out.println("CONTROL_STARTUP_POLICY_PASS");
 }}"""
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);runner=p/'WaitTest.java';runner.write_text(runner_source, encoding='utf-8')
            c=subprocess.run(['javac','-encoding','UTF-8','-d',str(p),str(ROOT/'src/com/dvk/control/ControlPolicy.java'),str(runner)],capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr)
            r=subprocess.run(['java','-cp',str(p),'WaitTest'],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr);self.assertIn('CONTROL_STARTUP_POLICY_PASS',r.stdout)
    def test_ci_failure_artifact_is_synthetic_only(self):
        source=(ROOT/'test-emulator.py').read_text(encoding='utf-8')
        self.assertLess(source.index("os.environ.get('GITHUB_ACTIONS')!='true'"),source.index('diagnostics=Path'))
        self.assertIn('control-last.json',source)
        workflow=(ROOT.parents[1]/'.github/workflows/mumu-navigation.yml').read_text(encoding='utf-8')
        self.assertIn('name: synthetic-control-diagnostics',workflow)
        self.assertIn('if: ${{ failure() }}',workflow)

if __name__=='__main__':unittest.main()
