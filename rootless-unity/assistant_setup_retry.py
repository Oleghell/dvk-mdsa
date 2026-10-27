"""MuMu profile compile-transport retry BEFORE any script load or UI action.

This is not a general native retry. Unknown load/root/send outcomes, changed
boot, authorization, storage and protocol failures keep the normal hard gates.
"""
import json
import time
from pathlib import Path

REPORT='last-profile-connection.json'
MAX_SETUP_ATTEMPTS=6


def retryable_profile_setup(error):
    from startup_failure import clean
    value=clean(getattr(error,'_dvk_failure',None))
    if getattr(error,'_dvk_profile_not_executed',False) is not True or value is None:
        return False
    if value['stage']=='script-create':
        return (value['error']=='startup-script-create-failed'
            and value['error_type'] in {'TransportError','ServerNotRunningError','TimedOutError'})
    if value['stage']=='profile-history-upload':
        # Reports 365-373: the script loaded and passed the runtime check, but
        # was destroyed during the history-upload RPC (Frida raises
        # InvalidOperationError when the script is gone). root() was never
        # called: no navigation, no UI action, no authorization thread, no
        # journal write — the same provably pre-execution state as a failed
        # create. Authored StateError (bad journal data) stays non-retryable.
        return (value['error']=='startup-profile-history-upload-failed'
            and value['error_type'] in {'TransportError','ServerNotRunningError','TimedOutError','InvalidOperationError'})
    return False


def write_report(value):
    from assistant_store import data_directory
    folder=Path(data_directory());folder.mkdir(parents=True,exist_ok=True)
    path=folder/REPORT;temporary=path.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class SetupRetry:
    def __init__(self,settings,stopped,progress=lambda _:None,*,write=write_report,
                 notify=None,clock=time.monotonic,wait=None):
        self.settings,self.stopped,self.progress=settings,stopped,progress
        self.write,self.clock=write,clock
        self.wait=stopped.wait if wait is None else wait
        self.notify=notify;self.alerted=False;self.attempts=0;self.last_failure=None;self.setup_metrics={}

    def report(self,status,delay=0):
        from mumu_version import VERSION
        return dict(tool_version=VERSION,status=status,reason='profile-script-not-created',
            setup_retry_attempts=min(self.attempts,1000000),retry_in_seconds=delay,
            profile_script_executed=False,send_attempted=False,send_handler_returned=False,
            last_preparation_failure=self.last_failure,**self.setup_metrics)

    def __call__(self,error,attempt,delay):
        from startup_failure import clean
        from assistant_pause import boundary
        if not retryable_profile_setup(error) or type(attempt) is not int or attempt<1 or type(delay) is not int or delay!=min(30,2**min(attempt-1,5)):
            raise ValueError('Unverified pre-execution retry')
        self.attempts=attempt;self.last_failure=clean(error._dvk_failure)
        self.setup_metrics={key:value for key in ('profile_source_bytes','profile_history_count','profile_setup_ms')
            if type(value:=getattr(error,'_dvk_'+key,None)) is int and 0<=value<=1000000}
        if attempt>=MAX_SETUP_ATTEMPTS:
            from assistant_store import StateError
            self.progress('Связь недоступна после 6 попыток • native-проход не запускался. Порт остановлен, журналы сохранены.')
            blocked=StateError('profile-script-unavailable')
            blocked._dvk_profile_not_executed=True
            blocked._dvk_failure=self.last_failure
            raise blocked
        self.write(self.report('reconnecting',delay))
        self.progress(f'Связь • скрипт ещё не запущен. Повтор подключения через {delay} с; проход сохранён.')
        # One attempt after three failures per continuous setup episode, not one
        # document per retry. Unknown Telegram delivery is never retried.
        if attempt>=3 and not self.alerted and getattr(self.settings,'errors_enabled',False):
            self.alerted=True
            try:
                from assistant_error_notify import notify_json
                (self.notify or notify_json)(self.report('reconnecting',delay))
            except Exception:pass
        until=self.clock()+delay
        while not self.stopped.is_set():
            boundary(self.stopped)
            if self.stopped.is_set():return True
            remaining=until-self.clock()
            if remaining<=0:return False
            if self.wait(min(.1,remaining)):return True
        return True

    def completed(self):
        if self.attempts:
            self.write(self.report('reconnected'))
            self.progress('Связь восстановлена • продолжаю текущую порцию анкет без сброса журнала.')
