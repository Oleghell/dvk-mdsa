"""One terminal-run error alert. Authored categories only, never exception bodies."""
from groq_reply import ERRORS as GROQ_ERRORS
from dialog_browser import ERRORS as NAV_ERRORS
import telegram_notify

KNOWN = GROQ_ERRORS | NAV_ERRORS | {
    'settings-check-stopped', 'device-busy-or-monitor-check-stopped', 'initial-pass-stopped',
    'search-screen-not-verified', 'dialog-list-not-verified', 'initial-pass-paused',
    'inbox-pass-stopped', 'monitor-check-stopped', 'report-write-failed', 'profile-pass-stopped',
    'profile-pass-paused', 'profile-repeat-stopped', 'message-not-approved', 'dialog-needs-review',
    'manual-review', 'telegram-outcome-unknown', 'contact-payload-blocked', 'telegram-disabled',
    'bound-chat-read-failed', 'snapshot-validation-failed', 'binding-or-history-check-stopped',
    'send-outcome-unknown', 'outgoing-not-observed', 'return-not-verified', 'city-not-verified',
    'city-no-alternative', 'search-cycle-limit', 'profile-scan-limit', 'profile-check-stopped',
    'device-or-journal-check-stopped', 'inbox-not-finished', 'profiles-not-finished',
    'guided-contact-history-changed', 'contact-protection-failed', 'contact-payload-invalid',
    'contact-limit-exceeded', 'guided-binding-not-authorized', 'guided-outgoing-not-verified',
    'unread-selection-not-verified', 'untracked-dialog', 'changed-dialog', 'navigation-stopped',
    'history-changed-during-approval', 'greeting-not-verified', 'submission-unknown',
    'start-before-peer-reply', 'guided-binding-changed', 'guided-history-not-verified',
    'guided-consent-required', 'legacy-reservation-present'}


def reasons(report):
    result = []
    def visit(value, depth=0):
        if not isinstance(value, dict) or depth > 5:
            return
        for k in ('reason', 'error', 'failure_point', 'last_error'):
            v = value.get(k)
            if isinstance(v, str):
                v = v[5:] if v.startswith('chat-') else v
                if v in KNOWN and v not in ('none', 'cancelled') and v not in result:
                    result.append(v)
        for key in ('last_pass', 'initial_run', 'last_profile_run', 'inbox', 'profiles',
                    'last_navigation', 'last_city_navigation', 'last_chat_diagnostics', 'last_read_failure'):
            visit(value.get(key), depth+1)
        for v in (value.get('outcomes') or {}):
            if v in KNOWN and v not in result:
                result.append(v)
    visit(report)
    return result[:6] or ['monitor-check-stopped']


def notify(report, *, loader=telegram_notify.load, sender=telegram_notify.send):
    if report.get('status') not in ('stopped', 'paused'):
        return 'not-needed'
    try:
        token, chat = loader()
    except Exception:
        return 'not-configured'
    message = ('⚠️ DvkAssistant: цикл ' + ('на паузе' if report['status'] == 'paused' else 'остановлен') +
               '.\nПричина: ' + ', '.join(reasons(report)) +
               '\nОтчёт: last-monitor.json. Неизвестные отправки не повторяются.')
    try:
        return 'accepted' if sender(token, chat, message) is True else 'unknown'
    except Exception:
        return 'unknown'  # No retry: Telegram may have accepted the first request.
