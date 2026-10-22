"""File-first PackageInstaller flow. Known APKs only; commit once; no shell strings."""
import re
import uuid
from morelogin_install import InstallError,guard,HASHES,PACKAGE

def _unexpected(code):
    error=InstallError(code);error.reason='unexpected-output'
    error.operation={'session-create-failed':'install-create','session-write-failed':'install-write','operation-uncertain':'install-commit'}.get(code)
    return error

def verify_upload(adb,identity,stopped):
    for name,expected in HASHES.items():
        guard(adb,identity,stopped)
        remote=adb.upload_dir+'/'+name
        response=adb.op('shell','toybox','sha256sum',remote,timeout=60)
        if not re.fullmatch(re.escape(expected)+r'\s+\*?'+re.escape(remote),response):
            raise InstallError('transfer-hash-mismatch')

def transfer_apks(adb,directory,identity,stopped,progress,record):
    # Unique, fixed-owned directory, not a user's download/app-data folder.
    adb.upload_dir='/data/local/tmp/dvk-install-'+uuid.uuid4().hex
    guard(adb,identity,stopped)
    record(stage='prepare-upload')
    if adb.op('shell','mkdir',adb.upload_dir)!='':raise _unexpected('transfer-failed')
    for index,name in enumerate(HASHES,1):
        guard(adb,identity,stopped)
        size=(adb.folder/name).stat().st_size
        record(stage='transfer-apk',apk_index=index,apk_count=2,apk_size_bytes=size)
        progress('Передаю APK %d/2 (%.1f МБ). Лимит передачи файла — 10 минут. Приложение не удаляется.'%(index,size/1024**2))
        adb.op('push',str(adb.folder/name),adb.upload_dir+'/'+name,timeout=600)
        record(stage='verify-upload',apk_index=index)
        response=adb.op('shell','toybox','sha256sum',adb.upload_dir+'/'+name,timeout=60)
        if not re.fullmatch(re.escape(HASHES[name])+r'\s+\*?'+re.escape(adb.upload_dir+'/'+name),response):
            raise InstallError('transfer-hash-mismatch')
    guard(adb,identity,stopped)
    record(stage='transfer-complete',transferred_apks_verified=True)

def install_session(adb,replace,identity,stopped,progress,record):
    verify_upload(adb,identity,stopped)
    total=sum((adb.folder/name).stat().st_size for name in HASHES)
    record(stage='session-create',status='installing')
    progress('APK переданы и проверены. Создаю сессию установки Android.')
    response=adb.op('shell','pm','install-create','--pkg',PACKAGE,*(['-r'] if replace else []),'-S',str(total),timeout=60)
    match=re.fullmatch(r'Success: created install session \[([1-9][0-9]{0,9})\]',response)
    if not match:raise _unexpected('session-create-failed')
    session=match.group(1)
    if int(session)>2147483647:raise _unexpected('session-create-failed')
    adb.session_ids.add(session)
    commit_started=False;definite_failure=False
    try:
        for index,name in enumerate(HASHES,1):
            guard(adb,identity,stopped)
            # Recheck bytes before each session write; no unrelated paths permitted.
            verify_upload(adb,identity,stopped)
            record(stage='session-write',apk_index=index,session_created=True)
            progress('Android подготавливает APK %d/2. Передача по сети уже завершена.'%index)
            size=(adb.folder/name).stat().st_size
            response=adb.op('shell','pm','install-write','-S',str(size),session,name,adb.upload_dir+'/'+name,timeout=180)
            if not re.fullmatch(r'Success: streamed '+str(size)+r' bytes',response):
                raise _unexpected('session-write-failed')
        guard(adb,identity,stopped)
        record(stage='session-commit',commit_started=True)
        progress('Android устанавливает проверенный комплект. Подтверждение — до 3 минут; автоповтора нет.')
        commit_started=True
        try:response=adb.op('shell','pm','install-commit',session,timeout=180)
        except InstallError as error:
            definite_failure=error.reason=='android-failure'
            raise
        if response!='Success':raise _unexpected('operation-uncertain')
        record(stage='session-committed',commit_confirmed=True)
    finally:
        # Never abandon an uncertain commit or touch another application's session.
        if not commit_started or definite_failure:
            try:
                # Do not erase the useful failing-operation report during cleanup.
                audit=adb.audit;adb.audit=lambda **kw:None
                try:adb.op('shell','pm','install-abandon',session,timeout=30)
                finally:adb.audit=audit
            except Exception:pass

def cleanup_upload(adb,record):
    if not getattr(adb,'upload_dir',None):return
    try:
        audit=adb.audit;adb.audit=lambda **kw:None
        try:
            adb.op('shell','rm',adb.upload_dir+'/base.apk',adb.upload_dir+'/split-001.apk')
            adb.op('shell','rmdir',adb.upload_dir)
        finally:adb.audit=audit
        record(temporary_apks_removed=True)
    except Exception:
        record(temporary_apks_removed=False)
