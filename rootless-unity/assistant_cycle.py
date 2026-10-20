"""Readiness gate for the requested search -> dialogs -> next-city cycle.

There is no verified Android chat-list navigator in this repository yet. Do not
silently run the former one-open-chat mode or send greetings while replies cannot
be visited. Gather only the missing APK DEFINITIONS before any live action.
"""
from assistant_lock import operation_lock
from dialog_catalog import write_report


def start(settings, stopped, progress=lambda text: None):
    if stopped.is_set():
        return dict(status='cancelled', reason='cancelled', live_cycle_available=False)
    with operation_lock():
        progress('Проверяю готовность общего цикла. Собираю определения лички без нажатий и сообщений.')
        report, path = write_report(settings.folder, stopped.is_set)
    if stopped.is_set():
        return dict(status='cancelled', reason='cancelled', live_cycle_available=False)
    if report['status'] != 'catalog-ready':
        return dict(status='blocked', reason=report['reason'], live_cycle_available=False)
    return dict(status='navigation-required', reason='verified-dialog-navigator-missing',
                live_cycle_available=False, report_name=path.name)
