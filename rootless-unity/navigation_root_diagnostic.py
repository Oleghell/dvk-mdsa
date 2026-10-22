"""Closed, non-sensitive explanation of a root probe which precedes navigation."""
from uikit_root import STAGES, STEPS, SOURCES
FLAGS = ('api_available','metadata_ready','observer_installed','observed_callback','main_thread_confirmed')
KEYS = set(FLAGS) | {'stage','step','frame_source','observed_calls'}

def clean(value):
    if not isinstance(value,dict) or set(value)!=KEYS:
        raise ValueError('Invalid root diagnostic fields')
    if value['stage'] not in STAGES or value['step'] not in STEPS or value['frame_source'] not in SOURCES+['not-observed']:
        raise ValueError('Invalid root diagnostic category')
    if any(type(value[k]) is not bool for k in FLAGS):
        raise ValueError('Invalid root diagnostic flag')
    if type(value['observed_calls']) is not int or not 0<=value['observed_calls']<=10000:
        raise ValueError('Invalid root diagnostic count')
    return dict(value)

def extract(validated_probe):
    # Caller must validate the full probe first. Never export arbitrary RPC fields.
    return clean({k:validated_probe[k] for k in KEYS})

LABELS = {
 'api-incomplete':'В приложении не найдены нужные функции IL2CPP.',
 'metadata-not-ready':'Внутренние компоненты приложения ещё не готовы.',
 'signature-mismatch':'Внутренняя структура приложения не совпала с поддерживаемой.',
 'native-call-failed':'Ошибка обращения к внутренним компонентам приложения.',
 'callback-timeout':'Не дождался проверенного кадра интерфейса приложения.',
 'hook-unavailable':'Не удалось включить наблюдение за интерфейсом.',
 'hook-limit':'Превышен безопасный предел наблюдения за интерфейсом.',
 'off-main-thread':'Не удалось подтвердить главный поток интерфейса.',
 'runtime-not-ready':'Среда интерфейса приложения ещё не готова.',
 'window-not-ready':'Главное окно приложения ещё не готово.'}

def message(navigation):
    if not isinstance(navigation,dict) or navigation.get('stage')!='not-attempted':return None
    try:root=clean(navigation.get('root_probe'))
    except (ValueError,TypeError):return None
    return LABELS.get(root['stage'])
