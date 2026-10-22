"""Allowlisted diagnostics: never serialize exception text, response bodies or credentials."""
import shlex
import re
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

def format_summary(entry):
    """No raw command, host, user, option value, password or arbitrary field name."""
    if not isinstance(entry,dict):return None
    def kind(value):
        if value is None:return 'null'
        if isinstance(value,bool):return 'boolean'
        if isinstance(value,str):return 'string'
        if type(value) in (int,float):return 'number'
        return 'other'
    command=entry.get('command')
    try:args=shlex.split(command) if isinstance(command,str) and len(command)<=2048 else []
    except ValueError:args=[]
    options=[]
    known={'hostkeyalgorithms','pubkeyacceptedalgorithms','pubkeyacceptedkeytypes','stricthostkeychecking','userknownhostsfile','proxycommand','localcommand','hostname','forwardagent','identityfile'}
    for index,arg in enumerate(args):
        if arg.startswith('-o'):
            option=arg[2:] or (args[index+1] if index+1<len(args) else '')
            name=option.partition('=')[0].lower()
            options.append(name if name in known else 'unknown')
    host=entry.get('adbIp')
    return dict(command_kind=args[0] if args and args[0] in ('ssh','adb','adb.exe') else 'other',
        token_count=len(args),option_keys=options,
        endpoint_kind='ipv4-shaped' if isinstance(host,str) and re.fullmatch(r'[0-9.]+',host) else 'non-ipv4',
        fields={name:kind(entry.get(name)) for name in ('command','adbIp','adbPort','adbPassword')})

def save_failure(ids, error, *, path=None, entry=None):
    # Only validated IDs + fixed diagnostic fields; no raw errors/URLs/server msg.
    payload = {'status':'error', 'phone_ids':[phone_id(x) for x in ids], **diagnostic(error)}
    if entry is not None:payload['format']=format_summary(entry)
    try:
        atomic_json(path or root_directory()/'last-connection.json', payload)
    except Exception:
        return False
    return True

def completion_text(failed):
    return ('Проверка завершилась с ошибкой. Причина указана у телефона; отчёт last-connection.json.'
            if failed else 'Проверка завершена. Смотри статусы телефонов.')
