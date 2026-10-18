import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('test_device_core',Path(__file__).resolve().parents[1]/'test_device.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
ORIGINAL='11111111-1111-1111-1111-111111111111'
TARGET_ID='44444444-4444-4444-4444-444444444444'
TOKEN='a'*64


def good_probe(*args):
    return {'frida_version':'17.24.1','arch':'arm64','platform':'linux','unity_loaded':True,
            'il2cpp_loaded':True,'il2cpp_exports':{n:True for n in m.EXPORTS}}


class FakeAdb:
    def __init__(self, present=False,same=False,change=False,fail_install=False):
        self.present=present;self.same=same;self.change=change;self.fail_install=fail_install
        self.forward_port=None;self.calls=[];self.id_reads=0
    def run(self,args,timeout=30):
        self.calls.append(args)
        if args[-1]=='get-state':return 'device'
        if args[-2:]==['cat',m.BOOT_ID]:
            self.id_reads+=1
            if args[1]==m.WORKING:return ORIGINAL
            return ORIGINAL if self.same else ('55555555-5555-5555-5555-555555555555' if self.change and self.id_reads>2 else TARGET_ID)
        if args[-2:]==['getprop','sys.boot_completed']:return '1'
        if args[-4:]==['pm','list','packages',m.PACKAGE]:return 'package:'+m.PACKAGE if self.present else ''
        if len(args)>2 and args[2]=='install-multiple':
            if self.fail_install:raise m.TestError('synthetic installation failure')
            self.present=True;return 'Success'
        if args[-3:]==['forward','tcp:0','tcp:27042']:return '37149'
        return 'ok'


class AdbGuards(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'adb.exe').touch()
        self.reader=m.TestAdb(str(self.root/'adb.exe'),self.root)
    def test_allow_only_fixed_target_install(self):
        self.reader.validate(['-s',m.TARGET,'install-multiple',str(self.reader.folder/'base.apk'),str(self.reader.folder/'split-001.apk')])
        for serial in (m.WORKING,m.TARGET):
            self.reader.validate(['-s',serial,'get-state'])
            self.reader.validate(['-s',serial,'shell','cat',m.BOOT_ID])
    def test_never_modify_working_or_unknown_device(self):
        for serial in (m.WORKING,'127.0.0.1:16512','127.0.0.1:16384','example.com:5555'):
            for op in (['install-multiple','base.apk','split-001.apk'],['shell','am','start','-n',m.LAUNCHER],['forward','tcp:0','tcp:27042']):
                with self.subTest(serial=serial,op=op):
                    with self.assertRaises(m.TestError):self.reader.validate(['-s',serial,*op])
    def test_no_root_replacement_uninstall_or_ui_actions(self):
        for op in (['root'],['shell','su'],['uninstall',m.PACKAGE],['install-multiple','-r','base.apk'],
                   ['shell','input','tap','1','1'],['shell','screencap'],['shell','run-as',m.PACKAGE],
                   ['shell','pm','clear',m.PACKAGE],['shell','settings','get','secure','android_id']):
            with self.subTest(op=op):
                with self.assertRaises(m.TestError):self.reader.validate(['-s',m.TARGET,*op])
    def test_forward_removal_only_owned_port(self):
        with self.assertRaises(m.TestError):self.reader.validate(['-s',m.TARGET,'forward','--remove','tcp:37149'])
        self.reader.forward_port=37149
        self.reader.validate(['-s',m.TARGET,'forward','--remove','tcp:37149'])
        with self.assertRaises(m.TestError):self.reader.validate(['-s',m.TARGET,'forward','--remove-all'])
    def test_install_only_verified_local_names(self):
        with self.assertRaises(m.TestError):self.reader.validate(['-s',m.TARGET,'install-multiple','/other/base.apk','/other/split-001.apk'])
    def test_subprocess_no_shell_and_local_server(self):
        import subprocess
        def fake(command,**kwargs):
            self.assertFalse(kwargs['shell']);self.assertEqual(kwargs['env']['ADB_SERVER_SOCKET'],'tcp:localhost:5037')
            kwargs['stdout'].write(b'ok');return subprocess.CompletedProcess(command,0)
        with patch.object(m.subprocess,'run',fake):self.assertEqual(self.reader.run(['version']),'ok')


class Preflight(unittest.TestCase):
    def test_same_device_alias_stops_before_any_install(self):
        adb=FakeAdb(same=True)
        with self.assertRaises(m.TestError):m.preflight(adb,True)
        self.assertFalse(any('install-multiple' in c for c in adb.calls))
    def test_existing_app_blocks_install_but_allows_readonly_probe(self):
        with self.assertRaises(m.TestError):m.preflight(FakeAdb(present=True),True)
        self.assertEqual(m.preflight(FakeAdb(present=True),False),(ORIGINAL,TARGET_ID))
    def test_no_app_cannot_probe(self):
        with self.assertRaises(m.TestError):m.preflight(FakeAdb(),False)
    def test_identity_recheck_stops_port_switch(self):
        adb=FakeAdb(change=True);identities=m.preflight(adb,True)
        with self.assertRaises(m.TestError):m.recheck(adb,identities)
    def test_boot_id_must_be_uuid(self):
        class Bad(FakeAdb):
            def run(self,args,timeout=30):return 'Permission denied'
        with self.assertRaises(m.TestError):m.boot_id(Bad(),m.TARGET)


class Result(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'test-apks';self.folder.mkdir()
        self.mock=patch.object(m,'bundle_token',return_value=TOKEN);self.mock.start();self.addCleanup(self.mock.stop)
    def test_install_launch_probe_only_on_target_and_cleanup(self):
        adb=FakeAdb()
        report,path=m.execute(adb,self.folder,True,probe=good_probe)
        self.assertEqual(report['probe_status'],'passed');self.assertTrue(report['test_apks_installed'])
        self.assertEqual(report['unity_object_access'],'not-tested')
        self.assertEqual(sum('install-multiple' in c for c in adb.calls),1)
        modifications=[c for c in adb.calls if 'install-multiple' in c or 'am' in c or 'forward' in c]
        self.assertTrue(all(c[1]==m.TARGET for c in modifications))
        self.assertIn(['-s',m.TARGET,'forward','--remove','tcp:37149'],adb.calls)
        text=path.read_text(encoding='utf-8')
        for private in (TOKEN,ORIGINAL,TARGET_ID):self.assertNotIn(private,text)
        self.assertFalse(report['working_device_modified']);self.assertEqual(report['messages_sent'],0)
    def test_probe_only_does_not_install_or_launch(self):
        adb=FakeAdb(present=True);report,_=m.execute(adb,self.folder,False,probe=good_probe)
        self.assertEqual(report['probe_status'],'passed')
        self.assertFalse(any('install-multiple' in c or 'am' in c for c in adb.calls))
    def test_probe_failure_cleans_forward_and_does_not_leak_error(self):
        adb=FakeAdb()
        def bad(*args):raise RuntimeError(TOKEN+' private internal diagnostic')
        report,path=m.execute(adb,self.folder,True,probe=bad)
        self.assertEqual(report['probe_status'],'failed');self.assertTrue(report['test_apks_installed'])
        self.assertIn(['-s',m.TARGET,'forward','--remove','tcp:37149'],adb.calls)
        self.assertNotIn(TOKEN,path.read_text(encoding='utf-8'))
    def test_existing_app_never_replaced(self):
        adb=FakeAdb(present=True);report,_=m.execute(adb,self.folder,True,probe=good_probe)
        self.assertEqual(report['failure_stage'],'device-preflight')
        self.assertFalse(any('install-multiple' in c for c in adb.calls))
    def test_install_failure_does_not_launch_or_retry(self):
        adb=FakeAdb(fail_install=True);report,_=m.execute(adb,self.folder,True,probe=good_probe)
        self.assertFalse(report['test_apks_installed'])
        self.assertEqual(sum('install-multiple' in c for c in adb.calls),1)
        self.assertFalse(any('am' in c or 'forward' in c for c in adb.calls))
    def test_cancellation_before_install(self):
        adb=FakeAdb();m.execute(adb,self.folder,True,cancelled=lambda:True,probe=good_probe)
        self.assertFalse(any('install-multiple' in c for c in adb.calls))
    def test_modules_missing_not_reported_as_working(self):
        def missing(*args):
            data=good_probe();data['il2cpp_loaded']=False;return data
        report,_=m.execute(FakeAdb(),self.folder,True,probe=missing)
        self.assertEqual(report['probe_status'],'modules-not-ready')
    def test_bad_schema_or_arch_rejected(self):
        for key,value in (('arch','x64'),('frida_version','17.0.0'),('unity_loaded','yes'),('il2cpp_exports',{})):
            data=good_probe();data[key]=value
            with self.assertRaises(m.TestError):m.validate_probe(data)
    def test_fixed_script_cannot_read_users_or_trigger_actions(self):
        for forbidden in ('NativeFunction','Interceptor','Memory.read','Java.perform','sendMessage','UnityEngine.UI','InputField'):
            self.assertNotIn(forbidden,m.PROBE_SCRIPT)
        self.assertIn('findModuleByName',m.PROBE_SCRIPT)
        self.assertIn('findExportByName',m.PROBE_SCRIPT)


class Bundle(unittest.TestCase):
    def test_bad_hash_prevents_device_access(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'base.apk').write_bytes(b'wrong')
            with self.assertRaises(m.TestError):m.bundle_token(folder)


if __name__=='__main__':unittest.main()
