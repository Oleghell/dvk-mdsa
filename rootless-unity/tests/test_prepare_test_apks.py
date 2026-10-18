import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('prepare_test_apks', Path(__file__).resolve().parents[1]/'prepare_test_apks.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(path, overrides=None):
    data={'AndroidManifest.xml':b'original manifest', 'resources.arsc':b'original resources',
          'classes.dex':b'original dex1', 'classes5.dex':b'original dex5',
          'assets/test.txt':b'original asset', 'META-INF/BNDLTOOL.RSA':b'old signature',
          'META-INF/MANIFEST.MF':b'old manifest signature', 'stamp-cert-sha256':b'old source stamp'}
    data.update(overrides or {})
    with zipfile.ZipFile(path,'w') as z:
        for name,payload in data.items():z.writestr(name,payload)


class Bootstrap(unittest.TestCase):
    def test_unknown_launcher_rejected(self):
        with self.assertRaises(ValueError):m.patch_launcher('.class Lother/App;')

    def test_exact_gate_appends_only_new_initializer(self):
        original='.class Lexample/Synthetic;\n'
        with patch.object(m,'LAUNCHER_SHA256',hashlib.sha256(original.encode()).hexdigest()):
            result=m.patch_launcher(original)
        self.assertEqual(result,original+m.METHOD)
        self.assertIn('const-string v0, "frida-gadget"',result)
        self.assertNotIn('onCreate',result)
        self.assertNotIn('catch',result)

    def test_existing_initializer_rejected_even_with_hash(self):
        text='.method static constructor <clinit>()V\n'
        with patch.object(m,'LAUNCHER_SHA256',hashlib.sha256(text.encode()).hexdigest()):
            with self.assertRaises(ValueError):m.patch_launcher(text)

    def test_config_local_authenticated_nonblocking_no_scripts(self):
        config=m.gadget_config('a'*64)
        self.assertEqual(set(config),{'interaction'})
        cfg=config['interaction']
        self.assertEqual(cfg['address'],'127.0.0.1')
        self.assertEqual(cfg['on_load'],'resume')
        self.assertEqual(cfg['on_port_conflict'],'fail')
        self.assertEqual(cfg['token'],'a'*64)
        self.assertNotIn('asset_root',cfg)
        self.assertNotIn('path',cfg)
        self.assertEqual(cfg['type'],'listen')

    def test_no_empty_authentication(self):
        for value in ('', 'a'*63, 'g'*64, 'token'):
            with self.assertRaises(ValueError):m.gadget_config(value)

    def test_rewrite_changes_only_selected_dex_and_signature_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/'src.apk';dst=Path(temp)/'dst.apk'
            fixture(src)
            m.rewrite_apk(src,dst,{'classes5.dex':b'modified synthetic dex'})
            report=m.verify_preserved(src,dst,{'classes5.dex'})
            self.assertTrue(report['manifest_byte_identical'])
            self.assertEqual(report['unchanged_entries_verified'],4)
            with zipfile.ZipFile(dst) as z:
                self.assertEqual(z.read('classes5.dex'),b'modified synthetic dex')
                self.assertEqual(z.read('classes.dex'),b'original dex1')
                self.assertNotIn('stamp-cert-sha256',z.namelist())
                self.assertNotIn('META-INF/BNDLTOOL.RSA',z.namelist())

    def test_native_library_entries_preserved_when_gadget_added(self):
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/'src.apk';dst=Path(temp)/'dst.apk'
            fixture(src,{'lib/arm64-v8a/libunity.so':b'original engine'})
            additions={'lib/arm64-v8a/libfrida-gadget.so':b'synthetic gadget',
                       'lib/arm64-v8a/libfrida-gadget.config.so':json.dumps(m.gadget_config('b'*64)).encode()}
            m.rewrite_apk(src,dst,additions)
            self.assertTrue(m.verify_preserved(src,dst,set(additions))['manifest_byte_identical'])
            with zipfile.ZipFile(dst) as z:
                self.assertEqual(z.read('lib/arm64-v8a/libunity.so'),b'original engine')

    def test_unexpected_replacement_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/'src.apk';dst=Path(temp)/'dst.apk';fixture(src)
            with self.assertRaises(ValueError):m.rewrite_apk(src,dst,{'AndroidManifest.xml':b'modified'})

    def test_preservation_check_rejects_arbitrary_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/'src.apk';dst=Path(temp)/'dst.apk';fixture(src)
            fixture(dst,{'assets/test.txt':b'changed'})
            with self.assertRaises(ValueError):m.verify_preserved(src,dst,{'classes5.dex'})

    def test_input_sha_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic';path.write_bytes(b'synthetic')
            m.require_hash(path,hashlib.sha256(b'synthetic').hexdigest())
            with self.assertRaises(ValueError):m.require_hash(path,'0'*64)

    def test_tool_does_not_import_adb_or_network_clients(self):
        import ast
        source=Path(m.__file__).read_text(encoding='utf-8')
        tree=ast.parse(source)
        imports={alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names}
        self.assertFalse(imports & {'socket','urllib','requests','frida','apk_export'})
        self.assertNotIn('adb.exe',source)
        self.assertNotIn('Runtime;->exec',m.METHOD)
        self.assertNotIn('System;->exit',m.METHOD)


if __name__=='__main__':unittest.main()
