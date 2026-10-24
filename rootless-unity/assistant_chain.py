"""Opt-in automatic replies in ONE already open, journal-authorized dialog.

No navigation or chronology inferred from collection positions/IDs. Only set
changes observed AFTER our previous outgoing was observed may advance a stage.
Incoming bodies never enter SQLite; self-shared contacts use a separate DPAPI outbox.
"""
import hashlib
import hmac
import json
import re
import secrets

from assistant_store import StateError, Store
from assistant_contact_policy import should_close as contact_only_closed
from assistant_contact_budget import can_close as contact_budget_closed, exhausted as contact_budget_exhausted
from conversation_engine import QUESTIONS, CONTACT_TEXT, REFUSAL, NEGATIVE, normalized
from one_chat_probe import identity
from one_chat_send import checked
from shared_contact import self_shared, voluntary_batch, payload as contact_payload, display_name
from telegram_notify import protect
from assistant_contact_clarify import TEXT as CLARIFY_TEXT, chosen as chose_messenger, MAX_TEXT, max_selected, NUMBER_TEXT, indifferent_selected

from assistant_contact_followup import TEXT as FOLLOWUP_TEXT, eligible as followup_eligible, refused as contact_refused

TERMINAL = {'done', 'declined', 'manual-review'}
REVIEW_CAUSES = {'history-missing', 'history-edited', 'contact-batch-ambiguous',
                 'incoming-during-pending', 'pending-outgoing-mismatch',
                 'unjournalled-outgoing', 'legacy-incoming-ambiguous',
                 'legacy-contact-not-shared', 'legacy-reply-unclassified',
                 'ai-context-review', 'review-cause-unavailable'}
REPLIES = QUESTIONS + (CONTACT_TEXT, CLARIFY_TEXT, MAX_TEXT, NUMBER_TEXT, FOLLOWUP_TEXT)
POSITIVE = re.compile(r'^(?:вс[её]\s+)?(?:хорошо|отлично|нормально|норм|супер|прекрасно|замечательно|неплохо|класс)(?:\s+(?:спасибо|вс[её]\s+хорошо))?[\s!.,)🙂😊👍]*$', re.I)
HELLO = re.compile(r'^(?:привет(?:ик)?|здравствуй(?:те)?|добрый\s+(?:день|вечер)|доброе\s+утро|хай|hello|hi)[\s!.,)🙂😊👋]*$', re.I)


class ReviewRequired(StateError):
    """A bound history does not verify the original greeting; never auto-reply."""


def fingerprint(message, salt):
    raw = json.dumps(message, ensure_ascii=False, sort_keys=True).encode()
    return hmac.new(bytes.fromhex(salt), raw, hashlib.sha256).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class Chain:
    # Only the explicitly selected, per-message-approved guided mode opts in.
    any_replies = False
    media_required = False

    def __init__(self, store, choose=lambda: secrets.randbelow(2), *, contact_notifications=False,
                 seal=protect, unseal=lambda data: protect(data, decrypt=True)):
        self.store, self.choose = store, choose
        self.contact_notifications = contact_notifications is True
        self.seal, self.unseal = seal, unseal
        with store.connection() as db:
            # Do not use executescript: it would commit the surrounding tx.
            for sql in (
                'CREATE TABLE IF NOT EXISTS chain_contact_media(chat TEXT PRIMARY KEY,payload BLOB NOT NULL)',
                'CREATE TABLE IF NOT EXISTS chain_contact_outbox(chat TEXT PRIMARY KEY,message TEXT,payload BLOB NOT NULL,status TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS chain_dialogs(account TEXT,peer TEXT,chat TEXT UNIQUE,greeting TEXT,stage TEXT,salt TEXT,PRIMARY KEY(account,peer))',
                'CREATE TABLE IF NOT EXISTS chain_review_reasons(chat TEXT PRIMARY KEY,reason TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS chain_seen(chat TEXT,message TEXT,fingerprint TEXT,PRIMARY KEY(chat,message))',
                'CREATE TABLE IF NOT EXISTS chain_actions(chat TEXT,kind TEXT,trigger TEXT,text_hash TEXT,status TEXT,PRIMARY KEY(chat,kind))',
                'CREATE TABLE IF NOT EXISTS chain_notifications(chat TEXT,message TEXT,status TEXT,PRIMARY KEY(chat,message))',
            ):
                db.execute(sql)

    def authorized(self, who):
        who = identity(who)
        with self.store.connection() as db:
            row = db.execute('SELECT initial_chat,text_hash,status FROM manual_actions WHERE account=? AND peer=?',
                             (who['account'], who['peer'])).fetchone()
            bound = db.execute('SELECT chat FROM chain_dialogs WHERE account=? AND peer=?',
                               (who['account'], who['peer'])).fetchone()
        if (row is None or row[2] == 'not-invoked' or (int(row[0]) > 0 and row[0] != who['chat'])
                or (bound is not None and bound[0] != who['chat'])):
            raise StateError('Этот чат не привязан к приветствию DvkAssistant. Переписка не читалась.')
        return row[1]

    def consume(self, snapshot):
        if not isinstance(snapshot, dict) or set(snapshot) not in ({'identity', 'messages'}, {'identity', 'messages', 'peer_name'}):
            raise ValueError('Invalid private snapshot fields')
        s = checked({k: snapshot[k] for k in ('identity', 'messages')})
        who, messages = s['identity'], s['messages']
        greeting_hash = self.authorized(who)
        chat = who['chat']
        action = None
        review_cause = None
        with self.store.connection() as db:
            row = db.execute('SELECT greeting,stage,salt FROM chain_dialogs WHERE account=? AND peer=?',
                             (who['account'], who['peer'])).fetchone()
            if row is None:
                own = [m for m in messages if m['sender'] == who['account']]
                if len(own) != 1 or not isinstance(own[0]['text'], str) or text_hash(own[0]['text']) != greeting_hash:
                    error=ReviewRequired('Не подтверждено единственное исходное приветствие. Автоцепочка не запущена.')
                    error.anchor_reason='multiple-own' if len(own)>1 else 'missing-own' if not own else 'hash-mismatch'
                    raise error
                row = (own[0]['id'], 'wait-reply', secrets.token_hex(32))
                db.execute('INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)',
                           (who['account'], who['peer'], chat, *row))
                db.execute('INSERT INTO chain_seen VALUES(?,?,?)',
                           (chat, own[0]['id'], fingerprint(own[0], row[2])))
            greeting, stage, salt = row
            if stage not in TERMINAL | {'wait-reply', 'wait-mood', 'wait-contact', 'pending-question', 'pending-contact', 'pending-clarify', 'pending-followup'}:
                raise StateError('Неизвестный сохранённый этап. Автоматическая отправка запрещена.')
            old = dict(db.execute('SELECT message,fingerprint FROM chain_seen WHERE chat=?', (chat,)))
            now = {m['id']: fingerprint(m, salt) for m in messages}
            # A changed/truncated history is not an empty chat or a new reply.
            if not set(old) <= set(now):
                stage, review_cause = 'manual-review', 'history-missing'
            elif any(now[k] != v for k, v in old.items()):
                stage, review_cause = 'manual-review', 'history-edited'
            if review_cause:
                db.execute('INSERT INTO chain_review_reasons VALUES(?,?) ON CONFLICT(chat) DO NOTHING', (chat, review_cause))
            if stage in TERMINAL:
                db.execute('UPDATE chain_dialogs SET stage=? WHERE chat=?', (stage, chat))
                return stage, None
            new = [m for m in messages if m['id'] not in old]
            incoming = [m for m in new if m['sender'] == who['peer']]
            outgoing = [m for m in new if m['sender'] == who['account']]
            max_choice = max_selected([m for m in messages if m['sender']==who['peer']])
            number_choice = indifferent_selected(db,s,[m['id'] for m in incoming])
            clarify_text = MAX_TEXT if max_choice else NUMBER_TEXT if number_choice else CLARIFY_TEXT
            pending_contact_observed = False
            pending_contact_kind = stage.removeprefix('pending-')
            if stage in ('pending-contact','pending-clarify','pending-followup') and len(outgoing) == 1:
                pending = db.execute('SELECT text_hash,status FROM chain_actions WHERE chat=? AND kind=?', (chat,pending_contact_kind)).fetchone()
                pending_contact_observed = bool(pending and pending[1] == 'handler-returned-unconfirmed'
                    and isinstance(outgoing[0]['text'], str) and text_hash(outgoing[0]['text']) == pending[0])
            from assistant_contact_receipt import requested as receipt_requested,packet_blocked
            anchored_request = self.any_replies and receipt_requested(db,who,messages)
            independent_contact = self.any_replies and (voluntary_batch(incoming) or any(self_shared(m['text']) for m in incoming))
            shared = [(m, self_shared(m['text'], requested=stage == 'wait-contact' or pending_contact_observed or independent_contact or anchored_request)) for m in incoming]
            shared = [(m, items) for m, items in shared if items]
            if packet_blocked(incoming):shared=[]
            contact_requested = anchored_request or stage in ('wait-contact','pending-clarify','pending-followup') or pending_contact_observed
            from assistant_contact_followup import scoped_messages
            refusal_inputs = scoped_messages(db,s, [m['id'] for m in incoming],requested=contact_requested)
            if (any(m['text'] and REFUSAL.search(normalized(m['text'])) for m in incoming)
                    or contact_refused(refusal_inputs if contact_requested else incoming,
                                       requested=contact_requested,contact_shared=bool(shared),alternative_selected=max_choice)):
                # Respect an explicit stay-here/no-apps preference already read
                # by an older version too. This never replays or removes actions.
                stage = 'declined'
            elif shared:
                aggregate = self.any_replies and (stage == 'wait-contact' or pending_contact_observed or independent_contact or anchored_request)
                if (outgoing and not pending_contact_observed and not independent_contact and not anchored_request) or (not aggregate and (len(shared) != 1 or len(incoming) != 1)):
                    stage, review_cause = 'manual-review', 'contact-batch-ambiguous'
                else:
                    message, items = shared[0]
                    if aggregate:
                        # Only independently self-shared contacts from this bound
                        # chat and this newly observed batch; never profile data.
                        items = list(dict.fromkeys(c for _, values in shared for c in values))
                        if len(items) > 4:
                            raise StateError('contact-limit-exceeded')
                    from assistant_contact_receipt import save as save_contact
                    save_contact(self,db,snapshot,message,items)
                    # Voluntary sharing is independent of earlier send outcome.
                    # Preserve unknown/returned action records; do not infer delivery.
                    if pending_contact_observed:
                        db.execute("UPDATE chain_actions SET status='outgoing-observed' WHERE chat=? AND kind=?", (chat,pending_contact_kind))
                    stage = 'done'
            elif self.any_replies and contact_only_closed(db,s,stage,incoming,
                    requested=contact_requested,max_choice=max_choice,number_choice=number_choice):
                # Full-history/identity checks and voluntary contact/refusal gates
                # have already run. Do not reserve any off-topic response.
                stage = 'declined'
            elif self.any_replies and contact_budget_closed(db, chat, stage):
                # Contact/refusal gates above win. Terminal skip retains every
                # reservation, fingerprint, archived reply and unsent draft.
                stage = 'declined'
            elif stage.startswith('pending-'):
                kind = stage.removeprefix('pending-')
                reserved = db.execute('SELECT text_hash,status FROM chain_actions WHERE chat=? AND kind=?', (chat, kind)).fetchone()
                if not reserved:
                    raise StateError('Не найден резерв этапа. Отправка запрещена.')
                verified_own = (len(outgoing) == 1 and isinstance(outgoing[0]['text'],str)
                    and text_hash(outgoing[0]['text']) == reserved[0]
                    and (reserved[1] == 'handler-returned-unconfirmed' or not self.any_replies))
                if incoming and self.any_replies and not outgoing:
                    # Peer arrivals while awaiting visibility do not prove a send
                    # failed or succeeded. Keep them UNCONSUMED for a later sample.
                    return stage, None
                if incoming and self.any_replies and verified_own:
                    # Observe the exact returned reservation, not a guessed order.
                    # The complete verified incoming set is one contextual batch.
                    db.execute("UPDATE chain_actions SET status='outgoing-observed' WHERE chat=? AND kind=?",(chat,kind))
                    if kind == 'question':
                        db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,'reserved-unknown')",
                                   (chat,'contact',incoming[0]['id'],text_hash(CONTACT_TEXT)))
                        stage='pending-contact';action=dict(kind='contact',text=CONTACT_TEXT)
                    else:
                        stage='wait-contact'
                        if self.any_replies and contact_budget_exhausted(db, chat):
                            stage='declined'
                        elif kind in ('contact','followup') and (chose_messenger(incoming) or max_choice or number_choice) and not db.execute(
                                "SELECT 1 FROM chain_actions WHERE chat=? AND kind='clarify'",(chat,)).fetchone():
                            db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,'reserved-unknown')",
                                       (chat,'clarify',incoming[0]['id'],text_hash(clarify_text)))
                            stage='pending-clarify';action=dict(kind='clarify',text=clarify_text)
                        elif not max_choice and not number_choice and followup_eligible(incoming) and not db.execute(
                                "SELECT 1 FROM chain_actions WHERE chat=? AND kind='followup'",(chat,)).fetchone():
                            db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,'reserved-unknown')",
                                       (chat,'followup',incoming[0]['id'],text_hash(FOLLOWUP_TEXT)))
                            stage='pending-followup';action=dict(kind='followup',text=FOLLOWUP_TEXT)
                elif incoming:
                    stage, review_cause = 'manual-review', 'incoming-during-pending'
                elif outgoing:
                    if not verified_own:
                        stage, review_cause = 'manual-review', 'pending-outgoing-mismatch'
                    else:
                        stage = 'wait-mood' if kind == 'question' else 'wait-contact'
                        db.execute("UPDATE chain_actions SET status='outgoing-observed' WHERE chat=? AND kind=?", (chat, kind))
            elif outgoing:
                stage, review_cause = 'manual-review', 'unjournalled-outgoing'
            elif incoming and self.any_replies:
                if stage == 'wait-contact':
                    # A messenger choice is consent to ONE clarification, not a
                    # fabricated contact. Never reuse or reset an existing action.
                    if (chose_messenger(incoming) or max_choice or number_choice) and not db.execute(
                            "SELECT 1 FROM chain_actions WHERE chat=? AND kind='clarify'",(chat,)).fetchone():
                        db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,'reserved-unknown')",
                                   (chat,'clarify',incoming[0]['id'],text_hash(clarify_text)))
                        stage='pending-clarify';action=dict(kind='clarify',text=clarify_text)
                    elif not max_choice and not number_choice and followup_eligible(incoming) and not db.execute(
                            "SELECT 1 FROM chain_actions WHERE chat=? AND kind='followup'",(chat,)).fetchone():
                        db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,'reserved-unknown')",
                                   (chat,'followup',incoming[0]['id'],text_hash(FOLLOWUP_TEXT)))
                        stage='pending-followup';action=dict(kind='followup',text=FOLLOWUP_TEXT)
                else:
                    # Any newly observed reply (including media or a burst of
                    # messages) advances exactly one stage. Explicit refusal and
                    # uncertain outgoing/history are handled above.
                    kind = 'question' if stage == 'wait-reply' else 'contact'
                    choice = self.choose() if kind == 'question' else 0
                    if type(choice) is not int or choice not in (0, 1):
                        raise StateError('Неверный вариант вопроса.')
                    reply = QUESTIONS[choice] if kind == 'question' else CONTACT_TEXT
                    # FULL commit finishes before the caller can send.
                    db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,'reserved-unknown')",
                               (chat, kind, incoming[0]['id'], text_hash(reply)))
                    stage = 'pending-' + kind
                    action = dict(kind=kind, text=reply)
            elif incoming:
                if len(incoming) != 1 or not incoming[0]['text'] or NEGATIVE.search(normalized(incoming[0]['text'])):
                    stage, review_cause = 'manual-review', 'legacy-incoming-ambiguous'
                elif stage == 'wait-contact':
                    stage, review_cause = 'manual-review', 'legacy-contact-not-shared'  # No claimed contact, no Telegram notification.
                else:
                    text = incoming[0]['text'].strip()
                    safe = HELLO.fullmatch(text) if stage == 'wait-reply' else POSITIVE.fullmatch(text)
                    if not safe:
                        stage, review_cause = 'manual-review', 'legacy-reply-unclassified'
                    else:
                        kind = 'question' if stage == 'wait-reply' else 'contact'
                        choice = self.choose() if kind == 'question' else 0
                        if type(choice) is not int or choice not in (0, 1):
                            raise StateError('Неверный вариант вопроса.')
                        reply = QUESTIONS[choice] if kind == 'question' else CONTACT_TEXT
                        # FULL commit finishes before the caller can send.
                        db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,'reserved-unknown')",
                                   (chat, kind, incoming[0]['id'], text_hash(reply)))
                        stage = 'pending-' + kind
                        action = dict(kind=kind, text=reply)
            if review_cause:
                db.execute('INSERT INTO chain_review_reasons VALUES(?,?) ON CONFLICT(chat) DO NOTHING', (chat, review_cause))
            for m in new:
                db.execute('INSERT INTO chain_seen VALUES(?,?,?)', (chat, m['id'], now[m['id']]))
            db.execute('UPDATE chain_dialogs SET stage=? WHERE chat=?', (stage, chat))
        return stage, action

    def review_reason(self, who):
        who=identity(who)
        self.authorized(who)
        with self.store.connection() as db:
            row=db.execute('SELECT reason FROM chain_review_reasons WHERE chat=?', (who['chat'],)).fetchone()
        return row[0] if row and row[0] in REVIEW_CAUSES else 'review-cause-unavailable'

    def mark_review(self, who):
        who=identity(who)
        self.authorized(who)
        with self.store.connection() as db:
            # NULL greeting records a terminal block, not an invented message ID.
            db.execute("INSERT INTO chain_dialogs(account,peer,chat,greeting,stage,salt) VALUES(?,?,?,NULL,'manual-review',?) ON CONFLICT(account,peer) DO NOTHING",
                       (who['account'],who['peer'],who['chat'],secrets.token_hex(32)))
            cur=db.execute("UPDATE chain_dialogs SET stage='manual-review' WHERE account=? AND peer=? AND chat=?",
                           (who['account'],who['peer'],who['chat']))
            if cur.rowcount!=1:raise StateError('Не удалось сохранить блокировку диалога.')

    def finish(self, who, action, outcome):
        status = 'handler-returned-unconfirmed' if outcome is True else 'unknown'
        with self.store.connection() as db:
            db.execute("UPDATE chain_actions SET status=? WHERE chat=? AND kind=? AND status='reserved-unknown'",
                       (status, who['chat'], action['kind']))

    def has_media(self,who):
        with self.store.connection() as db:
            return db.execute('SELECT 1 FROM chain_contact_media WHERE chat=?',(who['chat'],)).fetchone() is not None

    def prepare_media(self,who,capture):
        self.authorized(who)
        if self.has_media(who):return
        if capture is None:raise StateError('profile-photo-unavailable')
        image=capture(who)
        from assistant_contact_photo import png_size
        png_size(image)
        protected=self.seal(image)
        if not isinstance(protected,bytes) or not protected:raise StateError('profile-photo-unavailable')
        with self.store.connection() as db:
            db.execute('INSERT OR IGNORE INTO chain_contact_media VALUES(?,?)',(who['chat'],protected))

    def notify(self, who, notifier, cancelled=lambda: False):
        # Never consume the former generic new-message outbox. It is obsolete.
        if notifier is None or not self.contact_notifications:
            return 'disabled'
        if cancelled():
            return 'cancelled'
        self.authorized(who)
        with self.store.connection() as db:
            row = db.execute("SELECT payload FROM chain_contact_outbox WHERE chat=? AND status='pending'", (who['chat'],)).fetchone()
            if row is None:
                return 'nothing-pending'
            try:
                data = json.loads(self.unseal(row[0]))
                if not isinstance(data, dict) or set(data) != {'name', 'contacts'}:
                    raise ValueError('Invalid payload')
                data = contact_payload(data['name'], data['contacts'])
            except Exception:
                db.execute("UPDATE chain_contact_outbox SET status='blocked' WHERE chat=?", (who['chat'],))
                return 'blocked'
            photo=db.execute('SELECT payload FROM chain_contact_media WHERE chat=?',(who['chat'],)).fetchone()
            if self.media_required and photo is None:return 'photo-required'
            if photo is not None:
                try:
                    data['photo']=self.unseal(photo[0])
                    from assistant_contact_photo import png_size
                    png_size(data['photo'])
                except Exception:return 'blocked'
            db.execute("UPDATE chain_contact_outbox SET status='attempted-unknown' WHERE chat=?", (who['chat'],))
        if cancelled():
            return 'cancelled'  # Reserved attempt remains consumed; no resend.
        try:
            outcome = 'accepted' if notifier(data) is True else 'unknown'
        except Exception:
            outcome = 'unknown'
        with self.store.connection() as db:
            db.execute('UPDATE chain_contact_outbox SET status=? WHERE chat=?', (outcome, who['chat']))
            db.execute('DELETE FROM chain_contact_media WHERE chat=?',(who['chat'],))
            from assistant_statistics import notified
            notified(db,who['account'],who['peer'],who['chat'],outcome)
        return outcome


def step(chain, before, sender, cancelled=lambda: False):
    if cancelled():
        return 'cancelled'
    stage, action = chain.consume(before)
    if action is not None:
        # A Stop after reservation consumes it; never retry on restart.
        if cancelled():
            return 'cancelled'
        try:
            result = sender({k: before[k] for k in ('identity', 'messages')}, action['text'])
            outcome = (isinstance(result, dict) and result.get('attempted') is True
                       and result.get('handler_returned') is True)
        except Exception:
            outcome = False
        chain.finish(before['identity'], action, outcome)
        return 'await-outgoing' if outcome else 'submission-unknown'
    return stage


def run(executable, folder, stopped, progress=lambda text: None, *, store=None, notifier=None,
        capture=None, submit=None, interval=5):
    """Caller explicitly starts this mode; hold the shared device lock throughout."""
    from assistant_lock import operation_lock
    from one_chat_device import capture as native_capture
    from one_chat_send_device import submit as native_submit
    if type(interval) not in (int, float) or interval < 5:
        raise ValueError('Read interval must be at least five seconds')
    capture = native_capture if capture is None else capture
    submit = native_submit if submit is None else submit
    notifications = dict(accepted=0, unknown=0, blocked=0)
    def outcome(state):
        return dict(state=state, notifications=dict(notifications))
    with operation_lock():
        chain = Chain(Store() if store is None else store, contact_notifications=notifier is not None)
        if stopped.is_set():
            return outcome('cancelled')
        # Identity-only pass cannot collect message bodies from an unknown chat.
        bound = capture(executable, folder, stopped.is_set)['identity']
        chain.authorized(bound)
        while not stopped.is_set():
            before = (capture(executable, folder, stopped.is_set, bound, read_name=True)
                      if notifier is not None else capture(executable, folder, stopped.is_set, bound))
            state = step(chain, before, lambda snapshot, text: submit(
                executable, folder, snapshot, stopped.is_set, text=text), stopped.is_set)
            if stopped.is_set():
                return outcome('cancelled')
            while not stopped.is_set():
                notification = chain.notify(bound, notifier, stopped.is_set)
                if notification not in notifications:
                    break
                notifications[notification] += 1
            if stopped.is_set():
                return outcome('cancelled')
            progress(result_text(outcome(state)))
            if state in TERMINAL or state in {'submission-unknown', 'cancelled'}:
                return outcome(state)
            if stopped.wait(interval):
                break
    return outcome('cancelled')


def result_text(result):
    text = status_text(result['state'])
    counts = result['notifications']
    if counts['accepted']:
        text += ' Telegram принял уведомлений: ' + str(counts['accepted']) + '.'
    if counts['unknown']:
        text += ' Не подтверждено Telegram: ' + str(counts['unknown']) + '; автоповтора нет.'
    if counts.get('blocked'):
        text += ' Контакт не передан: не удалось проверить защищённые данные.'
    return text


def status_text(state):
    return {
        'wait-reply': 'Ожидаю ответ на приветствие в открытом чате.',
        'pending-question': 'Ожидаю появления отправленного вопроса в истории. Повтора нет.',
        'pending-contact': 'Ожидаю появления предложения перейти в мессенджер. Повтора нет.',
        'wait-mood': 'Вопрос появился в истории. Ожидаю новый ответ.',
        'wait-contact': 'Предложение перейти в мессенджер появилось в истории. Ожидаю ответ.',
        'await-outgoing': 'Обработчик отправки вернулся. Проверяю появление сообщения; доставка не подтверждена.',
        'submission-unknown': 'Результат отправки неизвестен. Цепочка остановлена, повтора нет.',
        'manual-review': 'Неоднозначный ответ или изменение истории. Цепочка остановлена — прочитай чат вручную.',
        'declined': 'Отказ от перехода или общения. Цепочка остановлена без нового ответа.',
        'done': 'Собеседник поделился своим контактом. Цепочка завершена; результат Telegram указан отдельно.',
        'cancelled': 'Автоцепочка остановлена.',
    }[state]
