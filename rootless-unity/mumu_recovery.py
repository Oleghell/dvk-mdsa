"""Port-local supervisor. Revalidate UI; quarantine before one exact-chat Back.

Never resets journals, replays a send or retries an unknown Back. Configuration,
identity, journal and explicit approval failures are not recoverable here.
"""

RETRY_CODES={'frame-budget','call-limit','frame-limit','transition-timeout','callback-timeout',
    'history-loading-timeout','history-read-budget-timeout','history-not-ready','profile-recovery-limit',
    'selection-unavailable','screen-not-ready','wrong-screen','unexpected-screen','read-stopped',
    'native-transport-error','native-operation-cancelled','native-script-error','native-state-error',
    'native-process-unavailable','transport-error','device-timeout','readonly-list-updated'}
BLOCK_CODES={'city-claim-changed','profile-authorization-pending','profile-authorization-missing','profile-authorization-failed','profile-script-unavailable','unverified-host-failure','identity-changed','identity-not-bound','untracked-dialog','changed-dialog',
    'report-write-failed','message-not-approved','greeting-not-approved','cancelled',
    'journal-busy','journal-locked','journal-readonly','journal-storage-full','journal-io-error',
    'journal-corrupt','journal-error','resource-missing','resource-access-denied'}

# Reports WHm3 (v1.3.71): a screen no fixed operation could verify kept the
# port in "recovering" forever - repair() returned False every round while
# the user could have resolved it with one or two Esc presses (the assistant
# opens chats ON TOP of a profile card, so a Back lands on the profile, which
# the old fixed navigation could not close). The navigation now performs that
# bounded Esc press itself, and supervision is bounded as well: after this many
# verified-connection rounds the port stops with an explicit reason instead of
# spinning silently, and the user can resume it manually from the window.
MAX_RECOVERY_ROUNDS = 8
# A transport failure usually means the emulator is restarting; it gets a far
# more generous bound than screen-recovery rounds, but never an infinite one.
MAX_TRANSPORT_FAILURES = 30


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
        from assistant_scan_retry import readonly_list_changed
        scan=readonly_list_changed('open',dict(state='stopped',identity=None,diagnostic=value.get('last_navigation')))
        if scan:codes.add('readonly-list-updated')
        if value.get('host_failure') in {'internal-error','internal-contract-error','state-check-failed','validation-failed','host-io-error'}:
            children=[value.get(k) for k in ('last_navigation_failure','last_preparation_failure','last_navigation','last_profile_diagnostics')]
            if value.get('host_checkpoint')=='city-navigation' and value.get('reason')=='city-not-verified':
                children.append(value.get('last_city_navigation'))
            current_transport=any(recoverable_adb(child) for child in children)
            current_navigation=any(type(child) is dict and child.get('stage')=='navigation-stopped' and child.get('error') in RETRY_CODES for child in children)
            from one_chat_device import verified_early_wrong_screen,verified_sample_wrong_screen
            current_read=(value.get('host_checkpoint')=='chat-read'
                and value.get('error_type')=='ReadStopped'
                and value.get('failure_point')=='bound-chat-read-failed'
                and (verified_early_wrong_screen(value.get('last_read_failure')) or verified_sample_wrong_screen(value.get('last_read_failure'))))
            if not (current_transport or current_navigation or scan or current_read):codes.add('unverified-host-failure')
        if recoverable_adb(value):codes.add('native-transport-error')
        for key in ('reason','error','host_failure'):
            v=value.get(key)
            if type(v) is str:codes.add(v)
        for key in ('inbox','profiles','last_navigation','last_navigation_failure','last_preparation_failure','last_profile_diagnostics','last_read_failure','last_chat_diagnostics','last_city_navigation'):
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
            blocked=StateError('Recovery device identity not verified')
            if evidence:blocked._dvk_failure=evidence
            raise blocked from None
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


def resume_recheck(recheck, stopped, progress, wait):
    """Read-only reconnect after a long pause; never retry UI/send/identity failures."""
    from assistant_pause import boundary
    from startup_failure import clean,recoverable_adb
    attempts=0
    while not stopped.is_set():
        boundary(stopped,restart=False)
        if stopped.is_set():return False
        try:
            recheck()
            return True
        except Exception as error:
            evidence=clean(getattr(error,'_dvk_failure',None))
            transient={'connection-refused','connection-timeout','device-offline','device-not-found','command-timeout'}
            if not (isinstance(error,(ConnectionError,TimeoutError)) or recoverable_adb(evidence)
                    or evidence and evidence.get('adb_reason') in transient):
                raise
            attempts+=1
            progress('Продолжение порта • восстанавливаю связь после паузы; отправки не повторяются.')
            if wait(min(30,2**min(attempts-1,5))):return False
    return False


def run(settings,stopped,approve,progress=lambda _:None,*,mode='full',fresh_session=False,
        write=None,continuous=True,monitor=None,repair=None,wait=None,json_alert=None,recheck=lambda:None):
    from assistant_monitor import run as engine,write_report,REPORT
    from assistant_store import Store
    from assistant_error_notify import notify_json
    from assistant_pause import boundary,PortResumed
    monitor=monitor or engine;write=write or write_report;wait=wait or stopped.wait
    repair=repair or Repair(settings,stopped,Store(),recheck=recheck)
    json_alert=json_alert or notify_json
    recoveries=0;first=True
    while not stopped.is_set():
        entered=False
        try:
            boundary(stopped)
            entered=True
            out=monitor(settings,stopped,approve,progress,mode=mode if first or mode!='new' else 'full',fresh_session=fresh_session if first else False,
                        write=write,continuous=continuous,terminal_notifications=False)
        except PortResumed:
            if stopped.is_set():break
            # Keep original endpoint/boot locks and journals. The new engine
            # pass verifies navigation again; never perform a speculative Back.
            if not resume_recheck(recheck,stopped,progress,wait):break
            progress('Порт продолжен • проверяю текущий экран; отправки не повторяются.')
            if entered:first=False
            continue
        first=False
        boundary(stopped,restart=False)
        if stopped.is_set():return dict(out,status='cancelled',reason='cancelled')
        if out.get('status')=='cancelled':return out
        can_recover=recoverable(out)
        if settings.errors_enabled and out.get('status')=='stopped':
            try:json_alert(dict(out,status='recovering') if can_recover else out)
            except Exception:pass # no duplicate retry of a Telegram document
        if not can_recover:return out
        recoveries+=1
        state=dict(out,status='recovering',reason='safe-recovery',recovery_attempts=recoveries)
        if write(state)!=REPORT:raise OSError('Recovery report was not saved')
        progress('Восстановление • проблемный чат будет пропущен; неизвестные отправки не повторяются.')
        rounds=0
        transport_failures=0
        while not stopped.is_set():
            boundary(stopped,restart=False)
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
                # A transport/connection failure does not consume screen-recovery
                # rounds: the emulator may be restarting. Identity and journal
                # problems already returned above; the transport class still has
                # its own generous bound so supervision never spins silently.
                transport_failures+=1
                if transport_failures>=MAX_TRANSPORT_FAILURES:
                    out=dict(out,status='stopped',reason='recovery-unfinished',
                        recovery_failure=dict(host_failure='native-transport-error',transport_failures=transport_failures))
                    if write(out)!=REPORT:raise OSError('Recovery report was not saved')
                    if settings.errors_enabled:
                        try:json_alert(out)
                        except Exception:pass
                    progress('Восстановление не удалось • порт остановлен: нет связи с MuMu. '
                             'Возобнови его кнопкой в окне программы.')
                    return out
                progress('Восстановление • нет связи с MuMu. Проверяю подключение; другие порты работают.')
                if wait(min(30,2**min(transport_failures,5))):break
                continue
            rounds+=1
            if rounds>=MAX_RECOVERY_ROUNDS:
                # Bounded supervision: never spin silently. The port stops with
                # an explicit reason; the user can resume it manually.
                out=dict(out,status='stopped',reason='recovery-unfinished',
                    recovery_failure=dict(host_failure='state-check-failed',recovery_rounds=rounds))
                if write(out)!=REPORT:raise OSError('Recovery report was not saved')
                if settings.errors_enabled:
                    try:json_alert(out)
                    except Exception:pass
                progress('Восстановление не удалось • порт остановлен после '+str(rounds)+
                         ' проверок экрана. Возобнови его кнопкой в окне программы.')
                return out
            progress('Восстановление • экран ещё не подтверждён. Проверяю связь; другие порты работают.')
            # Error-only cancellable backoff, never a normal idle delay or API quota bypass.
            if wait(min(30,2**min(rounds,5))):break
        if stopped.is_set():return dict(state,status='cancelled',reason='cancelled')
        progress('Возврат подтверждён • продолжаю с другими диалогами и анкетами.')
    return dict(status='cancelled',reason='cancelled')
