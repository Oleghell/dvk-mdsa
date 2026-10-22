"""No real accounts/devices/network: byte identity and transport error regression."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib,io,os,subprocess,sys,tempfile,threading,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import morelogin_install as install
import morelogin_ssh as ssh
from morelogin_common import CloudError
from test_morelogin_install import Adb,BOOT,no_lock,legacy_install

def apk_bytes(label):
    f=io.BytesIO()
    with zipfile.ZipFile(f,'w') as z:
        z.writestr('AndroidManifest.xml',b'synthetic-'+label)
        z.writestr('assets/synthetic',label)
    return f.getvalue()

class ReadingAdb(Adb):
    def __init__(self,folder,files,exists=True):
        super().__init__(folder,exists);self.files=files;self.backup_dir=None;self.paths_calls=0;self.change_paths=False
    def op(self,*args,timeout=30):
        if args==('shell','pm','path',install.PACKAGE):
            self.calls.append(args);self.paths_calls+=1
            package='drug.vokrug-other' if self.change_paths and self.paths_calls>1 else 'drug.vokrug-test'
            return '\n'.join('package:/data/app/'+package+'/'+x for x in self.files)
        if args[0]=='pull':
            self.calls.append(args);Path(args[2]).write_bytes(self.files[args[1].rsplit('/',1)[1]]);return '1 file pulled'
        return super().op(*args,timeout=timeout)

class InstalledCheck(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name).resolve()
        self.base=apk_bytes(b'base');self.split=apk_bytes(b'split');self.stopped=threading.Event()
        self.expected={'base.apk':hashlib.sha256(self.base).hexdigest(),'split-001.apk':hashlib.sha256(self.split).hexdigest()}
        self.patch=patch.object(install,'HASHES',self.expected);self.patch.start();self.addCleanup(self.patch.stop)
    def adb(self):return ReadingAdb(self.folder,{'base.apk':self.base,'split_config.arm64_v8a.apk':self.split})
    def check(self,a):return install.verify_installed(a,self.folder,BOOT,self.stopped)
    def test_exact_known_pair_confirmed_and_local_files_removed(self):
        a=self.adb();result=self.check(a)
        self.assertTrue(result['known_bundle']);self.assertEqual(result['result'],'known-bundle')
        self.assertEqual(len(result['files']),2);self.assertIsNone(a.backup_dir)
        self.assertEqual(list(self.folder.iterdir()),[])
        self.assertFalse(any(x[0] in ('install-multiple','uninstall') for x in a.calls))
        self.assertFalse(any(x[:2]==('shell','am') for x in a.calls))
    def test_changed_apk_not_claimed_as_known_gadget(self):
        a=self.adb();a.files['base.apk']=apk_bytes(b'other')
        self.assertEqual(self.check(a)['result'],'different-bundle')
    def test_extra_split_not_accepted_even_if_known_pair_present(self):
        a=self.adb();a.files['split_extra.apk']=self.split
        self.assertFalse(self.check(a)['known_bundle'])
    def test_missing_split_not_accepted(self):
        a=self.adb();del a.files['split_config.arm64_v8a.apk']
        self.assertFalse(self.check(a)['known_bundle'])
    def test_absent_package_no_pull(self):
        a=self.adb();a.exists=False
        self.assertEqual(self.check(a)['result'],'app-absent')
        self.assertFalse(any(x[0]=='pull' for x in a.calls))
    def test_path_change_not_accepted_and_temporary_files_removed(self):
        a=self.adb();a.change_paths=True
        with self.assertRaisesRegex(install.InstallError,'identity-changed'):self.check(a)
        self.assertEqual(list(self.folder.iterdir()),[]);self.assertIsNone(a.backup_dir)
    def test_cancel_never_pulls(self):
        a=self.adb();self.stopped.set()
        with self.assertRaisesRegex(install.InstallError,'cancelled'):self.check(a)
        self.assertFalse(any(x[0]=='pull' for x in a.calls))
    def test_insufficient_space_no_pull(self):
        with patch.object(install.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(install.InstallError,'check-failed'):self.check(self.adb())
    def test_pull_timeout_preserved_and_local_files_removed(self):
        a=self.adb();old=a.op
        def op(*args,**kwargs):
            if args[0]=='pull':raise install.InstallError('operation-uncertain')
            return old(*args,**kwargs)
        a.op=op
        with self.assertRaisesRegex(install.InstallError,'operation-uncertain'):self.check(a)
        self.assertEqual(list(self.folder.iterdir()),[]);self.assertIsNone(a.backup_dir)
    def test_install_success_requires_post_install_hash_confirmation(self):
        a=Adb(self.folder)
        with patch.dict(os.environ,{'LOCALAPPDATA':str(self.folder)}):
            with self.assertRaisesRegex(install.InstallError,'installed-unverified'):
                install.install_connected(a,'101',self.folder,self.stopped,lambda *_:True,lambda *_:None,lambda _:None,
                    verify_bundle=lambda _:None,lock=no_lock,transfer_fn=lambda *_:None,install_fn=legacy_install,inspect_fn=lambda *_:dict(known_bundle=False))
        self.assertEqual(a.installs,1);self.assertNotIn(('uninstall',install.PACKAGE),a.calls)
    def test_post_install_timeout_no_retry_or_false_success(self):
        a=Adb(self.folder);records=[]
        def inspect(*_):raise install.InstallError('operation-uncertain')
        with patch.dict(os.environ,{'LOCALAPPDATA':str(self.folder)}):
            with self.assertRaisesRegex(install.InstallError,'operation-uncertain'):
                install.install_connected(a,'101',self.folder,self.stopped,lambda *_:True,lambda *_:None,lambda _:None,
                    verify_bundle=lambda _:None,lock=no_lock,transfer_fn=lambda *_:None,install_fn=legacy_install,inspect_fn=inspect,record=lambda **x:records.append(x))
        self.assertEqual(a.installs,1);self.assertEqual(records[-1]['stage'],'verify-installed')
        self.assertNotIn(('uninstall',install.PACKAGE),a.calls)

class ErrorPreservation(unittest.TestCase):
    def context(self,fail_start=False,fail_close=False):
        class Resource:
            def close(self):
                if fail_close:raise RuntimeError('private cleanup error')
        class Transport(Resource):
            def __init__(self,_):pass
            def start_client(self,timeout):
                if fail_start:raise RuntimeError('private SSH banner')
        return ssh.handshake(SimpleNamespace(host='8.8.8.8',ssh_port=22),
            socket_factory=lambda *a,**k:Resource(),transport_factory=Transport)
    def test_install_timeout_not_relabelled_as_ssh(self):
        error=install.InstallError('operation-uncertain')
        with self.assertRaises(install.InstallError) as result:
            with self.context():raise error
        self.assertIs(result.exception,error)
    def test_signature_mismatch_reaches_installer_with_android_code(self):
        error=install.InstallError('adb-failed','INSTALL_FAILED_UPDATE_INCOMPATIBLE')
        with self.assertRaises(install.InstallError) as result:
            with self.context():raise error
        self.assertIs(result.exception,error);self.assertEqual(result.exception.android_code,error.android_code)
    def test_setup_failure_still_sanitized_as_ssh(self):
        with self.assertRaisesRegex(CloudError,'^ssh-unavailable$'):
            with self.context(fail_start=True):self.fail('Must not enter')
    def test_cleanup_failure_does_not_mask_operation_or_success(self):
        with self.context(fail_close=True):pass
        with self.assertRaisesRegex(install.InstallError,'^operation-uncertain$'):
            with self.context(fail_close=True):raise install.InstallError('operation-uncertain')
    def test_unexpected_caller_exception_not_claimed_as_ssh(self):
        with self.assertRaisesRegex(ValueError,'caller'):
            with self.context():raise ValueError('caller')

class ReadOnlyPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        exe=self.root/'adb.exe';exe.write_bytes(b'synthetic');self.serial='127.0.0.1:12345'
        self.adb=install.OwnedAdb(str(exe),self.serial,self.root,read_only=True)
    def test_read_only_wrapper_blocks_even_correct_scoped_mutations(self):
        for args in (['uninstall',install.PACKAGE],['install-multiple',str(self.root/'base.apk'),str(self.root/'split-001.apk')],
                     ['install-multiple','-r',str(self.root/'base.apk'),str(self.root/'split-001.apk')]):
            with self.assertRaises(install.InstallError):self.adb.validate(['-s',self.serial]+args)
    def test_android_failure_recognized_even_with_zero_exit_code(self):
        def fake(*a,**k):
            k['stdout'].write(b'Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: PRIVATE]');return SimpleNamespace(returncode=0)
        self.adb.runner=fake
        with self.assertRaises(install.InstallError) as result:self.adb.op('get-state')
        self.assertEqual(result.exception.android_code,'INSTALL_FAILED_UPDATE_INCOMPATIBLE')
        self.assertNotIn('PRIVATE',str(result.exception))

if __name__=='__main__':unittest.main()
