"""Guarded *supervised* five-profile test workflow, not an unattended sender.

UI anchors are exact crops of static controls from the tested 900x1600 layout.
They contain no names/photos. An agent must still inspect the full fresh screen.
"""
import hashlib
import hmac
from io import BytesIO
from PIL import Image
from test_session import TestSession, SessionError
from mumu_bridge import (BridgeError, GREETINGS, ACTION_LIMIT, content_pixel_sha256,
                         input_context_sha256, visual_header_fingerprint, profile_guard)

GRID_BOX = (650,1480,704,1566)
GRID_SHA = 'd3cfcb5a4519052a350bc2776d5faacdd270f6095c2a8562e3051254ae6160c8'
EMPTY_BOX = (250,1238,650,1284)
EMPTY_SHA = '6441e2dacbb6d0f642fdade12cc395f77dd023d8af34a2cfa0c1f11ef58ece2b'
SEND_BOX = (794,1486,850,1544)
SEND_SHA = '1dccd6736f3a0286f5b456950baa78fda5910b08767d8089d55fc794dc95fa01'


def matches(png, box, expected):
    with Image.open(BytesIO(png)) as im:
        if im.size != (900,1600) or im.format != 'PNG':
            raise BridgeError('Нужен PNG 900x1600; действие не начато.')
        return hmac.compare_digest(hashlib.sha256(im.convert('RGB').crop(box).tobytes()).hexdigest(), expected)


def _convert_error(fn):
    def call(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except SessionError as exc:
            raise BridgeError(str(exc)) from None
    return call


class _SessionBudget:
    def __init__(self, ledger):
        self.ledger = ledger
        self.variant = None
    def used(self):
        return self.ledger.used()
    def reserve(self, fingerprint):
        self.ledger.reserve_input(fingerprint, self.variant)
    def finish(self, fingerprint, result):
        self.ledger.finish_input(fingerprint, result)


class SupervisedReader:
    """Production facade. Every exposed mutation is routed through the run journal.

    The underlying v1.3.2 transport retains all Android/pixel/input guards. Its
    generic tap API is not exposed without the phase restrictions below.
    """
    def __init__(self, reader, ledger):
        self.inner, self.ledger = reader, ledger
        self.online_confirmed = False
        self.budget = _SessionBudget(ledger)
        self.inner.greeting_budget = self.budget

    def connect(self):
        return self.inner.connect()
    def install_helper(self, base):
        return self.inner.install_helper(base)
    def screen(self):
        return self.inner.screen()
    def inspect_layout(self):
        return self.inner.inspect_layout()
    def status(self):
        out = self.inner.status()
        out.update(test_session=self.ledger.status(),
                   automatic_send_supported=False,
                   sending_scope='one guarded send per visited profile, followed by explicit visual review')
        return out

    def _fresh(self, expected):
        if not isinstance(expected, str) or len(expected) != 64:
            raise BridgeError('Нужен хеш свежего экрана.')
        png = self.screen()
        if not hmac.compare_digest(content_pixel_sha256(png), expected):
            raise BridgeError('Экран изменился. Сначала прочитайте новый снимок.')
        return png

    def _run_ready(self):
        self.ledger._no_hold()
        self.ledger._active()
        if self.inner.action_attempts >= ACTION_LIMIT:
            raise BridgeError('50 действий подключения использованы. Переподключение продолжит тот же тест, не новый.')
        if self.inner.action_uncertain:
            raise BridgeError('Предыдущее действие не определено. Только чтение; нужен разбор.')

    def _dispatch(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BaseException:
            if self.inner.action_uncertain and self.ledger.status()['state'] == 'active':
                self.ledger.unknown()
            raise

    @_convert_error
    def begin_profile(self, expected_content_sha256, x, y):
        self._run_ready()
        if type(x) is not int or type(y) is not int or not (0 <= x < 900 and 72 <= y < 1268):
            raise BridgeError('Выберите видимую анкету в ленте, не историю/нижнюю панель.')
        if not self.online_confirmed:
            raise BridgeError('Сначала откройте настройки, подтвердите включённый Только онлайн и нажмите галочку.')
        png = self._fresh(expected_content_sha256)
        if not matches(png, GRID_BOX, GRID_SHA):
            raise BridgeError('Выбранная вкладка поиска не подтверждена; анкету не открываю.')
        self.ledger.begin_visit()
        try:
            result = self._dispatch(self.inner.navigate, 'tap', expected_content_sha256, x, y)
        except BridgeError:
            if not self.inner.action_uncertain:
                self.ledger.skip()
            raise
        return dict(result, test_session=self.ledger.status(), visit_counted_before_tap=True)

    @_convert_error
    def open_profile_chat(self, expected_profile_sha256):
        self._run_ready()
        self.ledger._visit(('opening',))
        # Commit next phase before the physical operation. Never blindly retry.
        self.ledger.transition(('opening',), 'chat_opening')
        return self._dispatch(self.inner.open_profile_chat, expected_profile_sha256)

    @_convert_error
    def check_new_chat(self, expected_content_sha256):
        self._run_ready()
        self.ledger._visit(('chat_opening',))
        png = self._fresh(expected_content_sha256)
        nodes = self.inspect_layout()
        if nodes.get('truncated') or nodes.get('content_sha256') != expected_content_sha256:
            raise BridgeError('Дерево и снимок не совпадают или неполны; ввод запрещён.')
        edits = [n for n in nodes['nodes'] if n.get('editable')]
        if (len(edits) != 1 or edits[0].get('text') or not edits[0].get('enabled')
                or edits[0].get('class') != 'android.widget.EditText'):
            self.ledger.skip()
            return {'eligible':False, 'reason':'nonempty_or_unsupported_input', 'test_session':self.ledger.status()}
        if not matches(png, EMPTY_BOX, EMPTY_SHA):
            self.ledger.skip()
            return {'eligible':False, 'reason':'new_chat_invitation_not_matched', 'test_session':self.ledger.status()}
        allowed = self.ledger.bind_empty_chat(visual_header_fingerprint(png))
        return {'eligible':allowed, 'reason':'visual_duplicate' if not allowed else 'new_chat_ui_matched',
                'identity_verified':False, 'full_history_automatically_verified':False,
                'requires_agent_visual_review':True, 'test_session':self.ledger.status()}

    @_convert_error
    def prepare_greeting(self, expected_input_sha256, variant):
        self._run_ready()
        visit = self.ledger._visit(('empty_checked',))
        png = self.screen()
        if (not matches(png, EMPTY_BOX, EMPTY_SHA)
                or visual_header_fingerprint(png) != visit['fingerprint']):
            raise BridgeError('Диалог или приглашение изменились. Ввод не начат.')
        self.budget.variant = variant
        return self._dispatch(self.inner.prepare_greeting, expected_input_sha256, variant)

    @_convert_error
    def finish_greeting_input(self, expected_input_sha256, variant):
        self._run_ready()
        visit = self.ledger._visit(('draft_native',))
        if type(variant) is not int or variant != visit['variant']:
            raise BridgeError('Вариант не совпадает с сохранённой попыткой.')
        png = self.screen()
        if visual_header_fingerprint(png) != visit['fingerprint']:
            raise BridgeError('Шапка диалога изменилась; действие остановлено.')
        self.ledger.transition(('draft_native',), 'finish_reserved')
        try:
            result = self._dispatch(self.inner.finish_greeting_input, expected_input_sha256, variant)
        except BaseException:
            if self.ledger.status()['state'] == 'active':
                self.ledger.unknown()
            raise
        self.ledger.transition(('finish_reserved',), 'draft_finished')
        return result

    @_convert_error
    def send_prepared(self, expected_content_sha256):
        self._run_ready()
        visit = self.ledger._visit(('draft_finished',))
        png = self._fresh(expected_content_sha256)
        if (visual_header_fingerprint(png) != visit['fingerprint']
                or not matches(png, EMPTY_BOX, EMPTY_SHA) or not matches(png, SEND_BOX, SEND_SHA)):
            raise BridgeError('Не подтверждены получатель, новый чат или кнопка отправки.')
        layout = self.inspect_layout()
        edits = [n for n in layout.get('nodes', []) if n.get('editable')]
        if (layout.get('truncated') or layout.get('content_sha256') != expected_content_sha256
                or len(edits) != 1 or edits[0].get('text') != GREETINGS[visit['variant']]
                or edits[0].get('focused') or not edits[0].get('enabled')
                or edits[0].get('class') != 'android.widget.EditText'
                or edits[0].get('bounds') != [152,1488,748,1544]):
            raise BridgeError('Нужен завершённый ввод точного приветствия в проверенном поле.')
        self.ledger.reserve_send()  # Durable BEFORE dispatch; no retry API.
        try:
            result = self.inner.navigate('tap', expected_content_sha256, 825, 1515)
        except BaseException:
            self.ledger.unknown()
            raise
        self.ledger.send_injected()
        return dict(result, message_sent_verified=False,
                    next_step='Read screen. Observe an outgoing bubble with the exact greeting for this recipient, then review_visit(sent_observed). No repeat send.',
                    test_session=self.ledger.status())

    @_convert_error
    def review_visit(self, expected_content_sha256, outcome):
        self._run_ready()
        png = self._fresh(expected_content_sha256)
        if outcome == 'sent_observed':
            visit = self.ledger._visit(('awaiting_send_review',))
            layout = self.inspect_layout()
            edits = [n for n in layout.get('nodes', []) if n.get('editable')]
            if (visual_header_fingerprint(png) != visit['fingerprint']
                    or matches(png, EMPTY_BOX, EMPTY_SHA) or layout.get('truncated')
                    or layout.get('content_sha256') != expected_content_sha256
                    or len(edits) != 1 or edits[0].get('text')):
                raise BridgeError('Результат не подтверждён. Не повторяйте отправку.')
            self.ledger.observe_sent()
        elif outcome == 'skipped':
            self.ledger.skip()
        elif outcome == 'unknown':
            self.ledger.unknown()
        else:
            raise BridgeError('Неизвестный результат проверки.')
        return {'observation_source':'agent_visual_review_not_autonomous_detection', 'test_session':self.ledger.status()}

    @_convert_error
    def return_to_grid(self, expected_content_sha256):
        self._run_ready()
        self.ledger._visit(('sent_observed', 'skip_ready'))
        png = self._fresh(expected_content_sha256)
        # At most two individually guarded Back actions, inspecting between each.
        for _ in range(2):
            if matches(png, GRID_BOX, GRID_SHA):
                break
            pg = profile_guard(png)
            if pg['button_matches']:
                self._dispatch(self.inner.leave_profile, pg['profile_sha256'])
            else:
                self._dispatch(self.inner.navigate, 'back', content_pixel_sha256(png), 0, 0)
            png = self.screen()
            if not matches(png, GRID_BOX, GRID_SHA) and not profile_guard(png)['button_matches']:
                self.ledger.unknown()
                raise BridgeError('После Назад открыт неизвестный экран. Второе нажатие не выполняю; нужен разбор.')
        if not matches(png, GRID_BOX, GRID_SHA):
            self.ledger.unknown()
            raise BridgeError('Возврат в поиск не подтверждён. Тест остановлен.')
        self.ledger.returned()
        return {'search_grid_observed':True, 'test_session':self.ledger.status()}

    @_convert_error
    def navigate(self, action, expected_content_sha256, x=0, y=0):
        self._run_ready()
        visit = self.ledger.current()
        step = visit['state'] if visit else None
        # Only field focus while a checked empty chat is active. No send by tap.
        if step == 'empty_checked':
            if action != 'tap' or type(x) is not int or type(y) is not int or not (200 <= x < 748 and 1488 <= y < 1544):
                raise BridgeError('В этом шаге разрешён только фокус пустого поля.')
            return self._dispatch(self.inner.navigate, action, expected_content_sha256, x, y)
        if visit is not None and step not in ('returned_sent', 'returned_skipped'):
            raise BridgeError('Используйте команды текущего шага; произвольное нажатие/отправка запрещены.')
        png = self._fresh(expected_content_sha256)
        is_grid = matches(png, GRID_BOX, GRID_SHA)
        confirming = False
        if is_grid:
            allowed = action == 'tap' and type(x) is int and type(y) is int and 770 <= x <= 860 and 1472 <= y <= 1535
        else:
            # Fixed filter dialog header, not a profile/chat screen.
            allowed = matches(png, FILTER_BOX, FILTER_SHA) and ((action == 'back' and x == y == 0) or
                (action == 'tap' and type(x) is int and type(y) is int and
                 ((756 <= x <= 858 and 981 <= y <= 1044) or (762 <= x <= 858 and 1468 <= y <= 1535))))
        if not allowed:
            raise BridgeError('Здесь разрешены только настройки онлайн-фильтра; анкеты открываются через begin_profile.')
        if is_grid:
            self.online_confirmed = False
        elif action == 'tap' and y >= 1468:
            if not matches(png, FILTER_ON_BOX, FILTER_ON_SHA):
                raise BridgeError('Только онлайн не подтверждён как включённый. Галочку не нажимаю.')
            confirming = True
        else:
            self.online_confirmed = False
        result = self._dispatch(self.inner.navigate, action, expected_content_sha256, x, y)
        if confirming:
            self.online_confirmed = True
        return result

    def leave_profile(self, expected_profile_sha256):
        raise BridgeError('Для учтённого возврата используйте mumu_return_to_grid после проверки результата/пропуска.')


FILTER_BOX = (360,244,543,289)
FILTER_SHA = '263efd838fe25309f9da855d3c23893e2edb303dfc5ac4322b8d9e2292f44b18'

FILTER_ON_BOX = (756, 981, 858, 1044)
FILTER_ON_SHA = 'f3bddf8b251375a403722b067b2dd00ab6de532212bbae90a8c1adccb0bf1d22'
