"""Helper migration is local-only, narrowly scoped and opt-in. No real ADB."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from mumu_bridge import (AdbReader, BridgeError, HelperSignatureConflict,
                         PINNED_HELPER_SHA256, SERIAL, TOOLS,
                         install_helper_with_local_consent)

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pinned_helper',ROOT/'android/pack-pinned-helper.py')
PIN=importlib.util.module_from_spec(spec);spec.loader.exec_module(PIN)

class HelperInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        adb=self.root/'adb.exe';adb.touch();self.r=AdbReader(adb)
        self.raw=base64.b64decode(''.join((ROOT/'android/pinned/helper-v132.apk.base64').read_text().split()))
        (self.root/'helper.apk').write_bytes(self.raw)
        (self.root/'helper-manifest.json').write_text(json.dumps({'helper_sha256':PINNED_HELPER_SHA256}))
    def tearDown(self):self.tmp.cleanup()
    def test_fixed_pinned_checksum_required_even_if_manifest_changed(self):
        bad=b'not approved'
        (self.root/'helper.apk').write_bytes(bad)
        (self.root/'helper-manifest.json').write_text(json.dumps({'helper_sha256':hashlib.sha256(bad).hexdigest()}))
        with patch.object(self.r,'_run') as run:
            with self.assertRaises(BridgeError):self.r.install_helper(self.root)
        run.assert_not_called()
    def test_successful_regular_update_does_not_uninstall(self):
        with patch.object(self.r,'_run',return_value=b'Success') as run:
            self.r.install_helper(self.root)
        self.assertTrue(self.r.helper_ready)
        self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[0][2:5],['install','-t','-r'])
    def test_uninstall_not_allowlisted_without_local_migration(self):
        with patch('subprocess.run') as run:
            with self.assertRaises(BridgeError):self.r._run(['-s',SERIAL,'uninstall','com.dvk.navigation.v132'])
        run.assert_not_called()
    def test_uninstall_other_package_never_allowlisted(self):
        self.r._local_helper_migration=True
        with patch('subprocess.run') as run:
            with self.assertRaises(BridgeError):self.r._run(['-s',SERIAL,'uninstall','drug.vokrug'])
        run.assert_not_called()
    def test_missing_local_confirmation_does_not_delete(self):
        with patch.object(self.r,'_run') as run:
            for answer in [False,None,1,'yes']:
                with self.assertRaises(BridgeError):self.r._reinstall_helper_locally(self.root,answer)
        run.assert_not_called()
    def test_corrupt_replacement_never_deletes_existing_helper(self):
        (self.root/'helper.apk').write_bytes(b'corrupt')
        with patch.object(self.r,'_run') as run:
            with self.assertRaises(BridgeError):self.r._reinstall_helper_locally(self.root,True)
        run.assert_not_called()
    def test_local_migration_deletes_only_helper_and_installs_pinned_apk(self):
        commands=[]
        def fake(args):
            commands.append(args)
            if args[2]=='uninstall':self.assertTrue(self.r._local_helper_migration)
            else:self.assertFalse(self.r._local_helper_migration)
            return b'Success'
        with patch.object(self.r,'_run',side_effect=fake):self.r._reinstall_helper_locally(self.root,True)
        self.assertEqual(commands[0],['-s',SERIAL,'uninstall','com.dvk.navigation.v132'])
        self.assertEqual(commands[1],['-s',SERIAL,'install','-t','-r',str((self.root/'helper.apk').resolve())])
        self.assertTrue(self.r.helper_ready);self.assertFalse(self.r._local_helper_migration)
    def test_failed_delete_never_installs_or_retries(self):
        with patch.object(self.r,'_run',side_effect=BridgeError('failure')) as run:
            with self.assertRaises(BridgeError):self.r._reinstall_helper_locally(self.root,True)
        self.assertEqual(run.call_count,1);self.assertFalse(self.r._local_helper_migration)
    def test_non_success_delete_output_stops_without_install(self):
        with patch.object(self.r,'_run',return_value=b'Failure') as run:
            with self.assertRaises(BridgeError):self.r._reinstall_helper_locally(self.root,True)
        self.assertEqual(run.call_count,1)
    def test_signature_error_detected_without_exposing_raw_stderr(self):
        self.r.helper_path=(self.root/'helper.apk').resolve()
        proc=subprocess.CompletedProcess([],1,b'',b'PRIVATE_PATH INSTALL_FAILED_UPDATE_INCOMPATIBLE PRIVATE_TOKEN')
        with patch('subprocess.run',return_value=proc):
            with self.assertRaises(HelperSignatureConflict) as exc:self.r._run(['-s',SERIAL,'install','-t','-r',str(self.r.helper_path)])
        self.assertNotIn('PRIVATE',str(exc.exception))
    def test_generic_error_reports_stage_without_private_output(self):
        self.r.helper_path=(self.root/'helper.apk').resolve()
        proc=subprocess.CompletedProcess([],1,b'private-output',b'private-output')
        with patch('subprocess.run',return_value=proc):
            with self.assertRaises(BridgeError) as exc:self.r._run(['-s',SERIAL,'install','-t','-r',str(self.r.helper_path)])
        self.assertIn('установка помощника',str(exc.exception));self.assertNotIn('private-output',str(exc.exception))
    def test_unknown_install_failure_does_not_prompt_or_uninstall(self):
        r=Mock();r.install_helper.side_effect=BridgeError('other failure');prompt=Mock(return_value=True)
        with self.assertRaises(BridgeError):install_helper_with_local_consent(r,self.root,prompt)
        prompt.assert_not_called();r._reinstall_helper_locally.assert_not_called()
    def test_declining_signature_prompt_preserves_helper(self):
        r=Mock();r.install_helper.side_effect=HelperSignatureConflict();prompt=Mock(return_value=False)
        with self.assertRaises(BridgeError):install_helper_with_local_consent(r,self.root,prompt)
        prompt.assert_called_once_with();r._reinstall_helper_locally.assert_not_called()
    def test_accepting_signature_prompt_calls_local_migration_once(self):
        r=Mock();r.install_helper.side_effect=HelperSignatureConflict();prompt=Mock(return_value=True)
        install_helper_with_local_consent(r,self.root,prompt)
        prompt.assert_called_once_with();r._reinstall_helper_locally.assert_called_once_with(self.root,confirmed=True)
    def test_migration_failure_has_no_second_prompt_or_repeat(self):
        r=Mock();r.install_helper.side_effect=HelperSignatureConflict();r._reinstall_helper_locally.side_effect=BridgeError('failure')
        prompt=Mock(return_value=True)
        with self.assertRaises(BridgeError):install_helper_with_local_consent(r,self.root,prompt)
        self.assertEqual(prompt.call_count,1);self.assertEqual(r._reinstall_helper_locally.call_count,1)
    def test_no_remote_install_delete_reset_or_migration_tool(self):
        for tool in TOOLS:
            self.assertFalse(any(s in tool['name'] for s in ['install','delete','reset','migration']))

class PinnedHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for name in [*PIN.SOURCE_SHA256,'pinned/helper-v132.apk.base64']:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'android'/name,p)
    def tearDown(self):self.tmp.cleanup()
    def test_repeat_packaging_is_byte_identical(self):
        first=PIN.validated_apk(self.root);second=PIN.validated_apk(self.root)
        self.assertEqual(first,second);self.assertEqual(hashlib.sha256(first).hexdigest(),PINNED_HELPER_SHA256)
    def test_source_change_fails_closed(self):
        for name in PIN.SOURCE_SHA256:
            p=self.root/name;old=p.read_bytes();p.write_bytes(old+b'\n')
            with self.assertRaises(ValueError):PIN.validated_apk(self.root)
            p.write_bytes(old)
    def test_missing_source_fails(self):
        (self.root/'AndroidManifest.xml').unlink()
        with self.assertRaises(FileNotFoundError):PIN.validated_apk(self.root)
    def test_corrupt_apk_fails(self):
        (self.root/'pinned/helper-v132.apk.base64').write_text(base64.b64encode(b'corrupt').decode())
        with self.assertRaises(ValueError):PIN.validated_apk(self.root)
    def test_rebuilt_dex_mismatch_blocks_distribution(self):
        p=self.root/'compiled.dex';p.write_bytes(b'different')
        with self.assertRaises(ValueError):PIN.validated_apk(self.root,p)
    def test_exact_dex_packages_pinned_apk_and_manifest(self):
        import zipfile
        from io import BytesIO
        raw=PIN.validated_apk(self.root)
        with zipfile.ZipFile(BytesIO(raw)) as z:dex=z.read('classes.dex')
        p=self.root/'out/helper/dex/classes.dex';p.parent.mkdir(parents=True);p.write_bytes(dex)
        PIN.package(self.root)
        self.assertEqual((self.root/'out/helper.apk').read_bytes(),raw)
        self.assertEqual(json.loads((self.root/'out/helper-manifest.json').read_text())['helper_sha256'],PINNED_HELPER_SHA256)

if __name__=='__main__':unittest.main()
