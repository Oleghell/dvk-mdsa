"""«Старт», step 1: active tracked chats, unread first then read-chat recovery.

Only chats with OUR greeting are eligible: an explicit guided binding or a
greeting recorded in the send journal. Outgoing messages need run-scoped
or per-message permission; unknown sends and notifications are never retried. Message
bodies stay in RAM (optional bounded Groq export); reports contain counters only.
"""
from assistant_chain import Chain, TERMINAL
from assistant_guided_chain import GuidedChain, walk as walk_chat
from assistant_store import StateError
from dialog_browser import targets
from one_chat_probe import identity
from version import VERSION
from assistant_authorization import flags

LIMIT = None
PAUSE_OUTCOMES = {'message-not-approved', 'manual-review'}
# Chat-local uncertainty is isolated, never retried; navigation failures still stop.
ISOLATE = {'send-outcome-unknown', 'outgoing-not-observed', 'manual-review',
           'history-changed-during-approval', 'local-own-message-unanchored',
           'groq-repeat-greeting', 'openrouter-repeat-greeting', 'groq-unsafe-reply', 'openrouter-unsafe-reply',
           'groq-invalid-response', 'openrouter-invalid-response'}
CONTINUE = {'chain-waiting', 'chain-completed', 'chain-needs-review', 'chain-paused'}


def isolation_reason(result):
    """Only one authored, chat-local read failure may leave via verified back.

    Do not skip arbitrary ReadStopped/identity/device failures. The native reader
    still rejects unanchored local messages without reading their bodies.
    """
    reason = result['reason']
    if reason == 'bound-chat-read-failed':
        failure = (result.get('diagnostics') or {}).get('last_read_failure') or {}
        expected = dict(error='local-own-message-unanchored',
                        stage='navigation-stopped', metadata_checkpoint='ready',
                        identity_checkpoint='recheck', scalar_checkpoint='message-chat-id',
                        scalar_state='negative', message_direction='own')
        if all(failure.get(key) == value for key, value in expected.items()):
            return 'local-own-message-unanchored'
        return None
    # A bare local-read code must not bypass the required native diagnostics.
    return reason if reason in ISOLATE - {'local-own-message-unanchored'} else None


class InboxChain(GuidedChain):
    """Guided chain that also accepts peers greeted through «Новые анкеты»."""

    def _guided(self, who):
        with self.store.connection() as db:
            return db.execute('SELECT 1 FROM guided_bindings WHERE account=? AND peer=?',
                              (who['account'], who['peer'])).fetchone() is not None

    def authorized(self, who):
        who = identity(who)
        if self._guided(who):
            return super().authorized(who)
        try:
            return Chain.authorized(self, who)
        except StateError:
            raise StateError('guided-binding-not-authorized') from None

    def bind(self, snapshot, greetings, *, approved=False):
        if approved is not True:
            raise StateError('guided-consent-required')
        who = identity(snapshot['identity'])
        if self._guided(who):
            return super().bind(snapshot, greetings, approved=True)
        try:
            Chain.authorized(self, who)
        except StateError:
            # Not in the send journal: only the guided fresh-greeting binding.
            return super().bind(snapshot, greetings, approved=True)
        # The journal already proves our greeting went to an empty chat; the
        # base chain anchors that exact greeting (hash) on first consumption.


def inbox_targets(chain):
    """Return (attention, unread) target lists. Terminal chats are excluded."""
    with chain.store.connection() as db:
        rows = db.execute('''
          WITH sources(account,peer,chat) AS (
            SELECT account,peer,chat FROM guided_bindings
            UNION ALL
            SELECT m.account,m.peer,m.initial_chat FROM manual_actions m
            WHERE m.status!='not-invoked' AND NOT EXISTS (
              SELECT 1 FROM guided_bindings g WHERE g.account=m.account AND g.peer=m.peer))
          SELECT s.account,s.peer,COALESCE(c.chat,s.chat),c.stage,
            EXISTS(SELECT 1 FROM chain_contact_outbox o WHERE o.chat=c.chat AND o.status='pending'),
            EXISTS(SELECT 1 FROM chain_actions a WHERE a.chat=c.chat
                   AND a.status IN ('awaiting-approval','handler-returned-unconfirmed'))
          FROM sources s LEFT JOIN chain_dialogs c ON c.account=s.account AND c.peer=s.peer
          ORDER BY s.account,s.peer''').fetchall()
    attention, unread = [], []
    for account, peer, chat, stage, outbox, pending in rows:
        item = dict(account=account, peer=peer, chat=chat)
        if stage in TERMINAL:
            if stage=='done' and outbox and chain.media_required and not chain.has_media(item):
                attention.append(item)
            continue
        elif pending or (stage or '').startswith('pending-'):
            attention.append(item)  # unconfirmed draft or unobserved outgoing
        else:
            unread.append(item)
    return attention, unread



def read_round(chain, active):
    """Fair read-chat fallback across bounded passes; no badge/history inference."""
    with chain.store.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS inbox_read_round(account TEXT,peer TEXT,PRIMARY KEY(account,peer))')
        seen=set(db.execute('SELECT account,peer FROM inbox_read_round'))
        remaining=[dict(who) for who in active if (who['account'],who['peer']) not in seen]
        if active and not remaining:
            db.execute('DELETE FROM inbox_read_round')
            remaining=[dict(who) for who in active]
    return remaining


def record_checked(chain, who):
    with chain.store.connection() as db:
        db.execute('INSERT OR IGNORE INTO inbox_read_round VALUES(?,?)', (who['account'],who['peer']))


def reset_read_round(chain):
    with chain.store.connection() as db:
        db.execute('DELETE FROM inbox_read_round')


def with_seen_ids(chain, allowed):
    # Read fallback excludes already-consumed incoming messages BEFORE opening.
    out=[]
    with chain.store.connection() as db:
        for who in allowed:
            rows=db.execute('SELECT message FROM chain_seen WHERE chat=? LIMIT 21', (who['chat'],)).fetchall()
            if len(rows)>20:raise StateError('observed-history-too-large')
            out.append(dict(who,seen_ids=[r[0] for r in rows]))
    return targets(out)


def report():
    return dict(tool_version=VERSION, mode='inbox-chain-pass', status='inbox-stopped',
                reason='not-started', dialog_limit=LIMIT, dialogs_opened=0,
                dialogs_processed=0, read_dialogs_checked=0, read_recovery_enabled=True, reply_filter_enabled=True, read_rows_skipped=0, waiting_rows_skipped=0, handled_rows_skipped=0, confirmations=0, automatic_authorizations=0,
                submission_calls=0, handler_returns=0, outgoing_observed=0, contacts_forwarded=0, contacts_detected=0, contact_delivery_pending=0,
                contact_notifications=dict(accepted=0,unknown=0,disabled=0,blocked=0),
                isolated_dialogs=0, isolated_reasons={}, review_causes={}, isolation_notification='not-needed', review_pending=0,
                groq_requests=0, openrouter_requests=0, ai_requests=0, ai_provider='groq', ai_model=None,
                groq_context_export_enabled=False, openrouter_context_export_enabled=False, outcomes={}, per_message_confirmation=True, automatic_send=False,
                return_verified=False, dialogs_verified=False, delivery_confirmed=False,
                all_dialogs_covered=False, ui_may_remain_open=False,
                personal_data_exported=False, chat_content_exported=False,
                device_scope='MuMu-4-only', last_navigation=None, last_chat_diagnostics=None)


def walk(settings, stopped, approve, progress, chain, *, navigator, reader, sender,
         notifier=None, greetings=(), pause=None, entry='search', return_to='search', exit_notifier=None, pager=None, contact_photo=None):
    from assistant_navigation_check import safe_diagnostic
    if entry not in ('search', 'dialogs') or return_to not in ('search', 'dialogs'):
        raise ValueError('Invalid inbox screen')
    out = report()
    out.update(flags(approve))
    out['exit_events'] = []
    # Telegram outbox is independent of the device. Never reopen a completed
    # conversation just to deliver an already encrypted, verified contact.
    with chain.store.connection() as db:
        pending=db.execute("SELECT c.account,c.peer,c.chat FROM chain_dialogs c JOIN chain_contact_outbox o ON o.chat=c.chat WHERE c.stage='done' AND o.status='pending'").fetchall()
    for account,peer,chat in pending:
        if stopped.is_set():
            out.update(status='inbox-cancelled',reason='cancelled')
            return out
        who=dict(account=account,peer=peer,chat=chat)
        if chain.media_required and not chain.has_media(who):continue
        status=chain.notify(who,notifier,stopped.is_set)
        if status in out['contact_notifications']:out['contact_notifications'][status]+=1
        if status=='accepted':out['contacts_forwarded']+=1
        if status in ('accepted','unknown'):out['personal_data_exported']=True
    def pending_contacts():
        with chain.store.connection() as db:
            return db.execute("SELECT COUNT(*) FROM chain_contact_outbox WHERE status='pending'").fetchone()[0]
    out['contact_delivery_pending']=pending_contacts()
    attention, unread = inbox_targets(chain)
    out['tracked_active']=len(unread)
    out['tracked_attention']=len(attention)
    with chain.store.connection() as db:
        out['tracked_terminal']={stage:number for stage,number in db.execute('SELECT stage,COUNT(*) FROM chain_dialogs GROUP BY stage') if stage in TERMINAL}
    if not attention and not unread:
        out.update(status='inbox-empty', reason='no-chain-dialogs')
        return out

    def call(operation, **kwargs):
        if stopped.is_set():
            raise StateError('cancelled')
        out['ui_may_remain_open'] = True
        value = navigator(operation, settings.adb, settings.folder, stopped.is_set, **kwargs)
        if not isinstance(value, dict) or set(value) != {'state', 'identity', 'diagnostic'}:
            raise ValueError('Invalid navigation result')
        n = out['last_navigation'] = safe_diagnostic(value['diagnostic'])
        if value['state'] == 'stopped':
            raise StateError('navigation-stopped')
        if n['stage'] != 'navigation-ready' or n['error'] != 'none' or not n['destination_verified']:
            raise ValueError('Unverified navigation')
        if value['state'] not in {'open': {'opened', 'exhausted'}, 'back': {'returned'},
                                  'return': {'search-ready'}}[operation]:
            raise ValueError('Unexpected navigation state')
        if operation == 'open':
            if not n.get('reply_filter_applied') or n.get('reply_needed_verified') != (value['state']=='opened'):
                raise StateError('reply-selection-not-verified')
            out['waiting_rows_skipped'] += n.get('waiting_rows_skipped',0)
            out['handled_rows_skipped'] += n.get('handled_rows_skipped',0)
        if operation == 'open' and kwargs['unread_only']:
            if not n['unread_filter_applied'] or n['unread_verified'] != (value['state'] == 'opened'):
                raise StateError('unread-selection-not-verified')
            out['read_rows_skipped'] += n['read_rows_skipped']
        who = identity(value['identity']) if value['identity'] is not None else None
        if (value['state'] in ('opened', 'returned')) != (who is not None):
            raise ValueError('Invalid navigation binding')
        if operation == 'open' and who is not None and not any(
                x['account'] == who['account'] and x['peer'] == who['peer'] and
                (int(x['chat']) <= 0 or x['chat'] == who['chat']) for x in kwargs['allowed']):
            raise StateError('untracked-dialog')
        if operation == 'back' and who != kwargs['expected']:
            raise StateError('changed-dialog')
        return value

    def count(outcome):
        out['outcomes'][outcome] = out['outcomes'].get(outcome, 0) + 1

    phase = 'navigation'
    try:
        reason = 'visible-pass-limit'
        groups = [(attention, False, 'pending'), (list(unread), True, 'unread'),
                  (read_round(chain, unread), False, 'read')]
        processed=set()
        def page_groups():
            attention,unread=inbox_targets(chain)
            groups=[(attention,False,'pending'),(list(unread),True,'unread'),(read_round(chain,unread),False,'read')]
            return [(targets([x for x in items[i:i+MAX_TARGETS] if (x['account'],x['peer']) not in processed]),unread_only,kind) for items,unread_only,kind in groups for i in range(0,len(items),MAX_TARGETS)]
        # Chunk transport payloads, not the number of dialogs processed.
        from dialog_browser import MAX_TARGETS
        groups=[(targets(items[i:i+MAX_TARGETS]),unread_only,kind) for items,unread_only,kind in groups for i in range(0,len(items),MAX_TARGETS)]
        if pager is not None:pager.reset()
        while groups or pager is not None:
            if not groups:
                if not pager.advance():
                    reason='available-exhausted'
                    break
                groups=page_groups()
                continue
            allowed, unread_only, group_kind = groups[0]
            if not allowed:
                groups.pop(0)
                continue
            phase = 'navigation'
            progress(f'Диалоги • чат {out["dialogs_opened"] + 1}' +
                     (' • проверка прочитанного' if group_kind == 'read' else ''))
            selected = call('open', allowed=with_seen_ids(chain,allowed) if group_kind=='read' else allowed,
                            entry=entry, unread_only=unread_only, needs_reply_only=True)
            entry = 'dialogs'
            if selected['state'] == 'exhausted':
                if group_kind == 'read':
                    reset_read_round(chain)  # Remaining targets may be offscreen.
                groups.pop(0)
                continue
            who = identity(selected['identity'])
            out['dialogs_opened'] += 1
            if group_kind == 'read':
                out['read_dialogs_checked'] += 1
            phase = 'chat'
            exit_messages=[]
            result = walk_chat(
                chain, who, stopped, approve,
                lambda expected: reader(settings.adb, settings.folder, stopped.is_set, expected),
                lambda snapshot, text: sender(settings.adb, settings.folder, snapshot,
                                              stopped.is_set, text=text),
                approved=True, greetings=greetings, notifier=notifier, progress=progress,
                pause=pause, max_polls=8, until_waiting=True, exit_capture=lambda texts:exit_messages.__setitem__(slice(None),texts), contact_photo=contact_photo,
                contact_reader=lambda expected: reader(settings.adb, settings.folder,
                                                       stopped.is_set, expected, read_name=True))
            out['last_chat_diagnostics'] = result['diagnostics']
            out['automatic_authorizations'] += result.get('automatic_authorizations', 0)
            for key in ('confirmations', 'submission_calls', 'handler_returns'):
                out[key] += result[key]
            out['outgoing_observed'] += result['outgoing_observed_this_run']
            out['contacts_forwarded'] += result['notifications']['accepted']
            out['contacts_detected'] += int(result['stages']['peer_contact'])
            for status in out['contact_notifications']:
                out['contact_notifications'][status] += result['notifications'][status]
            out['contact_delivery_pending']=pending_contacts()
            if result['stages']['peer_contact']:
                progress('Контакт получен • передан в Telegram' if result['notifications']['accepted'] else
                         'Контакт получен • сохранён в очереди; передача в Telegram выключена' if result['notifications']['disabled'] else
                         'Контакт получен • результат передачи в Telegram требует проверки')
            if result['telegram_used']:
                out['personal_data_exported'] = True
            isolated_code = isolation_reason(result)
            isolated = isolated_code is not None
            if not isolated:
                count(result['reason'] if result['status'] != 'chain-waiting' else result['status'] + ':' + result['reason'])
            if result['status'] == 'chain-cancelled' or stopped.is_set():
                raise StateError('cancelled')
            if result['status'] not in CONTINUE and not isolated:
                # Global/API/read/identity errors must not be treated as local.
                out.update(status='inbox-stopped', reason='chat-' + result['reason'])
                return out
            phase = 'navigation'
            # Mark durably BEFORE leaving: a failed back cannot enable a resend.
            if isolated:
                chain.mark_review(who)
            call('back', expected=who)
            if (not result['notifications']['accepted']
                    and (not result['outgoing_observed_this_run'] or result['stages']['peer_contact'])):
                from assistant_exit_notify import notify_exit
                event = notify_exit(chain, who, dict(result,_exit_messages=exit_messages), sender=exit_notifier, enabled=exit_notifier is not None)
                out['exit_events'].append(event)
                if event['notification'] in ('accepted','unknown'):
                    out['personal_data_exported']=True
                    if exit_messages:out['chat_content_exported']=True
            if isolated:
                out['isolated_dialogs'] += 1
                code = isolated_code
                out['isolated_reasons'][code] = out['isolated_reasons'].get(code, 0) + 1
                cause = result['diagnostics'].get('review_cause')
                from assistant_chain import REVIEW_CAUSES
                if cause in REVIEW_CAUSES:
                    out['review_causes'][cause] = out['review_causes'].get(cause, 0) + 1
                count('isolated:' + code)
                progress('Диалоги • один чат на проверке, продолжаю остальные')
            out['dialogs_processed'] += 1
            processed.add((who['account'],who['peer']))
            record_checked(chain, who)
            for group in groups:
                group[0][:] = [x for x in group[0] if (x['account'], x['peer']) != (who['account'], who['peer'])]
            if result['reason'] in PAUSE_OUTCOMES and not isolated:
                reason = 'needs-review'
                break  # No further approval prompts in this pass after No/timeout.
        else:
            reason = 'visible-exhausted' if not groups else 'visible-pass-limit'
        out['pages_checked']=pager.pages if pager is not None else 1
        phase = 'navigation'
        if return_to == 'search':
            call('return')
        out.update(status='inbox-completed', reason=reason, return_verified=return_to == 'search',
                   dialogs_verified=return_to == 'dialogs',
                   ui_may_remain_open=False)
    except Exception as error:
        n = out['last_navigation']
        out.update(status='inbox-cancelled' if stopped.is_set() else 'inbox-stopped',
                   reason='cancelled' if stopped.is_set() else
                   str(error) if isinstance(error, StateError) and str(error) in
                   {'unread-selection-not-verified', 'reply-selection-not-verified', 'untracked-dialog', 'changed-dialog',
                    'navigation-stopped'} else
                   n['error'] if n and n['error'] != 'none' else phase + '-check-stopped')
    return out


def run(settings, stopped, approve, progress=lambda _: None, *, store=None, navigator=None,
        reader=None, sender=None, notifier=None, greetings=None, pause=None,
        entry='search', return_to='search', exit_notifier=None, pager=None, contact_photo=None):
    """Caller must hold the shared device lock."""
    from assistant_config import load
    from assistant_store import Store
    from dialog_browser import perform
    from one_chat_device import capture
    from one_chat_send_device import submit
    import telegram_notify
    if stopped.is_set():
        return dict(report(), status='inbox-cancelled', reason='cancelled')
    if notifier is None and settings.contacts_enabled:
        token, chat_id = telegram_notify.load()
        notifier = lambda payload: telegram_notify.send_contact(token, chat_id, payload)
    from assistant_ai import responder as make_responder
    responder = make_responder(settings.ai_provider, settings.ai_model, stopped.is_set) if settings.groq_enabled else None
    chain = InboxChain(Store() if store is None else store, responder=responder)
    chain.media_required=settings.contacts_enabled
    if contact_photo is None and settings.contacts_enabled:
        from assistant_contact_photo import capture_profile
        contact_photo=lambda who:capture_profile(settings.adb,settings.folder,who,stopped.is_set)
    if exit_notifier is None and settings.errors_enabled:
        try:
            exit_token, exit_chat = telegram_notify.load()
            exit_notifier = lambda text: telegram_notify.send(exit_token, exit_chat, text)
        except telegram_notify.TelegramError:
            pass
    if navigator is None and pager is None:
        from assistant_dialog_pages import Pager
        # The initial full pass may still be on search. Verify the list before
        # any paging gesture; this route never opens a conversation.
        prepared=perform('list',settings.adb,settings.folder,stopped.is_set,entry=entry)
        if prepared['state']!='dialogs-ready':raise StateError('dialog-list-not-verified')
        entry='dialogs'
        pager=Pager(settings,stopped.is_set)
    result = walk(settings, stopped, approve, progress, chain,
                navigator=perform if navigator is None else navigator,
                reader=capture if reader is None else reader,
                sender=submit if sender is None else sender,
                notifier=notifier, pause=pause, entry=entry, return_to=return_to, exit_notifier=exit_notifier, pager=pager,contact_photo=contact_photo,
                greetings=load().greetings if greetings is None else greetings)

    with chain.store.connection() as db:
        result['review_pending'] = db.execute(
            "SELECT COUNT(*) FROM chain_dialogs WHERE stage='manual-review'").fetchone()[0]
    if settings.errors_enabled and result['isolated_dialogs'] and not any(e['notification'] in ('accepted','unknown','already-attempted') for e in result.get('exit_events',[])):
        from assistant_error_notify import notify_isolated
        result['isolation_notification'] = notify_isolated(result)
    result['ai_provider'], result['ai_model'] = settings.ai_provider, settings.ai_model
    result['ai_requests'] = responder.calls if responder is not None else 0
    result['groq_requests'] = result['ai_requests'] if settings.ai_provider == 'groq' else 0
    result['openrouter_requests'] = result['ai_requests'] if settings.ai_provider == 'openrouter' else 0
    result['groq_context_export_enabled'] = settings.groq_enabled and settings.ai_provider == 'groq'
    result['openrouter_context_export_enabled'] = settings.groq_enabled and settings.ai_provider == 'openrouter'
    if result['ai_requests']:
        result.update(chat_content_exported=True, personal_data_exported=True)
    return result
