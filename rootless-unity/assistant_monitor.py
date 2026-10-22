"""Explicitly started, serial monitoring of journal-authorized dialogs.

Full mode repeats qualified-profile batches with a 120-second idle interval,
serially between tracked inbox passes. Reply-only mode never starts profiles.
One device lock and durable journals survive all batches. Unknown sends are isolated.
"""
from contextlib import nullcontext
import json
import time
import math

from assistant_lock import operation_lock
from assistant_store import StateError, data_directory
from assistant_navigation_check import safe_diagnostic
from assistant_inbox import run as inbox_pass, PAUSE_OUTCOMES
from assistant_run import start as initial_pass
from dialog_browser import perform
from version import VERSION
from assistant_authorization import flags

PROFILE_INTERVAL = 120
REPORT = 'last-monitor.json'
COUNTERS = ('submission_calls', 'handler_returns', 'outgoing_observed', 'contacts_forwarded', 'groq_requests', 'openrouter_requests', 'ai_requests', 'isolated_dialogs')


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
                automatic_profile_repeat=False, profile_interval_seconds=PROFILE_INTERVAL,
                profile_batches_completed=0, profile_next_in_seconds=None, last_profile_run=None, error_notification='not-needed',
                contacts_enabled=False, immediate_rechecks=0, between_profile_checks=0,
                groq_enabled=False, ai_enabled=False, ai_provider='groq', ai_model=None,
                groq_context_export_enabled=False, openrouter_context_export_enabled=False, chat_content_exported=False, delivery_confirmed=False,
                all_dialogs_covered=False, report_name=None)


def run(settings, stopped, approve, progress=lambda _: None, *, mode='full',
        fresh_session=False, initial=initial_pass, inbox=inbox_pass,
        navigator=perform, lock=operation_lock, write=write_report, wait=None,
        clock=time.monotonic, repeat=initial_pass, alert=None):
    """No startup/resume actions without an explicit UI Start. Begin on search or dialogs; unknown screens are rejected."""
    if mode not in ('full', 'inbox'):
        raise ValueError('Invalid monitor mode')
    out = report(mode)
    out.update(flags(approve))
    out.update(contacts_enabled=settings.contacts_enabled, automatic_profile_repeat=mode == 'full', groq_enabled=settings.groq_enabled,
               ai_enabled=settings.groq_enabled, ai_provider=settings.ai_provider, ai_model=settings.ai_model,
               groq_context_export_enabled=settings.groq_enabled and settings.ai_provider == 'groq',
               openrouter_context_export_enabled=settings.groq_enabled and settings.ai_provider == 'openrouter')
    wait = stopped.wait if wait is None else wait
    phase = 'settings-check-stopped'

    def add_counters(value):
        for key in COUNTERS:
            number = value.get(key, 0) if key in ('groq_requests', 'openrouter_requests', 'ai_requests', 'isolated_dialogs') else value[key]
            if type(number) is not int or number < 0:
                raise ValueError('Invalid inbox counter')
            out['totals'][key] += number
        if value.get('chat_content_exported'):
            out['chat_content_exported'] = True

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

    last_between_check = clock()
    def between_profiles():
        nonlocal last_between_check
        check_stop()
        if clock() - last_between_check < settings.reply_interval:
            return
        navigate('list','search')
        current = inbox(settings,stopped,approve,progress,entry='dialogs',return_to='dialogs')
        out['last_pass'] = current
        add_counters(current)
        check_stop()
        if (current['status'] not in ('inbox-completed','inbox-empty') or
                current['status'] != 'inbox-empty' and not current.get('dialogs_verified') or
                set(current['outcomes']) & PAUSE_OUTCOMES):
            raise StateError('between-profile-inbox-stopped')
        out['passes_completed'] += 1
        out['between_profile_checks'] += 1
        navigate('return','dialogs')
        last_between_check = clock()
        out.update(status='checking',reason='between-profile-inbox')
        publish()


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
                                mode='full', fresh_session=fresh_session, lock=nullcontext,
                                between_profiles=between_profiles)
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
                out['profile_batches_completed'] = 1
            next_profiles = clock() + PROFILE_INTERVAL
            entry = 'search' if mode == 'full' else 'either'
            immediate_passes = 0
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
                # A peer can reply while we are in another chat. Rescan from
                # the list with fresh journal targets BEFORE sleeping/profiles.
                # Bounded burst avoids an unbounded busy loop/stale badges.
                active = current.get('dialogs_processed',0) > 0
                if active and immediate_passes < 3:
                    immediate_passes += 1
                    out['immediate_rechecks'] += 1
                    out.update(status='checking',reason='drain-incoming')
                    publish()
                    continue
                if mode == 'full' and not active and clock() >= next_profiles:
                    # Only between completed inbox passes; never overlap device work
                    # or reset greeting reservations/profile/city history.
                    phase = 'search-screen-not-verified'
                    navigate('return', 'dialogs')
                    check_stop()
                    phase = 'profile-repeat-stopped'
                    out.update(dialogs_verified=False, ui_may_remain_open=True)
                    batch = repeat(settings, stopped, approve, progress, mode='profiles',
                                   fresh_session=True, lock=nullcontext, between_profiles=between_profiles)
                    out['last_profile_run'] = batch
                    check_stop()
                    if batch['status'] == 'paused':
                        raise StateError('profile-pass-paused')
                    if batch['status'] != 'completed':
                        raise StateError('profile-pass-stopped')
                    if batch.get('report_name') is None:
                        raise StateError('report-write-failed')
                    out['profile_batches_completed'] += 1
                    phase = 'dialog-list-not-verified'
                    navigate('list', 'search')
                    next_profiles = clock() + PROFILE_INTERVAL
                    immediate_passes = 0
                    # No idle delay between the profile batch and inbox.
                    continue
                out['profile_next_in_seconds'] = math.ceil(max(0, next_profiles-clock())) if mode == 'full' else None
                out.update(status='waiting', reason='next-inbox-pass')
                publish()  # A failed report always stops further device work.
                phase = 'monitor-check-stopped'
                delay = min(settings.reply_interval, max(0.01, next_profiles-clock())) if mode == 'full' and not active else settings.reply_interval
                progress(summary(out) + f' Следующая проверка через {delay:g} сек.')
                immediate_passes = 0
                if wait(delay):
                    out.update(status='cancelled', reason='cancelled')
                    break
    except Exception as error:
        known = {'cancelled', 'report-write-failed', 'initial-pass-stopped',
                 'inbox-pass-stopped', 'dialog-list-not-verified', 'initial-pass-paused',
                 'profile-pass-paused', 'profile-pass-stopped', 'profile-repeat-stopped'}
        out.update(status='cancelled' if stopped.is_set() else
                   'paused' if isinstance(error, StateError) and str(error) in ('initial-pass-paused', 'profile-pass-paused') else 'stopped',
                   reason='cancelled' if stopped.is_set() else
                   str(error) if isinstance(error, StateError) and str(error) in known else phase)
    try:
        publish()
    except StateError:
        out.update(status='stopped', reason='report-write-failed')
    if settings.errors_enabled and out['status'] in ('stopped', 'paused'):
        from assistant_error_notify import notify
        try:
            out['error_notification'] = (notify if alert is None else alert)(out)
            if out['error_notification'] not in ('accepted', 'unknown', 'not-configured', 'not-needed'):
                out['error_notification'] = 'unknown'
        except Exception:
            out['error_notification'] = 'unknown'
        try:
            publish()
        except StateError:
            out.update(status='stopped', reason='report-write-failed')
    return out


def summary(result):
    """Compact status only. Detailed counters/reasons remain in last-monitor.json."""
    totals=result['totals']
    status=result['status']
    if status=='waiting':
        text=f"Диалоги • проходов {result['passes_completed']} • в истории {totals['outgoing_observed']} • контактов TG {totals['contacts_forwarded']}"
        contact_pending = (result.get('last_pass') or {}).get('contact_delivery_pending',0)
        if contact_pending:
            text += f" • контактов ожидают TG {contact_pending}"
            if not result.get('contacts_enabled'):text += ' (передача выключена)'
        pending = (result.get('last_pass') or {}).get('review_pending', 0)
        if pending or totals.get('isolated_dialogs', 0):
            text += f" • на проверке {max(pending, totals.get('isolated_dialogs', 0))}"
        if result.get('automatic_profile_repeat'):
            text+=f"\nАнкеты • порций {result.get('profile_batches_completed',0)} • следующая через {result.get('profile_next_in_seconds',120)} с"
        else:
            text+='\nТолько ответы • без новых анкет'
        return text
    if status=='cancelled':
        return 'Остановлено • действия не откатываются. Отчёт: last-monitor.json'
    from assistant_error_notify import reasons
    from groq_reply import ERRORS as GROQ_ERRORS
    codes=reasons(result)
    reason=next((c for c in codes if c in GROQ_ERRORS),result['reason'])
    text=('Пауза' if status=='paused' else 'Ошибка')+' • '+reason
    notification=result.get('error_notification')
    if notification=='accepted':
        text+=' • причина передана в TG'
    elif notification in ('unknown','not-configured'):
        text+=' • TG не подтверждён'
    return text+'\nПроверь экран. Отчёт: last-monitor.json'
