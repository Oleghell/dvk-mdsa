"""Developer-only historical UI. NOT the packaged DvkAssistant entry point."""
import json
from pathlib import Path
import queue
import sys
import threading
import time

from assistant_config import ConfigError, load
from assistant_pass import APPROVAL_SECONDS, run, run_automatic
from assistant_chain import run as run_chain, result_text as chain_result_text
import telegram_notify
from assistant_store import StateError, data_directory
from search_catalog import write_report as prepare_search_report
from search_online import run as enable_online
from search_city import run as select_city
from assistant_rotation import run as preview_profiles, status_text as preview_status

# User-confirmed working paths on MuMu #4. Saved local choices take priority.
DEFAULT_ADB = 'C:/Users/XXX/Desktop/platform-tools/adb.exe'
DEFAULT_TEST_APKS = 'C:/Users/XXX/Desktop/spam-dvk-main/test-apks'


def launch(self_check=False):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('ДругВокруг · помощник')
    root.geometry('740x650')
    root.minsize(700, 620)
    pane = ttk.Frame(root, padding=22)
    pane.pack(fill='both', expand=True)
    ttk.Label(pane, text='Помощник · MuMu №4', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
    ttk.Label(pane, text='Одна анкета с подтверждением сообщения или до 5 анкет без чатов и сообщений.',
              wraplength=660).pack(anchor='w', pady=(8, 18))
    adb = tk.StringVar(value=DEFAULT_ADB)
    folder = tk.StringVar(value=DEFAULT_TEST_APKS)
    status = tk.StringVar(value='Готов к работе')
    consent = tk.BooleanVar(value=False)
    auto_allowed = tk.BooleanVar(value=False)
    telegram_enabled = tk.BooleanVar(value=False)
    auto_window = None
    auto_controls = []
    settings_path = None
    if not self_check:
        try:
            settings_path = data_directory() / 'settings.json'
            if settings_path.exists():
                settings = json.loads(settings_path.read_text(encoding='utf-8'))
                if set(settings) == {'adb', 'test_apks'} and all(isinstance(v, str) and v == v.strip() and 1 <= len(v) <= 4096 and not any(ord(c) < 32 for c in v) for v in settings.values()):
                    adb.set(settings['adb'])
                    folder.set(settings['test_apks'])
        except Exception:
            status.set('Не удалось прочитать настройки. Выбери пути заново.')
    controls = []
    for label, variable, picker in (
        ('Путь к ADB', adb, lambda: filedialog.askopenfilename(filetypes=[('ADB', '*.exe')])),
        ('Прежняя папка test-apks', folder, filedialog.askdirectory),
    ):
        ttk.Label(pane, text=label).pack(anchor='w')
        row = ttk.Frame(pane)
        row.pack(fill='x', pady=(4, 12))
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side='left', fill='x', expand=True)
        def choose(var=variable, pick=picker):
            result = pick()
            if result:
                var.set(result)
        button = ttk.Button(row, text='Выбрать', command=choose)
        button.pack(side='right', padx=(8, 0))
        controls.extend((entry, button))
    ttk.Label(pane, text='Перед запуском: открой поиск анкет в №4. Город и «Только онлайн» можно настроить кнопками ниже. '
              'Не переключай экран во время работы. Закрой другие инструменты управления MuMu.',
              wraplength=660).pack(anchor='w', pady=(8, 12))
    check = ttk.Checkbutton(pane, variable=consent, text='Разрешаю работу с поиском, анкетами и состоянием чатов на №4')
    check.pack(anchor='w')
    controls.append(check)
    ttk.Label(pane, textvariable=status, wraplength=660, font=('Segoe UI', 12)).pack(anchor='w', pady=18)
    events = queue.Queue()
    stopped = threading.Event()
    busy = False
    approval = None
    reject_approval = None
    search_report_path = None

    def save_paths():
        if not adb.get() or not folder.get():
            raise ConfigError('Выбери ADB и прежнюю папку test-apks.')
        if settings_path is not None:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            temp = settings_path.with_suffix('.tmp')
            temp.write_text(json.dumps(dict(adb=adb.get(), test_apks=folder.get()), ensure_ascii=False), encoding='utf-8')
            temp.replace(settings_path)

    def worker(executable, directory, greeting, automatic=False):
        def approve(pending, text, cancelled):
            reply = queue.Queue(maxsize=1)
            deadline = time.monotonic() + APPROVAL_SECONDS
            valid = lambda: not cancelled() and time.monotonic() < deadline
            events.put(('approval', (pending, text, reply, valid)))
            while valid():
                try:
                    return reply.get(timeout=.05) is True
                except queue.Empty:
                    pass
            return False
        try:
            if automatic:
                value = run_automatic(executable, directory, greeting, stopped.is_set, enabled=True)
            else:
                value = run(executable, directory, greeting, approve, stopped.is_set)
            events.put(('result', value))
        except Exception as error:
            text = str(error) if isinstance(error, (StateError, ConfigError)) else 'Операция остановлена. Проверь ADB, папку test-apks и экран MuMu №4.'
            events.put(('error', text))

    def refresh():
        for control in controls:
            control.configure(state='disabled' if busy else 'normal')
        start.configure(state='disabled' if busy else 'normal')
        auto_button.configure(state='disabled' if busy else 'normal')
        for control in auto_controls:
            control.configure(state='disabled' if busy else 'normal')
        stop.configure(state='normal' if busy else 'disabled')
        search_button.configure(state='disabled' if busy else 'normal')
        online_button.configure(state='disabled' if busy else 'normal')
        city_button.configure(state='disabled' if busy else 'normal')
        preview_button.configure(state='disabled' if busy else 'normal')
        search_report_button.configure(state='normal' if search_report_path is not None and not busy else 'disabled')

    def begin(automatic=False):
        nonlocal busy
        if busy:
            return
        if not consent.get():
            messagebox.showinfo('Разрешение', 'Подтверди проверку анкет и состояния чатов на №4.')
            return
        if automatic and not auto_allowed.get():
            messagebox.showinfo('Автоматические сообщения', 'Включи явное разрешение в окне автоматического режима.')
            return
        try:
            config = load()
            save_paths()
            greeting = config.greeting()
        except Exception as error:
            status.set(str(error) if isinstance(error, ConfigError) else 'Не удалось сохранить настройки. Запуск отменён.')
            return
        stopped.clear()
        busy = True
        status.set('Одна анкета: приветствие без отдельного подтверждения, только в пустой чат.' if automatic else 'Проверяю анкету и чат. Сообщения без отдельного подтверждения не отправляются.')
        refresh()
        threading.Thread(target=worker, args=(adb.get(), folder.get(), greeting, automatic), daemon=True).start()

    def chain_worker(executable, directory, notify):
        try:
            notifier = None
            if notify:
                token, chat_id = telegram_notify.load()
                notifier = lambda payload: telegram_notify.send_contact(token, chat_id, payload)
            result = run_chain(executable, directory, stopped,
                               lambda text: events.put(('preview-progress', text)), notifier=notifier)
            events.put(('chain-result', result))
        except Exception as error:
            text = str(error) if isinstance(error, (StateError, telegram_notify.TelegramError)) else 'Автоцепочка остановлена. Проверь открытый чат, ADB и подключение №4. Отправка не повторяется.'
            events.put(('error', text))

    def begin_chain():
        nonlocal busy
        if busy:
            return
        if not consent.get() or not auto_allowed.get():
            messagebox.showinfo('Разрешение', 'Включи доступ к №4 и автоматические сообщения. Режим сам отвечает в одном открытом чате.')
            return
        try:
            save_paths()
        except Exception:
            status.set('Не удалось сохранить пути. Автоцепочка не запущена.')
            return
        stopped.clear()
        busy = True
        status.set('Проверяю привязку открытого чата к журналу. Другие чаты не открываю.')
        refresh()
        threading.Thread(target=chain_worker, args=(adb.get(), folder.get(), telegram_enabled.get()), daemon=True).start()

    def automatic_window():
        nonlocal auto_window
        if auto_window is not None:
            auto_window.lift()
            return
        w = tk.Toplevel(root)
        auto_window = w
        w.title('Автоцепочка · один открытый чат')
        box = ttk.Frame(w, padding=18)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text='Без подтверждения каждого сообщения', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        ttk.Label(box, text='Сначала можно отправить одно приветствие из поиска. Затем вручную открой этот диалог в MuMu и запусти автоцепочку. '
                  'Она читает только открытый чат, начатый DvkAssistant. Переключение чатов и общий цикл городов ещё не подключены.', wraplength=590).pack(anchor='w', pady=10)
        allow = ttk.Checkbutton(box, variable=auto_allowed, text='Разрешаю автоматическое приветствие и ответы по цепочке')
        allow.pack(anchor='w')
        notify = ttk.Checkbutton(box, variable=telegram_enabled, text='Telegram: только имя и явно присланный свой контакт')
        notify.pack(anchor='w', pady=6)
        actions = ttk.Frame(box)
        actions.pack(fill='x', pady=10)
        greet = ttk.Button(actions, text='Одно приветствие без подтверждения', command=lambda: begin(True))
        greet.pack(side='left')
        observe = ttk.Button(box, text='Запустить автоцепочку открытого чата', command=begin_chain)
        observe.pack(anchor='w')
        options = ttk.Frame(box)
        options.pack(fill='x', pady=10)
        telegram = ttk.Button(options, text='Настроить Telegram', command=lambda: telegram_notify.settings_window(w))
        telegram.pack(side='left')
        ttk.Button(options, text='Стоп', command=cancel).pack(side='left', padx=10)
        ttk.Label(box, textvariable=status, wraplength=590).pack(anchor='w', pady=8)
        ttk.Label(box, text='Приветствие → ответ → вопрос → ответ → предложение перейти в мессенджер → свой контакт → Telegram. '
                  'Неоднозначность, отказ или ошибка останавливают цепочку. Во время работы не меняй экран. Разрешения не сохраняются.', wraplength=590).pack(anchor='w')
        auto_controls.extend((allow, notify, greet, observe, telegram))
        def close_auto():
            nonlocal auto_window
            if busy:
                cancel()
                return
            auto_controls.clear()
            auto_allowed.set(False)
            telegram_enabled.set(False)
            auto_window = None
            w.destroy()
        w.protocol('WM_DELETE_WINDOW', close_auto)

    def preview_worker(executable, directory):
        try:
            result = preview_profiles(executable, directory, stopped.is_set,
                                      lambda text: events.put(('preview-progress', text)))
            events.put(('preview-result', result))
        except Exception as error:
            text = str(error) if isinstance(error, StateError) else 'Просмотр остановлен. Проверь экран MuMu №4 и подключение. Чаты и отправка этим режимом не запускаются.'
            events.put(('error', text))

    def begin_preview():
        nonlocal busy
        if busy:
            return
        if not consent.get():
            messagebox.showinfo('Разрешение', 'Подтверди просмотр анкет на №4. Этот режим не открывает чаты и не отправляет сообщения.')
            return
        try:
            save_paths()
        except Exception:
            status.set('Не удалось сохранить пути. Просмотр не запущен.')
            return
        stopped.clear()
        busy = True
        status.set('Просматриваю до 5 новых видимых анкет. Если новых нет — выберу другой город. Без чатов и сообщений.')
        refresh()
        threading.Thread(target=preview_worker, args=(adb.get(), folder.get()), daemon=True).start()

    def city_worker(executable, directory, city):
        try:
            result = select_city(executable, directory, city, stopped.is_set)
            events.put(('city-result', (city, result)))
        except Exception as error:
            note = ' [' + type(error).__name__ + (': ' + str(error)[:120].replace(chr(10), ' ') if type(error) is ValueError else '') + ']'
            events.put(('error', 'Выбор города не подтверждён' + note + '. Проверь текущий экран и настройки вручную: часть изменений могла выполниться. Анкеты и сообщения не запускались.'))

    def begin_city():
        nonlocal busy
        if busy:
            return
        if not consent.get():
            messagebox.showinfo('Разрешение', 'Подтверди доступ к MuMu №4. Эта кнопка выберет город из списка и включит онлайн-фильтр.')
            return
        try:
            city = load().city()
            save_paths()
        except Exception as error:
            status.set(str(error) if isinstance(error, ConfigError) else 'Не удалось сохранить пути. Выбор города не запущен.')
            return
        stopped.clear()
        busy = True
        status.set('Выбираю город: ' + city + '. Затем включу «Только онлайн». Сообщения не отправляются.')
        refresh()
        threading.Thread(target=city_worker, args=(adb.get(), folder.get(), city), daemon=True).start()

    def online_worker(executable, directory):
        try:
            result = enable_online(executable, directory, stopped.is_set)
            events.put(('online-result', result))
        except Exception:
            events.put(('error', 'Онлайн-фильтр не подтверждён. Проверь экран и настройки вручную: изменения могли успеть примениться. Анкеты и сообщения не запускались.'))

    def begin_online():
        nonlocal busy
        if busy:
            return
        if not consent.get():
            messagebox.showinfo('Разрешение', 'Подтверди доступ к MuMu №4. Эта кнопка изменит только онлайн-фильтр поиска.')
            return
        try:
            save_paths()
        except Exception:
            status.set('Не удалось сохранить пути. Онлайн-фильтр не запущен.')
            return
        stopped.clear()
        busy = True
        status.set('Включаю «Только онлайн» в №4. Проверяю результат и сохранение прежнего города. Сообщения не отправляются.')
        refresh()
        threading.Thread(target=online_worker, args=(adb.get(), folder.get()), daemon=True).start()

    def search_worker(directory):
        try:
            result, path = prepare_search_report(directory, stopped.is_set)
            events.put(('search-ready', (result, path)))
        except Exception:
            events.put(('error', 'Не удалось подготовить сведения о поиске. Проверь папку test-apks и право записи отчёта.'))

    def begin_search():
        nonlocal busy, search_report_path
        if busy:
            return
        try:
            # This action needs the existing local APKs, not a device, account
            # or consent to read a chat. It never calls the native run path.
            save_paths()
        except Exception:
            status.set('Не удалось сохранить пути. Подготовка поиска не запущена.')
            return
        search_report_path = None
        stopped.clear()
        busy = True
        status.set('Читаю технические определения поиска из прежних APK. MuMu и переписку не трогаю.')
        refresh()
        threading.Thread(target=search_worker, args=(folder.get(),), daemon=True).start()

    def open_search_report():
        if search_report_path is None or busy:
            return
        import os
        try:
            os.startfile(str(search_report_path))
        except (AttributeError, OSError):
            messagebox.showinfo('Сведения о поиске', str(search_report_path))

    def cancel():
        stopped.set()
        status.set('Останавливаю. Выполненные действия не откатываются. Новых действий не начинаю.')

    row = ttk.Frame(pane)
    row.pack(fill='x', pady=10)
    start = ttk.Button(row, text='Проверить одну анкету', command=begin)
    start.pack(side='left')
    stop = ttk.Button(row, text='Стоп', command=cancel, state='disabled')
    stop.pack(side='left', padx=10)
    auto_button = ttk.Button(row, text='Автоцепочка и Telegram', command=automatic_window)
    auto_button.pack(side='left')
    preview_row = ttk.Frame(pane)
    preview_row.pack(fill='x', pady=(4, 4))
    preview_button = ttk.Button(preview_row, text='Просмотреть до 5 анкет без сообщений', command=begin_preview)
    preview_button.pack(side='left')
    ttk.Label(pane, text='Просмотренные анкеты запоминаются. Если новых видимых нет — одна смена города и онлайн. Визит может быть виден владельцу анкеты.',
              wraplength=660).pack(anchor='w')
    settings_row = ttk.Frame(pane)
    settings_row.pack(fill='x', pady=(4, 6))
    city_button = ttk.Button(settings_row, text='Выбрать город и онлайн', command=begin_city)
    city_button.pack(side='left')
    online_button = ttk.Button(settings_row, text='Включить только онлайн', command=begin_online)
    online_button.pack(side='left', padx=10)
    search_row = ttk.Frame(pane)
    search_row.pack(fill='x', pady=(6, 4))
    search_button = ttk.Button(search_row, text='Подготовить настройки поиска', command=begin_search)
    search_button.pack(side='left')
    search_report_button = ttk.Button(search_row, text='Открыть сведения', command=open_search_report, state='disabled')
    search_report_button.pack(side='left', padx=10)
    ttk.Label(pane, text='Журнал попыток сохраняется между запусками. Не удаляй старые базы и lock-файлы. '
              'Просмотр работает без прокрутки. Если новых видимых анкет нет — выбирается другой город из списка. Автоответы для одного открытого чата — в «Автоцепочка и Telegram».',
              wraplength=660).pack(anchor='w', pady=(12, 0))

    def ask(data):
        nonlocal approval, reject_approval
        pending, text, reply, valid = data
        if not valid():
            return
        top = tk.Toplevel(root)
        approval = top
        top.title('Подтверди сообщение')
        box = ttk.Frame(top, padding=22)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text='У анкеты меньше 50 друзей. Чат проверен как пустой.', wraplength=500).pack(anchor='w')
        ttk.Label(box, text='Собеседник: ' + pending['peer'] + '\nАккаунт: ' + pending['account'], wraplength=500).pack(anchor='w', pady=10)
        ttk.Label(box, text='Отправить это приветствие?\n\n' + text, wraplength=500,
                  font=('Segoe UI', 12)).pack(anchor='w', pady=12)
        ttk.Label(box, text='Это реальная отправка. Программа заново проверит тот же чат. '
                  'Разрешение действует не больше 60 секунд.', wraplength=500).pack(anchor='w')
        answered = False
        def answer(yes):
            nonlocal answered, approval, reject_approval
            if answered:
                return
            answered = True
            reply.put_nowait(yes is True and valid())
            top.destroy()
            approval = None
            reject_approval = None
        reject_approval = lambda: answer(False)
        buttons = ttk.Frame(box)
        buttons.pack(fill='x', pady=(18, 0))
        ttk.Button(buttons, text='Отправить один раз', command=lambda: answer(True)).pack(side='left')
        ttk.Button(buttons, text='Не отправлять', command=lambda: answer(False)).pack(side='left', padx=10)
        top.protocol('WM_DELETE_WINDOW', lambda: answer(False))
        def expire():
            if answered:
                return
            if not valid():
                answer(False)
            else:
                root.after(100, expire)
        root.after(100, expire)

    def poll():
        nonlocal busy, search_report_path
        while not events.empty():
            kind, value = events.get_nowait()
            if kind == 'approval':
                ask(value)
                continue
            if kind == 'preview-progress':
                if not stopped.is_set():
                    status.set(value)
                continue
            busy = False
            if reject_approval is not None:
                reject_approval()
            if kind == 'error':
                status.set(value)
            elif kind == 'chain-result':
                status.set(chain_result_text(value))
                try:
                    path = data_directory() / 'last-chain.json'
                    temp = path.with_suffix('.tmp')
                    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
                    temp.replace(path)
                except Exception:
                    status.set(chain_result_text(value) + ' Итоговый отчёт не записан; журнал не удаляй.')
            elif kind == 'preview-result':
                status.set(preview_status(value))
                try:
                    path = data_directory() / 'last-preview.json'
                    temp = path.with_suffix('.tmp')
                    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
                    temp.replace(path)
                except Exception:
                    status.set(preview_status(value) + ' Итоговый отчёт не записан; журнал просмотров не удаляй.')
            elif kind == 'search-ready':
                result, search_report_path = value
                if result['status'] == 'catalog-ready':
                    status.set('Сведения о поиске сохранены. Пришли search-settings-definitions.json через «Открыть сведения». Эта подготовка не изменяет город и фильтры.')
                else:
                    status.set('Подготовка поиска остановлена: ' + result['reason'] + '. Подробности — в «Открыть сведения».')
            elif kind == 'city-result':
                city, result = value
                n = result['navigation']
                if n['stage'] == 'navigation-ready' and n['city_verified'] and n['online_verified']:
                    status.set('Город выбран и проверен: ' + n['city_selected_name'] + '. «Только онлайн» включён. Можно проверить одну анкету.')
                else:
                    reasons = {'city-ambiguous': 'Найдено несколько городов с одинаковым названием',
                               'city-results-incomplete': 'Не удалось проверить полный список городов',
                               'city-query-changed': 'Текст поиска города изменился',
                               'city-not-found': 'Город с точным названием не найден',
                               'frame-limit': 'Город не найден или поиск не завершился вовремя'}
                    reason = reasons.get(n['error'], 'Остановлено: ' + (n['error'] if n['error'] != 'none' else n['stage']))
                    if n['stage'] == 'not-attempted' and n['error'] == 'none':
                        reason = 'Эта версия приложения не поддерживается для выбора города (шаг проверки: ' + n['city_prepare'] + '). Ничего не выбиралось'
                    rd = n.get('readiness') or {}
                    detail = ('фаза=' + str(n['phase']) + '; этап=' + str(n['city_checkpoint']) + '; проверка=' + str(n['readiness_check']) +
                              '; путь=' + '>'.join(str(x) for x in n['controller_path']) + '; верх=' + str(n['root_top_kind']) +
                              '; последний=' + str(n['last_presented_kind']) + '; вид=' + ','.join(k + ':' + str(rd.get(k)) for k in
                              ('has_view', 'is_presented', 'hidden', 'interactive', 'attached_to_main_window')) +
                              '; проверка-объекта=' + str(n['city_identity']) + '; выбрано=' + str(n['city_matches']) + '/' + str(n['city_visible_rows']) + '/' + str(n['city_total_rows']) + '; кадров=' + str(n['frames']))
                    status.set(reason + '. Проверь текущий экран и настройки вручную. Анкеты и сообщения не запускались. [' + detail + ']')
                try:
                    keys = ('stage', 'phase', 'error', 'city_checkpoint', 'city_open_attempted', 'city_open_completed',
                            'city_query_attempted', 'city_query_completed', 'city_result_verified', 'city_select_attempted',
                            'city_select_completed', 'city_form_verified', 'city_verified', 'city_scan_samples',
                            'city_visible_rows', 'city_total_rows', 'city_matches', 'city_selected_name', 'city_prepare', 'city_identity', 'readiness_check', 'readiness',
                            'controller_path', 'root_top_kind', 'last_presented_kind', 'frames', 'managed_calls', 'online_verified',
                            'apply_attempted', 'apply_completed', 'return_verified')
                    report = {k: n[k] for k in keys}
                    report.update(device='MuMu #4', requested_city=city, chat_content_read=False, messages_sent=0)
                    path = data_directory() / 'last-city-settings.json'
                    temp = path.with_suffix('.tmp')
                    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                    temp.replace(path)
                except Exception:
                    status.set('Операция с городом завершилась, но отчёт не сохранён. Проверь настройки вручную.')
            elif kind == 'online-result':
                n = value['navigation']
                if n['online_verified'] and n['location_preserved'] and n['stage'] == 'navigation-ready':
                    status.set('«Только онлайн» включён и проверен в модели поиска. Прежний город не изменён. Можно проверить одну анкету.')
                else:
                    status.set('Онлайн-фильтр не подтверждён: ' + n['error'] + '. Проверь настройки вручную: часть изменений могла выполниться. Анкеты и сообщения не запускались.')
                try:
                    report = {k: n[k] for k in ('stage', 'phase', 'error', 'settings_checkpoint', 'online_before',
                              'online_set_attempted', 'online_set_completed', 'form_refreshed', 'apply_attempted',
                              'apply_completed', 'return_verified', 'online_verified', 'location_preserved')}
                    report.update(device='MuMu #4', city_selected=False, chat_content_read=False, messages_sent=0)
                    path = data_directory() / 'last-search-settings.json'
                    temp = path.with_suffix('.tmp')
                    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                    temp.replace(path)
                except Exception:
                    status.set('Операция с фильтром завершилась, но отчёт не сохранён. Проверь настройки в MuMu вручную.')
            else:
                n = value['navigation']
                if n['send_handler_returned']:
                    status.set('Команда отправки выполнена. Доставку проверь в приложении. Повтор для этого собеседника заблокирован.' + (' Возврат в поиск не подтверждён — проверь экран.' if not n['return_verified'] else ''))
                elif value['declined']:
                    status.set('Отправка отменена или подтверждение не получено вовремя. Проверь экран перед следующим запуском.')
                elif n['stage'] != 'navigation-ready':
                    status.set('Остановлено: ' + n['error'] + '. Проверь экран MuMu перед продолжением.')
                elif not n['friends_eligible']:
                    status.set('Анкета пропущена: друзей ' + str(n['friends_count']) + '. Возврат к поиску выполнен.')
                else:
                    status.set('В чате уже есть переписка. Приветствие не отправлено. Возврат к поиску выполнен.')
                try:
                    report = {k: n[k] for k in ('stage', 'phase', 'error', 'friends_status', 'friends_count',
                              'history_status', 'send_attempted', 'send_handler_returned', 'return_verified')}
                    report.update(device='MuMu #4', delivery_confirmed=False, text_exported=False, identities_exported=False)
                    path = data_directory() / 'last-operation.json'
                    temp = path.with_suffix('.tmp')
                    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                    temp.replace(path)
                except Exception:
                    status.set('Проход завершён, но отчёт не записан. Проверь чат вручную; не удаляй журнал.')
            refresh()
        root.after(100, poll)

    def close():
        if busy:
            cancel()
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    def fit_window():
        root.update_idletasks()
        width = max(740, pane.winfo_reqwidth())
        height = max(650, pane.winfo_reqheight())
        root.geometry(f'{width}x{height}')
        root.minsize(width, height)
    root.after_idle(fit_window)
    if self_check:
        fit_window()
        root.update()
        assert root.winfo_viewable() and start.winfo_viewable() and search_button.winfo_viewable() and online_button.winfo_viewable() and city_button.winfo_viewable() and preview_button.winfo_viewable()
        assert not busy and not consent.get() and not auto_allowed.get() and not telegram_enabled.get() and not stopped.is_set()
        assert str(stop.cget('state')) == 'disabled'
        assert auto_button.winfo_viewable()
        automatic_window()
        root.update()
        assert auto_window.winfo_viewable() and len(auto_controls) == 5
        assert all(control.winfo_viewable() for control in auto_controls)
        assert events.empty()
        assert load().greetings
        root.destroy()
        return
    root.after(100, poll)
    root.mainloop()


if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['--self-check']):
        raise SystemExit(2)
    launch(self_check=sys.argv[1:] == ['--self-check'])
