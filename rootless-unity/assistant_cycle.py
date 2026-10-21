"""Bounded no-send route check; this is NOT the complete automated cycle."""
import json
from assistant_lock import operation_lock
from assistant_store import data_directory
from dialog_navigation import VERSION, run as run_route, validate


def write_navigation_report(report):
    directory=data_directory();directory.mkdir(parents=True,exist_ok=True)
    target=directory/'messages-navigation-check.json'
    temporary=target.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(report,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def start(settings, stopped, progress=lambda text: None):
    if stopped.is_set():
        return dict(status='cancelled',reason='cancelled',live_cycle_available=False)
    with operation_lock():
        progress('Проверяю переход: анкеты → личка → обратно. Сообщения и Telegram не используются.')
        report=dict(tool_version=VERSION,mode='search-dialog-list-search-check',live_cycle_available=False,
                    messages_sent=0,telegram_used=False,chat_content_read=False,personal_data_exported=False,
                    device_scope='MuMu-4-only',ui_actions_may_have_occurred=True)
        try:
            result=validate(run_route(settings.adb,settings.folder,stopped.is_set))
            n=result['navigation']
            ready=n['stage']=='navigation-ready' and not stopped.is_set()
            reason='none' if ready else 'cancelled' if stopped.is_set() else n['error'] if n['error']!='none' else result['stage']
            report.update(status='route-ready' if ready else 'route-stopped',reason=reason,
                          navigation=n,root_stage=result['stage'])
        except Exception:
            # Native/ADB/Frida errors can embed paths or secrets. No raw exception
            # text, return values, tokens or private snapshots enter this report.
            ready=False
            reason='cancelled' if stopped.is_set() else 'device-preflight-or-transport-stopped'
            report.update(status='route-stopped',reason=reason)
        path=write_navigation_report(report)
    return dict(status='cancelled' if stopped.is_set() else 'dialog-route-ready' if ready else 'blocked',
                reason=reason,live_cycle_available=False,report_name=path.name)
