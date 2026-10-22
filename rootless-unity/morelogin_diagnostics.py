"""Allowlisted diagnostics: never serialize exception text, response bodies or credentials."""
from morelogin_common import CloudError, atomic_json, root_directory, phone_id

def diagnostic(error):
    error = error if isinstance(error, CloudError) else CloudError('api-unavailable')
    return {'code':error.code, 'stage':error.stage,
            'http_status':error.http_status, 'service_code':error.service_code}

def describe(error):
    item = diagnostic(error)
    reasons = {
        'configuration':'Не удалось загрузить настройки API (APP ID / Secret Key)',
        'api-transport':'Не удалось запустить защищённый Windows HTTP-клиент (проверь доступ к Windows PowerShell)',
        'api-http':'Сервер API вернул HTTP-ошибку',
        'api-denied':'MoreLogin отклонил запрос API',
        'api-response':'Ответ API не соответствует ожидаемому формату',
        'api-tls':'Не удалось проверить защищённое TLS-соединение',
        'api-dns':'Не удалось определить адрес api.morelogin.com',
        'api-timeout':'Сервер API не ответил вовремя',
        'api-network':'Не удалось установить сетевое соединение с API',
        'api-unavailable':'Внутренняя ошибка обращения к API',
    }
    text = reasons.get(item['code'], item['code'])
    if item['stage']:
        text = ('Авторизация API' if item['stage']=='auth' else 'Получение ADB-параметров') + ': ' + text
    if item['http_status'] is not None: text += ' (HTTP ' + str(item['http_status']) + ')'
    if item['service_code'] is not None: text += ' (код MoreLogin ' + str(item['service_code']) + ')'
    return text

def save_failure(ids, error, *, path=None):
    # Only validated IDs + fixed diagnostic fields; no raw errors/URLs/server msg.
    payload = {'status':'error', 'phone_ids':[phone_id(x) for x in ids], **diagnostic(error)}
    try:
        atomic_json(path or root_directory()/'last-connection.json', payload)
    except Exception:
        return False
    return True

def completion_text(failed):
    return ('Проверка завершилась с ошибкой. Причина указана у телефона; отчёт last-connection.json.'
            if failed else 'Проверка завершена. Смотри статусы телефонов.')
