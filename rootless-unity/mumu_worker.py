"""One explicit MuMu endpoint per child process; no root/install/implicit fallback."""
from contextlib import ExitStack
from dataclasses import asdict,replace
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from mumu_common import MumuError, port, serial, root_directory, device_directory, atomic, VERSION


TELEGRAM_DEVICE_NUMBERS={5563:1,5557:2,5559:3,5561:4,5565:5}

def telegram_device_label(value):
    n=port(value)
    number=TELEGRAM_DEVICE_NUMBERS.get(n)
    return 'MuMu ADB '+str(n)+(f' ({number})' if number is not None else '')

def configure(value):
    n=port(value)
    # Constants are imported by value throughout the original single-device engine.
    # Target must be fixed in a fresh process, BEFORE any of those imports.
    if any(x in sys.modules for x in ('target_only','diagnose_device','assistant_store','assistant_monitor','one_chat_device')):
        raise MumuError('worker-not-isolated')
    if os.environ.get('DVK_MORELOGIN')=='1':raise MumuError('wrong-platform')
    os.environ['DVK_MUMU_MULTI']='1';os.environ['DVK_MUMU_PORT']=str(n)
    import test_device
    test_device.TARGET=serial(n)
    from mumu_bundle import VerifiedBundle
    test_device.bundle_token=VerifiedBundle(test_device.bundle_token)
    import assistant_store
    original=assistant_store.Store
    from mumu_store import SharedStore
    assert issubclass(SharedStore,original)
    assistant_store.Store=SharedStore
    assistant_store.data_directory=lambda:device_directory(n)
    assistant_store.credential_directory=root_directory
    # Statistics always read the ONE database, not a device report directory.
    import assistant_statistics
    assistant_statistics.database_path=lambda:root_directory()/'assistant.sqlite3'
    import telegram_notify
    old_label=telegram_notify.cloud_label
    telegram_notify.cloud_label=lambda text:telegram_device_label(n)+'\n'+old_label(text)
    return n



def check_recovery_device(executable,folder,endpoint,boot):
    """Reconnect only the explicit endpoint; never adopt a different boot ID."""
    from target_only import TargetOnlyAdb,recheck
    from startup_failure import checkpoint
    recovery_adb=TargetOnlyAdb(executable,folder)
    with checkpoint('device-recheck',adb=recovery_adb):
        recovery_adb.run(['connect',endpoint])
        recheck(recovery_adb,boot)


def run(spec,stopped,progress=lambda _:None,*,runner=None):
    n=port(spec['port'])
    stage='worker-bootstrap'
    atomic(device_directory(n)/'last-startup.json',dict(tool_version=VERSION,platform='MuMu',device_port=n,
        status='starting',stage=stage,automatic_retry=False))
    try:
        configure(n)
        from assistant_settings import Settings
        from assistant_store import Store
        from assistant_authorization import RunAuthorization
        from assistant_lock import operation_lock
        from target_only import TargetOnlyAdb,preflight,recheck
        from test_device import bundle_token
        from mumu_fast_adb import transport
        stage='settings-check'
        current=replace(Settings(**spec['settings']),profile_interval=120,reply_interval=5).check()
        folder=Path(current.folder).resolve(strict=True)
        stage='bundle-check'
        bundle_token(folder)
        if stopped.is_set():raise MumuError('cancelled')
        with ExitStack() as scopes:
            stage='endpoint-lock'
            scopes.enter_context(operation_lock(device_directory(n)/'worker.lock'))
            metrics=scopes.enter_context(transport(serial(n),stopped.is_set))
            scopes.callback(lambda:atomic(device_directory(n)/'last-performance.json',
                dict(metrics.snapshot(),tool_version=VERSION,device_port=n)))
            stage='adb-preflight'
            adb=TargetOnlyAdb(current.adb,folder)
            boot=preflight(adb)
            # Two supplied ports may be aliases of ONE Android instance. Its boot
            # lock also blocks duplicate workers launched by a second GUI.
            stage='device-identity-lock'
            boot_key=hashlib.sha256(boot.encode()).hexdigest()
            scopes.enter_context(operation_lock(root_directory()/'locks'/(boot_key+'.lock')))
            recheck(adb,boot)
            stage='journal-initialization'
            from assistant_reply_window import enable
            enable(Store(),new_only=spec['mode']=='new')
            from assistant_contact_policy import enable as contact_only
            contact_only(Store())
            from assistant_monitor import REPORT
            from mumu_recovery import run as monitor
            stage='monitor'
            atomic(device_directory(n)/'last-startup.json',dict(tool_version=VERSION,platform='MuMu',device_port=n,status='running',stage=stage,automatic_retry=False))
            progress('Подключено. Обрабатываю диалоги и анкеты.')
            def write(value):
                def scope(v):
                    if type(v) is dict:
                        if 'device_scope' in v:v['device_scope']=serial(n)
                        if 'groq_context_export_enabled' in v:
                            from mumu_ai import strategy
                            for provider in ('groq','openrouter','gemini','zai'):
                                v[provider+'_context_export_enabled']=bool(current.groq_enabled)
                            v['ai_strategy']=strategy(current.ai_provider)
                        for child in v.values():scope(child)
                    elif type(v) is list:
                        for child in v:scope(child)
                scope(value)
                from mumu_version import ENGINE_VERSION
                value.update(tool_version=VERSION,engine_version=ENGINE_VERSION,platform='MuMu',device_port=n,
                    device_scope=serial(n),shared_database=True)
                atomic(device_directory(n)/'last-performance.json',dict(metrics.snapshot(),tool_version=VERSION,device_port=n))
                atomic(device_directory(n)/REPORT,value)
                return REPORT
            def recovery_recheck():
                # Fresh evidence + reconnect, retaining the original locked boot.
                check_recovery_device(current.adb,folder,serial(n),boot)
            extra={} if runner is not None else {'recheck':recovery_recheck}
            if runner is None and hasattr(stopped,'restart_on_resume'):stopped.restart_on_resume=True
            out=(runner or monitor)(current,stopped,RunAuthorization(stopped,immediate_greeting=True,progress=progress),progress,
                  mode=spec['mode'],fresh_session=spec['fresh'],write=write,continuous=True,**extra)
            write(out)
            atomic(device_directory(n)/'last-startup.json',dict(tool_version=VERSION,platform='MuMu',device_port=n,status='finished',stage='monitor',automatic_retry=False))
            return out
    except Exception as error:
        # Closed enums only. Never raw exception messages, ADB output or secrets.
        from startup_failure import clean
        name=type(error).__name__
        types={'MumuError','StateError','TestError','ReadStopped','ConfigError','ValueError',
               'FileNotFoundError','PermissionError','OSError','ModuleNotFoundError','ImportError','RuntimeError','OperationalError','IntegrityError'}
        report=dict(tool_version=VERSION,platform='MuMu',device_port=n,status='stopped',
            stage=stage,error_type=name if name in types else 'OtherError',
            reason='cancelled' if stopped.is_set() else 'startup-failed',
            evidence=clean(getattr(error,'_dvk_failure',None)),automatic_retry=False)
        atomic(device_directory(n)/'last-startup.json',report)
        raise MumuError('Этап: '+stage+'. Тип: '+report['error_type']+'. См. last-startup.json.') from None


def pipe_line(fd,limit):
    # Daemon readers must not hold Python BufferedReader's lock at shutdown.
    # Read the initial spec AND commands unbuffered, so no prefetched command
    # can be stranded in a different stream. Length bounds remain unchanged.
    value=bytearray()
    for _ in range(limit):
        part=os.read(fd,1)
        if not part:break
        value.extend(part)
        if part==b'\n':break
    return bytes(value)


def main():
    # The console worker is packed beside the GUI and has its own stdio pipes.
    if sys.argv[1:]==['--mumu-worker-self-check']:
        import mumu_store,mumu_fast_adb,mumu_claims,mumu_pause,assistant_pause,assistant_profile_read
        assert serial(5557)=='127.0.0.1:5557'
        return 0
    if sys.argv[1:]!=['--mumu-worker']:return 2
    emit_lock=threading.Lock()
    def emit(kind,value):
        with emit_lock:
            print(json.dumps(dict(kind=kind,value=value),ensure_ascii=True),flush=True)
    from mumu_pause import PauseGate
    stopped=PauseGate(threading.Event(),lambda state:emit('control',state))
    try:
        input_fd=sys.stdin.fileno()
        raw=pipe_line(input_fd,32769)
        if not raw or len(raw)>32768:raise MumuError('Invalid spec')
        # Validate settings WITHOUT importing engine stores before configure().
        value=json.loads(raw)
        if type(value) is not dict or set(value)!={'port','mode','fresh','settings'}:raise MumuError('Invalid spec')
        port(value['port'])
        if value['mode'] not in ('full','inbox','new') or type(value['fresh']) is not bool or type(value['settings']) is not dict:raise MumuError('Invalid spec')
        def watch():
            # EOF means parent died: revoke permission, do not leave orphan senders.
            while True:
                try:line=pipe_line(input_fd,32)
                except OSError:
                    stopped.set();return
                if not line or line==b'stop\n':
                    stopped.set();return
                if line in (b'pause\n',b'resume\n'):
                    stopped.command(line.decode('ascii').strip())
                else:
                    stopped.set();return
        threading.Thread(target=watch,daemon=True).start()
        out=run(value,stopped,lambda text:emit('progress',str(text)[:3000]))
        from assistant_monitor import summary
        emit('result',summary(out));return 0
    except Exception as error:
        emit('error',str(error) if type(error) is MumuError else 'Не удалось запустить рабочий процесс. Проверь last-startup.json.')
        return 1

if __name__=='__main__':raise SystemExit(main())
