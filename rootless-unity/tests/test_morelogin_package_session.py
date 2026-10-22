"""Real command policy + synthetic Android. No live phone, credentials or network."""
import hashlib,os,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import morelogin_install as install
import morelogin_package_session as session
from test_morelogin_install import BOOT,no_lock

class FileSession(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':str(self.root)});self.env.start();self.addCleanup(self.env.stop)
        self.data={'base.apk':b'known-base','split-001.apk':b'known-split'}
        hashes={name:hashlib.sha256(data).hexdigest() for name,data in self.data.items()}
        for module in (install,session):
            p=patch.object(module,'HASHES',hashes);p.start();self.addCleanup(p.stop)
        for name,data in self.data.items():(self.root/name).write_bytes(data)
        self.exe=self.root/'adb.exe';self.exe.write_bytes(b'synthetic')
        self.calls=[];self.remote={};self.installed=True;self.counter=100;self.commits=0;self.fail_first=False
        self.fail_operation=None;self.corrupt=False;self.confirm=None;self.backup_ok=True;self.mutated_boot=False
        self.stopped=threading.Event();self.records=[]
        self.adb=install.OwnedAdb(str(self.exe),'127.0.0.1:12345',self.root,runner=self.runner)
        self.adb.audit=lambda **x:self.records.append(x)
    def runner(self,args,**kw):
        op=args[3:];self.calls.append(op);value='';code=0
        kind=op[2] if op[:2]==['shell','pm'] else op[0]
        if self.fail_operation==kind:raise subprocess.TimeoutExpired('PRIVATE',kw['timeout'])
        if op==['get-state']:value='device'
        elif op==['shell','cat','/proc/sys/kernel/random/boot_id']:value=BOOT if not self.mutated_boot else '99999999-1234-1234-1234-123456789abc'
        elif op==['shell','getprop','sys.boot_completed']:value='1'
        elif op==['shell','getprop','ro.product.cpu.abilist']:value='arm64-v8a'
        elif op==['shell','getprop','ro.build.version.sdk']:value='35'
        elif op==['shell','pm','list','packages',install.PACKAGE]:value='package:'+install.PACKAGE if self.installed else ''
        elif op[:2]==['shell','mkdir']:pass
        elif op[0]=='push':self.remote[op[2]]=Path(op[1]).read_bytes();value='1 file pushed'
        elif op[:3]==['shell','toybox','sha256sum']:
            h=hashlib.sha256(self.remote[op[3]]).hexdigest() if not self.corrupt else '0'*64
            value=h+'  '+op[3]
        elif op[:3]==['shell','pm','install-create']:
            self.counter+=1;value='Success: created install session [%d]'%self.counter
        elif op[:3]==['shell','pm','install-write']:
            self.assertEqual(len(self.remote[op[-1]]),int(op[4]));value='Success: streamed '+op[4]+' bytes'
        elif op[:3]==['shell','pm','install-commit']:
            self.commits+=1
            if self.fail_first and self.commits==1:
                value='Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: PRIVATE]';code=1
            else:self.installed=True;value='Success'
        elif op[:3]==['shell','pm','install-abandon']:value='Success'
        elif op==['uninstall',install.PACKAGE]:self.installed=False;value='Success'
        elif op[:2]==['shell','rm']:
            for name in op[2:]:self.remote.pop(name,None)
        elif op[:2]==['shell','rmdir']:pass
        else:raise AssertionError(op)
        kw['stdout'].write(value.encode());return SimpleNamespace(returncode=code)
    def execute(self,approve=True,delete=None):
        return install.install_connected(self.adb,'101',self.root,self.stopped,lambda *_:approve,
            lambda *_:delete,lambda _:None,verify_bundle=lambda _:None,lock=no_lock,
            backup_fn=lambda *_:self.backup_ok,inspect_fn=lambda *_:dict(known_bundle=True),record=lambda **x:self.records.append(x))
    def commands(self,name):return [x for x in self.calls if x[:3]==['shell','pm',name]]
    def test_success_uses_file_first_verified_session_not_streaming(self):
        self.assertEqual(self.execute(),'installed')
        self.assertEqual(sum(x[0]=='push' for x in self.calls),2);self.assertEqual(len(self.commands('install-write')),2)
        self.assertEqual(self.commits,1);self.assertEqual(self.remote,{})
        self.assertFalse(any(x[0]=='install-multiple' for x in self.calls))
        create=self.commands('install-create')[0]
        self.assertIn('--pkg',create);self.assertIn(install.PACKAGE,create);self.assertIn('-r',create)
        first_create=self.calls.index(create);last_push=max(i for i,x in enumerate(self.calls) if x[0]=='push')
        self.assertLess(last_push,first_create)
    def test_no_approval_means_no_upload_session_or_delete(self):
        with self.assertRaisesRegex(install.InstallError,'declined'):self.execute(approve=False)
        self.assertFalse(any(x[0] in ('push','uninstall') for x in self.calls));self.assertEqual(self.counter,100)
    def test_hash_mismatch_never_creates_session_or_removes_app(self):
        self.corrupt=True
        with self.assertRaisesRegex(install.InstallError,'transfer-hash-mismatch'):self.execute()
        self.assertEqual(self.counter,100);self.assertEqual(self.commits,0);self.assertTrue(self.installed)
    def test_transfer_timeout_has_precise_reason_no_install(self):
        self.fail_operation='push'
        with self.assertRaises(install.InstallError) as ctx:self.execute()
        self.assertEqual(ctx.exception.code,'transfer-timeout');self.assertEqual(ctx.exception.reason,'timeout')
        self.assertEqual(ctx.exception.operation,'push');self.assertEqual(self.counter,100);self.assertTrue(self.installed)
    def test_commit_timeout_not_retried_abandoned_or_deleted(self):
        self.fail_operation='install-commit'
        with self.assertRaisesRegex(install.InstallError,'operation-uncertain'):self.execute()
        self.assertEqual(len(self.commands('install-commit')),1)
        self.assertEqual(self.commands('install-abandon'),[]);self.assertNotIn(['uninstall',install.PACKAGE],self.calls)
    def test_write_timeout_abandons_only_own_session_no_commit(self):
        self.fail_operation='install-write'
        with self.assertRaisesRegex(install.InstallError,'operation-uncertain'):self.execute()
        self.assertEqual(self.commits,0);self.assertEqual(self.commands('install-abandon'),[['shell','pm','install-abandon','101']])
    def test_signature_mismatch_cannot_delete_without_typed_id(self):
        self.fail_first=True
        with self.assertRaisesRegex(install.InstallError,'declined'):self.execute()
        self.assertEqual(self.commits,1);self.assertNotIn(['uninstall',install.PACKAGE],self.calls)
    def test_signature_replacement_reuses_verified_upload_and_commits_once_per_attempt(self):
        self.fail_first=True
        self.assertEqual(self.execute(delete='101'),'installed-after-replacement')
        self.assertEqual(self.commits,2);self.assertEqual(sum(x[0]=='push' for x in self.calls),2)
        self.assertEqual(self.calls.count(['uninstall',install.PACKAGE]),1)
        self.assertNotIn('-r',self.commands('install-create')[1])
    def test_backup_failure_never_uninstalls(self):
        self.fail_first=True;self.backup_ok=False
        with self.assertRaisesRegex(install.InstallError,'backup-failed'):self.execute(delete='101')
        self.assertNotIn(['uninstall',install.PACKAGE],self.calls);self.assertEqual(self.commits,1)
    def test_remote_tampering_during_backup_detected_before_delete(self):
        self.fail_first=True
        def backup(*_):self.corrupt=True;return True
        with self.assertRaisesRegex(install.InstallError,'transfer-hash-mismatch'):
            install.install_connected(self.adb,'101',self.root,self.stopped,lambda *_:True,lambda *_:'101',lambda _:None,
                verify_bundle=lambda _:None,backup_fn=backup,lock=no_lock,inspect_fn=lambda *_:dict(known_bundle=True))
        self.assertNotIn(['uninstall',install.PACKAGE],self.calls)
    def test_session_mutations_denied_on_read_only_connection(self):
        self.adb.read_only=True;self.adb.upload_dir='/data/local/tmp/dvk-install-'+'a'*32
        for op in (['shell','mkdir',self.adb.upload_dir],['push',str(self.root/'base.apk'),self.adb.upload_dir+'/base.apk']):
            with self.assertRaises(install.InstallError):self.adb.op(*op)
    def test_only_owned_uuid_paths_and_session_ids_allowed(self):
        self.adb.upload_dir='/data/local/tmp/dvk-install-'+'a'*32
        for op in (['shell','rm','-rf','/data/local/tmp'],['shell','pm','install-commit','999'],
                   ['shell','pm','install-write','-S','1','999','base.apk','/sdcard/a.apk'],
                   ['push',str(self.root/'base.apk'),'/data/local/tmp/other.apk'],
                   ['shell','pm','install-create','--pkg','other.app','-S','21']):
            with self.subTest(op=op),self.assertRaises(install.InstallError):self.adb.op(*op)
    def test_same_commit_cannot_be_submitted_twice(self):
        self.execute();sid=self.commands('install-commit')[0][3]
        with self.assertRaises(install.InstallError):self.adb.op('shell','pm','install-commit',sid)
        self.assertEqual(self.commits,1)
    def test_failure_report_has_fixed_operation_reason_not_stdout(self):
        self.fail_first=True
        with self.assertRaises(install.InstallError):self.execute()
        failed=[x for x in self.records if x.get('operation_status')=='failed']
        self.assertEqual(failed[0]['adb_operation'],'install-commit');self.assertEqual(failed[0]['reason'],'android-failure')
        self.assertNotIn('PRIVATE',str(self.records))
    def test_create_timeout_never_writes_or_commits_unknown_session(self):
        self.fail_operation='install-create'
        with self.assertRaisesRegex(install.InstallError,'operation-uncertain'):self.execute()
        self.assertEqual(self.commands('install-write'),[]);self.assertEqual(self.commands('install-commit'),[])
        self.assertEqual(self.commands('install-abandon'),[])

if __name__=='__main__':unittest.main()
