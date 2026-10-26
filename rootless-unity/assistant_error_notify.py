"""One terminal-run error alert. Authored categories only, never exception bodies."""
from groq_reply import ERRORS as GROQ_ERRORS
from dialog_browser import ERRORS as NAV_ERRORS, PHASES as NAV_PHASES, CHECKPOINTS as NAV_CHECKPOINTS, SELECTION as NAV_SELECTION
from chat_batch import ERRORS as PROFILE_ERRORS
from assistant_failure import CODES as HOST_ERRORS, CHECKPOINTS as HOST_CHECKPOINTS
import telegram_notify
from startup_failure import ERRORS as STARTUP_ERRORS, message as failure_message
import run_preparation
from one_chat_probe import ERRORS as READ_ERRORS
from search_city import ERRORS as CITY_ERRORS

KNOWN = {'account-owned-by-other-scope','city-claim-changed','profile-authorization-pending','profile-authorization-missing','profile-authorization-failed','profile-script-unavailable'} | CITY_ERRORS | READ_ERRORS | GROQ_ERRORS | NAV_ERRORS | PROFILE_ERRORS | HOST_ERRORS | STARTUP_ERRORS | run_preparation.ERRORS | {'initialization-failed','chat-input-disabled','contact-name-required','profile-return-not-verified','peer-contact-blocked','send-setup-unavailable','send-preflight-deferred','recovery-check-stopped', 'profile-recovery-limit'} | {'history-not-ready','history-snapshot-too-large','contact-clarification-sent', 'contact-followup-sent', 'history-loading-timeout','history-read-budget-timeout','between-profile-inbox-stopped',
    'send-native-check-failed', 'send-device-check-failed', 'send-validation-failed',
    'settings-check-stopped', 'device-busy-or-monitor-check-stopped', 'initial-pass-stopped',
    'search-screen-not-verified', 'dialog-list-not-verified', 'initial-pass-paused',
    'inbox-pass-stopped', 'monitor-check-stopped', 'report-write-failed', 'profile-pass-stopped',
    'profile-pass-paused', 'profile-repeat-stopped', 'message-not-approved', 'dialog-needs-review',
    'manual-review', 'telegram-outcome-unknown', 'contact-payload-blocked', 'telegram-disabled',
    'chat-check-stopped','navigation-check-stopped','unrecognized-diagnostic-code','bound-chat-read-failed', 'snapshot-validation-failed', 'binding-or-history-check-stopped',
    'send-outcome-unknown', 'outgoing-not-observed', 'return-not-verified', 'city-not-verified',
    'city-pool-exhausted', 'city-reservation-unresolved', 'city-no-alternative', 'search-cycle-limit', 'profile-scan-limit', 'profile-check-stopped',
    'device-or-journal-check-stopped', 'inbox-not-finished', 'profiles-not-finished',
    'guided-contact-history-changed', 'contact-protection-failed', 'contact-payload-invalid',
    'contact-limit-exceeded', 'guided-binding-not-authorized', 'guided-outgoing-not-verified',
    'reply-selection-not-verified', 'unread-selection-not-verified', 'untracked-dialog', 'changed-dialog', 'navigation-stopped',
    'history-changed-during-approval', 'greeting-not-verified', 'submission-unknown',
    'start-before-peer-reply', 'guided-binding-changed', 'guided-history-not-verified',
    'guided-consent-required', 'legacy-reservation-present'}


def reasons(report):
    result = []
    def visit(value, depth=0):
        if not isinstance(value, dict) or depth > 5:
            return
        # Completed sub-passes contain historical warnings, not the cause of
        # this terminal stop. Keep their AI failures in a separate section.
        status = value.get('status')
        if isinstance(status, str) and (status.endswith('-completed') or status == 'completed'):
            return
        for k in ('reason', 'error', 'failure_point', 'last_error', 'host_failure'):
            v = value.get(k)
            if isinstance(v, str):
                v = v[5:] if v.startswith('chat-') else v
                if v in KNOWN and v not in ('none', 'cancelled') and v not in result:
                    result.append(v)
        for key in ('recovery_failure','last_pass', 'initial_run', 'last_profile_run', 'inbox', 'profiles',
                    'last_navigation', 'last_navigation_failure', 'last_preparation_failure', 'preparation_failure', 'last_city_navigation', 'last_chat_diagnostics', 'last_read_failure'):
            visit(value.get(key), depth+1)
        for v in (value.get('outcomes') or {}):
            if v in KNOWN and v not in result:
                result.append(v)
    visit(report)
    return result[:6] or ['monitor-check-stopped']


def ai_warnings(report):
    """Closed historical AI availability categories; no raw errors or key data."""
    result = []
    def visit(value, depth=0):
        if not isinstance(value, dict) or depth > 5:
            return
        failures = value.get('ai_key_failures')
        if isinstance(failures, list):
            for code in failures:
                if isinstance(code, str) and code in GROQ_ERRORS and code not in result:
                    result.append(code)
        for key in ('initial_run', 'last_pass', 'last_profile_run', 'inbox', 'profiles'):
            visit(value.get(key), depth+1)
    visit(report)
    return result[:4]


def notify(report, *, loader=telegram_notify.load, sender=telegram_notify.send):
    if report.get('status') not in ('stopped', 'paused'):
        return 'not-needed'
    try:
        token, chat = loader()
    except Exception:
        return 'not-configured'
    from navigation_root_diagnostic import message as root_message
    detail = run_preparation.message(report) or root_message(report.get('last_navigation')) or failure_message(report.get('last_navigation_failure'))
    warnings = ai_warnings(report)
    message = ('⚠️ DvkAssistant: цикл ' + ('на паузе' if report['status'] == 'paused' else 'остановлен') +
               '.\n' + ((detail + '\n') if detail else '') + 'Причина: ' + ', '.join(reasons(report)) +
               (('\nПредупреждения ИИ (отдельно): ' + ', '.join(warnings)) if warnings else '') +
               '\nОтчёт: last-monitor.json. Неизвестные отправки не повторяются.')
    try:
        return 'accepted' if sender(token, chat, message) is True else 'unknown'
    except Exception:
        return 'unknown'  # No retry: Telegram may have accepted the first request.


def notify_isolated(report, *, loader=telegram_notify.load, sender=telegram_notify.send):
    """One bounded alert per pass with newly isolated chats; no IDs or message text."""
    from assistant_inbox import ISOLATE
    codes = sorted(k for k, v in report.get('isolated_reasons', {}).items()
                   if k in ISOLATE and type(v) is int and v > 0)
    if not codes:
        return 'not-needed'
    try:
        token, chat = loader()
    except Exception:
        return 'not-configured'
    from assistant_chain import REVIEW_CAUSES
    causes = sorted(k for k, v in report.get('review_causes', {}).items()
                    if k in REVIEW_CAUSES and type(v) is int and v > 0)
    message = ('⚠️ DvkAssistant: проблемный диалог оставлен на проверку. '
               'Остальные диалоги продолжаются после проверки возврата.\nПричина: ' +
               ', '.join(codes) + (('\nУточнение: ' + ', '.join(causes)) if causes else '') + '\nОтчёт: last-monitor.json. Неизвестная отправка не повторяется.')
    try:
        return 'accepted' if sender(token, chat, message) is True else 'unknown'
    except Exception:
        return 'unknown'


def diagnostic_json(report):
    """Closed diagnostic projection, not arbitrary report/exception export.

    Local full reports remain untouched. Cloud JSON excludes message content,
    identities, cities, paths, credentials and raw exceptions, even if inserted
    into an unexpected nested report field.
    """
    import json
    import re
    from chat_state_probe import READ_STEPS, WAIT_REASONS, CHECKPOINTS
    structures = {'send_failure_events','send_transport_failure','recovery_failure','initial_run','last_profile_run','last_pass','inbox','profiles',
        'last_city_recovery','root_probe','last_profile_diagnostics','last_city_navigation','last_navigation','last_navigation_failure',
        'last_preparation_failure','preparation_failure','last_chat_diagnostics','last_read_failure','photo_failure','diagnostic','recovery_events','ai_failures'}
    numbers = {'profile_source_bytes','profile_history_count','profile_setup_ms','state_samples','city_visible_rows','city_total_rows','city_scan_samples','city_matches','city_read_budget_retries','city_transition_overruns','send_snapshot_refreshes','photo_read_retries','read_retries','send_preflight_retries','recovery_attempts','frames','managed_calls','samples','message_count','profile_ready_waits','greeting_frame_splits',
        'setup_retry_attempts','profile_read_budget_retries','city_read_budget_retries','city_queries_started','city_candidates_skipped',
        'city_result_waits','city_query_text_returns','city_query_returns','profiles_checked','qualified_profiles',
        'skipped_unready_chat','read_recovery_limit','consecutive_read_recoveries','search_cycles','profile_limit','send_attempts',
        'entry_read_budget_retries','observation_budget_retries','back_budget_retries','rows_scanned','scan_batches','read_rows_skipped','handlers_returned','sequence','passes_completed','profile_batches_completed','history_deferred','isolated_dialogs'}
    from assistant_stage_timing import FIELDS as TIMING_FIELDS
    numbers |= TIMING_FIELDS
    flags = {'profile_cycle_no_send_verified','state_verified','city_open_attempted','city_open_completed','city_query_attempted','city_query_text_completed','city_query_completed','city_result_verified','city_form_verified','city_verified','online_verified','saved_receipt_only','input_disabled_verified','history_wait_exhausted','history_budget_exhausted','history_snapshot_oversized','post_send_checked','send_no_invocation_verified','profile_script_executed','submission_attempted','submission_returned','contact_review_reconciled','send_attempted','send_handler_returned','send_attempts_unknown','return_verified','search_verified',
        'open_attempted','open_completed','chat_open_attempted','chat_open_completed','chat_identity_verified',
        'chat_back_attempted','chat_back_completed','chat_return_verified','profile_read_skipped',
        'apply_attempted','apply_completed','city_form_verified','city_select_attempted','city_select_completed',
        'action_attempted','action_completed','entry_verified','selection_verified','dialogs_verified','destination_verified','cleanup_failed','continue_work','cooldown'}
    labels = {'send_host_failure','city_checkpoint','city_prepare','city_identity','photo_checkpoint','last_send_failure','status','reason','error','phase','stage','wait_reason','read_checkpoint','last_error',
        'scalar_checkpoint','scalar_state','identity_checkpoint','message_kind','message_direction','error_type','adb_check','adb_reason','host_failure','host_checkpoint','failure_point','profile_read_skip_reason','action','chat_return_route','notification','metadata_checkpoint','selection_checkpoint','provider','code','step','frame_source','validation_reason'}
    from groq_reply import VALIDATION_REASONS
    from chat_limits import MAX_MESSAGES
    from one_chat_send import ERRORS as SEND_ERRORS
    from one_chat_probe import SCALAR_CHECKPOINTS,SCALAR_STATES,IDENTITY_CHECKPOINTS
    from startup_failure import STAGES,TYPES,ADB_CHECKS
    from search_city import CHECKPOINTS as CITY_CHECKPOINTS,PREPARE_STEPS as CITY_PREPARE,IDENTITY as CITY_IDENTITY
    from adb_evidence import REASONS as ADB_REASONS
    codes = CITY_CHECKPOINTS | CITY_PREPARE | CITY_IDENTITY | SEND_ERRORS | SCALAR_CHECKPOINTS | SCALAR_STATES | IDENTITY_CHECKPOINTS | {'ReadStopped','not-read','text','non-text','own','not-own'} | STAGES | TYPES | {'OtherError','StateError','IntegrityError','OperationalError','DatabaseError','AttributeError'} | ADB_CHECKS | ADB_REASONS | KNOWN | HOST_CHECKPOINTS | {'chat-'+code for code in KNOWN} | NAV_PHASES | NAV_CHECKPOINTS | NAV_SELECTION | set(VALIDATION_REASONS) | set(READ_STEPS) | set(WAIT_REASONS) | set(CHECKPOINTS) | {
        'profile-open-call','profile-noop-check','profile-back-call','profile-after-back','profile-return-check','before-profile-open','reconnecting','reconnected','profile-script-not-created','groq','openrouter','gemini','zai','none','not-needed','accepted','unknown','not-configured','recovered','verified-back-and-skip',
        'stopped','paused','completed','profiles-completed','profiles-stopped','profiles-cancelled',
        'inbox-completed','inbox-stopped','inbox-empty','navigation-ready','navigation-stopped',
        'done','check-chat','prepare-greeting','submit-greeting','close-chat','wait-chat-back','search','profile','wait-return','scan-city',
        'query-city','confirm-profile','wait-profile','wait-chat','wait-city','verify-search','select-city',
        'profile-limit','visible-exhausted','model','last-message','chat-not-actual','history-loading',
        'history-not-loaded','profile-recovery-limit','working','checking','cancelled','recovering','safe-recovery'}
    from uikit_root import STAGES as ROOT_STAGES, STEPS as ROOT_STEPS, SOURCES as ROOT_SOURCES
    codes |= ROOT_STAGES | ROOT_STEPS | set(ROOT_SOURCES) | {'not-observed'}
    flags |= {'api_available','metadata_ready','observer_installed','observed_callback','main_thread_confirmed'}
    numbers |= {'observed_calls'}
    def clean(value, depth=0):
        if not isinstance(value, dict) or depth > 7:
            return {}
        result = {}
        for key, entry in value.items():
            if key in structures:
                if isinstance(entry, dict):
                    # Startup and run preparation have different closed schemas.
                    # Reuse the preparation validator: generic native labels omit
                    # its stages, ConfigError, filename category and reason.
                    prepared = run_preparation.clean(entry) if key in ('preparation_failure', 'last_preparation_failure') else None
                    result[key] = prepared if prepared is not None else clean(entry, depth+1)
                elif key == 'ai_failures' and isinstance(entry, list):
                    result[key] = [clean(e, depth+1) for e in entry[:64] if isinstance(e, dict)]
                elif key in ('recovery_events','send_failure_events') and isinstance(entry, list):
                    result[key] = [clean(e, depth+1) for e in entry[-3:] if isinstance(e, dict)]
            elif key == 'message_slot' and type(entry) is int and -1 <= entry < MAX_MESSAGES:
                result[key] = entry
            elif key in ('key_index','retry_in_seconds') and type(entry) is int and 0 <= entry <= (17 if key == 'key_index' else 86400):
                result[key] = entry
            elif key in numbers and (entry is None or type(entry) is int and 0 <= entry <= 1000000):
                result[key] = entry
            elif key in flags and type(entry) is bool:
                result[key] = entry
            elif key in labels and isinstance(entry, str) and entry in codes:
                result[key] = entry
            elif key in ('reason','error','failure_point','last_error') and isinstance(entry,str):
                result[key] = 'unrecognized-diagnostic-code'
            elif key in ('tool_version','engine_version') and isinstance(entry, str) and re.fullmatch(r'\d{1,2}\.\d{1,2}\.\d{1,2}', entry):
                result[key] = entry
        return result
    return json.dumps(dict(format='dvk-diagnostic-v1', diagnostic=clean(report)), ensure_ascii=False, indent=2).encode('utf-8')


def notify_json(report, *, loader=telegram_notify.load, sender=telegram_notify.send_json_document, recovered=False):
    if recovered:
        if report.get('status') != 'recovered' or report.get('return_verified') is not True or report.get('send_attempted') is not False:
            return 'not-needed'
        caption = ('↩️ DvkAssistant: возврат проверен, проблемная анкета пропущена. ' +
            ('Работа продолжается.' if report.get('continue_work', True) else 'Достигнут лимит восстановлений этого прохода.') +
            ' JSON-диагностика без текста переписки и ключей.')
    elif report.get('status') == 'reconnecting':
        if (report.get('reason')!='profile-script-not-created' or report.get('profile_script_executed') is not False
                or report.get('send_attempted') is not False or report.get('send_handler_returned') is not False):
            return 'not-needed'
        caption = '↻ DvkAssistant: переподключаюсь до запуска скрипта. Анкеты и сообщения не отправлялись в этой попытке; текущий проход сохранён. JSON без переписки и ключей.'
    elif report.get('status') == 'recovering':
        caption = '↻ DvkAssistant: восстанавливаю работу порта. Проблемный чат пропускается только после проверки; неизвестные отправки не повторяются. JSON без переписки и ключей.'
    else:
        if report.get('status') not in ('stopped','paused'):
            return 'not-needed'
        caption = '⚠️ DvkAssistant: JSON-диагностика остановки без текста переписки и ключей. Неизвестные отправки не повторяются.'
        detail = run_preparation.message(report)
        if detail:
            caption += '\n' + detail
    try:
        token, chat = loader()
    except Exception:
        return 'not-configured'
    try:
        return 'accepted' if sender(token, chat, caption, diagnostic_json(report)) is True else 'unknown'
    except Exception:
        return 'unknown'  # One attempt only, including transport/timeout errors.


def notify_recovery(event):
    return notify_json(event, recovered=True)
