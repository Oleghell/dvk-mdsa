"""Explicitly started, serial monitoring of journal-authorized dialogs.

The existing full pass runs at most once. Subsequent passes ONLY inspect the
tracked inbox, with explicit run or per-message permission, no city timer and no new profiles.
One OS device lock is held until Stop, failure or a declined approval. Reports
contain counters/categories only; unknown sends are never retried.
"""
from contextlib import nullcontext
import json

from assistant_lock import operation_lock
from assistant_store import StateError, data_directory
from assistant_navigation_check import safe_diagnostic
from assistant_inbox import run as inbox_pass, PAUSE_OUTCOMES
from assistant_run import start as initial_pass
from dialog_browser import perform
from version import VERSION
from assistant_authorization import flags

REPORT = 'last-monitor.json'
COUNTERS = ('submission_calls', 'handler_returns', 'outgoing_observed', 'contacts_forwarded')


def write_report(value):
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / REPORT
    temporary = target.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding='utf-8')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target.name


def report(mode):
    return dict(tool_version=VERSION, mode=mode, status='stopped', reason='not-started',
                initial_run=None, last_pass=None, passes_completed=0,
                totals={key: 0 for key in COUNTERS}, dialogs_verified=False,
                ui_may_remain_open=False, last_navigation=None,
                per_message_confirmation=True, automatic_send=False,
                automatic_profile_repeat=False, delivery_confirmed=False,
                all_dialogs_covered=False, report_name=None)


def run(settings, stopped, approve, progress=lambda _: None, *, mode='full',
        fresh_session=False, initial=initial_pass, inbox=inbox_pass,
        navigator=perform, lock=operation_lock, write=write_report, wait=None):
    """No startup/resume actions without an explicit UI Start. Begin on search or dialogs; unknown screens are rejected."""
    if mode not in ('full', 'inbox'):
        raise ValueError('Invalid monitor mode')
    out = report(mode)
    out.update(flags(approve))
    wait = stopped.wait if wait is None else wait
    phase = 'settings-check-stopped'

    def add_counters(value):
        for key in COUNTERS:
            number = value[key]
            if type(number) is not int or number < 0:
                raise ValueError('Invalid inbox counter')
            out['totals'][key] += number

    def publish():
        try:
            out['report_name'] = REPORT
            if write(out) != REPORT:
                raise OSError('Report was not saved')
        except Exception:
            out['report_name'] = None
            raise StateError('report-write-failed') from None

    def check_stop():
        if stopped.is_set():
            raise StateError('cancelled')

    def navigate(operation, entry):
        check_stop()
        out.update(dialogs_verified=False, ui_may_remain_open=True)
        value = navigator(operation, settings.adb, settings.folder, stopped.is_set, entry=entry)
        if not isinstance(value, dict) or set(value) != {'state', 'identity', 'diagnostic'}:
            raise ValueError('Invalid screen result')
        n = out['last_navigation'] = safe_diagnostic(value['diagnostic'])
        destination = 'dialogs-ready' if operation == 'list' else 'search-ready'
        if (value['state'] != destination or value['identity'] is not None
                or n['stage'] != 'navigation-ready' or n['error'] != 'none'
                or not n['destination_verified'] or n['phase'] != 'done'
                or n['rows_scanned'] or n['scan_batches'] or n['unread_filter_applied']
                or operation == 'return' and not n['action_completed']):
            raise ValueError('Unverified screen')
        out.update(dialogs_verified=operation == 'list', ui_may_remain_open=False)
        check_stop()

    try:
        check_stop()
        settings.check()
        phase = 'device-busy-or-monitor-check-stopped'
        with lock():
            check_stop()
            if mode == 'full':
                phase = 'dialog-list-not-verified'
                navigate('list', 'either')
                phase = 'search-screen-not-verified'
                navigate('return', 'dialogs')
                phase = 'initial-pass-stopped'
                out['ui_may_remain_open'] = True
                first = initial(settings, stopped, approve, progress,
                                mode='full', fresh_session=fresh_session, lock=nullcontext)
                out['initial_run'] = first
                if first.get('inbox'):
                    add_counters(first['inbox'])
                check_stop()
                if first['status'] == 'paused':
                    raise StateError('initial-pass-paused')
                if first['status'] != 'completed':
                    raise StateError('initial-pass-stopped')
                if first.get('report_name') is None:
                    raise StateError('report-write-failed')
            entry = 'search' if mode == 'full' else 'either'
            while True:
                check_stop()
                phase = 'dialog-list-not-verified'
                navigate('list', entry)
                entry = 'dialogs'
                phase = 'inbox-pass-stopped'
                out.update(dialogs_verified=False, ui_may_remain_open=True)
                current = inbox(settings, stopped, approve, progress,
                                entry='dialogs', return_to='dialogs')
                out['last_pass'] = current
                add_counters(current)
                check_stop()
                if current['status'] not in ('inbox-completed', 'inbox-empty'):
                    raise StateError('inbox-pass-stopped')
                if current['status'] != 'inbox-empty' and not current.get('dialogs_verified'):
                    raise StateError('dialog-list-not-verified')
                out.update(dialogs_verified=True, ui_may_remain_open=False)
                out['passes_completed'] += 1
                review = set(current['outcomes']) & PAUSE_OUTCOMES
                if review:
                    out.update(status='paused', reason='message-not-approved' if
                               'message-not-approved' in review else 'dialog-needs-review')
                    break
                out.update(status='waiting', reason='next-inbox-pass')
                publish()  # A failed report always stops further device work.
                phase = 'monitor-check-stopped'
                progress(summary(out) + f' Следующая проверка через {settings.reply_interval} сек.')
                if wait(settings.reply_interval):
                    out.update(status='cancelled', reason='cancelled')
                    break
    except Exception as error:
        known = {'cancelled', 'report-write-failed', 'initial-pass-stopped',
                 'inbox-pass-stopped', 'dialog-list-not-verified', 'initial-pass-paused'}
        out.update(status='cancelled' if stopped.is_set() else
                   'paused' if isinstance(error, StateError) and str(error) == 'initial-pass-paused' else 'stopped',
                   reason='cancelled' if stopped.is_set() else
                   str(error) if isinstance(error, StateError) and str(error) in known else phase)
    try:
        publish()
    except StateError:
        out.update(status='stopped', reason='report-write-failed')
    return out


def summary(result):
    totals = result['totals']
    text = (f"Мониторинг: проходов {result['passes_completed']}, попыток отправки {totals['submission_calls']}, "
            f"возвратов обработчика {totals['handler_returns']}, новых исходящих в истории "
            f"{totals['outgoing_observed']}, контактов в Telegram {totals['contacts_forwarded']}. "
            'Появление исходящего в истории не подтверждает доставку собеседнику. ')
    first = result.get('initial_run') or {}
    profiles = first.get('profiles')
    if profiles:
        text += (f"Начальная порция: подходящих {profiles.get('qualified_profiles', 0)}/{profiles['profile_limit']}, просмотрено {profiles['profiles_checked']}, "
                 f"попыток приветствия {profiles['send_attempts']}, возвратов обработчика "
                 f"{profiles['handlers_returned']}. Появление приветствий в истории не проверялось. ")
        city = profiles.get('last_city_navigation')
        if city and city['stage'] != 'navigation-ready':
            text += f"Выбор города остановлен: {city['error']}, этап {city['city_checkpoint']}. "
        if profiles.get('send_attempts_unknown'):
            text += 'Цикл оборвался: число дополнительных попыток приветствия неизвестно. '
    last = (result.get('last_pass') or first.get('inbox') or {}).get('last_chat_diagnostics') or {}
    read = last.get('last_read_failure')
    if read:
        text += f"Чтение истории: {read['error']}, этап {read.get('read_checkpoint', 'unknown')}, ожидание {read.get('wait_reason', 'unknown')}. "
    if result['status'] == 'waiting':
        text += 'Остаюсь в диалогах. Новые анкеты повторно не запускаются.'
    elif result['status'] == 'cancelled':
        text += 'Мониторинг остановлен. Выполненные действия не откатываются.'
    elif result['status'] == 'paused':
        text += 'Мониторинг на паузе: сообщение не подтверждено или нужна ручная проверка. Для продолжения нужен новый «Старт».'
    else:
        text += 'Мониторинг остановлен: ' + result['reason'] + '. Проверь экран; неизвестные отправки не повторяются.'
    return text + ' Отчёт: ' + (result.get('report_name') or 'не удалось сохранить') + '.'
