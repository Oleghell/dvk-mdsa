"""One explicitly selected chat, the complete chain, per-message confirmation.

The existing read-only Start is untouched. No profile search, name collection,
contact export, send retries or chronology inferred from list positions.
"""
import json
import secrets
import time

from assistant_chain import Chain, ReviewRequired, REPLIES, TERMINAL, text_hash, fingerprint
from assistant_store import Store, StateError, data_directory
from one_chat_probe import identity
from one_chat_send import checked
from conversation_engine import CONTACT_TEXT
from shared_contact import display_name

from version import VERSION
from assistant_authorization import flags
from assistant_history_wait import (verified_loading, HistoryWaitExpired, WAIT_SECONDS,
                                    WAIT_INTERVAL, MAX_READ_ATTEMPTS)


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
                                 failure_point='none', read_retries=0, last_read_failure=None, history_wait_exhausted=False),
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
        from assistant_ai_drafts import initialize
        initialize(store)
        with self.store.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS guided_bindings(
                account TEXT, peer TEXT, chat TEXT UNIQUE, greeting_hash TEXT,
                PRIMARY KEY(account,peer))''')

    def authorized(self, who):
        who = identity(who)
        with self.store.connection() as db:
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
        who = snapshot['identity']
        with self.store.connection() as db:
            unapproved = {row[0] for row in db.execute(
                "SELECT kind FROM chain_actions WHERE chat=? AND status='awaiting-approval'",
                (who['chat'],))}
        with self.store.connection() as db:
            seen = {r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?', (who['chat'],))}
        if unapproved:
            # Resume an unsent draft after a stop/API failure with newer peer
            # arrivals. Reserved/unknown attempts are deliberately excluded.
            for kind in unapproved.copy():
                with self.store.connection() as db:
                    state = db.execute('SELECT stage FROM chain_dialogs WHERE chat=?', (who['chat'],)).fetchone()
                    if not state or state[0] != 'pending-' + kind:
                        continue
                    row = db.execute('SELECT text_hash FROM chain_actions WHERE chat=? AND kind=?', (who['chat'],kind)).fetchone()
                    from assistant_ai_drafts import restore
                    text = restore(self, who['chat'], kind, row[0], connection=db)
                text = text or next((t for t in REPLIES if text_hash(t) == row[0]), None)
                if text is not None:
                    previous = dict(snapshot, messages=[m for m in snapshot['messages'] if m['id'] in seen])
                    if self.refresh_unsubmitted(previous, snapshot, dict(kind=kind,text=text)):
                        unapproved.discard(kind)
                        with self.store.connection() as db:
                            seen = {r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?', (who['chat'],))}
        reply_ids = [m['id'] for m in snapshot['messages'] if m['sender'] == who['peer'] and m['id'] not in seen]
        stage, action = self.consume(snapshot)
        if ((stage == 'wait-mood' and 'question' in unapproved) or
                (stage == 'wait-contact' and 'contact' in unapproved)):
            self.mark_review(who)
            return 'manual-review', None
        with self.store.connection() as db:
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
                    text = restore(self, who['chat'], kind, row[0], connection=db)
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
            db.execute('UPDATE chain_dialogs SET stage=? WHERE chat=?', ('wait-reply' if kind=='question' else 'wait-contact' if kind=='clarify' else 'wait-mood',chat))
        return True

    def reserve_confirmed(self, who, action):
        self.authorized(who)
        with self.store.connection() as db:
            stage = db.execute('SELECT stage FROM chain_dialogs WHERE chat=?',
                               (who['chat'],)).fetchone()
            if not stage or stage[0] != 'pending-' + action['kind']:
                raise StateError('guided-stage-changed')
            cur = db.execute("UPDATE chain_actions SET status='reserved-unknown' "
                             "WHERE chat=? AND kind=? AND text_hash=? AND status='awaiting-approval'",
                             (who['chat'], action['kind'], text_hash(action['text'])))
            if cur.rowcount != 1:
                raise StateError('guided-send-already-reserved')

def walk(chain, who, stopped, approve, reader, sender, *, approved=False,
         greetings=(), notifier=None, progress=lambda _: None, pause=None,
         max_polls=360, deadline=None, contact_reader=None, until_waiting=False, exit_capture=None, contact_photo=None,
         read_clock=time.monotonic):
    """Monitor ONE open chat through both replies; all bodies remain in RAM.

    until_waiting=True is used by the inbox pass: once the chat needs a NEW
    peer message, leave it (status chain-waiting) instead of polling it.
    """
    out = report()
    out.update(flags(approve))
    if approved is not True:
        out.update(reason='guided-consent-required')
        return out
    pause = stopped.wait if pause is None else pause
    who = identity(who)
    with chain.store.connection() as db:
        observed_at_start = {row[0] for row in db.execute(
            "SELECT kind FROM chain_actions WHERE chat=? AND status='outgoing-observed'",
            (who['chat'],))}
    def read(source=reader):
        if stopped.is_set():
            raise StateError('cancelled')
        from one_chat_device import ReadStopped, safe_read_failure, transient_read_failure
        started = read_clock()
        soft_retries = 0
        for attempt in range(MAX_READ_ATTEMPTS):
            try:
                private = source(who)  # Every native read independently rechecks the SAME bound identity.
                break
            except ReadStopped as error:
                failure = out['diagnostics']['last_read_failure'] = safe_read_failure(error)
                if stopped.is_set():
                    raise StateError('cancelled')
                loading = verified_loading(failure)
                if loading:
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
                progress('История ещё загружается. Жду тот же чат; отправки нет.')
                if pause(delay) or stopped.is_set():
                    raise StateError('cancelled')
                if loading and read_clock()-started >= WAIT_SECONDS:
                    out['diagnostics']['history_wait_exhausted'] = True
                    raise HistoryWaitExpired() from None
        else:
            raise ValueError('Read attempt bound exceeded')
        if (not isinstance(private, dict) or
                set(private) not in ({'identity', 'messages'},
                                     {'identity', 'messages', 'peer_name'})):
            raise ValueError('Invalid private snapshot fields')
        if identity(private['identity']) != who:
            raise StateError('guided-binding-changed')
        value = checked({key: private[key] for key in ('identity', 'messages')})
        if 'peer_name' in private:
            value['peer_name'] = private['peer_name']
        return value
    try:
        before = read()
        chain.bind(before, greetings, approved=True)
        pending_polls = 0
        for _ in range(max_polls):
            if stopped.is_set():
                break
            if deadline is not None and time.monotonic() >= deadline:
                out.update(status='chain-paused', reason='wait-timeout')
                return out
            with chain.store.connection() as db:
                seen_ids={r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?',(who['chat'],))}
            excerpts=[m['text'] if isinstance(m['text'],str) else '[нет текста]' for m in before['messages'] if m['sender']==who['peer'] and m['id'] not in seen_ids]
            if excerpts and exit_capture is not None:exit_capture(excerpts)
            try:
                stage, action = chain.proposal(before)
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
                stage, action = chain.proposal(before)
            out['stage'] = stage
            out['stages']['greeting'] = True
            with chain.store.connection() as db:
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
            if stage == 'submission-unknown':
                out.update(reason='send-outcome-unknown')
                return out
            if stage == 'done':
                if chain.media_required and notifier is not None:
                    try:
                        chain.prepare_media(who,contact_photo)
                    except Exception as error:
                        if str(error) in ('profile-return-not-verified','cancelled'):raise
                        out.update(status='chain-waiting',reason='contact-photo-unavailable')
                        return out
                notification = chain.notify(who, notifier, stopped.is_set)
                if notification == 'cancelled':
                    break
                if notification == 'nothing-pending':
                    with chain.store.connection() as db:
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
                if notification == 'accepted':
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
                    stage in ('wait-reply', 'wait-mood', 'wait-contact')):
                out.update(status='chain-waiting', reason=stage)
                return out
            if action is not None:
                progress('Подготовлено уточнение контакта.' if action['kind'] == 'clarify' else
                         'Подготовлен вопрос.' if action['kind'] == 'question' else
                         'Подготовлено предложение перейти в мессенджер.')
                if stopped.is_set():
                    break
                if approve(action['kind'], action['text'], stopped.is_set) is not True:
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
                                       stage='wait-reply' if action['kind']=='question' else 'wait-contact' if action['kind']=='clarify' else 'wait-mood')
                            return out
                        continue
                    chain.mark_review(who)
                    out.update(reason='history-changed-during-approval')
                    return out
                chain.reserve_confirmed(who, action)
                if stopped.is_set():
                    break
                out['submission_calls'] += 1
                send_failure = None
                try:
                    result = sender(fresh, action['text'])
                    returned = (isinstance(result, dict) and result.get('attempted') is True
                                and result.get('handler_returned') is True)
                    native = result.get('native_check') if isinstance(result, dict) else None
                    if isinstance(native, dict):
                        from one_chat_send import ERRORS as SEND_ERRORS
                        code = native.get('error')
                        if isinstance(code, str) and code in SEND_ERRORS and code not in {
                                'none', 'managed-exception', 'submission-already-attempted'}:
                            send_failure = 'send-native-check-failed'
                            out['diagnostics']['last_send_failure'] = code
                except Exception as send_error:
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
                if send_failure is not None:
                    out['diagnostics']['failure_point'] = send_failure
                    out.update(reason=send_failure)
                    return out
                if not returned:
                    out.update(reason='send-outcome-unknown')
                    return out
                pending_polls = 0
            elif stage.startswith('pending-'):
                pending_polls += 1
                if pending_polls >= 3:
                    out.update(reason='outgoing-not-observed')
                    return out
            else:
                pending_polls = 0
            progress({'wait-reply': 'Жду приветствие собеседника.',
                      'wait-mood': 'Вопрос виден в истории. Жду ответ собеседника.',
                      'wait-contact': 'Предложение видно в истории. Жду контакт собеседника.',
                      'pending-question': 'Проверяю появление вопроса. Повторной отправки нет.',
                      'pending-contact': 'Проверяю появление предложения. Повторной отправки нет.'
                      }.get(stage, 'Проверяю подтверждённое состояние чата.'))
            if stopped.is_set() or pause(5):
                break
            before = read()
        else:
            out.update(status='chain-paused', reason='wait-timeout')
            return out
        out.update(status='chain-cancelled', reason='cancelled')
    except HistoryWaitExpired:
        out['diagnostics']['failure_point'] = 'history-loading-timeout'
        out.update(status='chain-cancelled' if stopped.is_set() else 'chain-waiting',
                   reason='cancelled' if stopped.is_set() else 'history-loading-timeout')
    except ReviewRequired:
        out.update(status='chain-needs-review', reason='greeting-not-verified')
    except Exception as error:
        # Only fixed, authored categories; no arbitrary native exception text.
        allowed = {'start-before-peer-reply', 'guided-binding-changed',
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