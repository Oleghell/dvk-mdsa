"""«Старт», step 1: active tracked chats, unread first then read-chat recovery.

Only chats with OUR greeting are eligible: an explicit guided binding or a
greeting recorded in the send journal. Outgoing messages need run-scoped
or per-message permission; notifications are never retried; MuMu uncertain replies have one audited retry. Message
bodies stay in RAM (optional bounded Groq export); reports contain counters only.
"""
from assistant_chain import Chain, TERMINAL
from assistant_guided_chain import GuidedChain, walk as walk_chat
from assistant_store import StateError
from dialog_browser import targets
from one_chat_probe import identity
from version import VERSION
from assistant_authorization import flags
import time
from run_preparation import checkpoint
import assistant_history_wait as history_wait

from contextvars import ContextVar
from contextlib import contextmanager
_worker_store=ContextVar('mumu_worker_store',default=None)
@contextmanager
def runtime_store(store):
    if getattr(store,'mumu_shared_claims',False) is not True:raise ValueError('MuMu store required')
    token=_worker_store.set(store)
    try:yield
    finally:_worker_store.reset(token)

LIMIT = None
PAUSE_OUTCOMES = {'message-not-approved', 'manual-review'}
# Chat-local uncertainty is isolated; only the explicit MuMu recovery policy can retry once.
ISOLATE = {'greeting-not-verified', 'send-outcome-unknown', 'outgoing-not-observed', 'manual-review',
           'history-changed-during-approval', 'local-own-message-unanchored', 'groq-draft-unavailable',
           'groq-repeat-greeting', 'openrouter-repeat-greeting', 'groq-unsafe-reply', 'openrouter-unsafe-reply',
           'groq-invalid-response', 'openrouter-invalid-response',
           'gemini-repeat-greeting', 'gemini-unsafe-reply', 'gemini-invalid-response',
           'zai-repeat-greeting', 'zai-unsafe-reply', 'zai-invalid-response'}
CONTINUE = {'chain-waiting', 'chain-completed', 'chain-needs-review', 'chain-paused'}


def isolation_reason(result):
    """Only authored, identity-rechecked message failures may leave via verified back.

    Do not skip arbitrary ReadStopped/identity/device failures. The native reader
    still rejects unanchored local messages without reading their bodies.
    """
    reason = result['reason']
    if reason == 'chat-input-disabled':
        return reason if (result.get('diagnostics') or {}).get('input_disabled_verified') is True else None
    if reason == 'message-invalid':
        failure = (result.get('diagnostics') or {}).get('last_read_failure')
        return reason if history_wait.verified_message_invalid(failure) else None
    if reason == 'bound-chat-read-failed':
        failure = (result.get('diagnostics') or {}).get('last_read_failure') or {}
        expected = dict(error='local-own-message-unanchored',
                        stage='navigation-stopped', metadata_checkpoint='ready',
                        identity_checkpoint='recheck', scalar_checkpoint='message-chat-id',
                        scalar_state='negative', message_direction='own')
        if all(failure.get(key) == value for key, value in expected.items()):
            return 'local-own-message-unanchored'
        # Reject the content, not the entire port: a message-level invalid
        # server scalar can be quarantined ONLY after native identity recheck.
        # The caller persists review before a separately verified SAME-chat Back.
        # Account/peer/chat identity errors and unrecognized diagnostics never match.
        from chat_limits import MAX_MESSAGES
        scalars={'nonpositive-message-id':'message-id',
                 'nonpositive-message-sender-id':'message-sender-id',
                 'nonpositive-message-chat-id':'message-chat-id'}
        code=failure.get('error')
        if (code in scalars and failure.get('scalar_checkpoint')==scalars[code]
                and failure.get('scalar_state') in {'zero','negative'}
                and failure.get('stage')=='navigation-stopped'
                and failure.get('metadata_checkpoint')=='ready'
                and failure.get('identity_checkpoint')=='recheck'
                and failure.get('read_checkpoint')=='last-message'
                and failure.get('wait_reason')=='none'
                and type(failure.get('message_slot')) is int
                and -1 <= failure['message_slot'] < MAX_MESSAGES):
            return code
        return None
    # A bare local-read code must not bypass the required native diagnostics.
    return reason if reason in ISOLATE - {'local-own-message-unanchored'} else None


class InboxChain(GuidedChain):
    """Guided chain that also accepts peers greeted through «Новые анкеты»."""

    def _guided(self, who):
        with self.store.read_connection() as db:
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
        self.last_legacy_recovered=False
        self.legacy_recovery_reason='not-applicable'
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
        from assistant_legacy_recovery import recover
        self.last_legacy_recovered=recover(self,snapshot)


def inbox_targets(chain):
    """Return (attention, unread) target lists. Terminal chats are excluded."""
    manual_filter=(" WHERE NOT EXISTS(SELECT 1 FROM mumu_peer_blocks b LEFT JOIN mumu_manual_silences ms ON ms.peer=b.peer WHERE b.peer=s.peer AND (b.reason='manual-block' OR ms.peer IS NOT NULL))"
                   if getattr(chain.store,'mumu_shared_claims',False) is True else '')
    with chain.store.read_connection() as db:
        # The primary journal deliberately admits SELECT, not arbitrary WITH
        # statements, in read-only mode. Keep this query a SELECT with the same
        # source precedence; do not loosen the guard or take a writer lock.
        rows = db.execute('''
          SELECT s.account,s.peer,COALESCE(c.chat,s.chat),c.stage,
            EXISTS(SELECT 1 FROM chain_contact_outbox o WHERE o.chat=c.chat AND o.status='pending'),
            EXISTS(SELECT 1 FROM chain_actions a WHERE a.chat=c.chat
                   AND a.status IN ('awaiting-approval','handler-returned-unconfirmed')),
            EXISTS(SELECT 1 FROM chain_contact_media media WHERE media.chat=c.chat)
          FROM (
            SELECT account,peer,chat FROM guided_bindings
            UNION ALL
            SELECT m.account,m.peer,m.initial_chat FROM manual_actions m
            WHERE m.status!='not-invoked' AND NOT EXISTS (
              SELECT 1 FROM guided_bindings g WHERE g.account=m.account AND g.peer=m.peer)
          ) s LEFT JOIN chain_dialogs c ON c.account=s.account AND c.peer=s.peer
          '''+manual_filter+' ORDER BY s.account,s.peer').fetchall()
    attention, unread = [], []
    from assistant_contact_receipt import candidates as contact_candidates
    receipt_reviews=contact_candidates(chain.store)
    from assistant_selection_recovery import targets as selection_targets
    receipt_reviews |= selection_targets(chain)
    from assistant_legacy_recovery import candidates
    recoverable=candidates(chain.store) if chain.responder is not None else set()
    for account, peer, chat, stage, outbox, pending, media in rows:
        item = dict(account=account, peer=peer, chat=chat)
        if stage in TERMINAL and (account,peer,chat) not in recoverable | receipt_reviews:
            if stage=='done' and outbox and chain.media_required and not media:
                attention.append(item)
            continue
        elif pending or (stage or '').startswith('pending-'):
            attention.append(item)  # unconfirmed draft or unobserved outgoing
        else:
            unread.append(item)
    from assistant_reply_window import eligible_groups
    return eligible_groups(chain.store,attention,unread)



def read_round(chain, active):
    """Fair read-chat fallback across bounded passes; no badge/history inference."""
    chain.store.ensure_tables('CREATE TABLE IF NOT EXISTS inbox_read_round(account TEXT,peer TEXT,PRIMARY KEY(account,peer))')
    with chain.store.read_connection() as db:
        seen=set(db.execute('SELECT account,peer FROM inbox_read_round'))
        remaining=[dict(who) for who in active if (who['account'],who['peer']) not in seen]
    if active and not remaining:
        with chain.store.connection() as db:
            seen=set(db.execute('SELECT account,peer FROM inbox_read_round'))
            remaining=[dict(who) for who in active if (who['account'],who['peer']) not in seen]
            if remaining:return remaining
            db.execute('DELETE FROM inbox_read_round')
            remaining=[dict(who) for who in active]
    return remaining


def record_checked(chain, who):
    with chain.store.connection() as db:
        db.execute('INSERT OR IGNORE INTO inbox_read_round VALUES(?,?)', (who['account'],who['peer']))


def reset_read_round(chain):
    with chain.store.read_connection() as db:
        if db.execute('SELECT 1 FROM inbox_read_round LIMIT 1').fetchone() is None:return
    with chain.store.connection() as db:
        db.execute('DELETE FROM inbox_read_round')


def with_seen_ids(chain, allowed):
    # Read fallback excludes already-consumed incoming messages BEFORE opening.
    out=[]
    from assistant_contact_receipt import candidates as contact_candidates
    receipt_reviews=contact_candidates(chain.store)
    from assistant_selection_recovery import targets as selection_targets
    receipt_reviews |= selection_targets(chain)
    from assistant_unknown_reply import targets as unknown_targets
    receipt_reviews |= unknown_targets(chain)
    from assistant_reply_audit import DDL as receipt_ddl
    from assistant_skip_audit import DDL as skip_ddl
    chain.store.ensure_tables(receipt_ddl,skip_ddl)
    with chain.store.read_connection() as db:
        if chain.media_required:
            receipt_reviews |= set(db.execute("""SELECT c.account,c.peer,c.chat FROM chain_dialogs c
                JOIN chain_contact_outbox o ON o.chat=c.chat
                WHERE c.stage='done' AND o.status='pending'
                AND NOT EXISTS(SELECT 1 FROM chain_contact_media m WHERE m.chat=c.chat)"""))
        # At most 128 chats / 256 parameters and 129 rows per chat per query.
        # The 129th remains a hard overflow signal, never silent truncation.
        for offset in range(0,len(allowed),128):
            batch=allowed[offset:offset+128]
            chats=list(dict.fromkeys(who['chat'] for who in batch))
            marks=','.join('?' for _ in chats)
            query="""SELECT chat,message FROM (
              SELECT chat,message,ROW_NUMBER() OVER(PARTITION BY chat ORDER BY message) AS item_number FROM (
                SELECT s.chat,s.message FROM chain_seen s WHERE s.chat IN ("""+marks+""") AND s.message NOT IN
                  (SELECT message FROM chain_reply_receipts WHERE chat=s.chat AND status='pending')
                UNION SELECT r.chat,r.message FROM chain_reply_receipts r JOIN inbox_reported_inputs i
                  ON r.chat=i.chat AND r.message=i.message AND r.fingerprint=i.fingerprint
                  WHERE r.chat IN ("""+marks+""")
              ) observed
            ) ranked WHERE item_number<=129 ORDER BY chat,message"""
            seen={chat:[] for chat in chats}
            for chat,message in db.execute(query,tuple(chats+chats)):seen[chat].append(message)
            for who in batch:
                rows=seen[who['chat']]
                review=(who['account'],who['peer'],who['chat']) in receipt_reviews
                if len(rows)>128 and not review:raise StateError('observed-history-too-large')
                out.append(dict(who,seen_ids=[] if review else rows))
    return targets(out)


def report():
    return dict(tool_version=VERSION, mode='inbox-chain-pass', status='inbox-stopped',
                reason='not-started', dialog_limit=LIMIT, dialogs_opened=0,
                new_incoming_messages=0, incoming_scan_complete=False,
                dialogs_processed=0, read_dialogs_checked=0, read_recovery_enabled=True, reply_filter_enabled=True, read_rows_skipped=0, waiting_rows_skipped=0, handled_rows_skipped=0, confirmations=0, automatic_authorizations=0,
                submission_calls=0, handler_returns=0, outgoing_observed=0, contacts_forwarded=0, contacts_detected=0, contact_delivery_pending=0,
                contact_notifications=dict(accepted=0,unknown=0,disabled=0,blocked=0),
                isolated_dialogs=0, isolated_reasons={}, review_causes={}, isolation_notification='not-needed', review_pending=0,
                groq_requests=0, openrouter_requests=0, gemini_requests=0, zai_requests=0, ai_requests=0, ai_provider='groq', ai_model=None,
                groq_context_export_enabled=False, openrouter_context_export_enabled=False, gemini_context_export_enabled=False, zai_context_export_enabled=False, outcomes={}, per_message_confirmation=True, automatic_send=False,
                return_verified=False, dialogs_verified=False, delivery_confirmed=False,
                all_dialogs_covered=False, ui_may_remain_open=False,
                header_rows_skipped=0, history_deferred=0, history_cooldown_skipped=0, history_retry_after_seconds=60, personal_data_exported=False, chat_content_exported=False,
                device_scope='MuMu-4-only', last_navigation=None, last_chat_diagnostics=None)


def walk(settings, stopped, approve, progress, chain, *, navigator, reader, sender,
         notifier=None, greetings=(), pause=None, entry='search', return_to='search', exit_notifier=None, pager=None, contact_photo=None, exit_photo=None, exit_photo_sender=None, clock=time.time):
    from assistant_navigation_check import safe_diagnostic
    if entry not in ('search', 'dialogs') or return_to not in ('search', 'dialogs'):
        raise ValueError('Invalid inbox screen')
    out = report()
    out.update(flags(approve))
    out['exit_events'] = []
    # Telegram outbox is independent of the device. Never reopen a completed
    # conversation just to deliver an already encrypted, verified contact.
    with checkpoint('inbox-outbox'):
        with chain.store.read_connection() as db:
            query="SELECT c.account,c.peer,c.chat FROM chain_dialogs c JOIN chain_contact_outbox o ON o.chat=c.chat WHERE c.stage='done' AND o.status='pending'"
            if chain.media_required:query+=" AND EXISTS(SELECT 1 FROM chain_contact_media media WHERE media.chat=c.chat)"
            pending=db.execute(query).fetchall()
        for account,peer,chat in pending:
            if stopped.is_set():
                out.update(status='inbox-cancelled',reason='cancelled')
                return out
            who=dict(account=account,peer=peer,chat=chat)
            from mumu_peer_policy import manually_blocked
            if manually_blocked(chain.store,who):continue
            from mumu_namespace import owns_account
            if not owns_account(chain.store,who):continue
            status=chain.notify(who,notifier,stopped.is_set)
            if status in out['contact_notifications']:out['contact_notifications'][status]+=1
            if status=='accepted':out['contacts_forwarded']+=1
            if status in ('accepted','unknown'):out['personal_data_exported']=True
    def pending_contacts():
        with chain.store.read_connection() as db:
            return db.execute("SELECT COUNT(*) FROM chain_contact_outbox WHERE status='pending'").fetchone()[0]
    dispatcher=getattr(chain,'notification_dispatcher',None)
    if dispatcher is not None:
        for status in dispatcher.drain():
            if status in out['contact_notifications']:out['contact_notifications'][status]+=1
            if status=='accepted':out['contacts_forwarded']+=1
            if status in ('accepted','unknown'):out['personal_data_exported']=True
    progress('Подготавливаю список диалогов из общей базы…')
    with checkpoint('inbox-targets'):
        out['contact_delivery_pending']=pending_contacts()
        history_wait.initialize(chain.store)
        from assistant_reply_audit import DDL as resource_receipts
        chain.store.ensure_tables(resource_receipts)
        attention, unread = inbox_targets(chain)
        attention, unread, skipped = history_wait.eligible(chain.store, attention, unread, clock=clock)
        out['history_cooldown_skipped'] = skipped
        out['tracked_active']=len(unread)
        out['tracked_attention']=len(attention)
        with chain.store.read_connection() as db:
            out['tracked_terminal']={stage:number for stage,number in db.execute('SELECT stage,COUNT(*) FROM chain_dialogs GROUP BY stage') if stage in TERMINAL}
    if not attention and not unread:
        out.update(status='inbox-empty', reason='history-cooldown' if skipped else 'no-chain-dialogs',
                   dialogs_verified=entry=='dialogs', incoming_scan_complete=not skipped)
        return out

    def call(operation, **kwargs):
        if stopped.is_set():
            raise StateError('cancelled')
        out['ui_may_remain_open'] = True
        out['last_navigation'] = None
        for attempt in range(3):
            value = navigator(operation, settings.adb, settings.folder, stopped.is_set, **kwargs)
            from assistant_scan_retry import readonly_list_changed
            if not readonly_list_changed(operation,value) or attempt == 2:break
            kwargs = dict(kwargs,entry='dialogs')
            out['list_scan_retries'] = out.get('list_scan_retries',0)+1
            progress('Список диалогов обновился • перечитываю без отправки')
            if stopped.is_set():raise StateError('cancelled')
        if not isinstance(value, dict) or set(value) != {'state', 'identity', 'diagnostic'}:
            raise ValueError('Invalid navigation result')
        n = out['last_navigation'] = safe_diagnostic(value['diagnostic'])
        out['header_rows_skipped']+=n.get('header_rows_skipped',0)
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
    host_checkpoint = 'inbox-targets'
    try:
        reason = 'visible-pass-limit'
        groups = [(attention, False, 'pending'), (list(unread), True, 'unread'),
                  (read_round(chain, unread), False, 'read')]
        if getattr(chain.store,'mumu_shared_claims',False):
            # Let native row order decide, not unread/pending grouping. Both
            # read and unread inputs retain needs_reply_only/receipt filtering.
            combined={}
            for items,_,_ in groups:
                for who in items:combined.setdefault((who['account'],who['peer']),who)
            groups=[(list(combined.values()),False,'recent')]
            out['recent_window_limit']=50
            out['recent_window_direction']='bottom-up'
        processed=set()
        def leave_manual(who):
            nonlocal host_checkpoint,phase
            phase='navigation';host_checkpoint='inbox-back'
            call('back',expected=who)
            out['dialogs_processed']+=1
            processed.add((who['account'],who['peer']))
            for group in groups:
                group[0][:]=[x for x in group[0] if x['peer']!=who['peer']]
        def page_groups():
            attention,unread=inbox_targets(chain)
            attention,unread,_=history_wait.eligible(chain.store,attention,unread,clock=clock)
            groups=[(attention,False,'pending'),(list(unread),True,'unread'),(read_round(chain,unread),False,'read')]
            return [(targets([x for x in items[i:i+MAX_TARGETS] if (x['account'],x['peer']) not in processed]),unread_only,kind) for items,unread_only,kind in groups for i in range(0,len(items),MAX_TARGETS)]
        # Chunk transport payloads, not the number of dialogs processed.
        from dialog_browser import MAX_TARGETS
        groups=[(targets(items[i:i+MAX_TARGETS]),unread_only,kind) for items,unread_only,kind in groups for i in range(0,len(items),MAX_TARGETS)]
        if pager is not None:pager.reset()
        while groups or pager is not None:
            from assistant_pause import boundary
            boundary(stopped)
            if stopped.is_set():raise StateError('cancelled')
            if getattr(chain.store,'mumu_shared_claims',False) and out['dialogs_processed']>=50:
                reason='recent-window-limit'
                break
            if not groups:
                if not pager.advance():
                    reason='available-exhausted'
                    break
                groups=page_groups()
                continue
            allowed, unread_only, group_kind = groups[0]
            from mumu_peer_policy import without_manual_blocks,manually_blocked
            allowed[:]=without_manual_blocks(chain.store,allowed)
            if not allowed:
                groups.pop(0)
                continue
            phase = 'navigation'
            progress(f'Ищу следующий чат • обработано {out["dialogs_processed"]}' +
                     (' • проверка прочитанного' if group_kind == 'read' else ''))
            host_checkpoint = 'inbox-open'
            from assistant_stage_timing import timed
            open_timing = {}
            selected = timed(open_timing, 'open', call, 'open', allowed=with_seen_ids(chain,allowed),
                            entry=entry, unread_only=unread_only, needs_reply_only=True)
            entry = 'dialogs'
            if selected['state'] == 'exhausted':
                if group_kind == 'read':
                    reset_read_round(chain)  # Remaining targets may be offscreen.
                groups.pop(0)
                continue
            who = identity(selected['identity'])
            out['dialogs_opened'] += 1
            if manually_blocked(chain.store,who):
                # /num may commit during native open. Do not read, draft,
                # screenshot, notify or mutate the chain; only verified Back.
                leave_manual(who)
                continue
            progress(f'Читаю открытый диалог • {out["dialogs_opened"]}')
            if group_kind == 'read':
                out['read_dialogs_checked'] += 1
            phase = 'chat'
            from assistant_legacy_recovery import reserve_probe
            reserve_probe(chain,who)
            from assistant_contact_receipt import reserve_probe as reserve_contact_probe
            reserve_contact_probe(chain,who)
            exit_messages=[]
            private_snapshot=[]
            # IDs only, before consume can mark new arrivals seen. No message bodies
            # or IDs are added to the public pass report; repeat reads deduplicate.
            with chain.store.read_connection() as db:
                known_incoming={r[0] for r in db.execute(
                    'SELECT message FROM chain_seen WHERE chat=? UNION SELECT message FROM chain_reply_receipts WHERE chat=?',
                    (who['chat'],who['chat']))}
            def capture_snapshot(value):
                private_snapshot[:]=[value]
                fresh={m['id'] for m in value['messages'] if m['sender']==who['peer']} - known_incoming
                out['new_incoming_messages']+=len(fresh)
                known_incoming.update(fresh)
            host_checkpoint = 'inbox-read'
            result = walk_chat(
                chain, who, stopped, approve,
                lambda expected: reader(settings.adb, settings.folder, stopped.is_set, expected),
                lambda snapshot, text: sender(settings.adb, settings.folder, snapshot,
                                              stopped.is_set, text=text),
                approved=True, greetings=greetings, notifier=notifier, progress=progress,
                pause=pause, max_polls=8, until_waiting=True, snapshot_capture=capture_snapshot, exit_capture=lambda texts:exit_messages.__setitem__(slice(None),texts), contact_photo=contact_photo,
                contact_reader=lambda expected: reader(settings.adb, settings.folder,
                                                       stopped.is_set, expected, read_name=True))
            result['diagnostics'].update(open_timing)
            out['last_chat_diagnostics'] = result['diagnostics']
            if result.get('submission_calls',0)>0 and result['reason'] in ('send-outcome-unknown','send-preflight-deferred','send-native-check-failed',
                    'send-device-check-failed','send-validation-failed','outgoing-not-observed'):
                # Retain earlier send failures even if later chats succeed. No
                # identity, body, session ID or authorization token is copied.
                from assistant_error_notify import diagnostic_json
                import json
                safe=json.loads(diagnostic_json(dict(reason=result['reason'],diagnostic=result['diagnostics'])))['diagnostic']
                out['send_failure_events']=(out.get('send_failure_events',[])+[safe])[-3:]
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
                progress('Контакт получен • уведомление в фоновой очереди' if result['reason']=='contact-notification-queued' else
                         'Контакт получен • передан в Telegram' if result['notifications']['accepted'] else
                         'Контакт получен • сохранён в очереди; передача в Telegram выключена' if result['notifications']['disabled'] else
                         'Контакт получен • результат передачи в Telegram требует проверки')
            if result['telegram_used']:
                out['personal_data_exported'] = True
            if (result['status']=='chain-waiting' and result['reason']=='peer-contact-blocked'
                    and manually_blocked(chain.store,who)):
                leave_manual(who)
                continue
            deferred = result['reason'] in ('history-loading-timeout','history-read-budget-timeout','history-snapshot-too-large','send-preflight-deferred')
            ai_deferred=result['reason']=='ai-temporarily-unavailable'
            answer_deferred=result['reason']=='incoming-answer-pending'
            photo_deferred=(result['reason']=='contact-photo-unavailable' and result['status']=='chain-waiting')
            evidence = result['diagnostics']
            deferred_valid = ((result['reason'] == 'history-loading-timeout'
                    and evidence.get('history_wait_exhausted') is True
                    and history_wait.verified_loading(evidence.get('last_read_failure')))
                or (result['reason'] == 'history-read-budget-timeout'
                    and evidence.get('history_budget_exhausted') is True
                    and history_wait.verified_read_budget(evidence.get('last_read_failure'))))
            deferred_valid = deferred_valid or (result['reason']=='history-snapshot-too-large'
                and evidence.get('history_snapshot_oversized') is True
                and history_wait.verified_oversized(evidence.get('last_read_failure')))
            from one_chat_send import PREFLIGHT_RETRY_ERRORS
            deferred_valid = deferred_valid or (result['reason']=='send-preflight-deferred'
                and evidence.get('send_no_invocation_verified') is True
                and evidence.get('submission_attempted') is False and evidence.get('submission_returned') is False
                and evidence.get('last_send_failure') in PREFLIGHT_RETRY_ERRORS|{'submission-snapshot-changed'})
            if deferred and not (result['status'] == 'chain-waiting' and deferred_valid):
                out.update(status='inbox-stopped', reason='chat-bound-chat-read-failed')
                return out
            isolated_code = isolation_reason(result)
            isolated = isolated_code is not None
            if not isolated:
                count(result['reason'] if result['status'] != 'chain-waiting' else result['status'] + ':' + result['reason'])
            if result['status'] == 'chain-cancelled' or stopped.is_set():
                raise StateError('cancelled')
            if (result['status'] not in CONTINUE or result['reason']=='message-invalid') and not isolated:
                # Global/API/read/identity errors must not be treated as local.
                out.update(status='inbox-stopped', reason='chat-' + result['reason'])
                return out
            host_checkpoint = 'inbox-audit'
            from assistant_reply_audit import pending as pending_replies
            unanswered=pending_replies(chain,who)
            result['unanswered_messages']=len(unanswered)
            notice_needed=(result['reason']!='contact-notification-queued' and not manually_blocked(chain.store,who) and not result['notifications']['accepted']
                    and (bool(unanswered) or not result['outgoing_observed_this_run'] or result['stages']['peer_contact']))
            exit_image=None;exit_image_status=None
            capture_needed=notice_needed and exit_notifier is not None and exit_photo is not None
            if capture_needed:
                from assistant_exit_notify import notify_exit
                # A read-only preview avoids taking another expensive screenshot
                # for a Telegram state already attempted (including unknown).
                preview=notify_exit(chain,who,dict(result,_exit_messages=exit_messages),enabled=False)
                capture_needed=preview['notification'] not in ('already-attempted','manual-block-suppressed')
            if capture_needed:
                progress('Снимок чата для уведомления • чтение завершено.')
                try:
                    exit_image=timed(result['diagnostics'], 'exit_photo', exit_photo, who)
                    from assistant_contact_photo import png_size
                    png_size(exit_image);exit_image_status='captured'
                except Exception:
                    exit_image=None;exit_image_status='unavailable'
                    if stopped.is_set():raise StateError('cancelled')
            phase = 'navigation'
            # Mark durably BEFORE leaving: a failed back cannot enable a resend.
            if isolated:
                chain.mark_review(who)
            progress('Исходящее подтверждено → возвращаюсь к списку.' if result['outgoing_observed_this_run'] and not unanswered else 'Возвращаюсь к списку диалогов.')
            host_checkpoint = 'inbox-back'
            timed(result['diagnostics'], 'back', call, 'back', expected=who)
            # Only a successful, SAME-chat back may make a read failure local.
            # Do not change chain stage, reservations, consumed messages or review state.
            if deferred or ai_deferred or answer_deferred or photo_deferred:
                history_wait.defer(chain.store,who,clock=clock)
                out['history_deferred'] += 1
                progress('Контакт сохранён. Проверю фото позже, продолжаю другие чаты.' if photo_deferred else
                         'ИИ не дал проверенный ответ. Проверю чат позже.' if ai_deferred else 'Отправки не было. Проверю чат позже.' if result['reason']=='send-preflight-deferred' else 'Не удалось дочитать историю. Вернулся в личку; проверю этот чат позже.')
            else:
                history_wait.clear(chain.store,who)
            if notice_needed:
                host_checkpoint = 'inbox-exit-notify'
                from assistant_exit_notify import notify_exit
                event = notify_exit(chain, who, dict(result,_exit_messages=exit_messages), sender=exit_notifier, enabled=exit_notifier is not None, photo=exit_image, photo_status=exit_image_status, photo_sender=exit_photo_sender)
                out['exit_events'].append(event)
                if (event['notification'] in ('accepted','unknown','already-attempted') and exit_messages and private_snapshot
                        and result['reason']!='send-preflight-deferred'):
                    from assistant_skip_audit import reported
                    marked=reported(chain,who,private_snapshot[0])
                    if marked and (ai_deferred or answer_deferred):
                        # Exact old inputs are suppressed; a NEW input needs no
                        # leftover timer before becoming eligible.
                        history_wait.clear(chain.store,who)
                if event['notification'] in ('accepted','unknown'):
                    out['personal_data_exported']=True
                    if exit_messages or exit_image is not None:out['chat_content_exported']=True
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
            if not deferred and not ai_deferred and not answer_deferred and not photo_deferred and not unanswered:
                host_checkpoint = 'inbox-record'
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
            host_checkpoint = 'inbox-return'
            call('return')
        out.update(status='inbox-completed', reason=reason, return_verified=return_to == 'search',
                   dialogs_verified=return_to == 'dialogs',
                   ui_may_remain_open=False, incoming_scan_complete=(reason=='visible-exhausted'
                       and not any(out[k] for k in ('history_deferred','history_cooldown_skipped','isolated_dialogs','review_pending'))))
    except Exception as error:
        from assistant_failure import category,evidence
        out.update(host_failure=category(error),host_checkpoint=host_checkpoint)
        from cloud_database import diagnostic as database_diagnostic
        database=database_diagnostic(error)
        if database:out['database']=database
        failure=evidence(error)
        if failure:out['last_navigation_failure']=failure
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
        entry='search', return_to='search', exit_notifier=None, pager=None, contact_photo=None, exit_photo=None, exit_photo_sender=None):
    """Caller must hold the shared device lock."""
    with checkpoint('inbox-imports'):
        from assistant_config import config_directory, entries
        from assistant_store import Store
        from one_chat_device import capture
        from functools import partial
        from one_chat_send_device import submit
        import telegram_notify
    from assistant_pause import boundary
    boundary(stopped)
    if stopped.is_set():
        return dict(report(), status='inbox-cancelled', reason='cancelled')
    with checkpoint('inbox-contacts'):
        if notifier is None and settings.contacts_enabled:
            token, chat_id = telegram_notify.load()
            notifier = lambda payload: telegram_notify.send_contact(token, chat_id, payload)
    with checkpoint('inbox-ai'):
        from assistant_ai import responder as make_responder
        responder = make_responder(settings.ai_provider, settings.ai_model, stopped.is_set) if settings.groq_enabled else None
    progress('Подготавливаю базу первого прохода по входящим…')
    with checkpoint('inbox-database'):
        prepared_store=(store if store is not None else _worker_store.get())
        if prepared_store is None:prepared_store=Store()
    with checkpoint('inbox-chain'):
        chain = InboxChain(prepared_store,responder=responder)
    if getattr(prepared_store,'mumu_shared_claims',False) is True:
        from assistant_unknown_reply import enable as enable_unknown_recovery
        enable_unknown_recovery(chain)
        from assistant_selection_recovery import enable as enable_selection_recovery
        enable_selection_recovery(chain)
        chain.history_read_budget=12.0
        from assistant_notification_queue import current as notification_dispatcher
        chain.notification_dispatcher=notification_dispatcher()
    chain.media_required=settings.contacts_enabled
    with checkpoint('inbox-photo'):
        if contact_photo is None and settings.contacts_enabled:
            from assistant_contact_photo import capture_profile
            contact_photo=lambda who:capture_profile(settings.adb,settings.folder,who,stopped.is_set)
    if exit_notifier is None and settings.errors_enabled:
        try:
            exit_token, exit_chat = telegram_notify.load()
            exit_notifier = lambda text: telegram_notify.send(exit_token, exit_chat, text)
            exit_photo_sender=lambda text,image:telegram_notify.send_photo(exit_token,exit_chat,text,image)
            if exit_photo is None:
                from assistant_exit_photo import capture_chat
                exit_photo=lambda who:capture_chat(settings.adb,settings.folder,who,stopped.is_set)
        except telegram_notify.TelegramError:
            pass
    from assistant_exit_queue import resume as resume_exit_notifications
    resume_exit_notifications(chain,exit_notifier,exit_photo_sender,stopped.is_set)
    with checkpoint('inbox-navigation-adapter'):
        if navigator is None:
            from dialog_models import perform as model_navigation
            from functools import partial
            if getattr(prepared_store,'mumu_shared_claims',False):
                from dialog_models import RecentNavigator
                navigator=RecentNavigator(progress=progress,limit=50)
            else:
                navigator=partial(model_navigation,progress=progress)
    with checkpoint('inbox-config'):
        prepared_greetings=entries(config_directory(),'greetings',256) if greetings is None else greetings
    # No screen paging, automatic swipes or return-to-top scan.
    with checkpoint('inbox-walk'):
        result = walk(settings, stopped, approve, progress, chain,
                    navigator=navigator,
                    reader=partial(capture,read_latest=True,read_input=True,
                                   read_name=settings.contacts_enabled,read_name_optional=settings.contacts_enabled) if reader is None else reader,
                    sender=submit if sender is None else sender,
                    notifier=notifier, pause=pause, entry=entry, return_to=return_to, exit_notifier=exit_notifier, pager=pager,contact_photo=contact_photo,exit_photo=exit_photo,exit_photo_sender=exit_photo_sender,
                    greetings=prepared_greetings)

    with checkpoint('inbox-review'):
        with chain.store.read_connection() as db:
            result['review_pending'] = db.execute(
                "SELECT COUNT(*) FROM chain_dialogs WHERE stage='manual-review'").fetchone()[0]
    if settings.errors_enabled and result['isolated_dialogs'] and not any(e['notification'] in ('accepted','unknown','already-attempted') for e in result.get('exit_events',[])):
        from assistant_error_notify import notify_isolated
        result['isolation_notification'] = notify_isolated(result)
    result['ai_provider'], result['ai_model'] = settings.ai_provider, settings.ai_model
    result['ai_requests'] = responder.calls if responder is not None else 0
    counts=getattr(responder,'provider_calls',None) if responder is not None else None
    if type(counts) is dict:
        result['groq_requests']=counts['groq'];result['openrouter_requests']=counts['openrouter'];result['gemini_requests']=counts.get('gemini',0);result['zai_requests']=counts.get('zai',0)
        result['ai_key_failures']=list(responder.errors)
        result['ai_failure_history']=list(responder.failure_history) if type(getattr(responder,'failure_history',None)) is list else []
        result['ai_strategy']=getattr(responder,'strategy','selected-provider-only')
    else:
        result['groq_requests'] = result['ai_requests'] if settings.ai_provider == 'groq' else 0
        result['openrouter_requests'] = result['ai_requests'] if settings.ai_provider == 'openrouter' else 0
        result['gemini_requests'] = result['ai_requests'] if settings.ai_provider == 'gemini' else 0
        result['zai_requests'] = result['ai_requests'] if settings.ai_provider == 'zai' else 0
    for provider in ('groq','openrouter','gemini','zai'):
        result[provider+'_context_export_enabled'] = bool(settings.groq_enabled and
            (type(counts) is dict or settings.ai_provider == provider))
    if result['ai_requests']:
        result.update(chat_content_exported=True, personal_data_exported=True)
    return result
