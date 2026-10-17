"""Independently signed release: no production key in source/CI; no v1 removal."""
from pathlib import Path
import base64,hashlib,importlib.util,json,unittest
from control_protocol import COMPONENT,IME,args_allowed,SERIAL
from control_release import PACKAGES,SIGNER_SHA256,VERSION
ROOT=Path(__file__).resolve().parents[1]
V2=ROOT/'control-android-v2'

class V2ReleaseTests(unittest.TestCase):
    def test_signed_release_and_protocol_are_v2(self):
        self.assertEqual(VERSION,'1.7.0-beta.2')
        self.assertEqual(COMPONENT,'com.dvk.control.v2/com.dvk.control.ControlInstrumentation')
        self.assertEqual(IME,'com.dvk.keyboard.v2/com.dvk.keyboard.BridgeIme')
        payload=base64.b64encode(b'{"op":"inspect"}').decode()
        args=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','request_b64',payload,COMPONENT]
        self.assertTrue(args_allowed(args,True));args[-1]=args[-1].replace('.v2/','.v1/')
        self.assertFalse(args_allowed(args,True))
    def test_v2_manifest_permission_does_not_conflict_with_v1(self):
        a=(V2/'AndroidManifest.xml').read_text(encoding='utf-8');b=(V2/'KeyboardManifest.xml').read_text(encoding='utf-8')
        self.assertIn('package="com.dvk.control.v2"',a)
        self.assertIn('package="com.dvk.keyboard.v2"',b)
        self.assertIn('com.dvk.keyboard.v2.CONTROL',a+b)
        self.assertNotIn('"com.dvk.keyboard.CONTROL"',a+b)
        self.assertNotIn('android.permission.INTERNET',a+b)
    def test_manifest_and_host_agree_on_signer_and_apks(self):
        meta=json.loads((V2/'pinned/release.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['signer_sha256'],SIGNER_SHA256)
        for name,sha in PACKAGES.items():self.assertEqual(meta['packages'][name]['apk_sha256'],sha)
    def test_release_contains_tested_cursor_guard(self):
        a=(V2/'src/com/dvk/control/ControlInstrumentation.java').read_text(encoding='utf-8')
        candidate=(ROOT/'control-android-next/src/com/dvk/control/ControlInstrumentation.java').read_text(encoding='utf-8').replace('com.dvk.keyboard.v1','com.dvk.keyboard.v2').replace('com.dvk.keyboard.CONTROL','com.dvk.keyboard.v2.CONTROL')
        self.assertEqual(a,candidate)
        self.assertIn('gesture_editor_guard_supported',a)
    def test_install_never_uninstalls_app_or_old_control(self):
        source=(ROOT/'universal_control.py').read_text(encoding='utf-8')
        self.assertNotIn("'uninstall'",source);self.assertNotIn('com.dvk.control.v1',source)
    def test_ci_tests_actual_signed_release_before_publication(self):
        workflow=(ROOT.parent/'.github/workflows/mumu-navigation.yml').read_text(encoding='utf-8')
        self.assertIn('control-android-v2/pack-control.py',workflow)
        self.assertIn('control-android-v2/verify-signature.py',workflow)
        self.assertIn('control-android-v2/test-guarded-emulator.py',workflow)
        publish=workflow[workflow.index('  publish_release:'):workflow.index('  report_results:')]
        self.assertIn('needs: [python, android, candidate_android, windows]',publish)
        self.assertIn('startsWith(github.event.head_commit.message',publish)
        self.assertIn('contents: write',publish)
        self.assertNotIn('mumu-v2-release.p12',workflow)
    def test_synthetic_fixture_update_is_not_a_version_downgrade(self):
        source=(V2/'build-gesture-fixture.sh').read_text(encoding='utf-8')
        self.assertIn('android:versionCode="100"',source)
        self.assertNotIn('uninstall',source)
        self.assertNotIn('install -d',source)
    def test_keyboard_is_headless_and_updateable_in_place(self):
        source=(V2/'keyboard/com/dvk/keyboard/BridgeIme.java').read_text(encoding='utf-8')
        self.assertIn('onEvaluateInputViewShown(){return false;}',source)
        self.assertIn('onEvaluateFullscreenMode(){return false;}',source)
        self.assertIn('onCreateInputView(){return null;}',source)
        self.assertNotIn('new TextView',source)
        manifest=(V2/'KeyboardManifest.xml').read_text(encoding='utf-8')
        self.assertIn('android:versionCode="2"',manifest)
        runner=(V2/'test-emulator.py').read_text(encoding='utf-8')
        self.assertIn("start('city_resize')",runner)
        self.assertIn("d['bounds']==before['bounds']",runner)
        self.assertIn('HEADLESS_IME_ADJUST_RESIZE_PASS',runner)
        self.assertIn('mIsInputViewShown=false',runner)

    def test_headless_ime_diagnostic_uses_android_field_and_refuses_missing(self):
        spec=importlib.util.spec_from_file_location('v2_native_test',V2/'test-emulator.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        self.assertTrue(runner.headless_ime_dump('  mIsInputViewShown=false mInputViewStarted=false'))
        self.assertFalse(runner.headless_ime_dump('  mIsInputViewShown=true'))
        self.assertFalse(runner.headless_ime_dump('mInputViewShown=false'))
        self.assertFalse(runner.headless_ime_dump('No matching services'))

    def test_legacy_pins_are_unchanged(self):
        meta=json.loads((ROOT/'control-android/pinned/release.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['packages']['control-helper.apk']['apk_sha256'],'44824855e0da2746165ccebd9a704878dbd45513e0a0afb13b29087b8b895883')
        self.assertNotEqual(meta['packages']['control-helper.apk']['apk_sha256'],PACKAGES['control-helper.apk'])
    def test_no_private_key_files_in_source_tree(self):
        for p in V2.rglob('*'):
            if p.is_file() and 'out' not in p.relative_to(V2).parts:self.assertNotIn(p.suffix.lower(),('.jks','.keystore','.p12','.pfx'))

if __name__=='__main__':unittest.main()
