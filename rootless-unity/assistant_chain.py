"""Opt-in automatic replies in ONE already open, journal-authorized dialog.

No navigation or chronology inferred from collection positions/IDs. Only set
changes observed AFTER our previous outgoing was observed may advance a stage.
Incoming bodies and contact details never enter SQLite or Telegram.
"""
import hashlib
import hmac
import json
import re
import secrets

from assistant_store import StateError, Store
from conversation_engine import QUESTIONS, CONTACT_TEXT, REFUSAL, NEGATIVE, normalized
from one_chat_probe import identity
from one_chat_send import checked

TERMINAL = {'done', 'declined', 'manual-review'}
REPLIES = QUESTIONS + (CONTACT_TEXT,)
POSITIVE = re.compile(r'^(?:вс[её]\s+)?(?:хорошо|отлично|нормально|норм|супер|прекрасно|замечательно|неплохо|класс)(?:\s+(?:спасибо|вс[её]\s+хорошо))?[\s!.,)🙂😊👍]*$', re.I)
HELLO = re.compile(r'^(?:привет(?:ик)?|здравствуй(?:те)?|добрый\s+(?:день|вечер)|доброе\s+утро|хай|hello|hi)[\s!.,)🙂😊👋]*$', re.I)


def fingerprint(message, salt):
    raw = json.dumps(message, ensure_ascii=False, sort_keys=True).encode()
    return hmac.new(bytes.fromhex(salt), raw, hashlib.sha256).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class Chain:
    def __init__(self, store, choose=lambda: secrets.randbelow(2)):
        self.store, self.choose = store, choose
        with store.connection() as db:
            # Do not use executescript: it would commit the surrounding tx.
            for sql in (
                'CREATE TABLE IF NOT EXISTS chain_dialogs(account TEXT,peer TEXT,chat TEXT UNIQUE,greeting TEXT,stage TEXT,salt TEXT,PRIMARY KEY(account,peer))',
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
        s = checked(snapshot)
        who, messages = s['identity'], s['messages']
        greeting_hash = self.authorized(who)
        chat = who['chat']
        action = None
        with self.store.connection() as db:
            row = db.execute('SELECT greeting,stage,salt FROM chain_dialogs WHERE account=? AND peer=?',
                             (who['account'], who['peer'])).fetchone()
            if row is None:
                own = [m for m in messages if m['sender'] == who['account']]
                if len(own) != 1 or not isinstance(own[0]['text'], str) or text_hash(own[0]['text']) != greeting_hash:
                    raise StateError('Не подтверждено единственное исходное приветствие. Автоцепочка не запущена.')
                row = (own[0]['id'], 'wait-reply', secrets.token_hex(32))
                db.execute('INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)',
                           (who['account'], who['peer'], chat, *row))
                db.execute('INSERT INTO chain_seen VALUES(?,?,?)',
                           (chat, own[0]['id'], fingerprint(own[0], row[2])))
            greeting, stage, salt = row
            if stage not in TERMINAL | {'wait-reply', 'wait-mood', 'wait-contact', 'pending-question', 'pending-contact'}:
                raise StateError('Неизвестный сохранённый этап. Автоматическая отправка запрещена.')
            old = dict(db.execute('SELECT message,fingerprint FROM chain_seen WHERE chat=?', (chat,)))
            now = {m['id']: fingerprint(m, salt) for m in messages}
            # A changed/truncated history is not an empty chat or a new reply.
            if not set(old) <= set(now) or any(now[k] != v for k, v in old.items()):
                stage = 'manual-review'
            if stage in TERMINAL:
                db.execute('UPDATE chain_dialogs SET stage=? WHERE chat=?', (stage, chat))
                return stage, None
            new = [m for m in messages if m['id'] not in old]
            incoming = [m for m in new if m['sender'] == who['peer']]
            outgoing = [m for m in new if m['sender'] == who['account']]
            for m in incoming:
                db.execute("INSERT OR IGNORE INTO chain_notifications VALUES(?,?,'pending')", (chat, m['id']))
            if any(m['text'] and REFUSAL.search(normalized(m['text'])) for m in incoming):
                stage = 'declined'
            elif stage.startswith('pending-'):
                kind = stage.removeprefix('pending-')
                reserved = db.execute('SELECT text_hash FROM chain_actions WHERE chat=? AND kind=?', (chat, kind)).fetchone()
                if not reserved:
                    raise StateError('Не найден резерв этапа. Отправка запрещена.')
                if incoming:
                    stage = 'manual-review'
                elif outgoing:
                    # Simultaneous peer/own deltas have no verified order.
                    if (len(outgoing) != 1 or incoming or not isinstance(outgoing[0]['text'], str)
                            or text_hash(outgoing[0]['text']) != reserved[0]):
                        stage = 'manual-review'
                    else:
                        stage = 'wait-mood' if kind == 'question' else 'wait-contact'
                        db.execute("UPDATE chain_actions SET status='outgoing-observed' WHERE chat=? AND kind=?", (chat, kind))
            elif outgoing:
                stage = 'manual-review'
            elif incoming:
                if len(incoming) != 1 or not incoming[0]['text'] or NEGATIVE.search(normalized(incoming[0]['text'])):
                    stage = 'manual-review'
                elif stage == 'wait-contact':
                    stage = 'done'  # Notify only; do not extract or forward contacts.
                else:
                    text = incoming[0]['text'].strip()
                    safe = HELLO.fullmatch(text) if stage == 'wait-reply' else POSITIVE.fullmatch(text)
                    if not safe:
                        stage = 'manual-review'
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
            for m in new:
                db.execute('INSERT INTO chain_seen VALUES(?,?,?)', (chat, m['id'], now[m['id']]))
            db.execute('UPDATE chain_dialogs SET stage=? WHERE chat=?', (stage, chat))
        return stage, action

    def finish(self, who, action, outcome):
        status = 'handler-returned-unconfirmed' if outcome is True else 'unknown'
        with self.store.connection() as db:
            db.execute("UPDATE chain_actions SET status=? WHERE chat=? AND kind=? AND status='reserved-unknown'",
                       (status, who['chat'], action['kind']))

    def notify(self, who, notifier):
        if notifier is None:
            return 'disabled'
        with self.store.connection() as db:
            row = db.execute("SELECT message FROM chain_notifications WHERE chat=? AND status='pending' ORDER BY rowid LIMIT 1", (who['chat'],)).fetchone()
            if row is None:
                return 'nothing-pending'
            db.execute("UPDATE chain_notifications SET status='attempted-unknown' WHERE chat=? AND message=?", (who['chat'], row[0]))
        try:
            outcome = 'accepted' if notifier() is True else 'unknown'
        except Exception:
            outcome = 'unknown'
        with self.store.connection() as db:
            db.execute('UPDATE chain_notifications SET status=? WHERE chat=? AND message=?', (outcome, who['chat'], row[0]))
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
            result = sender(before, action['text'])
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
    notifications = dict(accepted=0, unknown=0)
    def outcome(state):
        return dict(state=state, notifications=dict(notifications))
    with operation_lock():
        chain = Chain(Store() if store is None else store)
        if stopped.is_set():
            return outcome('cancelled')
        # Identity-only pass cannot collect message bodies from an unknown chat.
        bound = capture(executable, folder, stopped.is_set)['identity']
        chain.authorized(bound)
        while not stopped.is_set():
            before = capture(executable, folder, stopped.is_set, bound)
            state = step(chain, before, lambda snapshot, text: submit(
                executable, folder, snapshot, stopped.is_set, text=text), stopped.is_set)
            if stopped.is_set():
                return outcome('cancelled')
            while not stopped.is_set():
                notification = chain.notify(bound, notifier)
                if notification not in notifications:
                    break
                notifications[notification] += 1
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
        'declined': 'Собеседник отказался от общения. Цепочка остановлена.',
        'done': 'Получен ответ на предложение перейти в мессенджер. Цепочка завершена; контакты не пересылались.',
        'cancelled': 'Автоцепочка остановлена.',
    }[state]
