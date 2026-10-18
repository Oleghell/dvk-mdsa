import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('apk_export', Path(__file__).resolve().parents[1] / 'apk_export.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
PARENT = '/data/app/~~abc==/drug.vokrug-XYZ=='
BASE = PARENT + '/base.apk'
SPLIT = PARENT + '/split_config.arm64_v8a.apk'
REPLY = 'package:' + SPLIT + '\npackage:' + BASE


def make_apk(path):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('AndroidManifest.xml', b'synthetic binary fixture, not a real application')
        archive.writestr('classes.dex', b'synthetic only')


class Paths(unittest.TestCase):
    def test_current_layout_and_sort(self):
        self.assertEqual(m.parse_apk_paths(REPLY), [BASE, SPLIT])

    def test_old_layout(self):
        p = '/data/app/drug.vokrug-test/base.apk'
        self.assertEqual(m.parse_apk_paths('package:' + p), [p])

    def test_reject_unsafe(self):
        for reply in ('', 'error: denied', 'package:/data/data/drug.vokrug/base.apk',
                      'package:' + BASE + ';id', 'package:' + BASE + '\x00',
                      'package:' + BASE.replace('drug.vokrug', 'other.package'),
                      'package:' + BASE.replace('~~abc==', '..'),
                      'package:' + BASE.replace('~~abc==', 'abc'),
                      'package:' + BASE.replace('/base.apk', '//base.apk'),
                      'package:' + SPLIT, 'package:' + BASE + '\npackage:' + BASE,
                      REPLY.replace('split_config', '../split_config'),
                      REPLY.replace('~~abc==/drug.vokrug-XYZ==/split', '~~abc==/drug.vokrug-new/split'),
                      'package:' + BASE.replace('base.apk', 'random.apk')):
            with self.subTest(reply=repr(reply)):
                with self.assertRaises(m.ExportError):
                    m.parse_apk_paths(reply)

    def test_bounds(self):
        for text in ('a' * 32769, 'package:' + BASE + '\n' + '\n'.join(
                'package:' + PARENT + '/split_' + str(i) + '.apk' for i in range(33))):
            with self.assertRaises(m.ExportError):
                m.parse_apk_paths(text)


class Commands(unittest.TestCase):
    def test_allow_readonly(self):
        for args in (['version'], ['connect', m.SERIAL], ['-s', m.SERIAL, 'get-state'],
                     ['-s', m.SERIAL, 'shell', 'pm', 'path', m.PACKAGE]):
            m.AdbReader.validate_args(args)
        with tempfile.TemporaryDirectory() as temp:
            m.AdbReader.validate_args(['-s', m.SERIAL, 'pull', BASE, str(Path(temp) / 'base.apk')])
            m.AdbReader.validate_args(['-s', m.SERIAL, 'pull', SPLIT, str(Path(temp) / 'split-001.apk')])

    def test_no_mutation_or_arbitrary_shell(self):
        for args in (['root'], ['shell', 'su'], ['install', 'x.apk'], ['uninstall', m.PACKAGE],
                     ['-s', m.SERIAL, 'shell', 'input', 'tap', '1', '1'],
                     ['-s', m.SERIAL, 'shell', 'screencap'],
                     ['-s', m.SERIAL, 'shell', 'run-as', m.PACKAGE],
                     ['-s', m.SERIAL, 'shell', 'pm', 'path', 'other.package'],
                     ['connect', 'example.com:5555'], ['-s', 'other', 'get-state']):
            with self.subTest(args=args):
                with self.assertRaises(m.ExportError):
                    m.AdbReader.validate_args(args)

    def test_pull_no_overwrite_or_private_data(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'base.apk'
            target.write_bytes(b'keep')
            for remote, local in ((BASE, target), ('/data/data/drug.vokrug/shared_prefs/a.xml', target),
                                  (BASE, 'relative/base.apk'), (BASE, Path(temp) / 'file.txt')):
                with self.assertRaises(m.ExportError):
                    m.AdbReader.validate_args(['-s', m.SERIAL, 'pull', remote, str(local)])
            self.assertEqual(target.read_bytes(), b'keep')

    def test_executable_restricted(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'not-adb.exe'
            p.touch()
            with self.assertRaises(m.ExportError):
                m.AdbReader(str(p))

    def test_subprocess_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'adb.exe'
            p.touch()
            reader = m.AdbReader(str(p))
            def fake(command, **kwargs):
                self.assertEqual(command, [str(p), 'version'])
                self.assertFalse(kwargs['shell'])
                self.assertEqual(kwargs['env']['ADB_SERVER_SOCKET'], 'tcp:localhost:5037')
                self.assertNotIn('ANDROID_SERIAL', kwargs['env'])
                kwargs['stdout'].write(b'Android Debug Bridge')
                return subprocess.CompletedProcess(command, 0)
            with patch.object(m.subprocess, 'run', fake):
                self.assertEqual(reader.run(['version']), 'Android Debug Bridge')

    def test_timeout_and_failure_do_not_leak_output(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'adb.exe'
            p.touch()
            reader = m.AdbReader(str(p))
            for error in (subprocess.TimeoutExpired('adb', 30), OSError('private path')):
                with patch.object(m.subprocess, 'run', side_effect=error):
                    with self.assertRaises(m.ExportError) as caught:
                        reader.run(['version'])
                    self.assertNotIn('private path', str(caught.exception))
            def failed(command, **kwargs):
                kwargs['stdout'].write(b'PRIVATE diagnostic data')
                return subprocess.CompletedProcess(command, 1)
            with patch.object(m.subprocess, 'run', failed):
                with self.assertRaises(m.ExportError) as caught:
                    reader.run(['version'])
                self.assertNotIn('PRIVATE', str(caught.exception))


class FakeReader:
    def __init__(self, fail=False, changed=False):
        self.calls = []
        self.fail = fail
        self.changed = changed
        self.path_reads = 0

    def run(self, args, timeout=30):
        m.AdbReader.validate_args(args)
        self.calls.append(args)
        if args[-1] == 'get-state':
            return 'device'
        if args[-3:] == ['pm', 'path', m.PACKAGE]:
            self.path_reads += 1
            return REPLY.replace('XYZ==', 'changed') if self.changed and self.path_reads > 1 else REPLY
        if 'pull' in args:
            if self.fail:
                raise m.ExportError('synthetic failure')
            make_apk(Path(args[-1]))
        return 'ok'


class Export(unittest.TestCase):
    def setUp(self):
        self.disk = patch.object(m.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 10 * 1024**3})())
        self.disk.start()
        self.addCleanup(self.disk.stop)

    def test_archive_contents_hashes_no_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            reader = FakeReader()
            output = m.export_apks(reader, Path(temp))
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {'base.apk', 'split-001.apk', 'manifest.json'})
                raw = archive.read('manifest.json').decode('utf-8')
                info = json.loads(raw)
                self.assertNotIn('/data/app', raw)
                self.assertNotIn(temp, raw)
                self.assertFalse(info['app_data_included'])
                self.assertEqual(info['app_version'], 'not-checked')
                for item in info['files']:
                    data = archive.read(item['file'])
                    self.assertEqual(item['sha256'], hashlib.sha256(data).hexdigest())
                    self.assertEqual(item['size_bytes'], len(data))
            self.assertEqual(reader.path_reads, 2)
            self.assertEqual(list(Path(temp).iterdir()), [output])

    def test_failure_cleans_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(m.ExportError):
                m.export_apks(FakeReader(fail=True), Path(temp))
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_racing_install_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(m.ExportError):
                m.export_apks(FakeReader(changed=True), Path(temp))
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_cancel_before_contact(self):
        with tempfile.TemporaryDirectory() as temp:
            reader = FakeReader()
            with self.assertRaises(m.ExportError):
                m.export_apks(reader, Path(temp), cancelled=lambda: True)
            self.assertEqual(reader.calls, [])

    def test_low_disk_no_contact(self):
        with tempfile.TemporaryDirectory() as temp:
            reader = FakeReader()
            with patch.object(m.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 0})()):
                with self.assertRaises(m.ExportError):
                    m.export_apks(reader, Path(temp))
            self.assertEqual(reader.calls, [])

    def test_cancel_mid_zip_cleans_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            checks = 0
            def cancel():
                nonlocal checks
                checks += 1
                return checks >= 8
            with self.assertRaises(m.ExportError):
                m.export_apks(FakeReader(), Path(temp), cancelled=cancel)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_no_overwrite_existing_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            a = m.export_apks(FakeReader(), Path(temp))
            original = a.read_bytes()
            b = m.export_apks(FakeReader(), Path(temp))
            self.assertNotEqual(a, b)
            self.assertEqual(a.read_bytes(), original)

    def test_invalid_zip_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'bad.apk'
            p.write_bytes(b'notzip')
            with self.assertRaises(m.ExportError):
                m.validate_apk(p)
            with zipfile.ZipFile(p, 'w') as archive:
                archive.writestr('other.txt', 'synthetic')
            with self.assertRaises(m.ExportError):
                m.validate_apk(p)

    def test_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'base.apk'
            make_apk(p)
            with patch.object(m, 'MAX_APK_BYTES', 1):
                with self.assertRaises(m.ExportError):
                    m.validate_apk(p)
            p.unlink()
            with patch.object(m, 'MAX_TOTAL_BYTES', 1):
                with self.assertRaises(m.ExportError):
                    m.export_apks(FakeReader(), Path(temp))
            self.assertEqual(list(Path(temp).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
