"""One local per-device heuristic warning, never a delivery/account-health verdict."""
import json
from pathlib import Path

PASS_LIMIT = 6
GREETING_LIMIT = 30


def notify(*, loader=None, sender=None):
    import telegram_notify
    try:
        token, chat = (loader or telegram_notify.load)()
    except Exception:
        return 'not-configured'
    text = ('⚠️ Нужна проверка ресурса.\n'
            'Не менее 6 завершённых проверок диалогов подряд без новых входящих; '
            'за этот период обработчик вернулся после минимум 30 приветствий.\n'
            'Проверь аккаунт и приложение. Это сигнал для проверки, не подтверждение '
            'блокировки или доставки сообщений. Работа продолжается.')
    try:
        return 'accepted' if (sender or telegram_notify.send)(token, chat, text) is True else 'unknown'
    except Exception:
        return 'unknown'  # Telegram may already have accepted it. Never retry.


class Watch:
    def __init__(self, path=None):
        if path is None:
            from assistant_store import data_directory
            path = data_directory() / 'resource-watch.json'
        self.path = Path(path)
        self.state = dict(schema=1, empty_passes=0, greetings=0, notified=False)
        if self.path.exists():
            if self.path.stat().st_size > 1024:
                raise ValueError('Invalid resource watch state')
            state = json.loads(self.path.read_text(encoding='utf-8'))
            if (type(state) is not dict or set(state) != set(self.state)
                    or type(state['schema']) is not int or state['schema'] != 1
                    or type(state['empty_passes']) is not int or not 0 <= state['empty_passes'] <= PASS_LIMIT
                    or type(state['greetings']) is not int or not 0 <= state['greetings'] <= GREETING_LIMIT
                    or type(state['notified']) is not bool):
                raise ValueError('Invalid resource watch state')
            self.state = state

    def save(self):
        from mumu_common import atomic
        atomic(self.path, self.state)

    def reset(self):
        # Retain the alert latch unless an actual new incoming was observed.
        self.state.update(empty_passes=0, greetings=0)

    def profiles(self, result):
        value = result.get('profiles') if isinstance(result, dict) else None
        if not isinstance(value, dict):return
        n = value.get('handlers_returned')
        if (result.get('status') != 'completed' or value.get('status') != 'profiles-completed'
                or value.get('send_attempts_unknown') is not False
                or type(n) is not int or n < 0):
            self.reset()
        else:
            self.state['greetings'] = min(GREETING_LIMIT, self.state['greetings'] + n)
        self.save()

    def inbox(self, result, *, enabled=True, alert=notify):
        incoming = result.get('new_incoming_messages')
        if type(incoming) is int and incoming > 0:
            self.reset()
            self.state['notified'] = False
        elif (result.get('status') not in ('inbox-completed', 'inbox-empty')
                or result.get('incoming_scan_complete') is not True
                or incoming != 0 or type(incoming) is not int
                or any(result.get(key, 0) != 0 for key in (
                    'submission_calls', 'handler_returns', 'outgoing_observed',
                    'history_deferred', 'history_cooldown_skipped', 'isolated_dialogs', 'review_pending'))
                or any(k in result.get('outcomes', {}) for k in ('manual-review', 'message-not-approved'))):
            self.reset()
        else:
            self.state['empty_passes'] = min(PASS_LIMIT, self.state['empty_passes'] + 1)
        due = (enabled and not self.state['notified'] and self.state['empty_passes'] >= PASS_LIMIT
               and self.state['greetings'] >= GREETING_LIMIT)
        if due:self.state['notified'] = True
        # Reserve before network. A failed save must not send or create repeats.
        self.save()
        if not due:return 'not-needed'
        try:
            outcome = alert()
            return outcome if outcome in ('accepted', 'unknown', 'not-configured') else 'unknown'
        except Exception:
            return 'unknown'
