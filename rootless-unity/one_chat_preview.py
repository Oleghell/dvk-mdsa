"""A fixed local demo draft, not the conversation engine and never a sender."""
from one_chat_device import report as read_report

TEST_TEXT = 'Тест предпросмотра'
QUESTION = 'Как дела?)'
CODE = 'ask-how-are-you'
FIELDS = {'preview_code', 'preview_reason', 'preview_available', 'preview_created'}
REASONS = {'baseline-only', 'no-new-messages', 'new-test-text', 'new-outgoing',
           'multiple-new-incoming', 'non-text-incoming', 'unsupported-test-text',
           'saved-preview-expired'}


def fields(code='none', reason='no-new-messages', created=False):
    value = dict(preview_code=code, preview_reason=reason,
                 preview_available=code == CODE, preview_created=created)
    return validate(value)


def validate(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('Invalid preview fields')
    code, reason = value['preview_code'], value['preview_reason']
    if code not in {'none', CODE} or reason not in REASONS:
        raise ValueError('Invalid preview enum')
    if type(value['preview_available']) is not bool or type(value['preview_created']) is not bool:
        raise ValueError('Invalid preview flags')
    if value['preview_available'] != (code == CODE):
        raise ValueError('Invalid preview availability')
    if reason == 'new-test-text':
        if code != CODE or value['preview_created'] is not True:
            raise ValueError('Invalid new preview')
    elif value['preview_created'] or (code == CODE and reason != 'no-new-messages'):
        raise ValueError('Invalid retained preview')
    return dict(value)


def decide(baseline, new_messages, account, saved=False, expired=False):
    """Set-based delta only. Never sort IDs or infer message chronology."""
    if baseline:
        return fields(reason='baseline-only')
    if not new_messages:
        if expired:
            return fields(reason='saved-preview-expired')
        return fields(CODE if saved else 'none')
    if any(m['sender'] == account for m in new_messages):
        return fields(reason='new-outgoing')
    if len(new_messages) != 1:
        return fields(reason='multiple-new-incoming')
    text = new_messages[0]['text']
    if text is None:
        return fields(reason='non-text-incoming')
    # Deliberately one explicit test phrase; not a semantic or production reply.
    if text.strip().casefold() != TEST_TEXT.casefold():
        return fields(reason='unsupported-test-text')
    return fields(CODE, 'new-test-text', True)


def display(value):
    p = validate({k: value[k] for k in FIELDS})
    if p['preview_available']:
        prefix = 'Новый тестовый черновик' if p['preview_created'] else 'Сохранённый тестовый черновик (не новое событие)'
        return prefix + ':\n' + QUESTION + '\nНе отправлен. В поле ввода приложения ничего не вставлено.'
    labels = {
        'baseline-only': 'Исходная история сохранена. Старые сообщения не создают черновик.',
        'no-new-messages': 'Новых сообщений нет. Черновика нет.',
        'new-outgoing': 'Есть новое исходящее сообщение. Черновик не предложен: проверь чат вручную.',
        'multiple-new-incoming': 'Пришло несколько сообщений. Их порядок не установлен: проверь чат вручную.',
        'non-text-incoming': 'Новое сообщение не текстовое. Черновик не предложен.',
        'unsupported-test-text': 'Для демонстрации отправь со второго аккаунта ровно: «' + TEST_TEXT + '». Другие тексты требуют ручного ответа.',
        'saved-preview-expired': 'История изменилась вне предпросмотра. Старый черновик скрыт.',
    }
    return labels[p['preview_reason']]


def report(outcome=None, *, failure=False):
    if outcome is None:
        result = read_report(failure=failure)
    else:
        if failure or set(outcome) != FIELDS | {'status', 'observed_messages', 'incoming_messages', 'new_incoming', 'baseline_recorded'}:
            raise ValueError('Invalid preview report')
        p = validate({k: outcome[k] for k in FIELDS})
        result = read_report({k: v for k, v in outcome.items() if k not in FIELDS})
        if p['preview_created'] and (result['status'] != 'read-complete' or result['new_incoming'] != 1):
            raise ValueError('Preview without one new incoming')
        if (result['status'] == 'baseline-recorded') != (p['preview_reason'] == 'baseline-only'):
            raise ValueError('Preview baseline mismatch')
        if p['preview_reason'] in {'no-new-messages', 'saved-preview-expired'} and result['new_incoming']:
            raise ValueError('Preview delta mismatch')
        result.update(p)
    result.update(mode='one-bound-test-chat-read-only-preview', preview_mode_available=True,
                  preview_test_phrase_only=True, draft_inserted=False)
    return result
