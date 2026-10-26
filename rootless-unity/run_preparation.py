"""Closed startup evidence; no exception messages, arguments, keys or paths."""
from contextlib import contextmanager
import sqlite3
from groq_reply import GroqError, ERRORS as AI_ERRORS

STAGES = {'profile-thread-drain','profile-selected-peer','profile-record-visit','profile-finish-journal','profile-authorization',
 'profile-pending-read','profile-peer-check','profile-skip-ack','profile-approval','profile-reserve','profile-terminal-check','profile-ack','profile-history','profiles-config','run-imports','run-lock','run-inbox','run-inbox-result','run-profiles','run-profiles-result','run-report',
 'inbox-imports','inbox-contacts','inbox-ai','inbox-database','inbox-chain','inbox-photo',
 'inbox-navigation-adapter','inbox-config','inbox-walk','inbox-outbox','inbox-targets','inbox-review'}
ERRORS = {'prepare-'+s+'-failed' for s in STAGES} | AI_ERRORS | {'configuration-invalid'}
TYPES = {'ValueError','TypeError','KeyError','AttributeError','FileNotFoundError','PermissionError',
 'ModuleNotFoundError','ImportError','OSError','RuntimeError','StateError','GroqError','ConfigError',
 'TransportError','ServerNotRunningError','TimedOutError','RPCException','OperationCancelledError','ProtocolError','ProcessNotFoundError','InvalidOperationError',
 'TelegramError','OperationalError','DatabaseError','IntegrityError','ProgrammingError','InterfaceError','OtherError','CloudDatabaseError'}
DATABASE_CODES = {'SQLITE_ERROR','SQLITE_AUTH','SQLITE_BUSY','SQLITE_BUSY_SNAPSHOT',
 'SQLITE_BUSY_RECOVERY','SQLITE_LOCKED','SQLITE_LOCKED_SHAREDCACHE','SQLITE_READONLY',
 'SQLITE_CANTOPEN','SQLITE_CORRUPT','SQLITE_NOTADB','SQLITE_FULL','SQLITE_IOERR',
 'SQLITE_CONSTRAINT','SQLITE_CONSTRAINT_PRIMARYKEY','SQLITE_CONSTRAINT_UNIQUE','SQLITE_SCHEMA'}
CONFIG_FIELDS = {'cities','greetings'}
CONFIG_REASONS = {'file-unavailable','invalid-json','invalid-structure','invalid-text','duplicate-text'}

def clean(value):
    required={'stage','error','error_type'}
    if not isinstance(value,dict) or not required<=set(value) or set(value)-required-{'database_code','config_field','config_reason','database'}:return None
    for key,allowed in (('stage',STAGES),('error',ERRORS),('error_type',TYPES)):
        if type(value[key]) is not str or value[key] not in allowed:return None
    if 'database_code' in value and (type(value['database_code']) is not str or value['database_code'] not in DATABASE_CODES):return None
    if {'config_field','config_reason'} & set(value):
        if not {'config_field','config_reason'}<=set(value):return None
        if type(value['config_field']) is not str or value['config_field'] not in CONFIG_FIELDS:return None
        if type(value['config_reason']) is not str or value['config_reason'] not in CONFIG_REASONS:return None
    if 'database' in value:
        from cloud_database import clean_diagnostic
        if clean_diagnostic(value['database']) is None:return None
    return dict(value)

def record(error,stage):
    if stage not in STAGES:raise ValueError('Invalid preparation stage')
    previous=clean(getattr(error,'_dvk_preparation',None))
    if previous:return previous
    from assistant_config import ConfigError
    code='prepare-'+stage+'-failed'
    if type(error) is GroqError and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in AI_ERRORS:code=error.args[0]
    if type(error) is ConfigError:code='configuration-invalid'
    name=type(error).__name__
    value=dict(stage=stage,error=code,error_type=name if name in TYPES else 'OtherError')
    if isinstance(error,sqlite3.Error):
        dbcode=getattr(error,'sqlite_errorname',None)
        if type(dbcode) is str and dbcode in DATABASE_CODES:value['database_code']=dbcode
    if type(error) is ConfigError:
        field=getattr(error,'field',None);reason=getattr(error,'reason',None)
        if type(field) is str and field in CONFIG_FIELDS and type(reason) is str and reason in CONFIG_REASONS:
            value.update(config_field=field,config_reason=reason)
    from cloud_database import diagnostic
    database=diagnostic(error)
    if database is not None:value['database']=database
    error._dvk_preparation=value
    return dict(value)

@contextmanager
def checkpoint(stage):
    try:yield
    except Exception as error:
        record(error,stage)
        raise

def from_report(report):
    if not isinstance(report,dict):return None
    for item in (report.get('last_preparation_failure'),report.get('preparation_failure')):
        safe=clean(item)
        if safe:return safe
    for key in ('initial_run','last_profile_run','last_pass'):
        nested=report.get(key)
        if isinstance(nested,dict):
            safe=clean(nested.get('preparation_failure'))
            if safe:return safe
    return None

LABELS = {
 'profile-thread-drain':'Поток проверки разрешения ещё не завершился; повтор отправки запрещён.',
 'profile-selected-peer':'Не удалось прочитать выбранную анкету после native-цикла.',
 'profile-record-visit':'Не удалось сохранить результат просмотра анкеты в основной базе.',
 'profile-finish-journal':'Не удалось завершить запись результата в журнал отправки.',
 'profile-authorization':'Ошибка проверки разрешения на приветствие.',
 'profile-pending-read':'Не удалось прочитать запрос разрешения native-прохода.',
 'profile-peer-check':'Не удалось проверить общий запрет первого приветствия.',
 'profile-skip-ack':'Не удалось подтвердить пропуск уже обработанного собеседника.',
 'profile-approval':'Не удалось проверить разрешение на приветствие.',
 'profile-reserve':'Не удалось сохранить атомарный резерв приветствия в основной базе.',
 'profile-terminal-check':'Не удалось повторно проверить контакт/отказ перед native ACK.',
 'profile-ack':'Не удалось подтвердить native-разрешение после резервирования.',
 'profile-history':'Не удалось прочитать историю анкет из основной базы до запуска native-скрипта.',
 'profiles-config':'Не удалось прочитать настройки перед проходом по анкетам.',
 'run-imports':'Не удалось загрузить компоненты первого прохода.',
 'run-lock':'Не удалось получить блокировку запуска.',
 'run-inbox':'Не удалось подготовить проход по входящим.',
 'run-inbox-result':'Получен неверный результат прохода по входящим.',
 'run-profiles':'Не удалось выполнить проход по анкетам.',
 'run-profiles-result':'Получен неверный результат прохода по анкетам.',
 'run-report':'Не удалось сохранить отчёт первого прохода.',
 'inbox-imports':'Не удалось загрузить компоненты обработки входящих.',
 'inbox-contacts':'Не удалось прочитать настройки Telegram для передачи контактов.',
 'inbox-ai':'Не удалось подготовить выбранный ИИ и список ключей.',
 'inbox-database':'Не удалось открыть общую базу диалогов.',
 'inbox-chain':'Не удалось подготовить таблицы и цепочку ответов.',
 'inbox-photo':'Не удалось загрузить компонент снимка профиля.',
 'inbox-navigation-adapter':'Не удалось загрузить обработчик списка диалогов.',
 'inbox-config':'Не удалось прочитать config/cities.json или config/greetings.json.',
 'inbox-walk':'Ошибка внутри прохода по входящим.',
 'inbox-outbox':'Не удалось прочитать очередь передачи контактов.',
 'inbox-targets':'Не удалось подготовить список диалогов из общей базы.',
 'inbox-review':'Не удалось прочитать итоговые счётчики диалогов.'}

def message(report):
    v=from_report(report)
    if not v:return None
    text=LABELS[v['stage']]
    if v['error'] in AI_ERRORS:
        from assistant_ai import explain
        text+=' '+explain(v['error'])
    if 'config_field' in v:
        text+=' Файл: config/'+v['config_field']+'.json. Причина: '+v['config_reason']+'.'
    if 'database_code' in v:text+=' Код базы: '+v['database_code']+'.'
    if 'database' in v:text+=' Код облачной базы: '+v['database']['code']+'. Операция: '+v['database']['operation']+'.'
    return text+' ['+v['error']+'; '+v['error_type']+']'
