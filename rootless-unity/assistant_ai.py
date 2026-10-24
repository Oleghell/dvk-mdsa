"""Provider adapters; MuMu workers use ordered failover, explicit-key UI tests do not."""
import groq_reply
import openrouter_reply
import gemini_reply
import zai_reply
from assistant_store import StateError

PRESETS = {'groq': (groq_reply.MODEL, 'llama-3.1-8b-instant'), 'openrouter': openrouter_reply.MODELS, 'gemini': gemini_reply.MODELS, 'zai': zai_reply.MODELS}
LABELS = {'groq': 'Groq', 'openrouter': 'OpenRouter', 'gemini': 'Google Gemini', 'zai': 'Z.AI'}


def module(provider):
    if provider not in LABELS:
        raise StateError('Выбери Groq, OpenRouter, Gemini или Z.AI.')
    return {'groq': groq_reply, 'openrouter': openrouter_reply, 'gemini': gemini_reply, 'zai': zai_reply}[provider]


def responder(provider, model, cancelled=lambda: False, *, entered_key=''):
    import os
    if os.environ.get('DVK_MUMU_MULTI')=='1' and not entered_key.strip():
        from mumu_ai import Responder
        return Responder(provider,model,cancelled)
    adapter = module(provider)
    options = dict(model=model, cancelled=cancelled)
    if entered_key.strip():
        key = adapter.key_value(entered_key.strip())
        options['key_loader'] = lambda: key
    if not entered_key.strip():
        from assistant_key_pool import load, Responder
        keys=load(provider)
        if keys:
            return Responder(provider,model,keys,cancelled)
    return adapter.Responder(**options)


def test_connection(provider, model, entered_key='', cancelled=lambda: False):
    ai = responder(provider, model, cancelled, entered_key=entered_key)
    for kind, messages, expected in (
            ('question', [('Привет', True), ('День тяжёлый, немного устала.', False)], 'reply'),
            ('contact', [('Привет', True), ('Привет', False), ('Как настроение?', True),
                         ('Уже лучше, спасибо!', False)], 'reply'),
            ('question', [('Привет', True), ('Не пиши мне больше.', False)], 'decline')):
        sample = dict(identity=dict(account='100', peer='200', chat='300'),
                      messages=[dict(id=str(i+1), sender='100' if own else '200', text=text)
                                for i, (text, own) in enumerate(messages)],
                      _reply_ids=[str(len(messages))])
        value = ai(kind, sample)
        if value['decision'] != expected:
            raise groq_reply.GroqError(provider + '-self-test-failed')
    return ai.calls


def explain(code):
    suffix = code.split('-', 1)[1] if '-' in code else code
    if code == 'groq-model-unavailable':
        return 'Groq: модель недоступна этому аккаунту или её ID не найден. Выбери доступную модель; корректный ключ сам по себе не даёт доступ ко всем моделям. [' + code + ']'
    if code in ('zai-model-unavailable','zai-paid-model-blocked'):
        return 'Z.AI: выбери glm-4.5-flash. Другие, в том числе платные, модели здесь не подключаются. [' + code + ']'
    if code == 'gemini-model-unavailable':
        return 'Gemini: модель недоступна аккаунту или этому API. Выбери доступный ID модели. [' + code + ']'
    message = {
        'key-unavailable': 'Сохранённый ключ недоступен. Вставь ключ в поле и нажми «Тест ИИ» или «Сохранить ключ ИИ».',
        'key-pool-invalid':'Проверь config/ai-keys.txt: секции [groq]/[openrouter]/[gemini]/[zai], один настоящий ключ на строку, до 16 на сервис.',
        'key-pool-exhausted':'Все доступные ключи временно недоступны. Чат пропущен, проверка продолжится позже.',
        'organization-restricted': 'Groq ограничил доступ организации. Проверь её статус в Groq Console; смена модели не снимает ограничение.',
        'key-invalid': 'Неверный формат ключа выбранного сервиса.',
        'unauthorized': 'Сервис отклонил ключ. Проверь его или выпусти новый.',
        'service-disabled': 'Google API отключён для проекта ключа. Включи Gemini Developer API в проекте; переключение ключа того же проекта не снимает ограничение.',
        'access-denied': 'Доступ запрещён настройками аккаунта или политикой сервиса.',
        'model-unavailable': 'Нет доступного провайдера для модели с текущей политикой приватности. Выбери другую бесплатную модель.',
        'rate-limit': 'Лимит запросов или перегрузка модели. Платного переключения нет.',
        'credits-required': 'Сервис отклонил запрос по балансу/лимиту. Платной замены не будет.',
        'timeout': 'Сервис не ответил вовремя. Автоматического повтора нет.',
        'rules-unavailable': 'Проверь файл config/groq-rules.txt: нужен непустой UTF-8.',
        'self-test-failed': 'Модель не прошла проверку структуры ответа или отказа.',
    }.get(suffix, 'Тест не пройден. Проверь модель, сеть и настройки.')
    return message + ' [' + code + ']'


def check_saved_keys(provider):
    from assistant_key_pool import load
    keys=load(provider)
    if keys:return len(keys)
    module(provider).load_key()
    return 1
