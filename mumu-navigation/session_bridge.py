"""Guarded *supervised* five-profile test workflow, not an unattended sender.

UI anchors are exact crops of static controls from the tested 900x1600 layout.
They contain no names/photos. An agent must still inspect the full fresh screen.
"""
import hashlib
import hmac
from io import BytesIO
from PIL import Image
from test_session import TestSession, SessionError
from filter_state import online_filter_state, FILTER_BOX, FILTER_SHA
from city_field import check_city_field, CITY_FOCUS_POINT
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

    def control_inspect(self):
        from universal_control import UniversalControl
        return UniversalControl(self.inner,self.ledger).inspect()

    def control_execute(self,name,args):
        from universal_control import UniversalControl
        return UniversalControl(self.inner,self.ledger).execute(name,args)

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
        session=dict(self.ledger.status())
        strict=getattr(self.inner,'native_only',False) is True
        if strict:session['identity_guard']='not verified in native mode; historical journal retained'
        out.update(test_session=session,
                   automatic_send_supported=False,
                   sending_scope='not exposed in strict native mode' if strict else 'one guarded send per visited profile, followed by explicit visual review')
        return out

    def _fresh(self, expected):
        if not isinstance(expected, str) or len(expected) != 64:
            raise BridgeError('Нужен хеш свежего экрана.')
        png = self.screen()
        if not hmac.compare_digest(content_pixel_sha256(png), expected):
            raise BridgeError('Экран изменился. Сначала прочитайте новый снимок.')
        return png

    def check_city_search(self, expected_content_sha256):
        """Read-only diagnostic. Does not infer row labels or change run state."""
        png = self._fresh(expected_content_sha256)
        layout = self.inspect_layout()
        result = check_city_field(png, layout, expected_content_sha256)
        # Bind observation to the still-current full frame, not just two crops.
        self._fresh(expected_content_sha256)
        return result

    @_convert_error
    def focus_city_search(self, expected_content_sha256):
        """One fixed focus tap; never city text, row selection, close or apply."""
        self._run_ready()
        visit = self.ledger.current()
        if visit is not None and visit['state'] not in ('returned_sent','returned_skipped'):
            raise BridgeError('Во время незавершённой анкеты поиск города недоступен.')
        result = self.check_city_search(expected_content_sha256)
        if not result['city_picker_verified']:
            raise BridgeError('Окно поиска города и нативное поле не подтверждены. Нажатия не было.')
        self.online_confirmed = False
        if result['focused']:
            return {'input_injected':False,'already_focused':True,'text_entered':False,
                    'city_selected':False}
        action=self.ledger.reserve_city_focus(0)
        try:
            result = self._dispatch(self.inner.navigate, 'tap', expected_content_sha256, *CITY_FOCUS_POINT)
        except BaseException:
            self.ledger.finish_city_focus(action,'unknown' if self.inner.action_uncertain else 'refused')
            raise
        self.ledger.finish_city_focus(action,'injected')
        return dict(result, text_entered=False, city_selected=False)

    def autotest_city(self):
        from city_autotest import run_city_diagnostics, save_diagnostic_report
        report=run_city_diagnostics(self.inner)
        report['report_saved']=save_diagnostic_report(report)
        return report

    @_convert_error
    def autofocus_city(self,expected_city_context_sha256):
        from city_autotest import autofocus_city
        return autofocus_city(self.inner,self.ledger,expected_city_context_sha256,self._run_ready,self._dispatch)

    def inspect_city_input(self):
        from city_transport import CityTransport
        return CityTransport(self.inner).inspect()

    @_convert_error
    def input_city(self, expected_city_context_sha256, city_index, previous_index):
        from city_transport import CityTransport
        self._run_ready()
        visit = self.ledger.current()
        if visit is not None and visit['state'] not in ('returned_sent','returned_skipped'):
            raise BridgeError('Ввод города разрешён только между анкетами.')
        transport=CityTransport(self.inner)
        transport.preflight(expected_city_context_sha256,city_index,previous_index)
        action=self.ledger.reserve_city_input(city_index,previous_index)
        self.online_confirmed=False
        try:
            result=transport.input(expected_city_context_sha256,city_index,previous_index)
        except BaseException:
            self.ledger.finish_city_input(action,'unknown' if self.inner.action_uncertain else 'refused')
            raise
        self.ledger.finish_city_input(action,'verified')
        return dict(result,test_session=dict(self.ledger.status()),city_attempt_recorded=True)

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
        return dict(result, test_session=dict(self.ledger.status()), visit_counted_before_tap=True)

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

    def _checked_empty_editor(self, png):
        layout = self.inspect_layout()
        edits = [n for n in layout.get('nodes', []) if n.get('editable')]
        if (layout.get('truncated') or layout.get('content_sha256') != content_pixel_sha256(png)
                or len(edits) != 1 or edits[0].get('text')
                or not edits[0].get('enabled')
                or edits[0].get('class') != 'android.widget.EditText'):
            raise BridgeError('Пустое поле и свежий полный экран не подтверждены. '
                              'Ничего не нажато и не введено; попытка ввода не израсходована.')
        return edits[0]

    @_convert_error
    def prepare_greeting(self, expected_input_sha256, variant):
        self._run_ready()
        visit = self.ledger._visit(('empty_checked',))
        png = self.screen()
        if (not matches(png, EMPTY_BOX, EMPTY_SHA)
                or visual_header_fingerprint(png) != visit['fingerprint']):
            raise BridgeError('Диалог или приглашение изменились. Ввод не начат.')
        # Read-only preflight BEFORE reserving an input attempt. Merely opening
        # a Unity chat does not activate its native message editor.
        if (not isinstance(expected_input_sha256, str) or len(expected_input_sha256) != 64
                or not hmac.compare_digest(input_context_sha256(png), expected_input_sha256)):
            raise BridgeError('Экран изменился. Прочитайте новый снимок после фокуса поля.')
        edit = self._checked_empty_editor(png)
        if not edit.get('focused') or edit.get('bounds') != [152,1488,748,1544]:
            raise BridgeError('Сначала нажмите «Сообщение…» через mumu_navigate(tap, CONTENT_RGB_SHA256, 400,1515), '
                              'затем прочитайте экран и дерево. Нужны фокус и границы [152,1488,748,1544]. '
                              'Попытка ввода не израсходована.')
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
                    test_session=dict(self.ledger.status()))

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
            png = self._fresh(expected_content_sha256)
            if (visual_header_fingerprint(png) != visit['fingerprint']
                    or not matches(png, EMPTY_BOX, EMPTY_SHA)):
                raise BridgeError('Диалог или приглашение изменились. Фокус не начат.')
            edit = self._checked_empty_editor(png)
            bounds = edit.get('bounds')
            if (not isinstance(bounds, list) or len(bounds) != 4
                    or any(type(v) is not int for v in bounds)
                    or not (0 <= bounds[0] < bounds[2] <= 900
                            and 1460 <= bounds[1] < bounds[3] <= 1560
                            and bounds[0] <= x < bounds[2] and bounds[1] <= y < bounds[3])):
                raise BridgeError('Точка не внутри подтверждённого поля «Сообщение…». Фокус не начат.')
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
            if online_filter_state(png) != 'on':
                raise BridgeError('Только онлайн: OFF или неопределённое состояние. Галочку не нажимаю.')
            confirming = True
        else:
            self.online_confirmed = False
            if action == 'tap' and online_filter_state(png) != 'off':
                raise BridgeError('Переключение разрешено только из подтверждённого OFF; ON не выключаю, неясное состояние не трогаю.')
        result = self._dispatch(self.inner.navigate, action, expected_content_sha256, x, y)
        if confirming:
            self.online_confirmed = True
        return result

    def leave_profile(self, expected_profile_sha256):
        raise BridgeError('Для учтённого возврата используйте mumu_return_to_grid после проверки результата/пропуска.')

