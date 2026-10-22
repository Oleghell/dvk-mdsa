"""Explicit single-phone split APK installer. No root, shell strings, auto-delete or sends."""
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from morelogin_common import CloudError, phone_id, fingerprint, root_directory, phone_directory, atomic_json
from morelogin_client import Client, plan, DirectPlan
from assistant_lock import operation_lock
from apk_export import parse_apk_paths, validate_apk
from test_device import PACKAGE, HASHES, bundle_token

ANDROID_CODES = {'INSTALL_FAILED_UPDATE_INCOMPATIBLE','INSTALL_FAILED_VERSION_DOWNGRADE',
 'INSTALL_FAILED_NO_MATCHING_ABIS','INSTALL_FAILED_INSUFFICIENT_STORAGE','INSTALL_FAILED_INVALID_APK',
 'INSTALL_FAILED_MISSING_SPLIT','INSTALL_FAILED_USER_RESTRICTED','INSTALL_FAILED_TEST_ONLY',
 'INSTALL_PARSE_FAILED_NO_CERTIFICATES','INSTALL_FAILED_INTERNAL_ERROR','DELETE_FAILED_INTERNAL_ERROR',
 'DELETE_FAILED_DEVICE_POLICY_MANAGER','DELETE_FAILED_USER_RESTRICTED'}
CODES={'configuration','bundle-required','cancelled','device-busy','device-not-ready','wrong-abi',
 'wrong-android','identity-changed','adb-failed','operation-uncertain','backup-failed','declined','install-failed',
 'delete-failed','not-installed','installed','installed-after-replacement',
 'known-bundle','different-bundle','app-absent','check-failed','installed-unverified',
 'transfer-failed','transfer-timeout','transfer-hash-mismatch','session-create-failed','session-write-failed'}
BOOT=re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
class InstallError(RuntimeError):
    def __init__(self,code,android_code=None):
        self.code=code if code in CODES else 'adb-failed'
        self.android_code=android_code if android_code in ANDROID_CODES else None
        self.reason=None;self.operation=None;self.elapsed_seconds=None
        super().__init__(self.code)

class OwnedAdb:
    def __init__(self,executable,serial,folder,*,runner=subprocess.run,read_only=False):
        path=Path(executable)
        if not path.is_absolute() or not path.is_file() or path.name.lower() not in ('adb','adb.exe','adb_server.exe'):
            raise InstallError('configuration')
        if not re.fullmatch(r'127\.0\.0\.1:[0-9]{1,5}',serial) or not 1024<=int(serial.split(':')[1])<=65535:
            raise InstallError('configuration')
        self.executable=str(path);self.serial=serial;self.folder=Path(folder).resolve(strict=True)
        self.runner=runner;self.backup_dir=None;self.read_only=read_only
        self.upload_dir=None;self.session_ids=set();self.committed_sessions=set();self.audit=lambda **kw:None
    def validate(self,args):
        if args in (['connect',self.serial],['disconnect',self.serial]):return
        if args[:2]!=['-s',self.serial]:raise InstallError('configuration')
        op=args[2:]
        read=[['get-state'],['shell','cat','/proc/sys/kernel/random/boot_id'],
          ['shell','getprop','sys.boot_completed'],['shell','getprop','ro.product.cpu.abilist'],
          ['shell','getprop','ro.build.version.sdk'],['shell','pm','list','packages',PACKAGE],
          ['shell','pm','path',PACKAGE]]
        if op in read:return
        if not self.read_only and op==['uninstall',PACKAGE]:return
        if not self.read_only and self.upload_dir is not None:
            remote=self.upload_dir
            if not re.fullmatch(r'/data/local/tmp/dvk-install-[0-9a-f]{32}',remote):raise InstallError('configuration')
            sizes={name:(self.folder/name).stat().st_size for name in HASHES}
            total=str(sum(sizes.values()))
            if op in (['shell','mkdir',remote],['shell','rmdir',remote],
                      ['shell','rm',remote+'/base.apk',remote+'/split-001.apk']):return
            for name in HASHES:
                if op in (['push',str(self.folder/name),remote+'/'+name],
                          ['shell','toybox','sha256sum',remote+'/'+name]):return
            if op in (['shell','pm','install-create','--pkg',PACKAGE,'-S',total],
                      ['shell','pm','install-create','--pkg',PACKAGE,'-r','-S',total]):return
            for session in self.session_ids:
                if op==['shell','pm','install-abandon',session]:return
                if session not in self.committed_sessions:
                    if op==['shell','pm','install-commit',session]:return
                    for name,size in sizes.items():
                        if op==['shell','pm','install-write','-S',str(size),session,name,remote+'/'+name]:return
        if len(op)==3 and op[0]=='pull' and self.backup_dir is not None:
            remote=op[1];base=remote.rsplit('/',1)[0]+'/base.apk'
            parse_apk_paths('package:'+remote+ ('\npackage:'+base if not remote.endswith('/base.apk') else ''))
            dest=Path(op[2])
            if dest.parent==self.backup_dir and re.fullmatch(r'(base|split-[0-9]{3})\.apk',dest.name) and not dest.exists():return
        raise InstallError('configuration')
    def run(self,args,timeout=30):
        self.validate(args)
        op=args[2:] if args[:2]==['-s',self.serial] else args
        operation=(op[2] if op[:2]==['shell','pm'] else
                   ('sha256sum' if op[:3]==['shell','toybox','sha256sum'] else op[0]))
        if op[:3]==['shell','pm','install-commit']:
            # Reserve before executing. Unknown commit is never submitted twice.
            self.committed_sessions.add(op[3])
        self.audit(adb_operation=operation,operation_status='started',timeout_seconds=timeout)
        env=os.environ.copy()
        for key in ('ADB_SERVER_SOCKET','ANDROID_ADB_SERVER_PORT','ANDROID_SERIAL'):env.pop(key,None)
        env['ADB_SERVER_SOCKET']='tcp:localhost:5037'
        started=time.monotonic()
        try:
            with tempfile.TemporaryFile() as out:
                result=self.runner([self.executable,*args],shell=False,stdin=subprocess.DEVNULL,
                    stdout=out,stderr=subprocess.STDOUT,timeout=timeout,env=env,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                out.seek(0);value=out.read(65537)
            if len(value)>65536:
                error=InstallError('operation-uncertain');error.reason='output-limit';raise error
            text=value.decode('utf-8',errors='replace').strip()
            match=re.search(r'Failure \[([A-Z_]+)',text)
            if result.returncode or match:
                error=InstallError('adb-failed',match.group(1) if match else None)
                error.reason='android-failure' if match else 'nonzero-exit';raise error
            self.audit(adb_operation=operation,operation_status='completed',elapsed_seconds=round(time.monotonic()-started,1))
            return text
        except subprocess.TimeoutExpired:
            error=InstallError('transfer-timeout' if operation=='push' else 'operation-uncertain')
            error.reason='timeout';error.operation=operation;error.elapsed_seconds=round(time.monotonic()-started,1)
            self.audit(adb_operation=operation,operation_status='failed',reason=error.reason,elapsed_seconds=error.elapsed_seconds)
            raise error from None
        except OSError:
            error=InstallError('adb-failed');error.reason='process-start-failed'
            error.operation=operation;error.elapsed_seconds=round(time.monotonic()-started,1)
            self.audit(adb_operation=operation,operation_status='failed',reason=error.reason,elapsed_seconds=error.elapsed_seconds)
            raise error from None
        except InstallError as error:
            error.operation=operation;error.elapsed_seconds=round(time.monotonic()-started,1)
            self.audit(adb_operation=operation,operation_status='failed',reason=error.reason,elapsed_seconds=error.elapsed_seconds)
            raise
    def op(self,*args,timeout=30):return self.run(['-s',self.serial,*args],timeout)

def boot(adb):
    value=adb.op('shell','cat','/proc/sys/kernel/random/boot_id')
    if not BOOT.fullmatch(value):raise InstallError('identity-changed')
    return value

def guard(adb,identity,stopped):
    if stopped.is_set():raise InstallError('cancelled')
    if boot(adb)!=identity:raise InstallError('identity-changed')
    if adb.op('shell','getprop','sys.boot_completed')!='1':raise InstallError('device-not-ready')

def present(adb):
    value=adb.op('shell','pm','list','packages',PACKAGE)
    if value=='package:'+PACKAGE:return True
    if value=='':return False
    raise InstallError('device-not-ready')

def backup(adb,directory,identity,stopped):
    """APK binaries only, never /data/data or account/session files."""
    paths=parse_apk_paths(adb.op('shell','pm','path',PACKAGE))
    if shutil.disk_usage(directory).free<4*1024**3:raise InstallError('backup-failed')
    folder=directory/'apk-backups'/uuid.uuid4().hex
    folder.mkdir(parents=True,mode=0o700);adb.backup_dir=folder
    files=[];total=0
    try:
        for index,remote in enumerate(paths):
            guard(adb,identity,stopped)
            name='base.apk' if remote.endswith('/base.apk') else 'split-%03d.apk'%index
            dest=folder/name
            adb.op('pull',remote,str(dest),timeout=240)
            item=validate_apk(dest)
            with zipfile.ZipFile(dest) as archive:
                if archive.testzip() is not None:raise InstallError('backup-failed')
            total+=item['size_bytes']
            if total>2*1024**3:raise InstallError('backup-failed')
            files.append(dict(file=name,**item))
        guard(adb,identity,stopped)
        atomic_json(folder/'APK_BACKUP.json',dict(account_data_backed_up=False,files=files))
        return True
    except InstallError:raise
    except Exception:raise InstallError('backup-failed') from None
    finally:adb.backup_dir=None

def verify_installed(adb,directory,identity,stopped,progress=lambda _:None):
    """Read APK binaries only; never attach Gadget, launch app or read account data."""
    guard(adb,identity,stopped)
    if not present(adb):return dict(result='app-absent',files=[],known_bundle=False)
    if shutil.disk_usage(directory).free<2*1024**3:raise InstallError('check-failed')
    paths=parse_apk_paths(adb.op('shell','pm','path',PACKAGE))
    files=[];total=0
    with tempfile.TemporaryDirectory(prefix='.gadget-check-',dir=directory) as local:
        adb.backup_dir=Path(local).resolve(strict=True)
        try:
            for index,remote in enumerate(paths):
                guard(adb,identity,stopped)
                progress('Проверяю установленный APK %d из %d. Данные аккаунта не читаются.'%(index+1,len(paths)))
                name='base.apk' if remote.endswith('/base.apk') else 'split-%03d.apk'%index
                dest=adb.backup_dir/name
                adb.op('pull',remote,str(dest),timeout=240)
                item=validate_apk(dest);total+=item['size_bytes']
                if total>2*1024**3:raise InstallError('check-failed')
                files.append(dict(file=name,**item))
            guard(adb,identity,stopped)
            if parse_apk_paths(adb.op('shell','pm','path',PACKAGE))!=paths:
                raise InstallError('identity-changed')
        finally:adb.backup_dir=None
    same=(len(files)==len(HASHES) and sorted(x['sha256'] for x in files)==sorted(HASHES.values()))
    return dict(result='known-bundle' if same else 'different-bundle',files=files,known_bundle=same)


def install_connected(adb,cloud_id,directory,stopped,confirm_install,confirm_delete,progress,
                      *,backup_fn=backup,verify_bundle=bundle_token,lock=operation_lock,record=lambda **kw:None,inspect_fn=verify_installed,transfer_fn=None,install_fn=None):
    from morelogin_package_session import transfer_apks, install_session, cleanup_upload, verify_upload
    transfer_fn=transfer_fn or transfer_apks;install_fn=install_fn or install_session
    cloud_id=phone_id(cloud_id)
    if adb.op('get-state')!='device':raise InstallError('device-not-ready')
    identity=boot(adb)
    with lock(root_directory()/'locks'/('boot-'+identity+'.lock')):
        guard(adb,identity,stopped)
        sdk=adb.op('shell','getprop','ro.build.version.sdk')
        abi=adb.op('shell','getprop','ro.product.cpu.abilist').split(',')
        if sdk not in ('34','35'):raise InstallError('wrong-android')
        if not abi or abi[0]!='arm64-v8a':raise InstallError('wrong-abi')
        exists=present(adb)
        if not confirm_install(cloud_id,sdk,exists):raise InstallError('declined')
        guard(adb,identity,stopped);verify_bundle(adb.folder);guard(adb,identity,stopped)
        record(status='preparing',stage='transfer',package_existed=exists,install_method='verified-files-package-session')
        transfer_fn(adb,directory,identity,stopped,progress,record)
        guard(adb,identity,stopped)
        try:
            install_fn(adb,exists,identity,stopped,progress,record)
        except InstallError as error:
            if error.android_code!='INSTALL_FAILED_UPDATE_INCOMPATIBLE' or not exists:raise
            record(status='replacement-required',stage='signature',android_code=error.android_code)
            # Typed exact ID is required, not a truthy checkbox or a generic Yes.
            if confirm_delete(cloud_id)!=cloud_id:raise InstallError('declined')
            guard(adb,identity,stopped)
            if not present(adb):raise InstallError('identity-changed')
            progress('Сохраняю исходные APK. Данные аккаунта в копию НЕ входят.')
            record(status='backing-up-apks',stage='backup')
            if backup_fn(adb,directory,identity,stopped) is not True:raise InstallError('backup-failed')
            verify_bundle(adb.folder);guard(adb,identity,stopped)
            # Recheck files already on the phone BEFORE any approved removal.
            if getattr(adb,'upload_dir',None):verify_upload(adb,identity,stopped)
            guard(adb,identity,stopped)
            # Durable marker survives a crash. Never auto-resume a destructive action.
            record(status='delete-started',stage='delete',apk_backup=True,account_data_backed_up=False)
            value=adb.op('uninstall',PACKAGE,timeout=120)
            if value!='Success':raise InstallError('operation-uncertain')
            guard(adb,identity,stopped)
            if present(adb):raise InstallError('delete-failed')
            verify_bundle(adb.folder);guard(adb,identity,stopped)
            record(status='installing-after-delete',stage='install',apk_backup=True)
            install_fn(adb,False,identity,stopped,progress,record)
            result='installed-after-replacement'
        else:result='installed'
        guard(adb,identity,stopped)
        if not present(adb):raise InstallError('not-installed')
        record(stage='verify-installed')
        progress('Android сообщил об установке. Сравниваю установленные APK с комплектом Gadget.')
        check=inspect_fn(adb,directory,identity,stopped,progress)
        record(installed_apks=check)
        if not check['known_bundle']:raise InstallError('installed-unverified')
        # Byte identity is NOT a claim that Gadget runs on Android 15A.
        record(status=result,stage='done',known_bundle=True,code=None,android_code=None,reason=None,failed_operation=None,failed_elapsed_seconds=None)
        cleanup_upload(adb,record)
        return result

@contextmanager
def connected_phone(cloud_id,adb_path,folder,stopped,record,*,read_only=False):
    """Use the existing pinned per-phone transport; never enumerate other devices."""
    with ExitStack() as stack:
        record(stage='api')
        from morelogin_credentials import load
        app_id,key=load();entry=Client(app_id,key).query([cloud_id])[cloud_id]
        selected=plan(entry,cloud_id)
        if isinstance(selected,DirectPlan):
            from morelogin_direct import connection
            serial=stack.enter_context(connection(selected,adb_path,stopped.is_set))
        else:
            value=json.loads((root_directory()/'phones.json').read_text(encoding='utf-8'))
            pin=fingerprint(value.get('pins',{}).get(cloud_id))
            from morelogin_ssh import tunnel
            serial=stack.enter_context(tunnel(selected,pin,stopped.is_set))
        adb=OwnedAdb(adb_path,serial,folder,read_only=read_only)
        adb.audit=record
        connected=False
        try:
            record(stage='adb');adb.run(['connect',serial]);connected=True
            yield adb
        finally:
            if connected:
                adb.audit=lambda **kw:None
                try:adb.run(['disconnect',serial])
                except Exception:pass

def _report(cloud_id,name):
    directory=phone_directory(cloud_id);directory.mkdir(parents=True,exist_ok=True)
    report=dict(cloud_phone_id=cloud_id,status='checking',stage='bundle',account_data_backed_up=False,
                live_gadget_verified=False)
    def record(**values):
        report.update(values);atomic_json(directory/name,report)
    return directory,record

def _failure(error,record):
    code=error.code if isinstance(error,(InstallError,CloudError)) else 'configuration'
    record(status='stopped',code=code,android_code=getattr(error,'android_code',None),
        reason=getattr(error,'reason',None),failed_operation=getattr(error,'operation',None),
        failed_elapsed_seconds=getattr(error,'elapsed_seconds',None))
    if isinstance(error,(InstallError,CloudError)):raise error
    raise InstallError('configuration') from None

def run(cloud_id,adb_path,folder,stopped,confirm_install,confirm_delete,progress):
    """Explicit install only. All reports contain fixed fields, never raw ADB output."""
    cloud_id=phone_id(cloud_id);directory,record=_report(cloud_id,'last-install.json')
    try:
        with ExitStack() as stack:
            try:stack.enter_context(operation_lock(directory/'cloud-run.lock'))
            except Exception:raise InstallError('device-busy') from None
            staged=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='.install-',dir=directory)))
            for name in HASHES:
                source=Path(folder)/name
                if not source.is_file() or source.stat().st_size>1024**3:raise InstallError('bundle-required')
                shutil.copyfile(source,staged/name)
            try:bundle_token(staged)
            except Exception:raise InstallError('bundle-required') from None
            if stopped.is_set():raise InstallError('cancelled')
            with connected_phone(cloud_id,adb_path,staged,stopped,record) as adb:
                return install_connected(adb,cloud_id,directory,stopped,confirm_install,confirm_delete,progress,record=record)
    except Exception as error:_failure(error,record)

def check_installed(cloud_id,adb_path,stopped,progress):
    """No bundle needed locally, no installation, deletion, app launch or messages."""
    cloud_id=phone_id(cloud_id);directory,record=_report(cloud_id,'last-gadget-check.json')
    try:
        with operation_lock(directory/'cloud-run.lock'):
            if stopped.is_set():raise InstallError('cancelled')
            with tempfile.TemporaryDirectory(prefix='.inspect-',dir=directory) as temporary:
                with connected_phone(cloud_id,adb_path,temporary,stopped,record,read_only=True) as adb:
                    if adb.op('get-state')!='device':raise InstallError('device-not-ready')
                    identity=boot(adb)
                    with operation_lock(root_directory()/'locks'/('boot-'+identity+'.lock')):
                        record(stage='read-installed-apks')
                        result=verify_installed(adb,directory,identity,stopped,progress)
                        record(status=result['result'],stage='done',installed_apks=result)
                        return result['result']
    except Exception as error:_failure(error,record)
