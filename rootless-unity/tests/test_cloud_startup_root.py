"""No cloud credentials, accounts, Android or actual UI operations."""
import json
import shutil
import subprocess
import threading
import unittest
from unittest.mock import MagicMock

import dialog_browser as browser
import navigation_root_diagnostic as root
from assistant_navigation_check import safe_diagnostic
from il2cpp_exports import RESOLVER
from test_dialog_browser import raw_open
from test_assistant_monitor import list_result


def early_failure(stage='api-incomplete'):
    v=raw_open()
    for k,value in list(v.items()):
        if type(value) is bool:v[k]=False
    v.update(stage=stage,step='resolve-api',observed_calls=0,managed_calls=0,
             frame_source='not-observed',watched_sources=dict.fromkeys(v['watched_sources'],False))
    n=v['navigation']
    for k,value in list(n.items()):
        if type(value) is bool:n[k]=False
        elif type(value) is int:n[k]=0
    n.update(stage='not-attempted',error='none',phase='entry',metadata_checkpoint='not-checked',
             selection_checkpoint='not-checked',private_identity=None,root_top_kind='not-checked',
             last_presented_kind='not-checked',controller_path=[],readiness_check='not-checked',
             readiness=dict.fromkeys(n['readiness'],None))
    return v


class RootEvidence(unittest.TestCase):
    def test_early_failure_keeps_real_cause_without_claiming_screen(self):
        result=browser.validate(early_failure(),'list')
        self.assertEqual(result['state'],'stopped')
        self.assertIsNone(result['identity'])
        d=safe_diagnostic(result['diagnostic'])
        self.assertEqual(d['root_probe']['stage'],'api-incomplete')
        self.assertEqual(d['root_probe']['step'],'resolve-api')
        self.assertFalse(d['action_attempted'])
        self.assertFalse(d['destination_verified'])
        self.assertIn('IL2CPP',root.message(d))
        self.assertNotIn('100',json.dumps(d))

    def test_root_diagnostic_rejects_private_fields_unknown_enums_and_bool_counts(self):
        d=browser.validate(early_failure(),'list')['diagnostic']
        for key,value in [('stage','PRIVATE'),('step','PRIVATE'),('observed_calls',True),
                          ('frame_source','0xSECRET'),('token','SECRET')]:
            bad=dict(d,root_probe=dict(d['root_probe'],**{key:value}))
            with self.assertRaises(ValueError):safe_diagnostic(bad)

    def test_legacy_diagnostic_still_accepted(self):
        self.assertEqual(safe_diagnostic(list_result()['diagnostic']),list_result()['diagnostic'])
        self.assertIsNone(root.message(list_result()['diagnostic']))

    def test_bad_full_probe_never_becomes_diagnostic_or_ready(self):
        v=early_failure();v['secret']='SECRET'
        with self.assertRaises(ValueError):browser.validate(v,'list')

    def test_search_entry_keeps_verified_semantic_tab_transition(self):
        s=browser.build('list',entry='either')
        self.assertIn("k!=='search'&&k!=='dialogs'",s)
        self.assertIn('switchTab(s.messageTab)',s)
        self.assertIn("if(operation==='list'){finish();return;}",s)
        for bad in ('input tap','Interceptor.replace','Memory.scan'):
            self.assertNotIn(bad,s)


@unittest.skipUnless(shutil.which('node'),'Node required for isolated JS resolver')
class ExportResolver(unittest.TestCase):
    def run_js(self,body):
        result=subprocess.run([shutil.which('node'),'-e',RESOLVER+'\n'+body],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_locally_loaded_engine_does_not_need_global_symbols(self):
        self.run_js("""
const assert=require('assert');
const Process={findModuleByName(name){assert.equal(name,'libil2cpp.so');return {findExportByName(n){assert.equal(n,'il2cpp_domain_get');return 'local-export';}};}};
const Module={findGlobalExportByName(){throw Error('must not use global namespace');}};
assert.equal(findIl2cppExport('il2cpp_domain_get'),'local-export');
""")

    def test_missing_engine_export_never_binds_unrelated_global(self):
        self.run_js("""
const assert=require('assert');
const Process={findModuleByName(){return {findExportByName(){return null;}};}};
const Module={findGlobalExportByName(){throw Error('wrong engine');}};
assert.equal(findIl2cppExport('il2cpp_domain_get'),null);
""")

    def test_legacy_fixture_without_named_engine_can_use_global_exports(self):
        self.run_js("""
const assert=require('assert');
const Process={findModuleByName(){return null;}};
const Module={findGlobalExportByName(n){assert.equal(n,'il2cpp_domain_get');return 'fixture';}};
assert.equal(findIl2cppExport('il2cpp_domain_get'),'fixture');
""")

    def test_all_native_paths_share_resolver(self):
        import uikit_root,native_metadata,chat_runtime_metadata,reply_contract
        for source in (uikit_root.FUNCTION,native_metadata.NATIVE_FUNCTION,chat_runtime_metadata.FUNCTION,reply_contract.FUNCTION):
            self.assertIn(RESOLVER,source)
            self.assertEqual(source.count('Module.findGlobalExportByName('),1)
            self.assertIn('findIl2cppExport(',source)
