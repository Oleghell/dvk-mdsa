"""CI status belongs in artifacts, not generated repository commits."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]

class NoReportCommitsTests(unittest.TestCase):
    def test_build_has_readonly_permissions_and_artifact_reports(self):
        text=(ROOT/'.github/workflows/mumu-navigation.yml').read_text(encoding='utf-8')
        self.assertIn('contents: read',text)
        self.assertIn('name: mumu-ci-result',text)
        readonly=text[:text.index('  publish_release:')]+text[text.index('  report_results:'):]
        self.assertNotIn('contents: write',readonly)
        self.assertEqual(text.count('contents: write'),1)
        for forbidden in ('publish_mumu_ci.py','git push','git commit',
                          '/git/commits','report_started:','report_finished:'):
            self.assertNotIn(forbidden,text)
    def test_status_workflow_manual_and_readonly(self):
        text=(ROOT/'.github/workflows/mumu-ci-inspect.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:',text)
        self.assertIn('contents: read',text)
        for forbidden in ('push:','contents: write','git commit','git push','publish_mumu_ci.py'):
            self.assertNotIn(forbidden,text)
    def test_runner_never_claims_real_device_test(self):
        text=(ROOT/'mumu-navigation/run_local_autotests.py').read_text(encoding='utf-8')
        self.assertIn("'real_device_tested':False",text)

if __name__=='__main__':unittest.main()
