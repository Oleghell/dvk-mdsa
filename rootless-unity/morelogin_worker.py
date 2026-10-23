"""One OS process per phone. Bind target BEFORE importing device adapters.

stdin/stdout are private parent pipes, never command-line secrets or log files.
EOF/Stop requests cancellation; unknown native sends remain durably reserved.
"""
import json
import os
from pathlib import Path
import sys
import threading
from contextlib import ExitStack
from morelogin_common import CloudError, phone_id, root_directory, phone_directory, fingerprint
from morelogin_client import plan, DirectPlan


def event(kind, **value):
    print(json.dumps(dict(kind=kind, **value), ensure_ascii=True), flush=True)


def configure_target(serial, cloud_id):
    # This function MUST run in a fresh process, before any engine import.
    if any(name in sys.modules for name in ('target_only','one_chat_device','assistant_monitor','assistant_contact_photo')):
        raise CloudError('configuration')
    import re
    if not re.fullmatch(r'127\.0\.0\.1:[0-9]{1,5}', serial) or not 1024 <= int(serial.split(':')[1]) <= 65535:
        raise CloudError('configuration')
    os.environ['DVK_MORELOGIN'] = '1'
    os.environ['DVK_MORELOGIN_PHONE_ID'] = phone_id(cloud_id)
    import test_device
    test_device.TARGET = serial
    # Every allowlist (including photo and native transport) imports this exact
    # endpoint. No fallback to MuMu / implicit device / adb devices enumeration.
    import assistant_store
    from morelogin_store import SharedStore
    assistant_store.Store = SharedStore


def run(spec, stopped, progress, *, connect=None, runner=None):
    from morelogin_ssh import tunnel
    cloud_id = phone_id(spec['id'])
    ssh = plan(spec['entry'], cloud_id)
    pin = None if isinstance(ssh,DirectPlan) else fingerprint(spec['fingerprint'])
    if stopped.is_set(): raise CloudError('cancelled')
    if connect is None:
        if isinstance(ssh,DirectPlan):
            from morelogin_direct import connection
            transport=connection(ssh,spec['settings']['adb'],stopped.is_set)
        else:
            transport=tunnel(ssh,pin,stopped.is_set)
    else:
        transport=connect(ssh,pin,stopped.is_set)
    with transport as serial:
        configure_target(serial, cloud_id)
        from assistant_settings import Settings
        from assistant_store import Store
        from assistant_lock import operation_lock
        from target_only import TargetOnlyAdb, preflight, recheck
        from test_device import bundle_token
        from assistant_authorization import RunAuthorization
        settings = Settings(**spec['settings']).check()
        folder = Path(settings.folder).resolve(strict=True)
        try:
            bundle_token(folder)
        except Exception:
            raise CloudError('bundle-required') from None
        with ExitStack() as stack:
            # A duplicate ID in another GUI/process is rejected, never serialized
            # into a second active runner. Locks are released by the OS on crash.
            stack.enter_context(operation_lock(phone_directory(cloud_id)/'cloud-run.lock'))
            from morelogin_fast_adb import transport as fast_reads
            performance=stack.enter_context(fast_reads(serial,stopped.is_set))
            def record_performance():
                from morelogin_common import atomic_json
                try:atomic_json(phone_directory(cloud_id)/'last-performance.json',performance.snapshot())
                except OSError:pass
            stack.callback(record_performance)
            from morelogin_session import transport as gadget_session
            stack.enter_context(gadget_session(serial,stopped.is_set,performance))
            from morelogin_ai import runtime as ai_runtime
            ai_totals=stack.enter_context(ai_runtime(stopped.is_set,metrics=performance,
                models=dict(groq=settings.groq_model,openrouter=settings.openrouter_model)))
            from assistant_monitor import run as monitor, summary
            def ai_report(value):
                value.update(ai_provider_order=['groq','openrouter'],
                    groq_context_export_enabled=settings.groq_enabled,
                    openrouter_context_export_enabled=settings.groq_enabled)
                if isinstance(value.get('totals'),dict):
                    value['totals'].update(groq_requests=ai_totals['groq'],openrouter_requests=ai_totals['openrouter'],
                        ai_requests=ai_totals['groq']+ai_totals['openrouter'])
            adb = TargetOnlyAdb(settings.adb, folder)
            boot = preflight(adb)
            stack.enter_context(operation_lock(root_directory()/'locks'/('boot-'+boot+'.lock')))
            recheck(adb, boot)
            Store()  # Create/validate ONE shared database before allowing a run.
            progress('Подключение проверено. Запускаю цикл.')
            def write(value):
                from morelogin_version import VERSION, ENGINE_VERSION
                from morelogin_common import atomic_json
                ai_report(value)
                value.update(tool_version=VERSION, engine_version=ENGINE_VERSION,
                             platform='MoreLogin', cloud_phone_id=cloud_id)
                atomic_json(phone_directory(cloud_id)/'last-performance.json',performance.snapshot())
                atomic_json(phone_directory(cloud_id)/'last-monitor.json', value)
                return 'last-monitor.json'
            result = (monitor if runner is None else runner)(settings, stopped, RunAuthorization(stopped), progress,
                       mode=spec['mode'], fresh_session=spec['mode']=='full', write=write)
            from morelogin_version import VERSION, ENGINE_VERSION
            ai_report(result)
            result['tool_version'] = VERSION
            result['engine_version'] = ENGINE_VERSION
            result['platform'] = 'MoreLogin'
            result['cloud_phone_id'] = cloud_id
            # The report remains phone-local; no endpoints, API responses or keys.
            from morelogin_common import atomic_json
            atomic_json(phone_directory(cloud_id)/'last-monitor.json', result)
            return summary(result).replace('MuMu №4','Cloud Phone '+cloud_id).replace('MuMu','Cloud Phone')


def main():
    if sys.argv[1:] == ['--self-check']:
        # Offline packaging check: disposable shared DB/config, no phone or credentials.
        import paramiko
        from morelogin_store import SharedStore
        from assistant_monitor import run as monitor
        from morelogin_preparation_check import check
        check()
        return 0
    stopped = threading.Event()
    try:
        line = sys.stdin.buffer.readline(262145)
        if len(line)>262144: raise CloudError('configuration')
        spec = json.loads(line)
        if set(spec) != {'id','entry','fingerprint','settings','mode'} or spec['mode'] not in ('full','inbox'):
            raise CloudError('configuration')
        def commands():
            # The only post-start command is Stop. Closing the GUI pipe also stops.
            for value in sys.stdin:
                if value.strip() == 'stop':
                    stopped.set()
                    return
            stopped.set()
        threading.Thread(target=commands, daemon=True).start()
        text = run(spec, stopped, lambda text:event('progress', text=str(text)[:2500]))
        event('finished', text=text[:4000])
        return 0
    except Exception as error:
        code = str(error) if isinstance(error,CloudError) else 'cancelled' if stopped.is_set() else 'device-not-ready'
        try:
            from morelogin_common import atomic_json
            from morelogin_version import VERSION, ENGINE_VERSION
            cloud_id = phone_id(spec['id'])
            atomic_json(phone_directory(cloud_id)/'last-startup.json',
                        dict(platform='MoreLogin', tool_version=VERSION, engine_version=ENGINE_VERSION,
                             cloud_phone_id=cloud_id, status='stopped', reason=code,
                             automatic_retry=False))
        except Exception:
            pass
        event('error', code=code)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
