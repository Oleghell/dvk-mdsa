"""Durable, privacy-safe reasons for verified exits without a reply.

Only explicitly enabled peer excerpts are exported; raw identities stay local. Each state/reason is
attempted once; an unknown Telegram result is never automatically retried.
"""
import hashlib
import hmac
import json
import telegram_notify

REASONS = {
 'contact-photo-unavailable':'Контакт сохранён. Не удалось проверить снимок профиля; отправка отложена.',
 'wait-contact':'Контакт не найден. Повторно просить не стал.',
 'wait-reply':'Нового сообщения для ответа нет.',
 'wait-mood':'Жду ответ на уже отправленный вопрос.',
 'incoming-burst-pending':'Ещё приходят сообщения. Отвечу после следующей проверки.',
 'ai-temporarily-unavailable':'Сервис ИИ сейчас недоступен. Попробую позже.',
 'declined':'Собеседник отказался от общения.',
 'telegram-disabled':'Контакт сохранён, но отправка контактов в Telegram выключена.',
 'telegram-outcome-unknown':'Контакт найден, но Telegram не подтвердил приём. Не повторяю, чтобы не было дубля.',
 'contact-payload-blocked':'Не удалось проверить данные контакта.',
 'contact-already-handled':'Этот контакт уже обработан.',
 'manual-review':'Не удалось безопасно продолжить этот чат.',
 'history-changed-during-approval':'История изменилась. Не стал отправлять ответ вслепую.',
 'send-outcome-unknown':'Неясно, ушёл ли ответ. Не повторяю, чтобы не было дубля.',
 'outgoing-not-observed':'Не вижу отправленный ответ в истории. Повторять не стал.',
 'bound-chat-read-failed':'Не удалось прочитать переписку.',
 'groq-unsafe-reply':'Ответ ИИ не прошёл проверку. Отправлять его не стал.',
 'openrouter-unsafe-reply':'Ответ ИИ не прошёл проверку. Отправлять его не стал.',
 'groq-invalid-response':'ИИ вернул непонятный ответ.',
 'openrouter-invalid-response':'ИИ вернул непонятный ответ.',
 'groq-repeat-greeting':'ИИ снова поздоровался. Такой ответ не отправляю.',
 'openrouter-repeat-greeting':'ИИ снова поздоровался. Такой ответ не отправляю.',
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
    excerpts=result.get('_exit_messages',[])
    excerpts=[x for x in excerpts if isinstance(x,str)] if isinstance(excerpts,list) else []
    excerpt=' / '.join(excerpts).replace('\x00','')[:800]
    text = ('Собеседник: «'+excerpt+'»\n' if excerpt else 'Сообщение собеседника прочитать не удалось.\n') + 'Пропущено: ' + REASONS.get(reason,'Не удалось безопасно продолжить этот чат.')
    try:
        status = 'accepted' if sender(text) is True else 'unknown'
    except Exception:
        status = 'unknown'
    with chain.store.connection() as db:
        db.execute('UPDATE chain_exit_notices SET status=? WHERE chat=? AND signature=?', (status,who['chat'],signature))
    return dict(chat_ref=ref,reason=reason,review_cause=cause,notification=status)
