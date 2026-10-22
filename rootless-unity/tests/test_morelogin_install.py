"""Installer safety regression tests. Synthetic ADB only, no accounts/devices."""
from contextlib import contextmanager
import io,json,os
from pathlib import Path
import subprocess,sys,tempfile,threading,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from morelogin_install import OwnedAdb,InstallError,install_connected,backup,PACKAGE
BOOT='12345678-1234-1234-1234-123456789abc'
@contextmanager
def no_lock(_):yield
class Adb:
    def __init__(self,folder,exists=True,failure=None,sdk='35',abi='arm64-v8a'):
        self.folder=folder;self.exists=exists;self.failure=failure;self.sdk=sdk;self.abi=abi;self.calls=[];self.identity=BOOT;self.installs=0
    def op(self,*args,timeout=30):
        self.calls.append(args)
        if args==('get-state',):return 'device'
        if args==('shell','cat','/proc/sys/kernel/random/boot_id'):return self.identity
        if args==('shell','getprop','sys.boot_completed'):return '1'
        if args==('shell','getprop','ro.build.version.sdk'):return self.sdk
        if args==('shell','getprop','ro.product.cpu.abilist'):return self.abi
        if args==('shell','pm','list','packages',PACKAGE):return 'package:'+PACKAGE if self.exists else ''
        if args==('uninstall',PACKAGE):self.exists=False;return 'Success'
        if args[0]=='install-multiple':
            self.installs+=1
            if self.installs==1 and self.failure:raise self.failure
            self.exists=True;return 'Success'
        raise AssertionError(args)
def legacy_install(adb,replace,identity,stopped,progress,record):
    # Flow orchestration fake; real PackageInstaller protocol is tested separately.
    result=adb.op('install-multiple',*(['-r'] if replace else []),str(adb.folder/'base.apk'),str(adb.folder/'split-001.apk'))
    if result!='Success':raise InstallError('operation-uncertain')

class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':self.tmp.name});self.env.start();self.addCleanup(self.env.stop)
        self.stopped=threading.Event();self.records=[]
    def execute(self,adb,approve=True,delete=None,backup_fn=lambda *_:True,verify=lambda _:None):
        return install_connected(adb,'101',self.folder,self.stopped,lambda *a:approve,
            lambda *a:delete,lambda _:None,backup_fn=backup_fn,verify_bundle=verify,lock=no_lock,
            record=lambda **x:self.records.append(x),inspect_fn=lambda *_:dict(known_bundle=True),
            transfer_fn=lambda *_:None,install_fn=legacy_install)
    def writes(self,adb):return [x for x in adb.calls if x[0] in ('uninstall','install-multiple')]
    def test_update_success_preserves_existing_app_no_delete_prompt(self):
        a=Adb(self.folder)
        self.assertEqual(self.execute(a),'installed');self.assertEqual(a.installs,1)
        self.assertNotIn(('uninstall',PACKAGE),a.calls);self.assertIn('-r',self.writes(a)[0])
    def test_absent_package_is_installed_once_no_remove(self):
        a=Adb(self.folder,exists=False)
        self.assertEqual(self.execute(a),'installed');self.assertEqual(a.installs,1)
        self.assertNotIn('-r',self.writes(a)[0]);self.assertNotIn(('uninstall',PACKAGE),a.calls)
    def test_first_confirmation_no_means_no_write(self):
        a=Adb(self.folder)
        with self.assertRaisesRegex(InstallError,'declined'):self.execute(a,approve=False)
        self.assertEqual(self.writes(a),[])
    def test_signature_mismatch_requires_exact_typed_cloud_id(self):
        for response in (None,False,True,'','202',' 101 '):
            a=Adb(self.folder,failure=InstallError('adb-failed','INSTALL_FAILED_UPDATE_INCOMPATIBLE'))
            with self.subTest(response=response),self.assertRaisesRegex(InstallError,'declined'):self.execute(a,delete=response)
            self.assertEqual(a.installs,1);self.assertNotIn(('uninstall',PACKAGE),a.calls)
    def test_approved_replacement_backs_up_before_single_delete_and_single_reinstall(self):
        a=Adb(self.folder,failure=InstallError('adb-failed','INSTALL_FAILED_UPDATE_INCOMPATIBLE'))
        def checked(*_):
            self.assertNotIn(('uninstall',PACKAGE),a.calls);return True
        self.assertEqual(self.execute(a,delete='101',backup_fn=checked),'installed-after-replacement')
        self.assertEqual(a.calls.count(('uninstall',PACKAGE)),1);self.assertEqual(a.installs,2)
        self.assertIn(dict(status='delete-started',stage='delete',apk_backup=True,account_data_backed_up=False),self.records)
    def test_failed_backup_never_deletes(self):
        a=Adb(self.folder,failure=InstallError('adb-failed','INSTALL_FAILED_UPDATE_INCOMPATIBLE'))
        with self.assertRaisesRegex(InstallError,'backup-failed'):self.execute(a,delete='101',backup_fn=lambda *_:False)
        self.assertNotIn(('uninstall',PACKAGE),a.calls)
    def test_unknown_first_install_never_deletes_or_retries(self):
        for error in (InstallError('operation-uncertain'),InstallError('adb-failed'),InstallError('adb-failed','INSTALL_FAILED_NO_MATCHING_ABIS')):
            a=Adb(self.folder,failure=error)
            with self.assertRaises(InstallError):self.execute(a,delete='101')
            self.assertEqual(a.installs,1);self.assertNotIn(('uninstall',PACKAGE),a.calls)
    def test_wrong_platform_never_installs(self):
        for sdk,abi in (('33','arm64-v8a'),('35','x86_64'),('35','armeabi-v7a,arm64-v8a')):
            a=Adb(self.folder,sdk=sdk,abi=abi)
            with self.subTest(sdk=sdk,abi=abi),self.assertRaises(InstallError):self.execute(a)
            self.assertEqual(self.writes(a),[])
    def test_identity_change_after_confirmation_stops_before_write(self):
        a=Adb(self.folder)
        def change(_):a.identity='99999999-1234-1234-1234-123456789abc'
        with self.assertRaisesRegex(InstallError,'identity-changed'):self.execute(a,verify=change)
        # A second guard after bundle verification is mandatory.
        self.assertEqual(self.writes(a),[])
    def test_cancel_during_confirmation_does_not_install(self):
        a=Adb(self.folder)
        def stop(_):self.stopped.set()
        with self.assertRaisesRegex(InstallError,'cancelled'):self.execute(a,verify=stop)
        self.assertEqual(self.writes(a),[])

class UncertainReplacement(unittest.TestCase):
    setUp=Flow.setUp
    execute=Flow.execute
    writes=Flow.writes
    def test_uncertain_new_install_after_delete_is_not_retried_or_restored(self):
        class Broken(Adb):
            def op(self,*args,timeout=30):
                if args[0]=='install-multiple' and self.installs==1:
                    self.calls.append(args);self.installs+=1;raise InstallError('operation-uncertain')
                return super().op(*args,timeout=timeout)
        a=Broken(self.folder,failure=InstallError('adb-failed','INSTALL_FAILED_UPDATE_INCOMPATIBLE'))
        with self.assertRaisesRegex(InstallError,'operation-uncertain'):self.execute(a,delete='101')
        self.assertEqual(a.installs,2);self.assertEqual(a.calls.count(('uninstall',PACKAGE)),1)
        self.assertEqual(self.records[-1]['status'],'installing-after-delete')
    def test_identity_change_during_backup_never_deletes(self):
        a=Adb(self.folder,failure=InstallError('adb-failed','INSTALL_FAILED_UPDATE_INCOMPATIBLE'))
        def backup_changes(*_):a.identity='99999999-1234-1234-1234-123456789abc';return True
        with self.assertRaisesRegex(InstallError,'identity-changed'):self.execute(a,delete='101',backup_fn=backup_changes)
        self.assertNotIn(('uninstall',PACKAGE),a.calls)
    def test_cancel_during_backup_never_deletes(self):
        a=Adb(self.folder,failure=InstallError('adb-failed','INSTALL_FAILED_UPDATE_INCOMPATIBLE'))
        def cancelled(*_):self.stopped.set();return True
        with self.assertRaisesRegex(InstallError,'cancelled'):self.execute(a,delete='101',backup_fn=cancelled)
        self.assertNotIn(('uninstall',PACKAGE),a.calls)

class CommandPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve(strict=True)
        self.exe=self.root/'adb.exe';self.exe.write_bytes(b'synthetic');self.serial='127.0.0.1:12345'
        self.adb=OwnedAdb(str(self.exe),self.serial,self.root)
    def test_wrong_device_shell_uninstall_scope_and_global_ops_blocked(self):
        for args in (['devices'],['kill-server'],['disconnect'],['-s','127.0.0.1:5563','uninstall',PACKAGE],
          ['-s',self.serial,'shell','su'],['-s',self.serial,'shell','pm','clear',PACKAGE],
          ['-s',self.serial,'uninstall','other.app'],['-s',self.serial,'shell','am','start','anything']):
            with self.subTest(args=args),self.assertRaises(InstallError):self.adb.validate(args)
    def test_install_requires_two_exact_staged_apks_no_downgrade_or_permissions_flags(self):
        valid=['-s',self.serial,'install-multiple','-r',str(self.root/'base.apk'),str(self.root/'split-001.apk')]
        # The legacy streaming install path is forbidden, including its valid-looking form.
        for args in (valid,valid+['-g'],valid+['-d'],valid[:-1],valid[:-1]+['/tmp/other.apk']):
            with self.assertRaises(InstallError):self.adb.validate(args)
    def test_shell_false_scoped_server_and_hidden_output(self):
        def fake(args,**kwargs):
            self.assertEqual(args,[str(self.exe),'-s',self.serial,'get-state']);self.assertFalse(kwargs['shell'])
            self.assertEqual(kwargs['env']['ADB_SERVER_SOCKET'],'tcp:localhost:5037')
            kwargs['stdout'].write(b'device');return type('R',(),{'returncode':0})()
        self.adb.runner=fake;self.assertEqual(self.adb.op('get-state'),'device')
    def test_timeout_is_uncertain_not_a_failure_to_retry(self):
        self.adb.runner=lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired('PRIVATE',30))
        with self.assertRaisesRegex(InstallError,'^operation-uncertain$'):self.adb.op('get-state')
    def test_error_does_not_export_raw_device_output(self):
        def fake(args,**kwargs):
            kwargs['stdout'].write(b'SECRET HOST PASSWORD Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: PRIVATE]')
            return type('R',(),{'returncode':1})()
        self.adb.runner=fake
        with self.assertRaises(InstallError) as ctx:self.adb.op('get-state')
        self.assertNotIn('SECRET',str(ctx.exception));self.assertEqual(ctx.exception.android_code,'INSTALL_FAILED_UPDATE_INCOMPATIBLE')
    def test_backup_paths_cannot_escape_package_or_destination(self):
        self.adb.backup_dir=self.root
        for remote,dest in (('/data/data/drug.vokrug/databases/a',self.root/'base.apk'),('/data/app/other.app-xx/base.apk',self.root/'base.apk'),('/data/app/drug.vokrug-xx/base.apk',self.root.parent/'base.apk')):
            with self.assertRaises(Exception):self.adb.validate(['-s',self.serial,'pull',remote,str(dest)])

if __name__=='__main__':unittest.main()
