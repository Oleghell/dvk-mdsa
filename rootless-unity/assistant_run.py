"""One «Старт»: replies in unread chain chats, then new profiles. One device lock."""
import json
from run_preparation import checkpoint,record,message as preparation_message

from assistant_lock import operation_lock
from assistant_store import StateError, data_directory
from version import VERSION
from assistant_authorization import flags
from assistant_inbox import PAUSE_OUTCOMES

MODES = ('full', 'inbox', 'profiles')
REPORT = 'last-run.json'


def write_report(value):
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / REPORT
    temporary = target.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding='utf-8')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target.name


def start(settings, stopped, approve, progress=lambda _: None, *, mode='full', fresh_session=False,
          inbox=None, profiles=None, lock=operation_lock, write=write_report, between_profiles=None):
    if mode not in MODES:
        raise ValueError('Invalid mode')
    result = dict(tool_version=VERSION, mode=mode, status='stopped', reason='not-started',
                  inbox=None, profiles=None, preparation_failure=None, per_message_confirmation=True, automatic_send=False)
    result.update(flags(approve))
    stage='run-lock'
    try:
        if stopped.is_set():
            raise StateError('cancelled')
        stage='run-imports'
        with checkpoint(stage):
            if inbox is None:
                from assistant_inbox import run as inbox
            if profiles is None:
                from assistant_profiles import run as profiles
        stage='run-lock'
        with lock():
            if mode in ('full', 'inbox'):
                stage='run-inbox'
                with checkpoint(stage):
                    result['inbox'] = inbox(settings, stopped, approve, progress)
                stage='run-inbox-result'
                if result['inbox']['status'] not in ('inbox-completed', 'inbox-empty'):
                    raise StateError('inbox-not-finished')
                if set(result['inbox']['outcomes']) & PAUSE_OUTCOMES:
                    raise StateError('inbox-needs-review')
            if mode in ('full', 'profiles'):
                stage='run-profiles'
                with checkpoint(stage):
                    result['profiles'] = profiles(settings, stopped, approve, progress,
                                                  limit=settings.profile_limit,
                                                  fresh_session=fresh_session,
                                                  **({'between_profiles': between_profiles} if between_profiles is not None else {}))
                stage='run-profiles-result'
                if result['profiles']['status'] != 'profiles-completed':
                    raise StateError('profiles-not-finished')
        result.update(status='completed', reason='none')
    except Exception as error:
        if not (isinstance(error,StateError) and str(error) in ('cancelled','inbox-not-finished','inbox-needs-review','profiles-not-finished')):
            result['preparation_failure']=record(error,stage)
        result.update(status='cancelled' if stopped.is_set() else
                      'paused' if isinstance(error, StateError) and str(error) == 'inbox-needs-review' else 'stopped',
                      reason='cancelled' if stopped.is_set() else
                      str(error) if isinstance(error, StateError) and str(error) in
                      ('inbox-not-finished', 'inbox-needs-review', 'profiles-not-finished', 'cancelled') else
                      'initialization-failed')
    try:
        result['report_name'] = write(result)
    except Exception as error:
        result['report_name'] = None
        if result['preparation_failure'] is None:result['preparation_failure']=record(error,'run-report')
    return result


def summary(result):
    """Plain-language Russian status for the main window."""
    parts = []
    inbox = result.get('inbox')
    if inbox:
        if inbox['status'] == 'inbox-empty':
            parts.append('Ответы: чатов цепочки пока нет.')
        else:
            parts.append(f"Ответы: открыто чатов {inbox['dialogs_opened']}, попыток отправки "
                         f"{inbox['submission_calls']}, новых исходящих замечено {inbox['outgoing_observed']}, контактов в Telegram {inbox['contacts_forwarded']}.")
            if inbox['status'] != 'inbox-completed':
                parts.append(INBOX_REASONS.get(inbox['reason'], 'Ответы остановлены: ' + inbox['reason'] + '.'))
    profiles = result.get('profiles')
    if profiles:
        city = profiles['current_city']
        parts.append(f"Анкеты{(' (' + city + ')') if city else ''}: подходящих {profiles.get('qualified_profiles', 0)}/{profiles['profile_limit']}, просмотрено {profiles['profiles_checked']}, "
                     f"попыток приветствия {profiles['send_attempts']}, возвратов обработчика {profiles['handlers_returned']}, "
                     f"пропущено (50+ друзей) {profiles['skipped_friends']}, "
                     f"пропущено (уже есть переписка) {profiles['skipped_existing_chat']}.")
        if profiles.get('send_attempts_unknown'):
            parts.append('Цикл оборвался: число дополнительных попыток приветствия неизвестно.')
        if profiles['status'] != 'profiles-completed':
            parts.append(PROFILE_REASONS.get(profiles['reason'], 'Анкеты остановлены: ' + profiles['reason'] + '.'))
    if inbox or profiles:
        parts.append('Доставка собеседнику не подтверждена; появление приветствий в истории не проверялось.'
                     if profiles else 'Появление исходящего в истории не подтверждает доставку собеседнику.')
    if result['status'] == 'completed':
        parts.append('Готово. Возврат к анкетам подтверждён.')
    elif result['status'] == 'cancelled':
        parts.append('Остановлено. Выполненные действия не откатываются.')
    elif preparation_message(result):
        parts.append(preparation_message(result))
    elif result['reason'] == 'device-busy-or-start-check-stopped':
        parts.append('Запуск не выполнен: проверь пути в настройках и MuMu №4.')
    else:
        parts.append('Проверь экран MuMu вручную. Неизвестные отправки не повторяются.')
    return ' '.join(parts) + ' Отчёт: ' + REPORT + '.'


INBOX_REASONS = {
    'chat-send-outcome-unknown': 'Результат отправки неизвестен — повтора не будет, проверь чат.',
    'chat-outgoing-not-observed': 'Сообщение не появилось в истории — проверь чат, повтора не будет.',
    'chat-history-changed-during-approval': 'Чат изменился во время подтверждения — отправки не было.',
    'unread-selection-not-verified': 'Не удалось проверить непрочитанные — чаты не тронуты.',
    'untracked-dialog': 'Открылся чужой чат — остановка без чтения.',
    'cancelled': 'Остановлено.',
}
PROFILE_REASONS = {
    'profile-scan-limit': 'Достигнут предел просмотра 200 анкет. Подходящих недостаточно; продолжение — новым запуском.',
    'greeting-not-approved': 'Приветствие не подтверждено — оно не отправлялось.',
    'send-outcome-unknown': 'Результат отправки приветствия неизвестен — повтора не будет.',
    'city-pool-exhausted': 'Свободных городов нет: остальные заняты другими портами. Добавь города в настройки.',
    'city-reservation-unresolved': 'Предыдущая смена города не подтверждена. Останови порт и проверь поиск вручную; неизвестный переход не повторяется.',
    'city-no-alternative': 'В config/cities.json нет другого города.',
    'city-not-verified': 'Смена города не подтверждена — проверь настройки поиска вручную.',
    'search-cycle-limit': 'Достигнут предел 200 поисковых циклов, включая пустые города. Подходящих недостаточно; продолжение — новым запуском.',
    'return-not-verified': 'Возврат к анкетам не подтверждён — проверь экран.',
    'profile-check-stopped': 'Анкета не прочиталась (например, не видно число друзей) — проверь экран.',
    'legacy-reservation-present': 'Найден старый незавершённый резерв отправки — нужна ручная сверка.',
    'cancelled': 'Остановлено.',
}
