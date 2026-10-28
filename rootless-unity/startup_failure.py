"""Closed, data-minimal navigation failure evidence. No exception bodies/args."""
from contextlib import contextmanager

STAGES = {
 'bundle-check', 'adb-create', 'adb-preflight', 'device-recheck', 'forward-open',
 'device-recheck-after', 'forward-close', 'device-inspection', 'gadget-import',
 'gadget-manager', 'gadget-connect', 'gadget-process', 'gadget-attach',
 'profile-thread-drain','profile-selected-peer','profile-record-visit','profile-finish-journal','profile-authorization','profile-history-upload','script-create', 'script-load', 'runtime-check', 'script-run', 'result-validation',
 'navigation-targets-upload', 'navigation-source', 'navigation-result', 'navigation-diagnostic', 'navigation-destination'}
TYPES = {'StateError','CloudDatabaseError','TransportError','ServerNotRunningError','ProcessNotFoundError','PermissionDeniedError',
 'OperationCancelledError','ProtocolError','InvalidArgumentError','TimedOutError','RPCException',
 'InvalidOperationError','NotSupportedError','TestError','ValueError','KeyError','TypeError',
 'FileNotFoundError','PermissionError','ModuleNotFoundError','ImportError','OSError','RuntimeError'}
READ_CODES = {'client-version','cancelled','ambiguous-process','unexpected-process',
 'unsupported-runtime','invalid-forward','not-ready'}
ERRORS = {'startup-'+s+'-failed' for s in STAGES} | READ_CODES

# Reports 458-461 (v1.3.69, port 5573): a profile cycle died at
# startup-result-validation-failed (ValueError) and the closed report kept
# only the stage, never WHICH authored invariant rejected the navigation.
# The validators raise exactly these authored one-line messages; the exact
# literal is exported as a closed enum so the next report pinpoints the
# invariant. Source-pin tests keep this set in sync with the validators:
# every single-quoted raise ValueError('...') literal in the five validator
# files must be listed here. Nothing else may enter the report.
VALIDATION_CODES = frozenset({
    'Action without a selected visible result',
    'Chat action out of order',
    'Chat without eligible profile',
    'Cleanup failure not propagated',
    'Contradictory empty history',
    'Empty cycle did not submit',
    'Exactly ten bounded greeting choices are required',
    'False submission state',
    'Friends stage skipped',
    'Friends without profile',
    'Greeting split without complete empty history',
    'Greeting submitted without split frame',
    'Inconsistent avatar counts',
    'Inconsistent invalid friends source',
    'Inconsistent missing friends source',
    'Inconsistent navigation cleanup',
    'Inconsistent navigation success',
    'Inconsistent row counts',
    'Inconsistent selection counts',
    'Inconsistent selection exhaustion',
    'Inconsistent selection skips',
    'Inconsistent table counts',
    'Inconsistent temporary handle peak',
    'Input skip without disabled model',
    'Invalid action delay',
    'Invalid chat action flag',
    'Invalid chat checkpoint',
    'Invalid chat count',
    'Invalid chat return route',
    'Invalid chat state flag',
    'Invalid controller path',
    'Invalid cooperative scan counters',
    'Invalid cycle timeout',
    'Invalid empty skip',
    'Invalid friends count',
    'Invalid greeting preparation',
    'Invalid history samples',
    'Invalid history state',
    'Invalid manual-cycle deadline',
    'Invalid metadata diagnostic',
    'Invalid navigation count',
    'Invalid navigation flag',
    'Invalid navigation state',
    'Invalid observer call count',
    'Invalid parent depth',
    'Invalid profile handle count',
    'Invalid profile read counter',
    'Invalid profile read skip',
    'Invalid profile verification',
    'Invalid readiness flags',
    'Invalid readiness step',
    'Invalid selection category',
    'Invalid selection counter',
    'Invalid selection retry count',
    'Invalid temporary handle peak',
    'Invalid verified input flag',
    'Invalid visited profiles',
    'Missing automatic navigation',
    'Missing chat cycle fields',
    'Missing navigation report',
    'Missing profile navigation',
    'Missing profile read evidence',
    'Missing profile read skip reason',
    'Missing profile step',
    'Missing stop reason',
    'Navigation without confirmed UI thread',
    'Navigation without ready attached view',
    'Out-of-order navigation',
    'Profile skip before bounded reads',
    'Profile skip without read failure',
    'Readiness wait without verified chat',
    'Selection action without scan',
    'Send without stable empty history',
    'Shared skip outside MuMu worker',
    'Shared skip with submission',
    'Skipped profile opened chat',
    'Submission without invocation',
    'Unexpected backend or screen data',
    'Unexpected friends state',
    'Unexpected metadata checkpoint',
    'Unexpected navigation fields',
    'Unexpected profile fields',
    'Unexpected profile path',
    'Unexpected profile phase',
    'Unexpected selection checkpoint',
    'Unexpected selection counters',
    'Unexpected unattempted navigation',
    'Unfinished chat cycle',
    'Unfinished navigation',
    'Unknown count must remain unknown',
    'Unknown cycle error',
    'Unknown friends must remain unknown',
    'Unreported handle leak',
    'Unverified direct search return',
    'Unverified empty skip',
    'Unverified history classification',
    'Unverified profile identity',
    'Unverified profile skip',
    'Unverified send',
    'Unverified shared peer skip',
    'Unverified unready skip',
})

ADB_CHECKS = {'adb-version','test-connect','test-state','test-identity','test-boot-completed',
              'test-package-presence','test-forward-open','test-forward-close'}

def clean(value):
    required = {'stage','error','error_type'}
    if not isinstance(value, dict) or not required <= set(value) or set(value)-required-{'adb_check','adb_reason','validation'}:
        return None
    if (type(value['stage']) is not str or value['stage'] not in STAGES
        or type(value['error']) is not str or value['error'] not in ERRORS
        or type(value['error_type']) is not str or value['error_type'] not in TYPES | {'OtherError'}):
        return None
    if 'validation' in value and (type(value['validation']) is not str
        or value['validation'] not in VALIDATION_CODES):
        return None
    if set(value)-required:
        from adb_evidence import REASONS
        extra = set(value)-required
        if not extra <= {'adb_check','adb_reason','validation'}:
            return None
        if 'adb_check' in extra or 'adb_reason' in extra:
            if (not {'adb_check','adb_reason'} <= set(value) or type(value['adb_check']) is not str
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
    # Only a locally authored ValueError literal may name the broken invariant;
    # never str(error) for anything outside the closed set above.
    if type(error) is ValueError and len(error.args) == 1 and type(error.args[0]) is str \
            and error.args[0] in VALIDATION_CODES:
        value['validation'] = error.args[0]
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
 'profile-thread-drain':'Не удалось дождаться завершения потока разрешения. Новый проход не запускается.',
 'profile-selected-peer':'Не удалось получить результат выбранной анкеты.',
 'profile-record-visit':'Не удалось сохранить проверенный просмотр анкеты.',
 'profile-finish-journal':'Не удалось завершить запись результата в журнале отправок.',
 'profile-authorization':'Ошибка потока разрешения текущего приветствия.',
 'profile-history-upload':'Не удалось подготовить список исключённых анкет до начала native-прохода.',
 'bundle-check':'Не удалось проверить комплект APK.',
 'adb-create':'Не удалось подготовить ADB.',
 'adb-preflight':'Не удалось проверить подключение к MuMu этого порта.',
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
 'navigation-targets-upload':'Не удалось подготовить список чатов до начала перехода.',
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
