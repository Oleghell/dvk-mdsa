"""Explicitly started, serial monitoring of journal-authorized dialogs.

Continuous full mode drains eligible incoming work before each profile batch;
serially between tracked inbox passes. Reply-only mode never starts profiles.
One device lock and durable journals survive all batches. Unknown sends are isolated.
"""
from contextlib import nullcontext, contextmanager
import json
import time
import math
import run_preparation

from assistant_lock import operation_lock
from assistant_store import StateError, data_directory
from assistant_navigation_check import safe_diagnostic
from assistant_inbox import run as inbox_pass, PAUSE_OUTCOMES
from assistant_run import start as initial_pass
from dialog_browser import perform
from version import VERSION
from assistant_authorization import flags

PROFILE_INTERVAL = 300
REPORT = 'last-monitor.json'
COUNTERS = ('submission_calls', 'handler_returns', 'outgoing_observed', 'contacts_forwarded', 'groq_requests', 'openrouter_requests', 'gemini_requests', 'zai_requests', 'ai_requests', 'isolated_dialogs')


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
                ui_may_remain_open=False, last_navigation=None, last_navigation_failure=None, last_preparation_failure=None,
                per_message_confirmation=True, automatic_send=False,
                automatic_profile_repeat=False, profile_interval_seconds=PROFILE_INTERVAL,
                profile_batches_completed=0, profile_next_in_seconds=None, last_profile_run=None, error_notification='not-needed', error_json_notification='not-needed',
                contacts_enabled=False, immediate_rechecks=0, between_profile_checks=0,
                groq_enabled=False, ai_enabled=False, ai_provider='groq', ai_model=None,
                groq_context_export_enabled=False, openrouter_context_export_enabled=False, gemini_context_export_enabled=False, zai_context_export_enabled=False, chat_content_exported=False, delivery_confirmed=False,
                all_dialogs_covered=False, report_name=None)


def run(settings, stopped, approve, progress=lambda _: None, *, mode='full',
        fresh_session=False, initial=initial_pass, inbox=inbox_pass,
        navigator=perform, lock=operation_lock, write=write_report, wait=None,
        clock=time.monotonic, repeat=initial_pass, alert=None, continuous=False, json_alert=None, terminal_notifications=True, resource_factory=None):
    """No startup/resume actions without an explicit UI Start. Begin on search or dialogs; unknown screens are rejected."""
    if type(continuous) is not bool:raise ValueError('Invalid continuous mode')
    new_start=mode=='new'
    if new_start:mode='full'
    if mode not in ('full', 'inbox'):
        raise ValueError('Invalid monitor mode')
    from assistant_polling import Schedule
    polling=Schedule(clock)
    adaptive=continuous and getattr(approve,'fast_runtime',False) is True
    out = report(mode)
    out.update(continuous_work=continuous, early_profile_batches=0)
    out.update(flags(approve))
    out['profile_interval_seconds'] = settings.profile_interval
    out['recent_exit_events'] = []
    out['isolated_reasons_total'] = {}
    out['review_causes_total'] = {}
    out.update(contacts_enabled=settings.contacts_enabled, automatic_profile_repeat=mode == 'full', groq_enabled=settings.groq_enabled,
               ai_enabled=settings.groq_enabled, ai_provider=settings.ai_provider, ai_model=settings.ai_model,
               groq_context_export_enabled=settings.groq_enabled and settings.ai_provider == 'groq',
               openrouter_context_export_enabled=settings.groq_enabled and settings.ai_provider == 'openrouter',
               gemini_context_export_enabled=settings.groq_enabled and settings.ai_provider == 'gemini',
               zai_context_export_enabled=settings.groq_enabled and settings.ai_provider == 'zai')
    wait = stopped.wait if wait is None else wait
    phase = 'settings-check-stopped'
    resource = None
    out['resource_watch'] = dict(status='not-started')

    def resource_event(kind, value):
        nonlocal resource
        if resource is None:return
        try:
            outcome = (resource.inbox(value, enabled=settings.errors_enabled) if kind=='inbox'
                       else resource.profiles(value))
            out['resource_watch'] = dict(resource.state, status='active')
            if outcome is not None and outcome != 'not-needed':
                out['resource_notification'] = outcome
        except Exception:
            # Optional diagnostics cannot stop device work or bypass a send gate.
            resource = None
            out['resource_watch'] = dict(status='unavailable')


    @contextmanager
    def resource_scope():
        nonlocal resource
        try:
            from assistant_resource_watch import Watch
            resource = (resource_factory or Watch)()
            out['resource_watch'] = dict(resource.state, status='active')
        except Exception:
            out['resource_watch'] = dict(status='unavailable')
        try:
            yield
        except BaseException:
            resource_event('inbox',{})
            raise
        else:
            if out['status'] == 'paused':resource_event('inbox',{})

    def add_counters(value):
        out['send_failure_events']=(out.get('send_failure_events',[])+value.get('send_failure_events',[]))[-3:]
        out['recent_exit_events'] = (out['recent_exit_events'] + value.get('exit_events', []))[-20:]
        for key, source in (('isolated_reasons_total','isolated_reasons'),('review_causes_total','review_causes')):
            for code, number in value.get(source, {}).items():
                out[key][code] = out[key].get(code, 0) + number
        for key in COUNTERS:
            number = value.get(key, 0) if key in ('groq_requests', 'openrouter_requests', 'gemini_requests', 'zai_requests', 'ai_requests', 'isolated_dialogs') else value[key]
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
        from startup_failure import record
        out['last_navigation'] = None
        out['last_navigation_failure'] = None
        stage = 'device-inspection'
        try:
            value = navigator(operation, settings.adb, settings.folder, stopped.is_set, entry=entry)
            stage = 'navigation-result'
            if not isinstance(value, dict) or set(value) != {'state', 'identity', 'diagnostic'}:
                raise ValueError('Invalid screen result')
            stage = 'navigation-diagnostic'
            n = out['last_navigation'] = safe_diagnostic(value['diagnostic'])
            stage = 'navigation-destination'
            destination = 'dialogs-ready' if operation == 'list' else 'search-ready'
            if (value['state'] != destination or value['identity'] is not None
                    or n['stage'] != 'navigation-ready' or n['error'] != 'none'
                    or not n['destination_verified'] or n['phase'] != 'done'
                    or n['rows_scanned'] or n['scan_batches'] or n['unread_filter_applied']
                    or operation == 'return' and not n['action_completed']):
                raise ValueError('Unverified screen')
            out.update(dialogs_verified=operation == 'list', ui_may_remain_open=False)
            check_stop()

        except Exception as error:
            out['last_navigation_failure'] = dict(record(error, stage), operation=operation)
            if out['last_navigation'] is None:
                try:
                    out['last_navigation'] = safe_diagnostic(getattr(error, '_dvk_navigation', None))
                except Exception:
                    pass
            raise



    try:
        check_stop()
        settings.check()
        phase = 'device-busy-or-monitor-check-stopped'
        with lock(), resource_scope():
            from assistant_pause import boundary
            boundary(stopped)
            check_stop()
            if mode == 'full':
                phase = 'dialog-list-not-verified'
                navigate('list', 'either')
                phase = 'search-screen-not-verified'
                navigate('return', 'dialogs')
                phase = 'initial-pass-stopped'
                out['ui_may_remain_open'] = True
                first = initial(settings, stopped, approve, progress,
                                mode='profiles' if new_start else 'full', fresh_session=fresh_session, lock=nullcontext)
                out['initial_run'] = first
                out['last_preparation_failure']=run_preparation.from_report(first)
                if first.get('inbox'):
                    add_counters(first['inbox'])
                check_stop()
                if first['status'] == 'paused':
                    raise StateError('initial-pass-paused')
                if first['status'] != 'completed':
                    raise StateError('initial-pass-stopped')
                if first.get('report_name') is None:
                    raise StateError('report-write-failed')
                if first.get('inbox'):
                    resource_event('inbox',first['inbox'])
                resource_event('profiles',first)
                out['profile_batches_completed'] = 1
            next_profiles = clock() + settings.profile_interval
            entry = 'search' if mode == 'full' else 'either'
            immediate_passes = 0
            while True:
                boundary(stopped)
                check_stop()
                phase = 'dialog-list-not-verified'
                navigate('list', entry)
                entry = 'dialogs'
                phase = 'inbox-pass-stopped'
                out.update(dialogs_verified=False, ui_may_remain_open=True)
                current = inbox(settings, stopped, approve, progress,
                                entry='dialogs', return_to='dialogs')
                if adaptive:polling.record(current)
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
                resource_event('inbox',current)
                # A peer can reply while we are in another chat. Rescan from
                # the list with fresh journal targets BEFORE sleeping/profiles.
                # Only productive passes drain again; stale handled headers are filtered before open.
                # v1.3.88: "productive" means the pass actually advanced dialog
                # work - a reply was submitted, an outgoing was observed, a
                # genuinely NEW incoming message was read, or a contact was
                # forwarded. A pass that only OPENED rows and deliberately left
                # them without an answer (a globally blocked chat, an AI/history
                # deferral, a manual /num silence) is NOT productive: the same
                # scan would find exactly the same rows again, and counting it
                # as work kept the monitor rechecking the inbox forever instead
                # of moving on to the profile search - the reported «когда все
                # чаты прочитаны, не отвеченный просто заходит в чат постоянно и
                # выходит по кругу, а анкеты не ищутся». Unproductive passes now
                # fall through to the profile batch / idle wait below.
                productive = any(current.get(key, 0) > 0 for key in (
                    'submission_calls', 'new_incoming_messages', 'outgoing_observed', 'contacts_forwarded'))
                active = current.get('dialogs_processed', 0) > 0 and productive
                profile_due = mode == 'full' and clock() >= next_profiles
                # MuMu drains until a fresh pass finds no eligible work, even
                # across the old profile deadline. Deferred/review-only inputs
                # are excluded by durable input marks/cooldowns, not called answered.
                if active and ((continuous and mode == 'full') or immediate_passes < 3):
                    immediate_passes += 1
                    out['immediate_rechecks'] += 1
                    out.update(status='checking',reason='drain-incoming')
                    publish()
                    continue
                if mode == 'full' and (continuous or profile_due):
                    # Only between completed inbox passes; never overlap device work
                    # or reset greeting reservations/profile/city history.
                    if continuous and not profile_due:out['early_profile_batches'] += 1
                    out.update(status='working',reason='next-profile-batch',profile_next_in_seconds=0)
                    progress('Доступные диалоги обработаны → поиск новых анкет. Отложенные чаты сохранены.')
                    publish()
                    phase = 'search-screen-not-verified'
                    navigate('return', 'dialogs')
                    check_stop()
                    phase = 'profile-repeat-stopped'
                    out.update(dialogs_verified=False, ui_may_remain_open=True)
                    batch = repeat(settings, stopped, approve, progress, mode='profiles',
                                   fresh_session=True, lock=nullcontext)
                    out['last_profile_run'] = batch
                    out['last_preparation_failure']=run_preparation.from_report(batch)
                    check_stop()
                    if batch['status'] == 'paused':
                        raise StateError('profile-pass-paused')
                    if batch['status'] != 'completed':
                        raise StateError('profile-pass-stopped')
                    if batch.get('report_name') is None:
                        raise StateError('report-write-failed')
                    resource_event('profiles',batch)
                    out['profile_batches_completed'] += 1
                    phase = 'dialog-list-not-verified'
                    navigate('list', 'search')
                    next_profiles = clock() + settings.profile_interval
                    immediate_passes = 0
                    # No idle delay between the profile batch and inbox.
                    continue
                out['profile_next_in_seconds'] = math.ceil(max(0, next_profiles-clock())) if mode == 'full' else None
                out.update(status='waiting', reason='next-inbox-pass')
                publish()  # A failed report always stops further device work.
                phase = 'monitor-check-stopped'
                delay = min(settings.reply_interval, max(0.01, next_profiles-clock())) if mode == 'full' and not active else settings.reply_interval
                if adaptive:
                    # The adaptive schedule owns the whole wait: hot drains stay
                    # at the fast 2s recheck, while the idle wait is jittered so
                    # the MuMu worker fleet does not resynchronize its polling
                    # into one wave against the shared pooler/AI backend.
                    delay = polling.delay(delay)
                progress(summary(out) + f' Следующая проверка через {delay:g} сек.')
                immediate_passes = 0
                if wait(delay):
                    out.update(status='cancelled', reason='cancelled')
                    break
    except Exception as error:
        prepared=run_preparation.clean(getattr(error,'_dvk_preparation',None))
        if prepared:
            out['last_preparation_failure']=prepared
        elif phase=='inbox-pass-stopped' and not out.get('last_pass'):
            out['last_preparation_failure']=run_preparation.record(error,'run-inbox')
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
    if terminal_notifications and settings.errors_enabled and out['status'] in ('stopped', 'paused'):
        from assistant_error_notify import notify
        try:
            out['error_notification'] = (notify if alert is None else alert)(out)
            if out['error_notification'] not in ('accepted', 'unknown', 'not-configured', 'not-needed'):
                out['error_notification'] = 'unknown'
        except Exception:
            out['error_notification'] = 'unknown'
        if alert is None or json_alert is not None:
            from assistant_error_notify import notify_json
            try:
                result = (notify_json if json_alert is None else json_alert)(out)
                out['error_json_notification'] = result if result in ('accepted','unknown','not-configured','not-needed') else 'unknown'
            except Exception:
                out['error_json_notification'] = 'unknown'
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
        deferred = (result.get('last_pass') or {}).get('history_deferred',0)
        cooling = (result.get('last_pass') or {}).get('history_cooldown_skipped',0)
        if deferred or cooling:
            text += f' • ждут загрузки истории {max(deferred,cooling)}'
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
    from startup_failure import message as failure_message
    from navigation_root_diagnostic import message as root_message
    owner_detail=('Этот аккаунт закреплён за другой установкой или портом. Автоматический перенос журналов запрещён.'
                  if 'account-owned-by-other-scope' in codes else None)
    detail = owner_detail or run_preparation.message(result) or root_message(result.get('last_navigation')) or failure_message(result.get('last_navigation_failure'))
    text=('Пауза' if status=='paused' else 'Ошибка')+' • '+reason
    if detail:
        text += '\n' + detail
    notification=result.get('error_notification')
    if notification=='accepted':
        text+=' • причина передана в TG'
    elif notification in ('unknown','not-configured'):
        text+=' • TG не подтверждён'
    return text+'\nПроверь экран. Отчёт: last-monitor.json'
