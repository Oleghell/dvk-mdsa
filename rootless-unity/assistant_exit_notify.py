"""Durable, privacy-safe reasons for verified exits without a reply.

No conversation body, phone or raw identity is exported. Each state/reason is
attempted once; an unknown Telegram result is never automatically retried.
"""
import hashlib
import hmac
import json
import telegram_notify

REASONS = {
    'incoming-burst-pending': 'Собеседник продолжает писать. Несохранённый к отправке ответ отложен до следующей проверки, чтобы учесть весь пакет.',
    'wait-reply': 'В проверенном снимке нет нового входящего для ответа.',
    'wait-mood': 'Ожидается новый ответ на уже отправленный вопрос.',
    'wait-contact': 'Контакт не распознан: этап ожидания добровольно присланного контакта. Повторная просьба не отправлена.',
    'declined': 'Собеседник отказался; автоматический ответ прекращён.',
    'telegram-disabled': 'Контакт сохранён в защищённой очереди, но передача контактов в Telegram выключена.',
    'telegram-outcome-unknown': 'Контакт найден, результат передачи в Telegram неизвестен. Повтор исключён.',
    'contact-payload-blocked': 'Контакт найден, но проверка уведомления не пройдена.',
    'contact-already-handled': 'Контакт уже обработан; повторная передача исключена.',
    'manual-review': 'Не удалось безопасно продолжить этот чат; он оставлен на проверку.',
    'history-changed-during-approval': 'История изменилась не только добавлением входящих. Отправка не выполнена.',
    'send-outcome-unknown': 'Результат предыдущей попытки отправки неизвестен. Повтор исключён.',
    'outgoing-not-observed': 'Отправленное сообщение не удалось подтвердить в истории. Повтор исключён.',
    'bound-chat-read-failed': 'Не удалось прочитать проверенный снимок привязанного чата.',
}

def notify_exit(chain, who, result, *, sender=None, enabled=True):
    reason = result.get('reason')
    from assistant_inbox import ISOLATE
    from assistant_chain import REVIEW_CAUSES
    if reason not in REASONS and reason not in ISOLATE:
        reason = 'manual-review'
    cause = (result.get('diagnostics') or {}).get('review_cause')
    cause = cause if cause in REVIEW_CAUSES else None
    with chain.store.connection() as db:
        row = db.execute('SELECT salt FROM chain_dialogs WHERE chat=?', (who['chat'],)).fetchone()
        # Some failed initial reads have no chain binding yet. The opaque token
        # still identifies the chat, without exposing the actual identity.
        salt = row[0] if row else 'exit-notice-v1'
        ref = hmac.new(salt.encode(), who['chat'].encode(), hashlib.sha256).hexdigest()[:10]
        seen = db.execute('SELECT message,fingerprint FROM chain_seen WHERE chat=? ORDER BY message', (who['chat'],)).fetchall()
        signature = hashlib.sha256(json.dumps([reason,cause,seen],ensure_ascii=True).encode()).hexdigest()
        db.execute('CREATE TABLE IF NOT EXISTS chain_exit_notices(chat TEXT,signature TEXT,status TEXT NOT NULL,PRIMARY KEY(chat,signature))')
        previous = db.execute('SELECT status FROM chain_exit_notices WHERE chat=? AND signature=?', (who['chat'],signature)).fetchone()
        if previous:
            return dict(chat_ref=ref,reason=reason,review_cause=cause,notification='already-attempted')
    if not enabled:
        return dict(chat_ref=ref,reason=reason,review_cause=cause,notification='disabled')
    if sender is None:
        try:
            token, chat = telegram_notify.load()
        except Exception:
            return dict(chat_ref=ref,reason=reason,review_cause=cause,notification='not-configured')
        sender = lambda text: telegram_notify.send(token,chat,text)
    with chain.store.connection() as db:
        cur = db.execute("INSERT OR IGNORE INTO chain_exit_notices VALUES(?,?,'attempted-unknown')", (who['chat'],signature))
        if cur.rowcount != 1:
            return dict(chat_ref=ref,reason=reason,review_cause=cause,notification='already-attempted')
    text = ('ℹ️ DvkAssistant: диалог '+ref+' прочитан, выход без нового ответа.\n'+
            REASONS.get(reason,'Чат изолирован: безопасное продолжение не подтверждено.')+
            '\nПричина: '+reason+ (' / '+cause if cause else '')+
            '\nВозврат в личку проверен; продолжаю остальные диалоги.')
    try:
        status = 'accepted' if sender(text) is True else 'unknown'
    except Exception:
        status = 'unknown'
    with chain.store.connection() as db:
        db.execute('UPDATE chain_exit_notices SET status=? WHERE chat=? AND signature=?', (status,who['chat'],signature))
    return dict(chat_ref=ref,reason=reason,review_cause=cause,notification=status)
