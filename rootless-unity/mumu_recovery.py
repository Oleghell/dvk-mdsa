"""Port-local supervisor. Revalidate UI; quarantine before one exact-chat Back.

Never resets journals, replays a send or retries an unknown Back. Configuration,
identity, journal and explicit approval failures are not recoverable here.
"""

RETRY_CODES={'frame-budget','call-limit','frame-limit','transition-timeout','callback-timeout',
    'history-loading-timeout','history-read-budget-timeout','history-not-ready','profile-recovery-limit',
    'selection-unavailable','screen-not-ready','wrong-screen','unexpected-screen','read-stopped',
    'native-transport-error','native-operation-cancelled','native-script-error','native-state-error',
    'native-process-unavailable','transport-error','device-timeout'}
BLOCK_CODES={'unverified-host-failure','identity-changed','identity-not-bound','untracked-dialog','changed-dialog',
    'report-write-failed','message-not-approved','greeting-not-approved','cancelled',
    'journal-busy','journal-locked','journal-readonly','journal-storage-full','journal-io-error',
    'journal-corrupt','journal-error','resource-missing','resource-access-denied'}


def recoverable(report):
    if report.get('status')!='stopped':return False
    reason=report.get('reason')
    if reason=='initial-pass-stopped':nodes=[report.get('initial_run')]
    elif reason=='inbox-pass-stopped':nodes=[report.get('last_pass')]
    elif reason in {'profile-pass-stopped','profile-repeat-stopped'}:nodes=[report.get('last_profile_run')]
    else:nodes=[report]
    codes=set()
    def visit(value):
        if type(value) is not dict:return
        if value.get('status') in {'completed','inbox-completed','profiles-completed','inbox-empty'}:return
        from startup_failure import recoverable_adb
        if value.get('host_failure') in {'internal-error','internal-contract-error','state-check-failed','validation-failed','host-io-error'}:
            children=[value.get(k) for k in ('last_navigation_failure','last_preparation_failure','last_navigation','last_profile_diagnostics')]
            current_transport=any(recoverable_adb(child) for child in children)
            current_navigation=any(type(child) is dict and child.get('stage')=='navigation-stopped' and child.get('error') in RETRY_CODES for child in children)
            if not (current_transport or current_navigation):codes.add('unverified-host-failure')
        if recoverable_adb(value):codes.add('native-transport-error')
        for key in ('reason','error','host_failure'):
            v=value.get(key)
            if type(v) is str:codes.add(v)
        for key in ('inbox','profiles','last_navigation','last_navigation_failure','last_preparation_failure','last_profile_diagnostics','last_read_failure','last_chat_diagnostics'):
            visit(value.get(key))
    for node in nodes:visit(node)
    return not bool(codes & BLOCK_CODES) and bool(codes & RETRY_CODES)


class Repair:
    def __init__(self,settings,stopped,store,*,reader=None,navigator=None,recheck=lambda:None):
        from one_chat_device import capture
        from dialog_browser import perform
        self.settings,self.stopped,self.store=settings,stopped,store
        self.reader=reader or capture;self.navigator=navigator or perform
        self.recheck=recheck;self.back_attempts=set()

    def screen(self,operation,**kwargs):
        from assistant_navigation_check import safe_diagnostic
        if self.stopped.is_set():return False
        value=self.navigator(operation,self.settings.adb,self.settings.folder,self.stopped.is_set,**kwargs)
        n=safe_diagnostic(value['diagnostic'])
        target='returned' if operation=='back' else 'dialogs-ready'
        return (value['state']==target and n['stage']=='navigation-ready' and n['error']=='none'
            and n['destination_verified'] is True and n['phase']=='done'
            and (value['identity']==kwargs['expected'] and n['action_completed'] is True if operation=='back' else value['identity'] is None))

    def __call__(self):
        if self.stopped.is_set():return False
        try:self.recheck()
        except Exception as error:
            from assistant_store import StateError
            from startup_failure import clean,recoverable_adb
            evidence=clean(getattr(error,'_dvk_failure',None))
            transient={'connection-refused','connection-timeout','device-offline','device-not-found','command-timeout'}
            if isinstance(error,(ConnectionError,TimeoutError)) or recoverable_adb(evidence) or evidence and evidence.get('adb_reason') in transient:
                raise ConnectionError('Recovery connection not available') from None
            raise StateError('Recovery device identity not verified') from None
        try:
            snapshot=self.reader(self.settings.adb,self.settings.folder,self.stopped.is_set)
        except Exception:
            snapshot=None
        if self.stopped.is_set():return False
        if snapshot is not None:
            from one_chat_send import checked
            from assistant_inbox import InboxChain
            snapshot=checked({k:snapshot[k] for k in ('identity','messages')})
            who=snapshot['identity'];key=tuple(who[k] for k in ('account','peer','chat'))
            # Commit skip BEFORE any UI action. Unknown greeting/reply actions
            # and drafts remain untouched; no reply generator is called here.
            self.store.skip_recovery_peer(who)
            chain=InboxChain(self.store)
            with self.store.connection() as db:
                row=db.execute('SELECT initial_chat,status FROM manual_actions WHERE account=? AND peer=?',(who['account'],who['peer'])).fetchone()
                bound=db.execute('SELECT chat,stage FROM chain_dialogs WHERE account=? AND peer=?',(who['account'],who['peer'])).fetchone()
            if row is not None:
                chain.authorized(who) # changed bindings are NOT guessed/repaired
                if not bound or bound[1] not in ('done','declined','manual-review'):chain.mark_review(who)
            if key in self.back_attempts:return False
            self.back_attempts.add(key) # latch precedes native call, even timeout
            return self.screen('back',expected=who)
        # Unlike startup entry='either', these cannot silently close a chat
        # whose history/identity could not be read and durably skipped.
        for entry in ('dialogs','search'):
            try:
                if self.screen('list',entry=entry):return True
            except Exception:
                pass
        return False


def run(settings,stopped,approve,progress=lambda _:None,*,mode='full',fresh_session=False,
        write=None,continuous=True,monitor=None,repair=None,wait=None,json_alert=None,recheck=lambda:None):
    from assistant_monitor import run as engine,write_report,REPORT
    from assistant_store import Store
    from assistant_error_notify import notify_json
    from assistant_pause import boundary
    monitor=monitor or engine;write=write or write_report;wait=wait or stopped.wait
    repair=repair or Repair(settings,stopped,Store(),recheck=recheck)
    json_alert=json_alert or notify_json
    recoveries=0;first=True
    while not stopped.is_set():
        boundary(stopped)
        out=monitor(settings,stopped,approve,progress,mode=mode,fresh_session=fresh_session if first else False,
                    write=write,continuous=continuous,terminal_notifications=False)
        first=False
        if out.get('status')=='cancelled' or stopped.is_set():return out
        can_recover=recoverable(out)
        if settings.errors_enabled:
            try:json_alert(dict(out,status='recovering') if can_recover else out)
            except Exception:pass # no duplicate retry of a Telegram document
        if not can_recover:return out
        recoveries+=1
        state=dict(out,status='recovering',reason='safe-recovery',recovery_attempts=recoveries)
        if write(state)!=REPORT:raise OSError('Recovery report was not saved')
        progress('Восстановление • проблемный чат будет пропущен; неизвестные отправки не повторяются.')
        failures=0
        while not stopped.is_set():
            boundary(stopped)
            try:
                if repair():break
            except Exception as error:
                # Storage/config/identity errors cannot be hidden by supervision.
                from assistant_failure import category
                if category(error) in {'journal-busy','journal-locked','journal-readonly','journal-storage-full',
                    'journal-io-error','journal-corrupt','journal-error','state-check-failed','resource-missing','resource-access-denied'}:
                    from startup_failure import clean
                    out=dict(out,status='stopped',reason='recovery-check-stopped',
                        recovery_failure=dict(host_failure=category(error)))
                    evidence=clean(getattr(error,'_dvk_failure',None))
                    if evidence:out['recovery_failure']['last_preparation_failure']=evidence
                    if write(out)!=REPORT:raise OSError('Recovery report was not saved')
                    if settings.errors_enabled:
                        try:json_alert(out)
                        except Exception:pass
                    return out
            failures+=1
            progress('Восстановление • экран ещё не подтверждён. Проверяю связь; другие порты работают.')
            # Error-only cancellable backoff, never a normal idle delay or API quota bypass.
            if wait(min(30,2**min(failures,5))):break
        if stopped.is_set():return dict(state,status='cancelled',reason='cancelled')
        progress('Возврат подтверждён • продолжаю с другими диалогами и анкетами.')
    return dict(status='cancelled',reason='cancelled')
