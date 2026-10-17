"""Native failure must expose fixed diagnostics, not lose status in an assert."""
import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/'control-android-next/test-emulator.py'
spec=importlib.util.spec_from_file_location('candidate_emulator_test',p)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class CandidateDiagnosticsTests(unittest.TestCase):
    def test_fixed_native_status_code_phase_survive(self):
        raw='INSTRUMENTATION_RESULT: control_status=denied_context\nINSTRUMENTATION_RESULT: control_diagnostic_code=editor_changed\nINSTRUMENTATION_RESULT: control_diagnostic_phase=gesture_guard\n'
        self.assertEqual(module.safe_native_diagnostic(raw,'tap'),{'operation':'tap','status':'denied_context','diagnostic_code':'editor_changed','diagnostic_phase':'gesture_guard'})
    def test_missing_or_duplicate_status_is_not_invented(self):
        raw='INSTRUMENTATION_RESULT: control_status=input_injected\n'*2
        self.assertNotIn('status',module.safe_native_diagnostic(raw,'tap'))
        self.assertNotIn('status',module.safe_native_diagnostic('','tap'))
    def test_unknown_diagnostics_and_private_output_are_never_echoed(self):
        raw='PRIVATE_SCREEN_TEXT\nINSTRUMENTATION_RESULT: control_status=private_message\nINSTRUMENTATION_RESULT: control_diagnostic_code=private_name\n'
        last=module.safe_native_diagnostic(raw,'private_payload',{'text':'PRIVATE_TEXT'})
        self.assertEqual(last,{'operation':'other'})
        self.assertNotIn('PRIVATE',module.failure_annotation(last))
    def test_only_tiny_fixed_report_fields_survive(self):
        last=module.safe_native_diagnostic('','tap',{'guard_check':1,'masked_context_match':False,'text':'PRIVATE'})
        self.assertEqual(last,{'operation':'tap','guard_check':1,'masked_context_match':False})
        self.assertEqual(module.safe_native_diagnostic('','tap',{'guard_check':True,'masked_context_match':'false'}),{'operation':'tap'})
    def test_pixel_difference_diagnostics_are_numeric_and_bounded(self):
        d={'diff_pixels':100,'diff_bounds':[40,500,700,580],'pixels':'PRIVATE'}
        self.assertEqual(module.safe_native_diagnostic('','tap',d),{'operation':'tap','diff_pixels':100,'diff_bounds':[40,500,700,580]})
        d={'diff_pixels':-1,'diff_bounds':[0,0,900,1600]}
        self.assertEqual(module.safe_native_diagnostic('','tap',d),{'operation':'tap'})
    def test_actions_annotation_contains_actual_failure_status(self):
        last=module.safe_native_diagnostic('INSTRUMENTATION_RESULT: control_status=indeterminate_after_attempt\n','tap')
        a=module.failure_annotation(last)
        self.assertTrue(a.startswith('::error title='));self.assertIn('indeterminate_after_attempt',a)

if __name__=='__main__':unittest.main()
