"""One existing semantic profile/chat cycle, with explicit per-message host consent.

No automatic approval, no batch loop, no new RPC accepting code or arbitrary ADB.
The native side rechecks the same identity and fully loaded empty history after
approval; its send latch still precedes the handler invocation.
"""
import json
import threading

import chat_batch
import cohort_pass
from assistant_config import check_text
from assistant_store import StateError
from uikit_profile_navigation import replace_once

APPROVAL_SECONDS = 60
CYCLE_TIMEOUT_MS = 90000


def build(text, visited=()):
    text = check_text(text)
    from conversation_engine import identifier
    if not isinstance(visited, (list, tuple)) or len(visited) > 10000:
        raise ValueError('Invalid visited profiles')
    visited = [identifier(peer) for peer in visited]
    source = cohort_pass.build([0] * 10)
    source = replace_once(source, 'let batchSeen=new Set(),',
                          'let batchSeen=new Set(' + json.dumps(visited) + '),')
    source = replace_once(source, 'batchSeen.size>=10', 'batchAttempts>1')
    source = replace_once(source, 'batchCandidateKey=identityKey;',
                          'batchCandidateKey=identityKey;assistantSelectedPeer=identityKey;')
    source = replace_once(source, 'const batchGreetings=' + json.dumps([cohort_pass.get_greeting(0)] * 10),
                          'const batchGreetings=' + json.dumps([text] * 10))
    # This is a single cycle, not a longer automatic pass. Existing per-frame,
    # managed-call, handle and identity budgets remain unchanged.
    source = replace_once(source, 'batchAttempts>=10', 'batchAttempts>=1')
    source = replace_once(source, 'finish(\'callback-timeout\');},30000);',
                          'finish(\'callback-timeout\');},90000);')
    source = replace_once(source, '"cycle_timeout_ms":30000', '"cycle_timeout_ms":90000')
    from assistant_profile_read import specialize
    source = specialize(source)
    import os
    if os.environ.get('DVK_MUMU_MULTI') == '1':
        from mumu_claims import specialize
        source = specialize(source)
    # Unready profile/return views used to spin on every Unity callback,
    # burning frame/call budgets before the next UI update. Throttle only
    # observations; existing action latches, 100ms frame and total budgets stay.
    source = replace_once(source, 'const deadline=Date.now()+100;',
        "const deadline=Date.now()+100;\n  if(n.phase==='wait-profile'||n.phase==='confirm-profile'||n.phase==='wait-return')state.nextActionAt=Date.now()+100;")
    return 'let assistantSelectedPeer=null;\n' + source


def validate(value, *, shared_peer_skipped=False):
    # Only normalize the declared timeout for the existing strict validator.
    # Never normalize a send flag, identity, history classification or result.
    import copy
    checked = copy.deepcopy(value)
    from assistant_profile_read import validate as validate_profile_read
    skipped_unready = validate_profile_read(checked['navigation'])
    if type(checked['navigation']['cycle_timeout_ms']) is not int or checked['navigation']['cycle_timeout_ms'] != CYCLE_TIMEOUT_MS:
        raise ValueError('Invalid manual-cycle deadline')
    checked['navigation']['cycle_timeout_ms'] = chat_batch.CYCLE_TIMEOUT_MS
    import os
    native_skip = checked['navigation'].pop('shared_peer_skipped', False)
    if type(native_skip) is not bool or type(shared_peer_skipped) is not bool or native_skip != shared_peer_skipped:
        raise ValueError('Unverified shared peer skip')
    if native_skip and os.environ.get('DVK_MUMU_MULTI') != '1':
        raise ValueError('Shared skip outside MuMu worker')
    chat_batch.validate(checked, skipped_empty=native_skip, skipped_unready=skipped_unready)
    return value


def monitor(script, store, text, approve, done, cancelled, state):
    """A successful FULL SQLite commit MUST happen before native authorization."""
    while not done.wait(.05):
        try:
            pending = script.exports_sync.cohortpending()
            if pending is None:
                continue
            pending = dict(cohort_pass.Store.check(pending))
            if cancelled() or done.is_set():
                return
            # A current shared claim skips before typing; reserve below still
            # checks atomically again in case another worker wins during typing.
            if getattr(store, 'mumu_shared_claims', False) is True and store.peer_claimed(pending):
                from mumu_claims import skip
                skip(script, pending, state)
                return
            # No reservation (and no send authorization) on No, Stop or timeout.
            if approve(dict(pending), text, lambda: cancelled() or done.is_set()) is not True:
                state['declined'] = True
                script.exports_sync.cancel()
                return
            if cancelled() or done.is_set():
                return
            try:
                state['action_id'] = store.reserve(pending, text, approved=True)
            except StateError as error:
                from mumu_store import SharedPeerClaimed
                if not isinstance(error, SharedPeerClaimed):
                    raise
                from mumu_claims import skip
                skip(script, pending, state)
                return
            if cancelled() or done.is_set():
                return  # Durable unknown reservation is intentionally retained.
            if not script.exports_sync.cohortack(pending):
                raise StateError('Подтверждение устарело. Отправка остановлена.')
            return  # Exactly one authorization per host operation.
        except Exception as error:
            state['error'] = str(error) if isinstance(error, StateError) else 'Не удалось сохранить или проверить разрешение отправки.'
            try:
                script.exports_sync.cancel()
            except Exception:
                pass
            return


def inspect(port, token, cancelled, text, store, approve, *, frida_api=None):
    if frida_api is None:
        import frida as frida_api
    from diagnose_device import cleanup_frida, validate_runtime
    from one_chat_device import ReadStopped
    from test_device import PACKAGE
    from startup_failure import record
    f = frida_api
    if f.__version__ != '17.24.1':
        raise ReadStopped('client-version')
    source = build(text, store.visited_peers()) + '''
rpc.exports={runtime(){return {frida_version:Frida.version,arch:Process.arch,platform:Process.platform};},
 root(){return probeBatchProfile();},cancel(){cancelNavigation();},
 selectedpeer(){return assistantSelectedPeer;},cohortpending(){return cohortReservation();},cohortack(value){return cohortAcknowledge(value);}};
'''
    try:
        manager = f.get_device_manager()
    except Exception as error:
        record(error,'gadget-manager');raise
    address = '127.0.0.1:' + str(port)
    device = session = script = None
    done = threading.Event()
    state = {}
    threads = []
    guard = f.Cancellable()
    timer = threading.Timer(100, guard.cancel)
    timer.daemon = True
    timer.start()
    stage='gadget-connect'
    try:
        with guard:
            if cancelled():
                raise ReadStopped('cancelled')
            device = manager.add_remote_device(address, token=token)
            stage='gadget-process'
            processes = device.enumerate_processes()
            if (len(processes) != 1 or type(processes[0].pid) is not int or processes[0].pid <= 0
                    or processes[0].name not in ('Gadget', PACKAGE)):
                raise ReadStopped('unexpected-process')
            stage='gadget-attach'
            session = device.attach(processes[0].pid)
            stage='script-create'
            script = session.create_script(source, name='dvk-assistant-manual-profile')
            stage='script-load'
            script.load()
            stage='runtime-check'
            runtime = validate_runtime(script.exports_sync.runtime())
            if runtime['arch'] != 'arm64' or runtime['platform'] != 'linux':
                raise ReadStopped('unsupported-runtime')
            def watch():
                while not done.wait(.1):
                    if cancelled():
                        try:
                            script.exports_sync.cancel()
                        except Exception:
                            pass
                        return
            for target, args in ((watch, ()), (monitor, (script, store, text, approve, done, cancelled, state))):
                thread = threading.Thread(target=target, args=args, daemon=True)
                threads.append(thread)
                thread.start()
            stage='script-run'
            raw = script.exports_sync.root()
            stage='result-validation'
            value = validate(raw, shared_peer_skipped=state.get('shared_peer_skipped', False))
            done.set()
            for thread in threads:
                thread.join(timeout=2)
            if any(thread.is_alive() for thread in threads):
                raise StateError('Подтверждение не завершилось. Проверь чат вручную.')
            n = value['navigation']
            peer = script.exports_sync.selectedpeer()
            if peer is not None:
                store.record_visit(peer, n)
            action_id = state.get('action_id')
            if n['send_attempted'] and action_id is None:
                raise StateError('Отправка без сохранённого разрешения.')
            if action_id is not None:
                store.finish(action_id, n)
            if state.get('error'):
                raise StateError(state['error'])
            return dict(navigation=n, declined=state.get('declined', False))
    except Exception as error:
        record(error,stage)
        raise
    finally:
        done.set()
        timer.cancel()
        for thread in threads:
            thread.join(timeout=2)
        cleanup_frida(f, manager, address, script, session, device)


def run(executable, folder, text, approve, cancelled=lambda: False, *, store=None):
    from pathlib import Path
    from one_chat_device import capture
    from assistant_lock import operation_lock
    from assistant_store import Store
    folder = Path(folder).resolve(strict=True)
    # Old anonymous locks cannot be safely assigned to a particular recipient.
    for name in ('.dvk-ten-profile-pass.lock', '.dvk-one-greeting.lock'):
        if (folder / name).exists():
            raise StateError('Есть прежний незавершённый резерв отправки. Не удаляй его; сначала нужна сверка старого запуска.')
    text = check_text(text)
    with operation_lock():
        store = Store() if store is None else store
        return capture(executable, folder, cancelled,
                       inspector=lambda port, token, cancel, expected: inspect(port, token, cancel, text, store, approve))


def run_automatic(executable, folder, text, cancelled=lambda: False, *, enabled=False, store=None):
    """Explicit one-run opt-in, ONE profile/greeting, same native checks/journal.

    No modal per-message approval. This is not a background/bulk sender.
    """
    if enabled is not True:
        raise StateError('Сначала явно включи автоматические сообщения в окне режима.')
    return run(executable, folder, text,
               lambda pending, greeting, native_cancelled: not cancelled() and not native_cancelled(),
               cancelled, store=store)
