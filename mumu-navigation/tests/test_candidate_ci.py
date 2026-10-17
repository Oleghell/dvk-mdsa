"""Candidate CI wiring must never distribute the ephemeral test signer/APKs."""
from pathlib import Path
import tempfile
import unittest
import importlib.util

ROOT=Path(__file__).resolve().parents[2]
NEXT=ROOT/'mumu-navigation/control-android-next'

class CandidateCITests(unittest.TestCase):
    def test_candidate_ci_is_a_gate_and_result_is_in_report(self):
        s=(ROOT/'.github/workflows/mumu-navigation.yml').read_text(encoding='utf-8')
        self.assertIn('  candidate_android:',s)
        self.assertIn('needs: [python, android, candidate_android]',s)
        self.assertIn('needs: [python, android, candidate_android, windows]',s)
        candidate=s[s.index('  candidate_android:'):s.index('  windows:')]
        self.assertIn('control-android-next/build-ci.sh',candidate)
        self.assertIn('control-android-next/test-emulator.py',candidate)
        self.assertIn('out/candidate-result.json',candidate)
        self.assertIn('out/synthetic-diagnostics/',candidate)
        self.assertNotIn('out/*.apk',candidate)
        self.assertNotIn('out/*.jks',candidate)
    def test_candidate_build_is_ci_only_and_uses_external_staging_path(self):
        s=(NEXT/'build-ci.sh').read_text(encoding='utf-8')
        self.assertIn('[ "${GITHUB_ACTIONS:-}" = true ]',s)
        self.assertIn('candidate="$workspace/out/cursor-stable-ci-source"',s)
        self.assertIn('CONTROL_VERIFY_ONLY=1',s)
        self.assertIn('synthetic-ci.jks',s)
        self.assertNotIn('CITY_KEYSTORE',s)
        self.assertNotIn('adb',s)
    def test_staging_does_not_modify_pinned_source_and_refuses_overwrite(self):
        spec=importlib.util.spec_from_file_location('candidate_prepare',NEXT/'prepare_candidate.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        original=ROOT/'mumu-navigation/control-android/src/com/dvk/control/ControlInstrumentation.java'
        before=original.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            dest=module.prepare(Path(tmp)/'new-candidate')
            self.assertEqual((dest/'src/com/dvk/control/ControlInstrumentation.java').read_bytes(),(NEXT/'src/com/dvk/control/ControlInstrumentation.java').read_bytes())
            with self.assertRaises(ValueError):module.prepare(dest)
        self.assertEqual(before,original.read_bytes())
    def test_native_test_is_emulator_only_and_has_no_action_retry_loop(self):
        s=(NEXT/'test-emulator.py').read_text(encoding='utf-8')
        self.assertIn("os.environ.get('GITHUB_ACTIONS')!='true'",s)
        self.assertIn('emulator-',s);self.assertNotIn('127.0.0.1:5555',s)
        self.assertIn("fresh=inspect();tap_status,_=call(payload(fresh))",s)
        self.assertIn("assert tap_status=='input_injected'",s)
        self.assertIn('candidate_taps=1',s)
        self.assertIn("results['outside_editor_change_refused']=True",s)
        self.assertIn("finally:",s)
    def test_legacy_fixture_is_static_but_candidate_retains_animation(self):
        legacy=(ROOT/'mumu-navigation/city-android/fixture/drug/vokrug/CityFixtureActivity.java').read_text(encoding='utf-8')
        candidate=(NEXT/'fixture/drug/vokrug/GestureFixtureActivity.java').read_text(encoding='utf-8')
        self.assertIn('input.setCursorVisible(false)',legacy)
        self.assertIn('input.setCursorVisible(true)',candidate)
        self.assertIn('cursor.postDelayed(this,80)',candidate)
        self.assertIn('input.setShowSoftInputOnFocus(false)',candidate)

    def test_windows_manifest_explicitly_says_fix_is_not_in_runtime_yet(self):
        s=(ROOT/'.github/workflows/mumu-navigation.yml').read_text(encoding='utf-8')
        self.assertIn('cursor_stable_runtime_included=$false',s)
        manifest=(NEXT/'fixture/AndroidManifest.xml').read_text(encoding='utf-8')
        self.assertNotIn('android.permission.INTERNET',manifest)

if __name__=='__main__':unittest.main()
