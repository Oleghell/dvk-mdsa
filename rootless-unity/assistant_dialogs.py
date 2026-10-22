"""One bounded pass over visible, journal-authorized dialogs. Not a city cycle.

The shared lock covers navigation, FULL-committed chain reservations, bounded
history snapshots, replies, contact-only notification, and return to search.
"""
from assistant_chain import Chain, TERMINAL, ReviewRequired, step
from assistant_store import Store, StateError
from dialog_browser import VERSION, LIMIT, targets, perform
from one_chat_probe import identity

STATES={'wait-reply','wait-mood','wait-contact','pending-question','pending-contact','pending-clarify','await-outgoing','submission-unknown','manual-review','declined','done','cancelled'}


def journal_targets(chain):
    with chain.store.connection() as db:
        rows=db.execute('''SELECT m.account,m.peer,m.initial_chat,c.chat,c.stage,
          EXISTS(SELECT 1 FROM chain_contact_outbox o WHERE o.chat=c.chat AND o.status='pending')
          FROM manual_actions m LEFT JOIN chain_dialogs c ON c.account=m.account AND c.peer=m.peer
          WHERE m.status!='not-invoked' ORDER BY m.id''').fetchall()
    # Do not silently truncate the journal: a bounded explicit error is safer.
    result=[]
    for account,peer,initial,bound,stage,pending in rows:
        if stage in TERMINAL and not (stage=='done' and pending and chain.contact_notifications):continue
        result.append(dict(account=account,peer=peer,chat=bound if bound is not None else initial))
    return targets(result)


def report():
    return dict(tool_version=VERSION,mode='visible-journal-dialog-reply-pass',status='dialogs-stopped',reason='not-started',
                live_cycle_available=False,city_changes=0,new_greetings=0,all_dialogs_covered=False,
                device_scope='MuMu-4-only',dialog_limit=LIMIT,dialogs_opened=0,dialogs_processed=0,
                reply_submission_calls=0,reply_handler_returns=0,outgoing_observed=0,
                notifications=dict(accepted=0,unknown=0,blocked=0),states={k:0 for k in sorted(STATES)},
                return_verified=False,ui_may_remain_open=False,personal_data_exported=False,
                last_navigation=None,last_reader=None)


def safe_diagnostic(value):
    from assistant_navigation_check import safe_diagnostic as validate_diagnostic
    return validate_diagnostic(value)


def safe_reader_failure(error):
    from one_chat_device import ReadStopped
    from one_chat_probe import diagnostic, ERRORS as reader_errors
    from chat_state_probe import CHECKPOINTS,READ_STEPS,WAIT_REASONS
    if not isinstance(error,ReadStopped) or not isinstance(error.diagnostic,dict):return None
    value=error.diagnostic
    try:
        out=diagnostic(value)
        for key,allowed in [('stage',{'not-attempted','navigation-ready','navigation-stopped','cleanup-failed'}),
                            ('metadata_checkpoint',CHECKPOINTS),('read_checkpoint',READ_STEPS),('wait_reason',WAIT_REASONS)]:
            if value[key] not in allowed:return None
            out[key]=value[key]
        for key,limit in [('frames',180),('managed_calls',6000)]:
            if type(value[key]) is not int or not 0<=value[key]<=limit:return None
            out[key]=value[key]
        code=str(error)
        out['error']=code if code in reader_errors|{'not-ready','cancelled'} else 'reader-stopped'
        return out
    except Exception:return None


def walk(settings,stopped,progress,chain, *, navigator,reader,sender,notifier=None,pause=None):
    out=report()
    remaining=journal_targets(chain)
    if stopped.is_set():out.update(status='dialogs-cancelled',reason='cancelled');return out
    if not remaining:
        out.update(status='dialogs-empty',reason='no-active-journal-bindings')
        return out
    entry='search'
    def call(operation,**kwargs):
        if stopped.is_set():raise StateError('cancelled')
        # Conservatively mark possible navigation BEFORE transport invocation.
        out['ui_may_remain_open']=True
        value=navigator(operation,settings.adb,settings.folder,stopped.is_set,**kwargs)
        if not isinstance(value,dict) or set(value)!={'state','identity','diagnostic'}:raise ValueError('Invalid navigation result')
        out['last_navigation']=safe_diagnostic(value['diagnostic'])
        if value['state']=='stopped':raise StateError('navigation-stopped')
        if out['last_navigation']['stage']!='navigation-ready' or out['last_navigation']['destination_verified'] is not True:raise ValueError('Unverified navigation result')
        permitted={'open':{'opened','exhausted'},'back':{'returned'},'return':{'search-ready'}}[operation]
        if value['state'] not in permitted:raise ValueError('Unexpected navigation result')
        bound=identity(value['identity']) if value['identity'] is not None else None
        if (value['state'] in ('opened','returned'))!=(bound is not None):raise ValueError('Invalid private binding')
        if value['state']=='opened' and not any(x['account']==bound['account'] and x['peer']==bound['peer'] and (int(x['chat'])<=0 or x['chat']==bound['chat']) for x in remaining):raise StateError('untracked-dialog')
        if operation=='back' and bound!=kwargs['expected']:raise StateError('changed-dialog')
        return value
    try:
        for number in range(1,LIMIT+1):
            if stopped.is_set():break
            progress(f'Проверяю диалоги из журнала: {number}/{LIMIT}. Новые приветствия и смена города пока выключены.')
            if stopped.is_set():break
            selected=call('open',allowed=remaining,entry=entry)
            entry='dialogs'
            if selected['state']=='exhausted':
                out.update(status='dialogs-completed',reason='visible-exhausted');break
            who=identity(selected['identity'])
            out['dialogs_opened']+=1
            # The identity has to agree with durable authorization BEFORE body
            # or name collection, even if a UI row looked correct.
            chain.authorized(who)
            if stopped.is_set():break
            before=(reader(settings.adb,settings.folder,stopped.is_set,who,read_name=True) if notifier is not None
                    else reader(settings.adb,settings.folder,stopped.is_set,who))
            if before.get('identity')!=who:raise StateError('changed-dialog')
            def submit(snapshot,text):
                if stopped.is_set():raise StateError('cancelled')
                out['reply_submission_calls']+=1
                result=sender(settings.adb,settings.folder,snapshot,stopped.is_set,text=text)
                if isinstance(result,dict) and result.get('attempted') is True and result.get('handler_returned') is True:
                    out['reply_handler_returns']+=1
                return result
            try:
                state=step(chain,before,submit,stopped.is_set)
            except ReviewRequired:
                chain.mark_review(who)
                state='manual-review'
            if state=='await-outgoing' and not stopped.is_set():
                progress('Проверяю появление ответа в истории. Повторной отправки нет.')
                for observation in range(3):
                    if (pause or stopped.wait)(1):break
                    after=(reader(settings.adb,settings.folder,stopped.is_set,who,read_name=True) if notifier is not None
                           else reader(settings.adb,settings.folder,stopped.is_set,who))
                    if after.get('identity')!=who:raise StateError('changed-dialog')
                    state,unexpected_action=chain.consume(after)
                    if unexpected_action is not None:raise StateError('unexpected-second-action')
                    if state in ('wait-mood','wait-contact'):out['outgoing_observed']+=1
                    if state not in ('pending-question','pending-contact','pending-clarify') or stopped.is_set():break
            if state not in STATES:raise StateError('invalid-chain-stage')
            out['states'][state]+=1
            if state=='submission-unknown':
                out.update(reason='reply-outcome-unknown');break
            if stopped.is_set() or state=='cancelled':break
            notification=chain.notify(who,notifier,stopped.is_set)
            if notification in out['notifications']:out['notifications'][notification]+=1
            if stopped.is_set():break
            call('back',expected=who)
            out['dialogs_processed']+=1
            remaining=[x for x in remaining if (x['account'],x['peer'])!=(who['account'],who['peer'])]
            if not remaining:
                out.update(status='dialogs-completed',reason='active-bindings-visited');break
        else:
            out.update(status='dialogs-completed',reason='visible-pass-limit')
        if stopped.is_set():
            out.update(status='dialogs-cancelled',reason='cancelled')
        elif out['status']=='dialogs-completed':
            call('return')
            out.update(return_verified=True,ui_may_remain_open=False)
    except Exception as error:
        out['last_reader']=safe_reader_failure(error)
        # Errors may contain message bodies, IDs, paths or tokens. Export only a
        # fixed category and the already-validated, body-free native diagnostic.
        out.update(status='dialogs-cancelled' if stopped.is_set() else 'dialogs-stopped',
                   reason='cancelled' if stopped.is_set() else 'binding-navigation-or-history-check-stopped')
    return out


def run_pass(settings,stopped,progress=lambda text:None, *, store=None,navigator=None,reader=None,sender=None,notifier=None,pause=None):
    from assistant_lock import operation_lock
    from one_chat_device import capture
    from one_chat_send_device import submit
    import telegram_notify
    if stopped.is_set():return dict(report(),status='dialogs-cancelled',reason='cancelled')
    with operation_lock():
        # Credentials are loaded only on explicit Start with the saved opt-in.
        if settings.contacts_enabled:
            if notifier is None:
                token,chat_id=telegram_notify.load()
                notifier=lambda payload:telegram_notify.send_contact(token,chat_id,payload)
        else:notifier=None
        chain=Chain(Store() if store is None else store,contact_notifications=notifier is not None)
        return walk(settings,stopped,progress,chain,navigator=perform if navigator is None else navigator,
                    reader=capture if reader is None else reader,sender=submit if sender is None else sender,
                    notifier=notifier,pause=pause)
