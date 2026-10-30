"""One explicitly selected chat, the complete chain, per-message confirmation.

The existing read-only Start is untouched. No profile search, name collection,
contact export, send retries or chronology inferred from list positions.
"""
import json
import secrets
import time

from assistant_chain import Chain, ReviewRequired, REPLIES, TERMINAL, text_hash, fingerprint
from assistant_history_wait import HistoryMessageInvalid
from assistant_store import Store, StateError, data_directory
from one_chat_probe import identity
from one_chat_send import checked
from conversation_engine import CONTACT_TEXT
from shared_contact import display_name
from mumu_peer_policy import ensure_communication_allowed, PeerCommunicationBlocked

from version import VERSION
from assistant_stage_timing import timed, collect_read_timings
from assistant_authorization import flags
from assistant_history_wait import (verified_loading, HistoryWaitExpired, WAIT_SECONDS,
                                    WAIT_INTERVAL, MAX_READ_ATTEMPTS, verified_read_budget,
                                    HistoryReadBudgetExpired, BUDGET_READ_ATTEMPTS, BUDGET_RETRY_INTERVAL)


def report():
    return dict(tool_version=VERSION, mode='guided-open-dialog-chain',
                status='chain-stopped', reason='not-started', stage='not-started',
                stages=dict(greeting=False, peer_greeting=False, question=False,
                            peer_reply=False, contact_request=False,
                            peer_contact=False),
                confirmations=0, automatic_authorizations=0, submission_calls=0, handler_returns=0, outgoing_observed=0,
                outgoing_observed_this_run=0,
                notifications=dict(accepted=0, unknown=0, disabled=0, blocked=0),
                device_scope='MuMu-4-only', per_message_confirmation=True,
                automatic_send=False, delivery_confirmed=False,
                personal_data_exported=False, chat_content_exported=False,
                diagnostics=dict(name_source='not-requested', name_read='not-attempted',
                                 failure_point='none', read_retries=0, last_read_failure=None, history_wait_exhausted=False, history_budget_exhausted=False),
                telegram_used=False, ui_may_remain_open=True,
                live_cycle_available=False)


def same_snapshot(left, right):
    left = checked({key: left[key] for key in ('identity', 'messages')})
    right = checked({key: right[key] for key in ('identity', 'messages')})
    return (left['identity'] == right['identity'] and
            {m['id']: m for m in left['messages']} ==
            {m['id']: m for m in right['messages']})


def extends_snapshot(previous, current):
    """Allow arrivals during name lookup, never edits, truncation or chat changes."""
    previous = checked({key: previous[key] for key in ('identity', 'messages')})
    current = checked({key: current[key] for key in ('identity', 'messages')})
    old = {m['id']: m for m in previous['messages']}
    new = {m['id']: m for m in current['messages']}
    return previous['identity'] == current['identity'] and all(new.get(k) == v for k, v in old.items())


class GuidedChain(Chain):
    any_replies = True

    def __init__(self, store, choose=None, seal=None, unseal=None, responder=None):
        kwargs = {} if choose is None else dict(choose=choose)
        if seal is not None:
            kwargs['seal'] = seal
        if unseal is not None:
            kwargs['unseal'] = unseal
        # A notification is created only after a new incoming message is
        # conservatively verified as the peer's self-shared contact.
        super().__init__(store, contact_notifications=True, **kwargs)
        self.responder = responder
        self.ai_progress = None
        from assistant_ai_drafts import initialize
        initialize(store)
        self.store.ensure_tables('''CREATE TABLE IF NOT EXISTS guided_bindings(
                account TEXT, peer TEXT, chat TEXT UNIQUE, greeting_hash TEXT,
                PRIMARY KEY(account,peer))''')

    def authorized(self, who):
        who = identity(who)
        with self.store.read_connection() as db:
            row = db.execute('SELECT chat,greeting_hash FROM guided_bindings '
                             'WHERE account=? AND peer=?',
                             (who['account'], who['peer'])).fetchone()
            bound = db.execute('SELECT chat FROM chain_dialogs WHERE account=? AND peer=?',
                               (who['account'], who['peer'])).fetchone()
        if row is None or row[0] != who['chat'] or (bound and bound[0] != who['chat']):
            raise StateError('guided-binding-not-authorized')
        return row[1]

    def bind(self, snapshot, greetings, *, approved=False):
        """Read-only bindings are NOT send consent. This needs its own approval."""
        if approved is not True:
            raise StateError('guided-consent-required')
        snapshot = checked({key: snapshot[key] for key in ('identity', 'messages')})
        who, messages = snapshot['identity'], snapshot['messages']
        # Existing consent is verified afresh, without taking the global writer
        # lock just to read it. New bindings retain the original atomic writer.
        with self.store.read_connection() as db:
            bound=db.execute("""SELECT g.chat,c.chat FROM guided_bindings g LEFT JOIN chain_dialogs c
              ON c.account=g.account AND c.peer=g.peer WHERE g.account=? AND g.peer=?""",(who['account'],who['peer'])).fetchone()
        if bound:
            if bound[0]!=who['chat']:raise StateError('guided-binding-changed')
            if bound[1]!=who['chat']:raise StateError('guided-history-not-verified')
            return
        with self.store.connection() as db:
            old = db.execute('SELECT chat FROM guided_bindings WHERE account=? AND peer=?',
                             (who['account'], who['peer'])).fetchone()
            if old:
                if old[0] != who['chat']:
                    raise StateError('guided-binding-changed')
                baseline = db.execute('SELECT chat FROM chain_dialogs WHERE account=? AND peer=?',
                                      (who['account'], who['peer'])).fetchone()
                if not baseline or baseline[0] != who['chat']:
                    raise StateError('guided-history-not-verified')
                return
            # Never reset a previous chain or its unknown send reservations.
            previous = db.execute('SELECT greeting,chat FROM chain_dialogs '
                                  'WHERE account=? AND peer=?',
                                  (who['account'], who['peer'])).fetchone()
            if previous:
                greeting = next((m for m in messages if m['id'] == previous[0]), None)
                if previous[1] != who['chat'] or greeting is None:
                    raise StateError('guided-history-not-verified')
                legacy = db.execute('SELECT text_hash,status,initial_chat FROM manual_actions '
                                    'WHERE account=? AND peer=?',
                                    (who['account'], who['peer'])).fetchone()
                if (legacy is None or legacy[1] == 'not-invoked' or
                        (int(legacy[2]) > 0 and legacy[2] != who['chat']) or
                        greeting['sender'] != who['account'] or
                        not isinstance(greeting['text'], str) or
                        text_hash(greeting['text']) != legacy[0]):
                    raise StateError('guided-history-not-verified')
            else:
                # Observe the greeting BEFORE any incoming reply. The native
                # collection order and numeric message IDs are not timestamps.
                if (len(messages) != 1 or messages[0]['sender'] != who['account'] or
                        messages[0]['text'] not in greetings):
                    raise StateError('start-before-peer-reply')
                greeting = messages[0]
                # Commit the baseline in the SAME transaction as consent. A
                # crash cannot leave consent without a temporal greeting anchor.
                salt = secrets.token_hex(32)
                db.execute('INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)',
                           (who['account'], who['peer'], who['chat'],
                            greeting['id'], 'wait-reply', salt))
                db.execute('INSERT INTO chain_seen VALUES(?,?,?)',
                           (who['chat'], greeting['id'], fingerprint(greeting, salt)))
            db.execute('INSERT INTO guided_bindings VALUES(?,?,?,?)',
                       (who['account'], who['peer'], who['chat'], text_hash(greeting['text'])))

    def reset(self, snapshot, greetings, *, approved=False):
        """Explicitly replace one peer's stopped chain with one fresh greeting."""
        if approved is not True:
            raise StateError('guided-reset-consent-required')
        snapshot = checked({key: snapshot[key] for key in ('identity', 'messages')})
        who, messages = snapshot['identity'], snapshot['messages']
        if (len(messages) != 1 or messages[0]['sender'] != who['account'] or
                messages[0]['text'] not in greetings):
            raise StateError('reset-needs-one-fresh-greeting')
        greeting = messages[0]
        salt = secrets.token_hex(32)
        with self.store.connection() as db:
            for table in ('guided_bindings', 'chain_dialogs'):
                conflict = db.execute(
                    f'SELECT account,peer FROM {table} WHERE chat=?',
                    (who['chat'],)).fetchone()
                if conflict and tuple(conflict) != (who['account'], who['peer']):
                    raise StateError('guided-reset-binding-conflict')
            old_guided = db.execute(
                'SELECT chat FROM guided_bindings WHERE account=? AND peer=?',
                (who['account'], who['peer'])).fetchone()
            old_chain = db.execute(
                'SELECT chat FROM chain_dialogs WHERE account=? AND peer=?',
                (who['account'], who['peer'])).fetchone()
            chats = {who['chat']}
            chats.update(row[0] for row in (old_guided, old_chain) if row)
            for chat in chats:
                db.execute('DELETE FROM chain_contact_outbox WHERE chat=?', (chat,))
                db.execute('DELETE FROM chain_review_reasons WHERE chat=?', (chat,))
                db.execute('DELETE FROM chain_seen WHERE chat=?', (chat,))
                db.execute('DELETE FROM chain_actions WHERE chat=?', (chat,))
                db.execute('DELETE FROM chain_notifications WHERE chat=?', (chat,))
                if db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='guided_notices'").fetchone():
                    db.execute('DELETE FROM guided_notices WHERE chat=?', (chat,))
            db.execute('DELETE FROM guided_bindings WHERE account=? AND peer=?',
                       (who['account'], who['peer']))
            db.execute('DELETE FROM chain_dialogs WHERE account=? AND peer=?',
                       (who['account'], who['peer']))
            db.execute('INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)',
                       (who['account'], who['peer'], who['chat'],
                        greeting['id'], 'wait-reply', salt))
            db.execute('INSERT INTO chain_seen VALUES(?,?,?)',
                       (who['chat'], greeting['id'], fingerprint(greeting, salt)))
            db.execute('INSERT INTO guided_bindings VALUES(?,?,?,?)',
                       (who['account'], who['peer'], who['chat'],
                        text_hash(greeting['text'])))
        return True

    def proposal(self, snapshot):
        from assistant_reply_window import reason
        if reason(self.store,snapshot['identity']):return 'reply-excluded',None
        from assistant_reply_audit import observe, recycle_followup
        observe(self,snapshot)
        who = snapshot['identity']
        from shared_contact import self_shared,voluntary_batch
        from assistant_contact_receipt import requested as receipt_requested
        # One read-only snapshot for routing; consume independently revalidates
        # every safety gate under its original writer transaction below.
        with self.store.read_connection() as db:
            row=db.execute('SELECT stage FROM chain_dialogs WHERE chat=?',(who['chat'],)).fetchone()
            seen_before={r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?',(who['chat'],))}
            anchored_request=receipt_requested(db,who,snapshot['messages'])
        new_peer=[m for m in snapshot['messages'] if m['sender']==who['peer'] and m['id'] not in seen_before]
        requested=anchored_request or bool(row and row[0]=='wait-contact') or voluntary_batch(new_peer)
        if any(self_shared(m['text'],requested=requested) for m in new_peer):
            # This is only routing, NOT contact acceptance or send authority.
            # consume retains full-history hashes, refusals, third-party context,
            # terminal states, unknown sends and atomic contact persistence.
            # Do not fetch unrelated clarification/draft context first.
            stage,action=self.consume(snapshot)
            observe(self,snapshot,input_ids=[m['id'] for m in new_peer])
            return stage,action
        from assistant_contact_clarify import max_selected,selected_alternative_text,indifferent_selected
        from assistant_contact_followup import refused,scoped_messages
        from assistant_contact_policy import should_close
        from assistant_contact_budget import can_close
        max_choice=max_selected([m for m in snapshot['messages'] if m['sender']==who['peer']])
        reply_ids=[m['id'] for m in new_peer]
        contact_stage=bool(row and row[0] in ('wait-contact','pending-clarify','pending-followup'))
        # One fresh read-only transaction, not four separate round trips through
        # the cloud transaction setup. consume rechecks every gate under lock.
        with self.store.read_connection() as db:
            alt_text=selected_alternative_text(db,snapshot,reply_ids)
            refusal_inputs=scoped_messages(db,snapshot,reply_ids,requested=contact_stage)
            strict_closed=bool(row and should_close(db,snapshot,row[0],new_peer,
                requested=anchored_request or contact_stage,max_choice=max_choice,
                number_choice=indifferent_selected(db,snapshot,reply_ids)))
            budget_closed=bool(row and can_close(db,who['chat'],row[0]))
        refused_now=refused(refusal_inputs if contact_stage else new_peer,
                            requested=contact_stage,alternative_selected=max_choice or bool(alt_text))
        if refused_now or strict_closed or budget_closed:
            stage,action=self.consume(snapshot)
            from assistant_reply_audit import synchronize
            synchronize(self,snapshot)
            return stage,action
        # A terminal preference must not recycle even an observed old reply.
        recycle_followup(self,snapshot)
        with self.store.read_connection() as db:
            unapproved = {row[0] for row in db.execute(
                "SELECT kind FROM chain_actions WHERE chat=? AND status='awaiting-approval'",
                (who['chat'],))}
            seen = {r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?', (who['chat'],))}
        if unapproved:
            # Resume an unsent draft after a stop/API failure with newer peer
            # arrivals. Reserved/unknown attempts are deliberately excluded.
            for kind in unapproved.copy():
                with self.store.read_connection() as db:
                    state = db.execute('SELECT stage FROM chain_dialogs WHERE chat=?', (who['chat'],)).fetchone()
                    if not state or state[0] != 'pending-' + kind:
                        continue
                    row = db.execute('SELECT text_hash FROM chain_actions WHERE chat=? AND kind=?', (who['chat'],kind)).fetchone()
                    from assistant_ai_drafts import restore
                    text = restore(self, who['chat'], kind, row[0], connection=db, snapshot=snapshot)
                text = text or next((t for t in REPLIES if text_hash(t) == row[0]), None)
                if text is not None:
                    previous = dict(snapshot, messages=[m for m in snapshot['messages'] if m['id'] in seen])
                    if self.refresh_unsubmitted(previous, snapshot, dict(kind=kind,text=text)):
                        unapproved.discard(kind)
                        with self.store.read_connection() as db:
                            seen = {r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?', (who['chat'],))}
        reply_ids = [m['id'] for m in snapshot['messages'] if m['sender'] == who['peer'] and m['id'] not in seen]
        stage, action = self.consume(snapshot)
        observe(self,snapshot,input_ids=reply_ids)
        if ((stage == 'wait-mood' and 'question' in unapproved) or
                (stage == 'wait-contact' and 'contact' in unapproved)):
            self.mark_review(who)
            return 'manual-review', None
        with (self.store.connection() if action is not None else self.store.read_connection()) as db:
            if action is not None:
                db.execute("UPDATE chain_actions SET status='awaiting-approval' "
                           "WHERE chat=? AND kind=? AND status='reserved-unknown'",
                           (who['chat'], action['kind']))
                for message in reply_ids:
                    db.execute('INSERT OR IGNORE INTO ai_draft_inputs VALUES(?,?,?)', (who['chat'],action['kind'],message))
                if self.responder is not None:
                    # Atomically require AI BEFORE the draft can be resumed.
                    db.execute("INSERT OR IGNORE INTO ai_drafts VALUES(?,?,NULL,'needed')", (who['chat'], action['kind']))
            elif stage.startswith('pending-'):
                kind = stage.removeprefix('pending-')
                row = db.execute('SELECT text_hash,status FROM chain_actions WHERE chat=? AND kind=?',
                                 (who['chat'], kind)).fetchone()
                if row and row[1] == 'awaiting-approval':
                    from assistant_ai_drafts import restore
                    text = restore(self, who['chat'], kind, row[0], connection=db, snapshot=snapshot)
                    if text is None:
                        text = next((t for t in REPLIES if text_hash(t) == row[0]), None)
                    if text is None:
                        raise StateError('guided-template-changed')
                    action = dict(kind=kind, text=text)
                elif not row or row[1] != 'handler-returned-unconfirmed':
                    return 'submission-unknown', None
            # An outgoing not submitted after this mode's consent is ambiguous.
            if stage in ('wait-mood', 'wait-contact'):
                kind = 'question' if stage == 'wait-mood' else 'contact'
                row = db.execute('SELECT status FROM chain_actions WHERE chat=? AND kind=?',
                                 (who['chat'], kind)).fetchone()
                if not row or row[0] != 'outgoing-observed':
                    raise StateError('guided-outgoing-not-verified')
        if action is not None:
            from assistant_ai_drafts import prepare
            terminal, action = prepare(self, snapshot, action)
            if terminal is not None:
                stage = terminal
        return stage, action

    def refresh_unsubmitted(self, previous, fresh, action):
        """Replan ONLY an unsent draft after append-only peer arrivals.

        Never release reserved/unknown/handler-returned actions, infer message
        ordering, forget an outgoing message or reset a review quarantine.
        """
        if not extends_snapshot(previous, fresh):
            return False
        who = fresh['identity']; chat = who['chat']; kind = action['kind']
        self.authorized(who)
        old = {m['id']: m for m in previous['messages']}
        delta = [m for m in fresh['messages'] if m['id'] not in old]
        if not delta or any(m['sender'] != who['peer'] for m in delta):
            return False
        with self.store.connection() as db:
            state = db.execute('SELECT stage,salt FROM chain_dialogs WHERE chat=?', (chat,)).fetchone()
            row = db.execute('SELECT status,text_hash,trigger FROM chain_actions WHERE chat=? AND kind=?', (chat,kind)).fetchone()
            if (not state or state[0] != 'pending-'+kind or not row or
                    row[:2] != ('awaiting-approval', text_hash(action['text']))):
                return False
            seen = dict(db.execute('SELECT message,fingerprint FROM chain_seen WHERE chat=?', (chat,)))
            if any(k not in old or fingerprint(old[k],state[1]) != value for k,value in seen.items()):
                return False
            inputs = [r[0] for r in db.execute('SELECT message FROM ai_draft_inputs WHERE chat=? AND kind=?', (chat,kind))] or [row[2]]
            if any(k not in old or old[k]['sender'] != who['peer'] for k in inputs):
                return False
            db.execute('DELETE FROM ai_drafts WHERE chat=? AND kind=?', (chat,kind))
            db.execute('DELETE FROM ai_draft_inputs WHERE chat=? AND kind=?', (chat,kind))
            db.execute("DELETE FROM chain_actions WHERE chat=? AND kind=? AND status='awaiting-approval'", (chat,kind))
            db.executemany('DELETE FROM chain_seen WHERE chat=? AND message=?', [(chat,k) for k in inputs])
            db.execute('UPDATE chain_dialogs SET stage=? WHERE chat=?', ('wait-reply' if kind=='question' else 'wait-contact' if kind in ('clarify','followup') else 'wait-mood',chat))
        return True

    def reserve_confirmed(self, who, action):
        self.authorized(who)
        with self.store.connection() as db:
            ensure_communication_allowed(self.store,who,db=db)
            stage = db.execute('SELECT stage FROM chain_dialogs WHERE chat=?',
                               (who['chat'],)).fetchone()
            if not stage or stage[0] != 'pending-' + action['kind']:
                raise StateError('guided-stage-changed')
            cur = db.execute("UPDATE chain_actions SET status='reserved-unknown' "
                             "WHERE chat=? AND kind=? AND text_hash=? AND status='awaiting-approval'",
                             (who['chat'], action['kind'], text_hash(action['text'])))
            if cur.rowcount != 1:
                raise StateError('guided-send-already-reserved')
            if getattr(self,'retry_unknown_once',False) is True:
                from assistant_unknown_reply import reserve as reserve_unknown_retry
                reserve_unknown_retry(db,who,action)
            from assistant_send_safety import authorize
            return authorize(db,who,action)

def walk(chain, who, stopped, approve, reader, sender, *, approved=False,
         greetings=(), notifier=None, progress=lambda _: None, pause=None,
         max_polls=360, deadline=None, contact_reader=None, until_waiting=False, exit_capture=None, contact_photo=None, snapshot_capture=None,
         read_clock=time.monotonic):
    """Monitor ONE open chat through both replies; all bodies remain in RAM.

    until_waiting=True is used by the inbox pass: once the chat needs a NEW
    peer message, leave it (status chain-waiting) instead of polling it.
    """
    from assistant_history_wait import verified_oversized, HistorySnapshotTooLarge
    out = report()
    out.update(flags(approve))
    if approved is not True:
        out.update(reason='guided-consent-required')
        return out
    pause = stopped.wait if pause is None else pause
    who = identity(who)
    progress('Проверяю журнал диалога.')
    def observed_actions():
        with chain.store.read_connection() as db:
            return {row[0] for row in db.execute(
                "SELECT kind FROM chain_actions WHERE chat=? AND status='outgoing-observed'",
                (who['chat'],))}
    observed_at_start = timed(out['diagnostics'], 'bind', observed_actions)
    host_checkpoint='chat-read'
    def read(source=reader, *, keep_latest=False):
        nonlocal host_checkpoint
        host_checkpoint='chat-read'
        if stopped.is_set():
            raise StateError('cancelled')
        from one_chat_device import ReadStopped, safe_read_failure, transient_read_failure
        started = read_clock()
        read_deadline=started+getattr(chain,'history_read_budget',float('inf'))
        def deadline_expired():
            # Preserve the last fixed-reader evidence. A host timer alone is
            # NOT identity proof and cannot authorize a local Back or a send.
            if verified_loading(out['diagnostics'].get('last_read_failure')):
                out['diagnostics']['history_wait_exhausted']=True
                raise HistoryWaitExpired()
            out['diagnostics']['history_budget_exhausted']=True
            raise HistoryReadBudgetExpired()
        soft_retries = 0
        budget_failures = 0
        for attempt in range(MAX_READ_ATTEMPTS):
            if read_clock()>=read_deadline:deadline_expired()
            try:
                progress('Читаю историю • проверяю текущий чат.')
                with collect_read_timings(out['diagnostics'], progress):
                    from assistant_read_budget import limit
                    with limit(min(25,read_deadline-read_clock())):
                        private = timed(out['diagnostics'], 'read', source, who)  # Fresh SAME-bound read, never cached.
                break
            except Exception as error:
                if read_clock()>=read_deadline and type(error).__name__ in ('OperationCancelledError','CancelledError','TimedOutError'):
                    deadline_expired()
                if not isinstance(error,ReadStopped):raise

                failure = out['diagnostics']['last_read_failure'] = safe_read_failure(error)
                if stopped.is_set():
                    raise StateError('cancelled')
                from assistant_history_wait import verified_message_invalid, HistoryMessageInvalid
                if verified_message_invalid(failure):
                    # Preserve this exact read's type and evidence. Never use a
                    # stale last_read_failure to reinterpret a later StateError.
                    raise HistoryMessageInvalid() from None
                if verified_oversized(failure):
                    out['diagnostics']['history_snapshot_oversized']=True
                    raise HistorySnapshotTooLarge() from None
                loading = verified_loading(failure)
                if verified_read_budget(failure):
                    budget_failures += 1
                    if budget_failures >= (2 if failure.get("error") == "transition-timeout" else BUDGET_READ_ATTEMPTS) or attempt == MAX_READ_ATTEMPTS-1:
                        out['diagnostics']['history_budget_exhausted'] = True
                        raise HistoryReadBudgetExpired() from None
                    delay = BUDGET_RETRY_INTERVAL
                elif loading:
                    remaining = WAIT_SECONDS - (read_clock()-started)
                    if remaining <= 0 or attempt == MAX_READ_ATTEMPTS-1:
                        out['diagnostics']['history_wait_exhausted'] = True
                        raise HistoryWaitExpired() from None
                    delay = min(WAIT_INTERVAL, remaining)
                else:
                    # Keep the previous single read-only retry for other authored
                    # transient states. Identity/transport/schema failures never retry.
                    if soft_retries or not transient_read_failure(error):
                        raise
                    soft_retries += 1
                    delay = .5
                out['diagnostics']['read_retries'] += 1
                from one_chat_device import verified_early_wrong_screen
                progress('Экран чата ещё не подтверждён. Повторяю только чтение; отправки нет.' if verified_early_wrong_screen(failure) else
                         'Повторяю только чтение того же чата; отправки нет.' if verified_read_budget(failure) else
                         'История ещё загружается. Жду тот же чат; отправки нет.')
                delay=min(delay,max(0,read_deadline-read_clock()))
                if delay<=0:deadline_expired()
                if pause(delay) or stopped.is_set():
                    raise StateError('cancelled')
                if loading and read_clock()-started >= WAIT_SECONDS:
                    out['diagnostics']['history_wait_exhausted'] = True
                    raise HistoryWaitExpired() from None
        else:
            raise ValueError('Read attempt bound exceeded')
        if (not isinstance(private, dict) or
                not {'identity','messages'} <= set(private) or
                set(private) - {'identity','messages','peer_name','latest_message_id','input_enabled'}):
            raise ValueError('Invalid private snapshot fields')
        if identity(private['identity']) != who:
            raise StateError('guided-binding-changed')
        value = checked({key: private[key] for key in ('identity', 'messages')})
        if 'input_enabled' in private:
            if type(private['input_enabled']) is not bool:
                raise ValueError('Invalid input state')
            if not private['input_enabled']:
                out['diagnostics']['input_disabled_verified']=True
                raise StateError('chat-input-disabled')
        from mumu_namespace import ensure_account
        ensure_account(chain.store,value['identity'])
        if snapshot_capture is not None:
            snapshot_capture(checked({key:value[key] for key in ('identity','messages')}))
        if 'peer_name' in private:
            value['peer_name'] = private['peer_name']
        if keep_latest and 'latest_message_id' in private:
            value['latest_message_id']=private['latest_message_id']
        return value
    from assistant_runtime import collect as runtime_collect
    runtime_scope=runtime_collect(out['diagnostics'],progress)
    runtime_scope.__enter__()
    previous_ai_progress = chain.ai_progress
    chain.ai_progress = progress
    try:
        before = read(keep_latest=True)
        progress('История прочитана • сверяю журнал диалога.')
        host_checkpoint='chat-bind'
        timed(out['diagnostics'], 'bind', chain.bind, before, greetings, approved=True)
        from assistant_contact_receipt import reviewable,reconcile
        with chain.store.read_connection() as db:
            contact_review=reviewable(db,who['chat'])
        if contact_review:
            fresh=read(contact_reader if contact_reader is not None else reader,keep_latest=True)
            if chain.contact_notifications and 'peer_name' not in fresh:fresh['peer_name']='не определено'
            host_checkpoint='chat-contact-reconcile'
            out['diagnostics']['contact_review_reconciled']=reconcile(chain,before,fresh)
            before=fresh
        from assistant_selection_recovery import reserve as reserve_selection,recover as recover_selection
        if reserve_selection(chain,who):
            progress('Проверяю старый статус • уточняю выбор мессенджера.')
            fresh=read(keep_latest=True)
            recover_selection(chain,before,fresh)
            before=fresh
        before.pop('latest_message_id',None)
        out['diagnostics']['legacy_stage_recovered']=getattr(chain,'last_legacy_recovered',False) is True
        out['diagnostics']['legacy_recovery_reason']=getattr(chain,'legacy_recovery_reason','not-applicable')
        pending_polls = 0
        # v1.3.96: set right after a successful send in until_waiting mode -
        # the next loop iteration performs the single quick-check leave.
        leave_after_send_check = False
        from assistant_reply_audit import DDL as receipts_schema
        chain.store.ensure_tables(receipts_schema)
        for _ in range(max_polls):
            if stopped.is_set():
                break
            if deadline is not None and time.monotonic() >= deadline:
                out.update(status='chain-paused', reason='wait-timeout')
                return out
            # v1.3.83: seen ids, pending reply receipts and the saved-receipt
            # probe all describe the SAME journal state, so one read-only
            # transaction answers all three. The former three separate blocks
            # each paid a full cloud transaction preamble per poll iteration
            # of every open dialog. Values and their ordering are unchanged;
            # only the round trips are gone. The receipts table initializer is
            # ensured once above, exactly where pending() used to create it.
            with chain.store.read_connection() as db:
                seen_ids={r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?',(who['chat'],))}
                unanswered_ids={r[0] for r in db.execute(
                    "SELECT message FROM chain_reply_receipts WHERE chat=? AND status='pending'",(who['chat'],))}
                saved_receipt=db.execute("""SELECT 1 FROM chain_dialogs c JOIN chain_contact_outbox o ON o.chat=c.chat
                    WHERE c.account=? AND c.peer=? AND c.chat=? AND c.stage='done' AND o.status='pending'""",
                    (who['account'],who['peer'],who['chat'])).fetchone() is not None
            excerpts=[m['text'] if isinstance(m['text'],str) else '[нет текста]' for m in before['messages'] if m['sender']==who['peer'] and (m['id'] not in seen_ids or m['id'] in unanswered_ids)]
            if excerpts and exit_capture is not None:exit_capture(excerpts)
            try:
                # Deliver ONLY an already saved receipt; a global send ban must
                # not strand its pending photo forever. Never run proposal/AI or
                # authorize a new message through this receipt-only path.
                if saved_receipt:
                    stage, action = 'done', None
                    out['diagnostics']['saved_receipt_only']=True
                else:
                    ensure_communication_allowed(chain.store,who)
                    from assistant_unknown_reply import candidate as unknown_candidate,recover as recover_unknown
                    if unknown_candidate(chain,who):
                        progress('Проверяю неизвестный исход • заново читаю тот же чат.')
                        fresh=read()
                        recovery=recover_unknown(chain,before,fresh)
                        if recovery=='prepared':
                            progress('Ответ не найден • подготовлена одна повторная попытка; возможен дубль.')
                        elif recovery=='observed':
                            progress('Ответ найден в истории • повтор не нужен.')
                        before=fresh
                    host_checkpoint='chat-proposal'
                    stage, action = timed(out['diagnostics'], 'proposal', chain.proposal, before)
            except StateError as error:
                if str(error) != 'contact-name-required':
                    raise
                out['diagnostics']['name_read'] = 'attempted'
                named = None
                if contact_reader is not None:
                    try:
                        candidate = read(contact_reader)
                        display_name(candidate.get('peer_name'))
                        named = candidate
                    except Exception:
                        # No exception text, private bodies or names enter reports.
                        out['diagnostics']['name_read'] = 'unavailable'
                if stopped.is_set():
                    raise StateError('cancelled')
                if named is None:
                    # Re-read the normal bound snapshot before using an explicit
                    # unknown-name label; never weaken identity/history checks.
                    named = read()
                    named['peer_name'] = 'не определено'
                    out['diagnostics']['name_source'] = 'unavailable-label'
                    out['diagnostics']['name_read'] = 'unavailable'
                else:
                    out['diagnostics']['name_source'] = 'bound-chat'
                    out['diagnostics']['name_read'] = 'verified'
                if not extends_snapshot(before, named):
                    raise StateError('guided-contact-history-changed')
                before = named
                stage, action = timed(out['diagnostics'], 'proposal', chain.proposal, before)
            out['stage'] = stage
            out['stages']['greeting'] = True
            with chain.store.read_connection() as db:
                observed = dict(db.execute('SELECT kind,status FROM chain_actions WHERE chat=?',
                                           (who['chat'],)))
            out['stages']['peer_greeting'] = 'question' in observed
            out['stages']['question'] = observed.get('question') == 'outgoing-observed'
            out['stages']['peer_reply'] = 'contact' in observed
            out['stages']['contact_request'] = observed.get('contact') == 'outgoing-observed'
            out['stages']['peer_contact'] = stage == 'done'
            out['outgoing_observed'] = sum(out['stages'][k] for k in ('question', 'contact_request'))
            out['outgoing_observed_this_run'] = len(
                {kind for kind, status in observed.items() if status == 'outgoing-observed'}
                - observed_at_start)
            if stage == 'reply-excluded':
                out.update(status='chain-waiting',reason='reply-excluded')
                return out
            if stage == 'submission-unknown':
                out.update(reason='send-outcome-unknown')
                return out
            if stage == 'done':
                progress('Контакт получен • сохранён в очереди.')
                if chain.media_required and notifier is not None:
                    try:
                        host_checkpoint='chat-contact-photo'
                        progress('Контакт получен • получаю проверенное фото профиля.')
                        timed(out['diagnostics'], 'media', chain.prepare_media, who, contact_photo)
                    except Exception as error:
                        from assistant_contact_photo import ProfilePhotoNotStarted, ProfileReturnUnverified
                        if isinstance(error, (ProfilePhotoNotStarted, ProfileReturnUnverified)):
                            out['diagnostics']['photo_failure']=error.diagnostic
                        if str(error) in ('profile-return-not-verified','cancelled'):raise
                        out.update(status='chain-waiting',reason='contact-photo-unavailable')
                        return out
                host_checkpoint='chat-contact-notify'
                progress('Контакт получен • отправляю уведомление.')
                notification = timed(out['diagnostics'], 'notify', chain.notify, who, notifier, stopped.is_set)
                if notification == 'cancelled':
                    break
                if notification == 'nothing-pending':
                    with chain.store.read_connection() as db:
                        previous = db.execute(
                            'SELECT status FROM chain_contact_outbox WHERE chat=?',
                            (who['chat'],)).fetchone()
                    if previous and previous[0] in ('unknown', 'attempted-unknown'):
                        notification = 'previous-unknown'
                    elif previous and previous[0] == 'blocked':
                        notification = 'blocked'
                if notification in out['notifications']:
                    out['notifications'][notification] += 1
                attempted = notification in ('accepted', 'unknown')
                out['telegram_used'] = attempted
                out['personal_data_exported'] = attempted
                if notification == 'queued':
                    out.update(status='chain-completed',reason='contact-notification-queued')
                elif notification == 'accepted':
                    out.update(status='chain-completed', reason='contact-forwarded')
                elif notification == 'nothing-pending':
                    out.update(status='chain-completed', reason='contact-already-handled')
                else:
                    out.update(status='chain-needs-review',
                               reason='telegram-disabled' if notification == 'disabled' else
                               'contact-payload-blocked' if notification == 'blocked' else
                               'telegram-outcome-unknown')
                return out
            if stage in TERMINAL:
                if stage == 'manual-review':
                    out['diagnostics']['review_cause'] = chain.review_reason(who)
                out.update(status='chain-needs-review', reason=stage)
                return out
            if (until_waiting and action is None and
                    stage in ('wait-reply', 'wait-mood', 'wait-contact')) or leave_after_send_check:
                wait_reason=stage
                if stage == 'wait-contact' and observed.get('clarify') == 'outgoing-observed':
                    wait_reason='contact-clarification-sent'
                if stage == 'wait-contact' and observed.get('followup') == 'outgoing-observed':
                    wait_reason='contact-followup-sent'
                if leave_after_send_check and stage.startswith('pending-'):
                    # The one quick check did not observe our outgoing: the
                    # receipt keeps its unconfirmed status and the chat is
                    # re-checked by the next pass (attention/unknown-recovery),
                    # exactly like the former three-poll exhaustion - just
                    # without sitting in the open chat between the checks.
                    wait_reason='outgoing-not-observed'
                from assistant_reply_audit import synchronize,pending
                synchronize(chain,before)
                if until_waiting and out['submission_calls'] and (out['outgoing_observed_this_run'] or leave_after_send_check):
                    # This bound read already took two complete native samples
                    # AFTER send. Don't take a third full history before Back.
                    out['diagnostics']['post_send_checked']=True
                if out['submission_calls'] and not out['diagnostics'].get('post_send_checked'):
                    fresh=read()
                    out['diagnostics']['post_send_checked']=True
                    if not same_snapshot(before,fresh):
                        if not extends_snapshot(before,fresh):raise StateError('guided-contact-history-changed')
                        before=fresh
                        continue
                remaining=pending(chain,who)
                out['unanswered_messages']=len(remaining)
                if remaining:
                    wait_reason='incoming-answer-pending'
                    if exit_capture is not None:
                        exit_capture([m['text'] if isinstance(m['text'],str) else '[нет текста]' for m in before['messages'] if m['id'] in remaining and m['sender']==who['peer']])
                out.update(status='chain-waiting', reason=wait_reason)
                return out
            if action is not None:
                progress('Подготовлен ответ по контексту.' if action['kind'] == 'followup' else
                         'Подготовлено уточнение контакта.' if action['kind'] == 'clarify' else
                         'Подготовлен вопрос.' if action['kind'] == 'question' else
                         'Подготовлено предложение перейти в мессенджер.')
                if stopped.is_set():
                    break
                if timed(out['diagnostics'], 'pacing', approve, action['kind'], action['text'], stopped.is_set) is not True:
                    out.update(status='chain-paused', reason='message-not-approved')
                    return out
                out['automatic_authorizations' if out['automatic_send'] else 'confirmations'] += 1
                if stopped.is_set():
                    break
                fresh = read()
                if not same_snapshot(before, fresh):
                    if chain.refresh_unsubmitted(before, fresh, action):
                        out['diagnostics']['incoming_draft_refreshes'] = out['diagnostics'].get('incoming_draft_refreshes', 0) + 1
                        before = fresh
                        if out['diagnostics']['incoming_draft_refreshes'] >= 3:
                            out.update(status='chain-waiting', reason='incoming-burst-pending',
                                       stage='wait-reply' if action['kind']=='question' else 'wait-contact' if action['kind'] in ('clarify','followup') else 'wait-mood')
                            return out
                        continue
                    chain.mark_review(who)
                    out.update(reason='history-changed-during-approval')
                    return out
                from assistant_reply_window import reason as reply_exclusion
                if reply_exclusion(chain.store,who):
                    out.update(status='chain-waiting',reason='reply-excluded')
                    return out
                # Read-only metadata (e.g. optional peer_name) is not part of
                # the native send contract. Validate/project BEFORE reservation;
                # the strict sender still accepts only identity and full history.
                submission_snapshot=checked({key:fresh[key] for key in ('identity','messages')})
                host_checkpoint='chat-send'
                send_authorization = chain.reserve_confirmed(who, action)
                if stopped.is_set():
                    # This control path never entered begin()/sender. Do not
                    # manufacture an unknown send merely because Stop arrived.
                    from assistant_send_safety import defer_unstarted
                    defer_unstarted(chain,send_authorization,who,action)
                    break
                out['submission_calls'] += 1
                send_failure = None
                input_disabled = False
                try:
                    from assistant_send_safety import submit_checked
                    result, deferred = timed(out['diagnostics'],'submit',submit_checked,chain,send_authorization,who,action,submission_snapshot,
                        sender,stopped,progress,out['diagnostics'])
                    if deferred:
                        # A new incoming may arrive between the host read and
                        # native preflight. Replan only this proven UNSENT draft,
                        # with fresh full history/approval. Never release unknowns.
                        if (not stopped.is_set() and out['diagnostics'].get('last_send_failure')=='submission-snapshot-changed'
                                and out['diagnostics'].get('send_snapshot_refreshes',0)<2):
                            renewed=read()
                            if chain.refresh_unsubmitted(fresh,renewed,action):
                                out['diagnostics']['send_snapshot_refreshes']=out['diagnostics'].get('send_snapshot_refreshes',0)+1
                                before=renewed
                                continue
                        out.update(status='chain-waiting',reason='send-preflight-deferred')
                        return out
                    returned = (isinstance(result, dict) and result.get('attempted') is True
                                and result.get('handler_returned') is True)
                    if isinstance(result,dict):
                        for source_key,diagnostic_key in (('attempted','submission_attempted'),('handler_returned','submission_returned')):
                            if type(result.get(source_key)) is bool:out['diagnostics'][diagnostic_key]=result[source_key]
                    from one_chat_send import input_disabled_before_submission
                    input_disabled = input_disabled_before_submission(result)
                    native = result.get('native_check') if isinstance(result, dict) else None
                    if isinstance(native, dict):
                        from one_chat_send import ERRORS as SEND_ERRORS
                        code = native.get('error')
                        if isinstance(code, str) and code in SEND_ERRORS and code not in {
                                'none', 'managed-exception', 'submission-already-attempted'}:
                            send_failure = 'send-native-check-failed'
                            out['diagnostics']['last_send_failure'] = code
                except PeerCommunicationBlocked:
                    raise  # Denied before adapter: never mislabel this as an unknown send.
                except Exception as send_error:
                    from assistant_failure import category,evidence
                    out['diagnostics']['send_host_failure']=category(send_error)
                    native=evidence(send_error)
                    if native:out['diagnostics']['send_transport_failure']=native
                    from one_chat_device import ReadStopped
                    if isinstance(send_error, ReadStopped):
                        send_failure = 'send-device-check-failed'
                    elif isinstance(send_error, ValueError):
                        send_failure = 'send-validation-failed'
                    returned = False
                    out['diagnostics']['failure_point'] = 'send-adapter-exception'
                if not returned and out['diagnostics']['failure_point'] == 'none':
                    out['diagnostics']['failure_point'] = 'send-handler-unconfirmed'
                out['handler_returns'] += int(returned)
                chain.finish(who, action, returned)
                out['diagnostics']['post_send_checked']=False
                if input_disabled:
                    # Keep the committed reservation conservative; never release
                    # or replay it. Only this validated call did not invoke send.
                    out['diagnostics']['input_disabled_verified']=True
                    out['diagnostics']['failure_point']='chat-input-disabled'
                    out.update(status='chain-needs-review',reason='chat-input-disabled')
                    return out
                if send_failure is not None:
                    out['diagnostics']['failure_point'] = send_failure
                    out.update(reason=send_failure)
                    return out
                if not returned:
                    out.update(reason='send-outcome-unknown')
                    return out
                if until_waiting:
                    # v1.3.96 «быстрая проверка отправки → сразу выхожу из
                    # чата»: after a successful send the inbox walk performs
                    # exactly ONE post-send verification read (the loop tail
                    # below) and then leaves the chat - never three pending
                    # polls, never a same-visit re-plan. Sitting in the open
                    # chat invites exactly the fast peer reply that would be
                    # left unread by the exit; her reply (already in the check
                    # read or arriving after it) keeps its unanswered state and
                    # the NEXT pass re-opens the row - which since v1.3.96
                    # admits by the genuinely NEW incoming message, badge or
                    # not. A draft her reply reserved is resumed by the
                    # attention machinery of the next pass, never re-sent blind.
                    leave_after_send_check=True
                pending_polls = 0
            elif stage.startswith('pending-'):
                if until_waiting and out['submission_calls']:
                    # Defensive twin of the flag above: a send this run plus a
                    # still-pending stage means the quick check already ran -
                    # leave instead of polling the open chat three more times.
                    out.update(status='chain-waiting', reason='outgoing-not-observed')
                    return out
                pending_polls += 1
                if pending_polls >= 3:
                    out.update(reason='outgoing-not-observed')
                    return out
            else:
                pending_polls = 0
            progress({'wait-reply': 'Жду приветствие собеседника.',
                      'wait-mood': 'Вопрос виден в истории. Жду ответ собеседника.',
                      'wait-contact': 'Предложение видно в истории. Жду контакт собеседника.',
                      'pending-question': 'Сверяю отправленный вопрос с историей → затем следующий чат.',
                      'pending-contact': 'Сверяю отправленное предложение с историей → затем следующий чат.'
                      }.get(stage, 'Проверяю подтверждённое состояние чата.'))
            # Inbox processing never waits for a new peer message. After send,
            # a fresh bound read itself observes native/UI progress; with the
            # v1.3.96 quick exit this ONE read is the whole post-send check,
            # without the artificial 5s sleep and without further polls.
            if stopped.is_set() or (not until_waiting and pause(5)):
                break
            before = read()
        else:
            out.update(status='chain-paused', reason='wait-timeout')
            return out
        out.update(status='chain-cancelled', reason='cancelled')
    except PeerCommunicationBlocked:
        out['diagnostics']['failure_point']='peer-contact-blocked'
        out.update(status='chain-waiting',reason='peer-contact-blocked')
    except HistorySnapshotTooLarge:
        out['diagnostics']['failure_point']='history-snapshot-too-large'
        out.update(status='chain-cancelled' if stopped.is_set() else 'chain-waiting',
                   reason='cancelled' if stopped.is_set() else 'history-snapshot-too-large')
    except HistoryMessageInvalid:
        out['diagnostics']['failure_point'] = 'message-invalid'
        out.update(status='chain-cancelled' if stopped.is_set() else 'chain-needs-review',
                   reason='cancelled' if stopped.is_set() else 'message-invalid')
    except HistoryReadBudgetExpired:
        out['diagnostics']['failure_point'] = 'history-read-budget-timeout'
        out.update(status='chain-cancelled' if stopped.is_set() else 'chain-waiting',
                   reason='cancelled' if stopped.is_set() else 'history-read-budget-timeout')
    except HistoryWaitExpired:
        out['diagnostics']['failure_point'] = 'history-loading-timeout'
        out.update(status='chain-cancelled' if stopped.is_set() else 'chain-waiting',
                   reason='cancelled' if stopped.is_set() else 'history-loading-timeout')
    except ReviewRequired as error:
        anchor=getattr(error,'anchor_reason',None)
        if anchor in ('multiple-own','missing-own','hash-mismatch'):
            out['diagnostics']['greeting_anchor_failure']=anchor
        out.update(status='chain-needs-review', reason='greeting-not-verified')
    except Exception as error:
        if (isinstance(error,StateError) and str(error)=='chat-input-disabled'
                and out['diagnostics'].get('input_disabled_verified') is True):
            out['diagnostics']['failure_point']='chat-input-disabled'
            out.update(status='chain-needs-review',reason='chat-input-disabled')
            return out
        from assistant_failure import category,evidence
        from cloud_database import diagnostic as database_diagnostic
        database=database_diagnostic(error)
        if database:out['diagnostics']['database']=database
        out['diagnostics']['host_failure']=category(error)
        out['diagnostics']['host_checkpoint']=host_checkpoint
        from startup_failure import TYPES
        error_type=type(error).__name__
        out['diagnostics']['error_type']=error_type if error_type in TYPES | {'ReadStopped','StateError','IntegrityError','OperationalError','DatabaseError','AttributeError'} else 'OtherError'
        native=evidence(error)
        if native:out['diagnostics']['last_navigation_failure']=native
        # Only fixed, authored categories; no arbitrary native exception text.
        allowed = {'account-owned-by-other-scope','start-before-peer-reply', 'guided-binding-changed',
                   'guided-history-not-verified', 'guided-consent-required'}
        allowed |= {'guided-contact-history-changed', 'contact-name-required',
                    'contact-protection-failed', 'contact-payload-invalid',
                    'contact-limit-exceeded', 'guided-binding-not-authorized',
                    'guided-outgoing-not-verified', 'profile-return-not-verified'}
        from groq_reply import ERRORS as GROQ_ERRORS
        allowed |= GROQ_ERRORS
        reason = str(error) if isinstance(error, StateError) and str(error) in allowed else 'binding-or-history-check-stopped'
        from assistant_key_pool import RETRY_SUFFIXES
        suffix=reason.split('-',1)[1] if '-' in reason else ''
        if suffix in RETRY_SUFFIXES - {'unsafe-reply','repeat-greeting','invalid-response'} or suffix=='key-pool-exhausted':
            out['diagnostics']['failure_point']=reason
            from mumu_ai import safe_failures
            out['diagnostics']['ai_failures']=safe_failures(chain.responder)
            out.update(status='chain-waiting',reason='ai-temporarily-unavailable')
            return out
        # Fixed, non-private categories distinguish transport from contact storage.
        if reason == 'binding-or-history-check-stopped':
            from one_chat_device import ReadStopped
            if isinstance(error, ReadStopped):
                reason = 'bound-chat-read-failed'
            elif isinstance(error, ValueError):
                reason = 'snapshot-validation-failed'
        out['diagnostics']['failure_point'] = reason
        out.update(status='chain-cancelled' if stopped.is_set() else 'chain-stopped',
                   reason='cancelled' if stopped.is_set() else reason)
    finally:
        chain.ai_progress = previous_ai_progress
        runtime_scope.__exit__(None,None,None)
    return out


def write_report(value):
    folder = data_directory()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'messages-chain-check.json'
    temporary = path.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path.name


def run_reset(settings, stopped, *, approved=False, store=None, reader=None,
              greetings=None):
    """Reset only the explicitly open peer after verifying one fresh greeting."""
    from assistant_lock import operation_lock
    from assistant_config import load
    from one_chat_device import capture
    if approved is not True or stopped.is_set():
        return dict(tool_version=VERSION, status='reset-cancelled',
                    reason='cancelled' if stopped.is_set() else
                    'guided-reset-consent-required')
    with operation_lock():
        try:
            greetings = load().greetings if greetings is None else greetings
            reader = capture if reader is None else reader
            private = reader(settings.adb, settings.folder, stopped.is_set, None)
            if set(private) != {'identity', 'messages'} or private['messages'] is not None:
                raise StateError('guided-identity-not-verified')
            who = identity(private['identity'])
            fresh = reader(settings.adb, settings.folder, stopped.is_set, who)
            if stopped.is_set():
                raise StateError('cancelled')
            chain = GuidedChain(Store() if store is None else store)
            chain.reset(fresh, greetings, approved=True)
            return dict(tool_version=VERSION, status='reset-completed',
                        reason='fresh-greeting-bound')
        except Exception as error:
            allowed = {'reset-needs-one-fresh-greeting',
                       'guided-reset-binding-conflict', 'cancelled'}
            reason = str(error) if isinstance(error, StateError) and \
                str(error) in allowed else 'reset-device-or-history-check-stopped'
            return dict(tool_version=VERSION,
                        status='reset-cancelled' if reason == 'cancelled' else
                        'reset-stopped', reason=reason)


def run(settings, stopped, approve, progress=lambda _: None, *, approved=False,
        store=None, reader=None, sender=None, notifier=None, greetings=None):
    from assistant_lock import operation_lock
    from assistant_config import load
    from one_chat_device import capture
    from one_chat_send_device import submit
    import telegram_notify
    if approved is not True or stopped.is_set():
        return dict(report(), reason='cancelled' if stopped.is_set() else 'guided-consent-required')
    with operation_lock():
        try:
            if not settings.contacts_enabled:
                raise StateError('telegram-disabled')
            if notifier is None:
                token, chat_id = telegram_notify.load()
                notifier = lambda payload: telegram_notify.send_contact(token, chat_id, payload)
            greetings = load().greetings if greetings is None else greetings
            reader = capture if reader is None else reader
            sender = submit if sender is None else sender
            private = reader(settings.adb, settings.folder, stopped.is_set, None)
            if set(private) != {'identity', 'messages'} or private['messages'] is not None:
                raise StateError('guided-identity-not-verified')
            who = identity(private['identity'])
            chain = GuidedChain(Store() if store is None else store)
            value = walk(chain, who, stopped, approve,
                         lambda expected: reader(settings.adb, settings.folder,
                                                 stopped.is_set, expected),
                         lambda snapshot, text: sender(settings.adb, settings.folder, snapshot,
                                                       stopped.is_set, text=text),
                         approved=True, greetings=greetings, notifier=notifier, progress=progress,
                         deadline=time.monotonic() + 1800,
                         contact_reader=lambda expected: reader(
                             settings.adb, settings.folder, stopped.is_set,
                             expected, read_name=True))
        except Exception as error:
            value = report()
            value.update(reason='telegram-disabled' if isinstance(error, StateError) and
                         str(error) == 'telegram-disabled' else 'settings-or-device-check-stopped')
        value['report_name'] = write_report(value)
        return value