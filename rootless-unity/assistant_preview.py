"""Button-start, profile-only preview. No chat, sending, scrolling or city change."""
import copy
import json
import threading

import profile_batch
from assistant_store import StateError
from conversation_engine import identifier
from search_scan import specialize
from uikit_profile_navigation import replace_once

LIMIT = 5
TOTAL_TIMEOUT_SECONDS = 65


def build(visited=()):
    if not isinstance(visited, (list, tuple)) or len(visited) > 10000:
        raise ValueError('Invalid visited profiles')
    visited = [identifier(peer) for peer in visited]
    source = profile_batch.FUNCTION
    source = replace_once(source, 'let batchSeen=new Set(),',
                          'let batchSeen=new Set(' + json.dumps(visited) + '),')
    # Old visits do not consume this run's five-attempt budget.
    source = replace_once(source, 'batchSeen.size>=10', 'batchAttempts>5')
    source = replace_once(source, 'batchAttempts>=10', 'batchAttempts>=5')
    source = replace_once(source, 'batchCandidateKey=identityKey;',
                          'batchCandidateKey=identityKey;previewSelectedPeer=identityKey;')
    source = replace_once(source, 'r.navigation=emptyNavigation();',
                          'r.navigation=emptyNavigation();Object.assign(r.navigation,{scan_yields:0,scan_slices:0});')
    # Same bounded cooperative search scan as the working single-profile path,
    # but the underlying script contains only profile open/read/close handlers.
    return 'let previewSelectedPeer=null;\n' + specialize(source)


def validate(value):
    checked = copy.deepcopy(value)
    n = checked['navigation']
    yields, slices = n.pop('scan_yields'), n.pop('scan_slices')
    if type(yields) is not int or not 0 <= yields <= 8 or type(slices) is not int or not 0 <= slices <= 180:
        raise ValueError('Invalid preview scan counters')
    profile_batch.validate(checked)
    return value


def walk(root, selected_peer, store, visited, cancelled=lambda: False, progress=lambda text: None):
    """Commit each verified visit before even considering another profile."""
    seen = {identifier(peer) for peer in visited}
    result = dict(limit=LIMIT, status='preview-stopped', reason='not-started',
                  attempts=0, visited=0, checked=0, eligible=0, skipped=0, unknown=0,
                  profile_may_remain_open=False, chats_opened=0, messages_sent=0)
    for number in range(1, LIMIT + 1):
        if cancelled():
            result.update(status='preview-cancelled', reason='cancelled')
            break
        progress(f'Смотрю анкету {number}/{LIMIT}. Чаты не открываю, сообщения не отправляю.')
        # A Stop pressed while publishing progress must not open the next profile.
        if cancelled():
            result.update(status='preview-cancelled', reason='cancelled')
            break
        result['attempts'] += 1
        try:
            value = validate(root())
        except Exception:
            result.update(reason='probe-failed', profile_may_remain_open=True)
            if cancelled():
                result.update(status='preview-cancelled', reason='cancelled')
            break
        n = value['navigation']
        result['profile_may_remain_open'] = n['open_attempted'] and not n['return_verified']
        if n['profile_verified']:
            try:
                peer = identifier(selected_peer())
                if peer in seen:
                    raise ValueError('Repeated profile')
                # This path has not opened or inspected any chat.
                store.record_visit(peer, dict(n, history_status='not-opened'))
            except Exception:
                raise StateError('Не удалось сохранить просмотр анкеты. Просмотр остановлен; проверь экран вручную.') from None
            seen.add(peer)
            result['visited'] += 1
        if n['stage'] != 'navigation-ready':
            if n['error'] == 'selection-unavailable' and not n['open_attempted']:
                result.update(status='preview-exhausted', reason='visible-exhausted')
            elif n['error'] == 'cancelled':
                result.update(status='preview-cancelled', reason='cancelled')
            else:
                result['reason'] = n['error'] if n['error'] != 'none' else 'not-ready'
            break
        if n['friends_status'] != 'read':
            result['unknown'] += 1
            result['reason'] = 'count-unavailable'
            break
        result['checked'] += 1
        result['eligible' if n['friends_eligible'] else 'skipped'] += 1
        if cancelled():
            result.update(status='preview-cancelled', reason='cancelled')
            break
    else:
        result.update(status='preview-completed', reason='limit-reached')
    return result


def status_text(result):
    prefix = {'preview-completed': 'Просмотр завершён.',
              'preview-exhausted': 'На видимом экране больше нет новых анкет. Это не конец всей ленты.',
              'preview-cancelled': 'Просмотр остановлен по кнопке «Стоп».',
              'preview-stopped': 'Не удалось безопасно продолжить просмотр.'}[result['status']]
    text = (prefix + f" Проверено: {result['checked']}/{LIMIT}; меньше 50 друзей: {result['eligible']};"
            f" 50 и больше: {result['skipped']}. Чаты не открывались, сообщения не отправлялись.")
    if result['reason'] == 'count-unavailable':
        text += ' Число друзей неизвестно — не считаю его нулём.'
    if result['profile_may_remain_open'] or result['status'] == 'preview-stopped':
        text += ' Проверь экран MuMu перед следующим запуском.'
    return text


def inspect(port, token, cancelled, store, progress, *, frida_api=None):
    if frida_api is None:
        import frida as frida_api
    from diagnose_device import cleanup_frida, validate_runtime
    from one_chat_device import ReadStopped
    from test_device import PACKAGE
    f = frida_api
    if f.__version__ != '17.24.1':
        raise ReadStopped('client-version')
    visited = store.visited_peers()
    source = build(visited) + '''
rpc.exports={runtime(){return {frida_version:Frida.version,arch:Process.arch,platform:Process.platform};},
 root(){previewSelectedPeer=null;return probeBatchProfile();},
 selectedpeer(){return previewSelectedPeer;},cancel(){cancelNavigation();}};
'''
    manager = f.get_device_manager()
    address = '127.0.0.1:' + str(port)
    device = session = script = monitor = None
    done = threading.Event()
    guard = f.Cancellable()
    timer = threading.Timer(TOTAL_TIMEOUT_SECONDS, guard.cancel)
    timer.daemon = True
    timer.start()
    try:
        with guard:
            if cancelled():
                raise ReadStopped('cancelled')
            device = manager.add_remote_device(address, token=token)
            processes = device.enumerate_processes()
            if (len(processes) != 1 or type(processes[0].pid) is not int or processes[0].pid <= 0
                    or processes[0].name not in ('Gadget', PACKAGE)):
                raise ReadStopped('unexpected-process')
            session = device.attach(processes[0].pid)
            script = session.create_script(source, name='dvk-assistant-profile-preview')
            script.load()
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
            monitor = threading.Thread(target=watch, daemon=True)
            monitor.start()
            return walk(script.exports_sync.root, script.exports_sync.selectedpeer, store, visited, cancelled, progress)
    finally:
        done.set()
        timer.cancel()
        if monitor:
            monitor.join(timeout=2)
        cleanup_frida(f, manager, address, script, session, device)


def run(executable, folder, cancelled=lambda: False, progress=lambda text: None, *, store=None):
    from pathlib import Path
    from one_chat_device import capture, ReadStopped
    from assistant_lock import operation_lock
    from assistant_store import Store
    folder = Path(folder).resolve(strict=True)
    with operation_lock():
        store = Store() if store is None else store
        completed = []

        def inspector(port, token, cancel, expected):
            value = inspect(port, token, cancel, store, progress)
            completed.append(value)
            return value
        try:
            return capture(executable, folder, cancelled, inspector=inspector)
        except ReadStopped as error:
            # capture checks boot identity and removes its forward before this
            # cancellation reaches us. Never mask a transport/cleanup failure.
            if str(error) == 'cancelled' and completed:
                value = completed[0]
                value.update(status='preview-cancelled', reason='cancelled')
                return value
            raise