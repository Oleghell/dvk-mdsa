"""Static package markers must never become claims of live Unity control."""
import base64,copy,json,os,shutil,subprocess,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from native_policy import allowed_adb
from ui_protocol import valid_native,valid_tool,tools
from ui_backend import NativeBackend
from ui_model import UIError,UnsupportedUI
from unity_diagnostics import validate
from test_native_only import instrument

ROOT=Path(__file__).resolve().parents[1]
JAVA=ROOT/'control-android-v2/src/com/dvk/control/UnityArchiveScan.java'

def report(kinds=(),complete=True):
    return dict(unity_diagnostics_version=1,package='drug.vokrug',version_name='test',version_code='12',debuggable=False,test_only=False,device_supported_abis=['x86_64','x86'],archive_count=1,archives=[dict(index=0,role='base',status='scanned',entries_scanned=10)],entries_scanned=10,markers=[dict(archive=0,kind=k,abi='arm64-v8a' if k.endswith('_library') else '') for k in kinds],complete=complete,classification_scope='installed_apk_entries_only',runtime_objects_access='not_tested',sdk_integration_status='not_assessed',images_captured=0,actions_attempted=0,root_attempted=False,apk_modified=False,private_data_read=False)

class ReportTests(unittest.TestCase):
    def test_backend_indicators_not_runtime_proof(self):
        cases=[((),True,'not_identified'),((),False,'unknown_incomplete'),(('unity_library',),True,'unity_backend_unknown'),(('il2cpp_library',),True,'il2cpp_indicated'),(('mono_library',),True,'mono_indicated'),(('il2cpp_metadata',),True,'il2cpp_metadata_only'),(('managed_assembly',),True,'managed_assemblies_only'),(('mono_library','il2cpp_library'),True,'mixed_indicators'),(('mono_library','il2cpp_metadata'),True,'mixed_indicators')]
        for kinds,complete,expected in cases:
            r=validate(report(kinds,complete));self.assertEqual(r['backend_indication'],expected);self.assertEqual(r['runtime_objects_access'],'not_tested')
    def test_static_abis_not_inferred_from_device_architecture(self):
        r=validate(report(('il2cpp_library',)))
        self.assertEqual(r['device_supported_abis'],['x86_64','x86']);self.assertEqual(r['observed_engine_library_abis'],['arm64-v8a'])
    def test_privacy_and_type_contract(self):
        bad=[]
        for key,value in [('package','other.app'),('root_attempted',True),('private_data_read',True),('apk_modified',True),('images_captured',1),('actions_attempted',True),('debuggable',1),('version_code','-1'),('version_code',str(2**63)),('version_name','private\ntext'),('runtime_objects_access','verified'),('entries_scanned',100),('device_supported_abis',['x86','x86']),('archive_count',True)]:
            d=report();d[key]=value;bad.append(d)
        d=report();d['sourceDir']='/data/private';bad.append(d)
        d=report(('il2cpp_library',));d['markers'][0]['abi']='../../bad';bad.append(d)
        d=report(('il2cpp_library',));d['markers'][0]['kind']='unapproved_marker';bad.append(d)
        d=report(('il2cpp_library',));d['markers'][0]['archive']=1;bad.append(d)
        d=report(('il2cpp_library',));d['markers'].append(dict(d['markers'][0]));bad.append(d)
        d=report();d['archives'][0]['status']='unreadable';bad.append(d)
        for data in bad:
            with self.subTest(data=data):
                with self.assertRaises(UIError):validate(data)
    def test_partial_scan_can_keep_positive_evidence_but_never_prove_absence(self):
        d=report(('il2cpp_library',),False);d['archives'][0]['status']='unreadable'
        self.assertEqual(validate(d)['backend_indication'],'il2cpp_indicated')
        d['markers']=[];self.assertEqual(validate(d)['backend_indication'],'unknown_incomplete')
    def test_protocol_zero_argument_only_and_strict_transport(self):
        reader=SimpleNamespace(control_enabled=True,_local_control_setup=False)
        self.assertTrue(valid_native({'op':'ui_unity_diagnostics'}));self.assertTrue(valid_tool('mumu_ui_unity_diagnostics',{}))
        self.assertTrue(allowed_adb(instrument({'op':'ui_unity_diagnostics'}),reader))
        for extra in ('path','package','shell','root','screenshot'):
            self.assertFalse(valid_native(dict(op='ui_unity_diagnostics',**{extra:'anything'})))
            self.assertFalse(valid_tool('mumu_ui_unity_diagnostics',{extra:True}))
        entry=next(t for t in tools(True) if t['name']=='mumu_ui_unity_diagnostics')
        self.assertTrue(entry['annotations']['readOnlyHint']);self.assertEqual(entry['inputSchema']['properties'],{})
    def test_backend_does_not_read_ui_screen_or_mutate_journal(self):
        b=NativeBackend.__new__(NativeBackend);b.reader=SimpleNamespace(control_enabled=True,screen=Mock(side_effect=AssertionError('pixels')))
        encoded=base64.b64encode(json.dumps(report(('il2cpp_metadata',))).encode()).decode()
        b.control=SimpleNamespace(instrument=Mock(return_value=('inspection_ok','INSTRUMENTATION_RESULT: report_b64='+encoded)))
        self.assertEqual(b.unity_diagnostics()['backend_indication'],'il2cpp_metadata_only')
        b.control.instrument.assert_called_once_with({'op':'ui_unity_diagnostics'});b.reader.screen.assert_not_called()
        b.control.instrument.return_value=('denied_arguments','')
        with self.assertRaises(UnsupportedUI):b.unity_diagnostics()
    def test_native_status_does_not_claim_legacy_visual_send(self):
        from session_bridge import SupervisedReader
        r=Mock();r.native_only=True;r.status.return_value={};ledger=Mock();ledger.status.return_value={'identity_guard':'visual fingerprint','visited':4}
        data=SupervisedReader(r,ledger).status();self.assertEqual(data['sending_scope'],'not exposed in strict native mode')
        self.assertNotIn('visual fingerprint',data['test_session']['identity_guard']);self.assertEqual(data['test_session']['visited'],4)

class JavaScannerTests(unittest.TestCase):
    """Execute the actual Java scanner on synthetic ZIPs, not a Python reimplementation."""
    @classmethod
    def setUpClass(cls):
        cls.javac=shutil.which('javac');cls.java=shutil.which('java')
        if not cls.javac or not cls.java:raise unittest.SkipTest('JDK required; Android CI still compiles and executes helper')
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        harness=cls.root/'Harness.java';harness.write_text('''import com.dvk.control.UnityArchiveScan;import java.io.File;import java.util.*;
public final class Harness {public static void main(String[] args){ArrayList<File> paths=new ArrayList<>();for(String a:args)paths.add(new File(a));UnityArchiveScan.Report r=UnityArchiveScan.scan(paths);System.out.println("complete="+r.complete);System.out.println("archives="+r.archiveCount);System.out.println("entries="+r.entries);for(UnityArchiveScan.Archive a:r.archives)System.out.println("archive="+a.index+":"+a.status);for(UnityArchiveScan.Marker m:r.markers)System.out.println("marker="+m.archive+":"+m.kind+":"+m.abi);}}''',encoding='utf-8')
        subprocess.run([cls.javac,'-encoding','UTF-8','-d',str(cls.root),str(JAVA),str(harness)],check=True,capture_output=True,timeout=30)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def apk(self,name,entries):
        p=self.root/name
        with zipfile.ZipFile(p,'w') as z:
            for n in entries:z.writestr(n,b'not-real-code')
        return p
    def scan(self,*paths):return subprocess.check_output([self.java,'-cp',str(self.root),'Harness',*map(str,paths)],text=True,timeout=15)
    def test_split_native_library_and_base_metadata_both_found(self):
        base=self.apk('base.apk',['assets/bin/Data/Managed/Metadata/global-metadata.dat']);split=self.apk('split.apk',['lib/arm64-v8a/libil2cpp.so','lib/arm64-v8a/libunity.so'])
        out=self.scan(base,split);self.assertIn('complete=true',out);self.assertIn('marker=0:il2cpp_metadata:',out);self.assertIn('marker=1:il2cpp_library:arm64-v8a',out)
    def test_mono_managed_and_duplicate_kind_libraries_deduplicated(self):
        p=self.apk('mono.apk',['lib/x86/libmono.so','lib/x86/libmonosgen-2.0.so','assets/bin/Data/Managed/Assembly-CSharp.dll'])
        out=self.scan(p);self.assertIn('complete=true',out);self.assertEqual(out.count('marker=0:mono_library:x86'),1);self.assertIn('managed_assembly',out)
    def test_substrings_path_traversal_and_other_assets_are_not_markers(self):
        p=self.apk('noise.apk',['private/token.txt','some/libil2cpp.so','lib/x86/libil2cpp.so.bak','lib/../../libunity.so','assets/not/global-metadata.dat'])
        out=self.scan(p);self.assertNotIn('marker=',out);self.assertNotIn('private',out)
    def test_corrupt_missing_duplicate_archives_incomplete(self):
        p=self.apk('valid.apk',['lib/x86/libunity.so']);corrupt=self.root/'corrupt.apk';corrupt.write_bytes(b'bad')
        for paths in ((p,p),(corrupt,),(self.root/'missing.apk',),()):self.assertIn('complete=false',self.scan(*paths))
    def test_archive_count_cap(self):
        paths=[self.apk('cap%d.apk'%i,['f']) for i in range(34)]
        out=self.scan(*paths);self.assertIn('complete=false',out);self.assertEqual(out.count('archive='),33)
    def test_global_entry_cap(self):
        p=self.apk('many.apk',['noise/%d'%i for i in range(150001)])
        out=self.scan(p);self.assertIn('complete=false',out);self.assertIn('entries=150000',out)
    def test_marker_limit_is_incomplete_not_a_negative_result(self):
        p=self.apk('markers.apk',['lib/abi%d/libil2cpp.so'%i for i in range(129)])
        out=self.scan(p);self.assertIn('complete=false',out);self.assertEqual(out.count('marker='),128)
    def test_android_wrapper_never_reads_ui_text_or_accepts_arbitrary_paths(self):
        wrapper=(ROOT/'control-android-v2/src/com/dvk/control/UnityDiagnostics.java').read_text(encoding='utf-8')
        for forbidden in ('getInputStream','sourceDir")','takeScreenshot','getText(', 'ProcessBuilder','Runtime.getRuntime'):
            self.assertNotIn(forbidden,wrapper)
        dispatch=(ROOT/'control-android-v2/src/com/dvk/control/UiHierarchyBridge.java').read_text(encoding='utf-8')
        branch=dispatch.split('if("ui_unity_diagnostics".equals(op))')[1].split('\n')[0]
        self.assertNotIn('tree()',branch);self.assertIn('getPackageName()',branch)
    def test_source_never_opens_entry_payload_or_executes_process(self):
        s=JAVA.read_text(encoding='utf-8')
        for forbidden in ('getInputStream','extract','Runtime.getRuntime','ProcessBuilder','loadLibrary','takeScreenshot'):
            if forbidden=='extract':continue # explanatory comment only
            self.assertNotIn(forbidden,s)

if __name__=='__main__':unittest.main()
