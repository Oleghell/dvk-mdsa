import json
import base64
from pathlib import Path
import runpy
import unittest

MOD=runpy.run_path(str(Path(__file__).resolve().parents[2]/'.github/scripts/publish_mumu_ci.py'))
class CIReportTests(unittest.TestCase):
    def env(self):return {'GITHUB_REPOSITORY':'Oleghell/spam-dvk','GITHUB_REF_NAME':'feature/mumu-limited-five-scenario','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'1234'}
    def test_started_does_not_claim_success(self):
        r=MOD['build_report']('started',self.env(),[])
        self.assertEqual(r['phase'],'in_progress');self.assertFalse(r['build_succeeded']);self.assertEqual(r['source_sha'],'a'*40)
    def test_finished_requires_all_three_successes(self):
        for results,expected in [({},False),({'python':'success'},False),({'python':'success','android':'failure','windows':'skipped'},False),({'python':'success','android':'success','windows':'success'},True)]:
            e=self.env();e['MUMU_NEEDS']=json.dumps({k:{'result':v} for k,v in results.items()})
            self.assertEqual(MOD['build_report']('finished',e,[])['build_succeeded'],expected)
    def test_no_foreign_repository_branch_or_invalid_identifier(self):
        for key,value in [('GITHUB_REPOSITORY','other/repo'),('GITHUB_REF_NAME','main'),('GITHUB_SHA','bad'),('GITHUB_RUN_ID','-2')]:
            with self.assertRaises(ValueError):MOD['build_report']('started',{**self.env(),key:value},[])
    def test_only_expected_jobs_and_failed_steps_included(self):
        jobs=[{'id':1,'name':'android','status':'completed','conclusion':'failure','steps':[{'name':'Build','conclusion':'failure'},{'name':'Checkout','conclusion':'success'}]}, {'name':'report_finished','steps':[]}]
        r=MOD['summarize_jobs'](jobs)
        self.assertEqual(len(r),1);self.assertEqual(r[0]['failed_steps'],[{'name':'Build','conclusion':'failure'}])
    def test_storage_requests_never_target_plaintext_or_foreign_hosts(self):
        for url in ['http://example.blob.core.windows.net/x','https://evil.example/x','https://evilgithubusercontent.com/x','https://name:password@x.blob.core.windows.net/x']:
            self.assertFalse(MOD['allowed_log_url'](url))
        self.assertTrue(MOD['allowed_log_url']('https://name.blob.core.windows.net/log?sig=hidden'))
    def test_sensitive_lines_and_signed_url_queries_are_removed(self):
        text='ordinary failure\nAuthorization: Bearer secret\nGITHUB_TOKEN=secret\npassword=secret\nhttps://name.blob.core.windows.net/log?sig=secret\nlast error'
        clean=MOD['safe_tail'](text)
        self.assertNotIn('secret',clean);self.assertIn('ordinary failure',clean);self.assertIn('last error',clean)
    def test_old_runs_and_late_started_report_do_not_replace_newer_result(self):
        new=MOD['build_report']('started',self.env(),[])
        for old in ({'run_id':9999,'phase':'completed'},{'run_id':1234,'phase':'completed'}):
            api=MOD['GitHub']('test-placeholder-not-a-credential');calls=[]
            def fake(path,body=None):
                calls.append(body)
                return {'sha':'file-sha','content':base64.b64encode(json.dumps(old).encode()).decode()}
            api.request=fake
            self.assertFalse(api.publish(self.env()['GITHUB_REF_NAME'],new))
            self.assertEqual(calls,[None])
    def test_api_target_is_fixed_to_expected_repository(self):
        with self.assertRaises(ValueError):MOD['GitHub']('test-placeholder-not-a-credential').request('/repos/other/repo/actions')
    def test_log_tail_is_bounded(self):self.assertLessEqual(len(MOD['safe_tail']('x'*1000+'\n'*10+'y'*30000)),12000)

if __name__=='__main__':unittest.main()
