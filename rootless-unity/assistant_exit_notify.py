"""Durable, privacy-safe reasons for verified exits without a reply.

Only explicitly enabled peer excerpts are exported; raw identities stay local. Each state/reason is
attempted once; an unknown Telegram result is never automatically retried.
"""
import hashlib
import hmac
import json
import telegram_notify

REASONS = {
 'greeting-not-verified':'Не удалось подтвердить исходное приветствие по журналу. Этот чат оставлен на проверку.',
 'history-read-budget-timeout':'Не удалось дочитать переписку. Проверю позже; отправленный ответ не повторяю.',
 'history-snapshot-too-large':'История слишком большая для проверенного чтения. Чат отложен, остальные продолжаются.',
 'history-loading-timeout':'История диалога не загрузилась. Пока пропустил, проверю позже.',
 'contact-photo-unavailable':'Контакт сохранён. Не удалось проверить снимок профиля; отправка отложена.',
 'contact-clarification-sent':'Номер или ник уже уточнил. Жду контакт, повторный запрос не отправлен.',
 'incoming-answer-pending':'Ответ на новые сообщения ещё не подтверждён. Чат остаётся в очереди, проверю позже.',
 'wait-contact':'Жду добровольный контакт или новое сообщение.',
 'contact-followup-sent':'Ответ подтверждён в переписке. Повторный запрос контакта не отправлен.',
 'wait-reply':'Нового сообщения для ответа нет.',
 'wait-mood':'Жду ответ на уже отправленный вопрос.',
 'incoming-burst-pending':'Ещё приходят сообщения. Отвечу после следующей проверки.',
 'ai-temporarily-unavailable':'Сервис ИИ сейчас недоступен. Попробую позже.',
 'declined':'Собеседник отказался от перехода или общения. Пропущено без нового ответа.',
 'telegram-disabled':'Контакт сохранён, но отправка контактов в Telegram выключена.',
 'telegram-outcome-unknown':'Контакт найден, но Telegram не подтвердил приём. Не повторяю, чтобы не было дубля.',
 'contact-payload-blocked':'Не удалось проверить данные контакта.',
 'contact-already-handled':'Этот контакт уже обработан.',
 'manual-review':'Не удалось безопасно продолжить этот чат.',
 'history-changed-during-approval':'История изменилась. Не стал отправлять ответ вслепую.',
 'chat-input-disabled':'Поле отправки недоступно. Чат пропущен; повторных отправок нет.',
 'send-outcome-unknown':'Неясно, ушёл ли ответ. Не повторяю, чтобы не было дубля.',
 'outgoing-not-observed':'Не вижу отправленный ответ в истории. Повторять не стал.',
 'bound-chat-read-failed':'Не удалось прочитать переписку.',
 'groq-unsafe-reply':'Ответ ИИ не прошёл проверку. Отправлять его не стал.',
 'zai-unsafe-reply':'Ответ ИИ не прошёл проверку. Отправлять его не стал.',
 'zai-invalid-response':'Z.AI вернул непонятный ответ.',
 'zai-repeat-greeting':'ИИ снова поздоровался. Такой ответ не отправляю.',
 'gemini-unsafe-reply':'Ответ ИИ не прошёл проверку. Отправлять его не стал.',
 'gemini-invalid-response':'Gemini вернул непонятный ответ.',
 'gemini-repeat-greeting':'ИИ снова поздоровался. Такой ответ не отправляю.',
 'openrouter-unsafe-reply':'Ответ ИИ не прошёл проверку. Отправлять его не стал.',
 'groq-invalid-response':'ИИ вернул непонятный ответ.',
 'openrouter-invalid-response':'ИИ вернул непонятный ответ.',
 'groq-repeat-greeting':'ИИ снова поздоровался. Такой ответ не отправляю.',
 'openrouter-repeat-greeting':'ИИ снова поздоровался. Такой ответ не отправляю.',
}

def notify_exit(chain, who, result, *, sender=None, enabled=True, photo=None, photo_status=None, photo_sender=None):
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
        # Distinct unread batches must not be hidden by an older notice.
        excerpts=result.get('_exit_messages',[])
        batch=hashlib.sha256(json.dumps(excerpts if isinstance(excerpts,list) else [],ensure_ascii=True).encode()).hexdigest()
        signature = hashlib.sha256(json.dumps([reason,cause,seen,batch],ensure_ascii=True).encode()).hexdigest()
        db.execute('CREATE TABLE IF NOT EXISTS chain_exit_notices(chat TEXT,signature TEXT,status TEXT NOT NULL,PRIMARY KEY(chat,signature))')
        previous = db.execute('SELECT status FROM chain_exit_notices WHERE chat=? AND signature=?', (who['chat'],signature)).fetchone()
        if previous:
            return dict(chat_ref=ref,reason=reason,review_cause=cause,notification='already-attempted')
    if not enabled:
        return dict(chat_ref=ref,reason=reason,review_cause=cause,notification='disabled')
    if photo is not None:
        from assistant_contact_photo import png_size
        png_size(photo)
    if sender is None:
        try:
            token, chat = telegram_notify.load()
        except Exception:
            return dict(chat_ref=ref,reason=reason,review_cause=cause,notification='not-configured')
        sender = lambda text: telegram_notify.send(token,chat,text)
        if photo is not None:photo_sender=lambda text,image:telegram_notify.send_photo(token,chat,text,image)
    with chain.store.connection() as db:
        cur = db.execute("INSERT OR IGNORE INTO chain_exit_notices VALUES(?,?,'attempted-unknown')", (who['chat'],signature))
        if cur.rowcount != 1:
            return dict(chat_ref=ref,reason=reason,review_cause=cause,notification='already-attempted')
    excerpts=result.get('_exit_messages',[])
    excerpts=[x for x in excerpts if isinstance(x,str)] if isinstance(excerpts,list) else []
    excerpt=' / '.join(excerpts).replace('\x00','')[:800]
    review_text = {
        'ai-context-review':'ИИ не смог подобрать подходящий ответ по контексту. Отправки не было.',
        'history-missing':'Не хватает ранее проверенных сообщений. Нужна сверка истории.',
        'history-edited':'Ранее проверенные сообщения изменились. Ответ вслепую не отправлен.',
        'incoming-during-pending':'Пришло сообщение, но предыдущая отправка ещё не подтверждена. Повтор не отправлен.',
        'pending-outgoing-mismatch':'Исходящее сообщение не совпало с сохранённой отправкой. Нужна проверка.',
        'unjournalled-outgoing':'Обнаружено исходящее вне журнала программы. Нужна проверка.',
        'contact-batch-ambiguous':'Не удалось безопасно связать контакт с текущим этапом.',
    }
    explanation = review_text.get(cause,REASONS.get(reason,'Не удалось безопасно продолжить этот чат.'))
    if reason == 'greeting-not-verified':
        anchor=(result.get('diagnostics') or {}).get('greeting_anchor_failure')
        explanation={
            'missing-own':'В загруженной истории нет исходного приветствия из журнала. Нужна сверка истории.',
            'multiple-own':'До привязки нашлось несколько исходящих. Нельзя уверенно восстановить этап по журналу.',
            'hash-mismatch':'Исходное приветствие не совпало с журналом. Этот чат требует проверки.',
        }.get(anchor,explanation)
    if reason=='ai-temporarily-unavailable':
        from mumu_ai import failure_explanation
        explanation=failure_explanation((result.get('diagnostics') or {}).get('ai_failures',[]))
    contact_received=(result.get('stages') or {}).get('peer_contact') is True
    label='Успех: Контакт получен. ' if contact_received else 'Статус: ' if reason in ('contact-followup-sent','contact-clarification-sent') else 'Пропущено: '
    text = ('Собеседник: «'+excerpt+'»\n' if excerpt else 'Текст сообщения не включён в уведомление.\n') + label + explanation
    if photo_status=='unavailable':text+='\nСнимок переписки получить не удалось.'
    text=text[:950]  # reserve room for the port label in the 1024-char caption
    try:
        accepted=photo_sender(text,photo) if photo is not None and photo_sender is not None else sender(text)
        status = 'accepted' if accepted is True else 'unknown'
    except Exception:
        status = 'unknown'
    with chain.store.connection() as db:
        db.execute('UPDATE chain_exit_notices SET status=? WHERE chat=? AND signature=?', (status,who['chat'],signature))
    return dict(chat_ref=ref,reason=reason,review_cause=cause,notification=status,photo='attached' if photo is not None and photo_sender is not None else 'unavailable' if photo_status=='unavailable' else 'not-requested')
