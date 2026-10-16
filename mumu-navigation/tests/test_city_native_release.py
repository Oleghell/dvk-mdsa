"""Pinned APK/source consistency and executable pure Java catalog policy tests.

Does not pretend to run Android instrumentation on the host. Native UI scenarios
are in city-android/test-emulator.sh and must pass in the synthetic CI emulator.
"""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from limited_scenario import CITIES
from city_release import CITY_SOURCE_HASHES,CITY_APK_SHA256,CITY_DEX_SHA256,CITY_CERT_SHA256

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'city-android'

class CityNativeReleaseTests(unittest.TestCase):
    def apk(self):return base64.b64decode(''.join((NATIVE/'pinned/city-helper.apk.base64').read_text(encoding='utf-8').split()),validate=True)
    def test_exact_apk_and_dex_pins(self):
        data=self.apk();self.assertEqual(hashlib.sha256(data).hexdigest(),CITY_APK_SHA256)
        with zipfile.ZipFile(BytesIO(data)) as z:
            self.assertEqual(hashlib.sha256(z.read('classes.dex')).hexdigest(),CITY_DEX_SHA256)
        self.assertRegex(CITY_CERT_SHA256,'^[0-9a-f]{64}$')
    def test_all_native_release_sources_are_pinned(self):
        expected={'AndroidManifest.xml','src/com/dvk/city/CityPolicy.java','src/com/dvk/city/CityInstrumentation.java'}
        self.assertEqual(set(CITY_SOURCE_HASHES),expected)
        for path,sha in CITY_SOURCE_HASHES.items():self.assertEqual(hashlib.sha256((NATIVE/path).read_bytes()).hexdigest(),sha)
    @unittest.skipUnless(shutil.which('git'),'Git required to verify Windows checkout rules')
    def test_windows_autocrlf_preserves_approved_source_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout=Path(tmp)
            shutil.copy(ROOT.parent/'.gitattributes',checkout/'.gitattributes')
            for name in CITY_SOURCE_HASHES:
                target=checkout/'mumu-navigation/city-android'/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((NATIVE/name).read_bytes())
            def git(*args):
                subprocess.run(['git','-C',tmp,*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            git('init');git('config','core.autocrlf','true');git('config','core.safecrlf','false')
            git('add','.')
            for name in CITY_SOURCE_HASHES:
                (checkout/'mumu-navigation/city-android'/name).unlink()
            git('checkout-index','-a','-f')
            for name,sha in CITY_SOURCE_HASHES.items():
                data=(checkout/'mumu-navigation/city-android'/name).read_bytes()
                self.assertNotIn(b'\r\n',data)
                self.assertEqual(hashlib.sha256(data).hexdigest(),sha)
    def test_native_city_catalog_exactly_matches_python(self):
        s=(NATIVE/'src/com/dvk/city/CityPolicy.java').read_text(encoding='utf-8')
        match=re.search(r'String\[\] CITIES = \{(.*?)\};',s,re.S)
        self.assertEqual(tuple(json.loads('['+match[1]+']')),CITIES)
    def test_native_has_no_network_chat_keyevent_or_tap_api(self):
        s=(NATIVE/'src/com/dvk/city/CityInstrumentation.java').read_text(encoding='utf-8')
        for token in ('MotionEvent','KeyEvent','injectInputEvent','performGlobalAction','ACTION_IME_ENTER','ACTION_CLICK'):
            self.assertNotIn(token,s)
        self.assertEqual(s.count('edit.performAction('),1)
        self.assertIn('edit.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,value)',s)
        manifest=(NATIVE/'AndroidManifest.xml').read_text(encoding='utf-8')
        self.assertNotIn('uses-permission',manifest);self.assertNotIn('<service',manifest)
        self.assertIn('com.dvk.city.v1',manifest);self.assertNotIn('com.dvk.navigation.v132',manifest)
    def test_builder_never_generates_new_release_key(self):
        s=(NATIVE/'build.sh').read_text(encoding='utf-8')
        self.assertNotIn('keytool -genkeypair',s)
        self.assertIn('CITY_KEYSTORE',s);self.assertIn('CITY_CERT_SHA256',s);self.assertIn('CITY_VERIFY_ONLY',s)
    def stage(self,tmp):
        root=Path(tmp)/'city-android';root.mkdir()
        shutil.copy(ROOT/'city_release.py',root.parent/'city_release.py')
        for path in CITY_SOURCE_HASHES:
            target=root/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy(NATIVE/path,target)
        (root/'pinned').mkdir();shutil.copy(NATIVE/'pinned/city-helper.apk.base64',root/'pinned/city-helper.apk.base64')
        (root/'out/dex').mkdir(parents=True)
        with zipfile.ZipFile(BytesIO(self.apk())) as z:(root/'out/dex/classes.dex').write_bytes(z.read('classes.dex'))
        return root
    def test_packaging_accepts_only_exact_release(self):
        pack=runpy.run_path(str(NATIVE/'pack-city-helper.py'))['package']
        with tempfile.TemporaryDirectory() as tmp:
            root=self.stage(tmp);path=pack(root);self.assertEqual(path.read_bytes(),self.apk())
            self.assertTrue((root/'out/city-helper-manifest.json').exists())
    def test_changed_source_dex_or_apk_is_refused(self):
        pack=runpy.run_path(str(NATIVE/'pack-city-helper.py'))['package']
        for target in ('src/com/dvk/city/CityPolicy.java','out/dex/classes.dex','pinned/city-helper.apk.base64'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as tmp:
                root=self.stage(tmp);p=root/target;p.write_bytes(p.read_bytes()+b'CHANGED')
                with self.assertRaises(ValueError):pack(root)
    @unittest.skipUnless(shutil.which('javac'),'Java compiler required; synthetic Android CI has Java17')
    def test_java_policy_executes_all_city_indices_and_denies_invalid_ops(self):
        expected=','.join(json.dumps(c,ensure_ascii=False) for c in CITIES)
        runner='''package com.dvk.city;
public final class PolicyTest {
 static void check(boolean b){if(!b)throw new AssertionError();}
 static final class Probe implements CityPolicy.RootProbe {
  int calls=0,pauses=0,readyAt,result;
  Probe(int readyAt,int result){this.readyAt=readyAt;this.result=result;}
  public int state(){calls++;return calls>=readyAt?result:0;}
  public void pause(){pauses++;}
 }
 public static void main(String[] args){
 String[] names={NAMES};String sha=new String(new char[64]).replace('\\0','a');
 Probe cold=new Probe(3,1);check(CityPolicy.awaitRoot(cold)==1 && cold.calls==3 && cold.pauses==2);
 Probe never=new Probe(99,1);check(CityPolicy.awaitRoot(never)==0 && never.calls==24 && never.pauses==23);
 Probe wrong=new Probe(1,-1);check(CityPolicy.awaitRoot(wrong)==-1 && wrong.calls==1 && wrong.pauses==0);
 Probe last=new Probe(24,1);check(CityPolicy.awaitRoot(last)==1 && last.pauses==23);
 check(CityPolicy.size()==30);
 for(int i=0;i<30;i++){
 check(CityPolicy.city(i).equals(names[i]));check(CityPolicy.matchesPrevious(names[i],i));
 check(CityPolicy.validArgs("city_input",sha,i,0));check(CityPolicy.validArgs("city_input",sha,i,30));
 }
 check(CityPolicy.matchesPrevious("",-1));check(!CityPolicy.matchesPrevious("KEEP_EXISTING",-1));
 check(!CityPolicy.validArgs("city_input",sha,-1,0));check(!CityPolicy.validArgs("city_input",sha,30,0));
 check(!CityPolicy.validArgs("city_input",sha,0,31));check(!CityPolicy.validArgs("city_input",sha,0,-1));
 for(String op:new String[]{"tap","back","greeting","finish_input","profile_chat","send",""})check(!CityPolicy.validArgs(op,sha,0,0));
 check(!CityPolicy.validArgs("city_input","bad",0,0));check(!CityPolicy.validArgs("city_input",null,0,0));
 check(CityPolicy.validArgs("inspect_city",sha,0,0));check(!CityPolicy.validArgs("inspect_city",sha,1,0));
 System.out.println("CITY_POLICY_JAVA_PASS");
 }
}'''.replace('NAMES',expected)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'PolicyTest.java').write_text(runner, encoding='utf-8', newline='\n')
            cmd=['javac','-encoding','UTF-8','-d',tmp,str(NATIVE/'src/com/dvk/city/CityPolicy.java'),str(p/'PolicyTest.java')]
            result=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr.decode()[:500])
            result=subprocess.run(['java','-cp',tmp,'com.dvk.city.PolicyTest'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr.decode()[:500]);self.assertIn(b'CITY_POLICY_JAVA_PASS',result.stdout)

if __name__=='__main__':unittest.main()
