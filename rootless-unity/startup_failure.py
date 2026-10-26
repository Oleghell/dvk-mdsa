"""Closed, data-minimal navigation failure evidence. No exception bodies/args."""
from contextlib import contextmanager

STAGES = {
 'bundle-check', 'adb-create', 'adb-preflight', 'device-recheck', 'forward-open',
 'device-recheck-after', 'forward-close', 'device-inspection', 'gadget-import',
 'gadget-manager', 'gadget-connect', 'gadget-process', 'gadget-attach',
 'profile-history-upload','script-create', 'script-load', 'runtime-check', 'script-run', 'result-validation',
 'navigation-source', 'navigation-result', 'navigation-diagnostic', 'navigation-destination'}
TYPES = {'TransportError','ServerNotRunningError','ProcessNotFoundError','PermissionDeniedError',
 'OperationCancelledError','ProtocolError','InvalidArgumentError','TimedOutError','RPCException',
 'InvalidOperationError','NotSupportedError','TestError','ValueError','KeyError','TypeError',
 'FileNotFoundError','PermissionError','ModuleNotFoundError','ImportError','OSError','RuntimeError'}
READ_CODES = {'client-version','cancelled','ambiguous-process','unexpected-process',
 'unsupported-runtime','invalid-forward','not-ready'}
ERRORS = {'startup-'+s+'-failed' for s in STAGES} | READ_CODES

ADB_CHECKS = {'adb-version','test-connect','test-state','test-identity','test-boot-completed',
              'test-package-presence','test-forward-open','test-forward-close'}

def clean(value):
    required = {'stage','error','error_type'}
    if not isinstance(value, dict) or not required <= set(value) or set(value)-required-{'adb_check','adb_reason'}:
        return None
    if (type(value['stage']) is not str or value['stage'] not in STAGES
        or type(value['error']) is not str or value['error'] not in ERRORS
        or type(value['error_type']) is not str or value['error_type'] not in TYPES | {'OtherError'}):
        return None
    if set(value)-required:
        from adb_evidence import REASONS
        if (set(value)-required != {'adb_check','adb_reason'} or type(value['adb_check']) is not str
            or value['adb_check'] not in ADB_CHECKS or type(value['adb_reason']) is not str
            or value['adb_reason'] not in REASONS-{'none'}):
            return None
    return dict(value)

def record(error, stage):
    if stage not in STAGES:
        raise ValueError('Invalid fixed failure stage')
    previous = clean(getattr(error, '_dvk_failure', None))
    if previous:
        return previous
    name = type(error).__name__
    code = 'startup-'+stage+'-failed'
    # Only a locally authored exception may contribute a fixed code, never str(error).
    from one_chat_device import ReadStopped
    if type(error) is ReadStopped and len(error.args) == 1 and type(error.args[0]) is str and error.args[0] in READ_CODES:
        code = error.args[0]
    value = dict(stage=stage, error=code, error_type=name if name in TYPES else 'OtherError')
    error._dvk_failure = value
    return dict(value)

@contextmanager
def checkpoint(stage, *, adb=None):
    try:
        yield
    except Exception as error:
        value = record(error, stage)
        if adb is not None:
            from adb_evidence import REASONS
            events = getattr(adb, 'adb_events', [])
            if type(events) is list:
                for event in reversed(events[:40]):
                    if (type(event) is dict and event.get('status') == 'failed'
                        and type(event.get('check')) is str and event['check'] in ADB_CHECKS
                        and type(event.get('reason')) is str and event['reason'] in REASONS-{'none'}):
                        value.update(adb_check=event['check'],adb_reason=event['reason'])
                        error._dvk_failure = value
                        break
        raise

LABELS = {
 'profile-history-upload':'Не удалось подготовить список исключённых анкет до начала native-прохода.',
 'bundle-check':'Не удалось проверить комплект APK.',
 'adb-create':'Не удалось подготовить ADB.',
 'adb-preflight':'Не удалось проверить подключение к MuMu №4.',
 'device-recheck':'Не удалось повторно проверить устройство.',
 'device-recheck-after':'Не удалось подтвердить устройство после операции.',
 'forward-open':'Не удалось открыть канал связи с приложением.',
 'forward-close':'Не удалось закрыть канал связи; результат не принят.',
 'device-inspection':'Не удалось выполнить проверку приложения.',
 'gadget-import':'Не удалось загрузить компонент подключения.',
 'gadget-manager':'Не удалось подготовить подключение к приложению.',
 'gadget-connect':'Не удалось подключиться к компоненту внутри приложения.',
 'gadget-process':'Не удалось подтвердить процесс приложения.',
 'gadget-attach':'Не удалось подключиться к процессу приложения.',
 'script-create':'Не удалось подготовить скрипт проверки.',
 'script-load':'Не удалось загрузить скрипт проверки.',
 'runtime-check':'Не удалось подтвердить совместимость приложения.',
 'script-run':'Ошибка выполнения проверки внутри приложения.',
 'result-validation':'Приложение вернуло неподтверждённый результат проверки.',
 'navigation-source':'Не удалось подготовить переход в приложении.',
 'navigation-result':'Получен неверный формат результата перехода.',
 'navigation-diagnostic':'Получен неверный формат диагностики перехода.',
 'navigation-destination':'Не удалось подтвердить нужный экран.'}

def message(value):
    if not isinstance(value, dict): return None
    evidence = clean({k:v for k,v in value.items() if k != 'operation'})
    if not evidence: return None
    text = LABELS[evidence['stage']]
    causes = {'connection-refused':'MuMu отклонил подключение.',
              'connection-timeout':'Подключение к MuMu не дождалось ответа.',
              'device-offline':'Устройство недоступно (offline).',
              'device-unauthorized':'ADB не авторизован на устройстве.',
              'device-not-found':'ADB не видит нужное устройство.',
              'command-timeout':'Команда ADB не дождалась ответа.',
              'executable-launch-failed':'Не удалось запустить ADB.',
              'adb-version-mismatch':'Не совпадают версии клиента и сервера ADB.'}
    cause = causes.get(evidence.get('adb_reason'))
    return text + (' ' + cause if cause else '')


def retryable_connection(error):
    value=clean(getattr(error,'_dvk_failure',None))
    return bool(value and value['stage'] in {'gadget-connect','gadget-process','gadget-attach'}
                and value['error_type'] in {'TransportError','ServerNotRunningError','TimedOutError'})


def recoverable_adb(value):
    """Only fixed ADB transport evidence; never generic internal/journal errors."""
    value=clean(value)
    if not value:return False
    stage=value['stage'];check=value.get('adb_check');reason=value.get('adb_reason')
    pairs={'forward-open':{'test-forward-open'},'forward-close':{'test-forward-close'},
           'adb-preflight':ADB_CHECKS-{'test-forward-open','test-forward-close'},
           'device-recheck':{'test-connect','test-state','test-identity','test-boot-completed'},
           'device-recheck-after':{'test-connect','test-state','test-identity','test-boot-completed'}}
    if check not in pairs.get(stage,set()):return False
    return reason in {'connection-refused','connection-timeout','connection-failed','device-offline',
                      'device-not-found','no-device','command-timeout','adb-server-unavailable'} or (
                      stage in {'forward-open','forward-close'} and reason=='command-failed')
