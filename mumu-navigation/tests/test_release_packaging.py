"""Final ZIP verifies the build inventory and excludes signing credentials."""
from pathlib import Path
import base64,hashlib,importlib.util,json,tempfile,unittest
from unittest.mock import patch
from control_release import PACKAGES,SIGNER_SHA256,VERSION
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_package',ROOT/'package-release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'windows';self.root.mkdir()
        for name in ('MuMu-navigation.exe','cloudflared.exe','helper.apk','helper-manifest.json','city-helper.apk','city-helper-manifest.json','README.md','START-HERE.md'):(self.root/name).write_bytes(b'MZsynthetic-test')
        for name in PACKAGES:(self.root/name).write_bytes(base64.b64decode((ROOT/'control-android-v2/pinned'/(name+'.base64')).read_text(encoding='utf-8')))
        self.info={'bridge_version':VERSION,'cursor_stable_runtime_included':True,'control_package':'com.dvk.control.v2','keyboard_package':'com.dvk.keyboard.v2','control_signer_sha256':SIGNER_SHA256,'source_commit':'a'*40}
        self.write_info();self.env=patch.dict('os.environ',{'GITHUB_SHA':'a'*40});self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def rehash(self):
        (self.root/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(self.root.iterdir()) if p.name!='SHA256SUMS.txt'), encoding='utf-8')
    def write_info(self):
        (self.root/'BUILD_INFO.json').write_text(json.dumps(self.info), encoding='utf-8');self.rehash()
    def test_complete_inventory_produces_zip_and_hash(self):
        out=module.package(self.root);self.assertTrue(out.is_file());self.assertIn(out.name,(out.parent/'SHA256SUMS.txt').read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):module.package(self.root)
    def test_changed_file_fails(self):
        (self.root/'MuMu-navigation.exe').write_bytes(b'MZchanged')
        with self.assertRaisesRegex(ValueError,'checksum'):module.package(self.root)
    def test_private_key_is_never_packaged_even_if_in_inventory(self):
        (self.root/'bad.p12').write_bytes(b'synthetic-not-a-key');self.rehash()
        with self.assertRaisesRegex(ValueError,'Private'):module.package(self.root)
    def test_false_runtime_or_wrong_commit_fails(self):
        self.info['cursor_stable_runtime_included']=False;self.write_info()
        with self.assertRaisesRegex(ValueError,'metadata'):module.package(self.root)
        self.info['cursor_stable_runtime_included']=True;self.info['source_commit']='b'*40;self.write_info()
        with self.assertRaisesRegex(ValueError,'commit'):module.package(self.root)
    def test_missing_documentation_fails(self):
        (self.root/'START-HERE.md').unlink();self.rehash()
        with self.assertRaisesRegex(ValueError,'Incomplete'):module.package(self.root)
if __name__=='__main__':unittest.main()
