"""DvkAssistant window: Start / Replies / Stop / Settings.

No startup actions. Explicit Start authorizes this run; Stop revokes it.
"""
import os
# Scope is selected before importing the engine. Workers use a separate process.
os.environ['DVK_MORELOGIN'] = '1'
os.environ.pop('DVK_MORELOGIN_PHONE_ID',None)
import sys
if __name__ == '__main__' and sys.argv[1:] == ['--cloud-worker']:
    from morelogin_worker import main
    raise SystemExit(main())
import queue
import sys
import threading

from assistant_authorization import RunAuthorization
from assistant_store import StateError, data_directory
from assistant_settings import Settings, load, save
from assistant_monitor import run as monitor, summary as monitor_summary
import telegram_notify
import groq_reply
import assistant_ai
from morelogin_version import VERSION
from morelogin_diagnostics import describe, save_failure, completion_text


def launch(self_check=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk()
    root.title('DvkAssistant ' + VERSION + ' · MoreLogin Cloud Phone')
    root.geometry('920x740')
    root.minsize(820, 650)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='ДругВокруг · MoreLogin', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
    status = tk.StringVar(value='Готово • версия ' + VERSION)
    try:
        settings = Settings() if self_check else load()
    except StateError as error:
        settings = Settings()
        status.set(str(error))
    ttk.Label(frame, textvariable=status, wraplength=520).pack(anchor='w', pady=(18, 12))
    ttk.Label(frame, text='Старт: анкеты + ответы. Только ответы: без поиска анкет.\nВыбранный ИИ получает контекст чата; Telegram — контакты и коды ошибок.', wraplength=640).pack(anchor='w')
    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=(18, 0))
    events = queue.Queue()
    stopped = threading.Event()
    busy = False
    dialog = None
    first_profiles_run = True
    from morelogin_common import (root_directory, atomic_json, ids_from_text,
                                  CloudError, fingerprint)
    import json
    pins = {}
    saved_ids = []
    if not self_check:
        try:
            path = root_directory()/'phones.json'
            if path.exists():
                if path.stat().st_size > 65536: raise ValueError()
                value = json.loads(path.read_text(encoding='utf-8'))
                saved_ids = ids_from_text('\n'.join(value['ids']))
                pins = {x:fingerprint(v) for x,v in value['pins'].items() if x in saved_ids}
        except Exception:
            status.set('Проверь список ID и SSH-ключи; автоматически они не восстанавливаются.')
    cloud_box = ttk.LabelFrame(frame, text='Cloud Phone ID — новый список, по одному на строку', padding=8)
    cloud_box.pack(fill='both', expand=True, pady=8)
    id_text = tk.Text(cloud_box, height=5, width=30)
    id_text.pack(side='left', fill='y')
    id_text.insert('1.0', '\n'.join(saved_ids))
    phone_status = ttk.Treeview(cloud_box, columns=('id','state'), show='headings', height=7)
    phone_status.heading('id', text='Cloud Phone ID')
    phone_status.heading('state', text='Состояние')
    phone_status.column('id', width=155, stretch=False)
    phone_status.column('state', width=460)
    phone_status.pack(side='left', fill='both', expand=True, padx=8)
    ttk.Label(frame, text='Одна общая SQLite-база. Все ID запускаются параллельно; состояние чатов изолировано.\nСначала сохрани APP ID / Secret Key в настройках, затем проверь SSH-подключения.\nНужна совместимая тестовая копия приложения с Gadget; обычный APK не подключается автоматически.', wraplength=850).pack(anchor='w')

    def save_ids(values):
        atomic_json(root_directory()/'phones.json', {'ids':values, 'pins':{x:pins[x] for x in values if x in pins}})

    def set_phone(cloud_id, text):
        if phone_status.exists(cloud_id):
            phone_status.item(cloud_id, values=(cloud_id,text))
        else:
            phone_status.insert('', 'end', iid=cloud_id, values=(cloud_id,text))

    def api_entries(values):
        from morelogin_credentials import load as credentials
        from morelogin_client import Client
        app_id, key = credentials()
        return Client(app_id,key).query(values)

    def check_connections():
        nonlocal busy
        if busy: return
        try:
            values = ids_from_text(id_text.get('1.0','end'))
            save_ids(values)
        except Exception:
            status.set('Укажи от 1 до 200 разных числовых Cloud Phone ID.')
            return
        for cloud_id in values:
            set_phone(cloud_id, 'Проверяю подключение')
        stopped.clear()
        busy=True
        refresh()
        status.set('Проверяю Open API и SSH-ключи. Пароли SSH на этом этапе не передаются.')
        def check():
            failed = False
            try:
                from morelogin_client import plan
                from morelogin_ssh import probe
                from concurrent.futures import ThreadPoolExecutor, as_completed
                entries=api_entries(values)
                def check_one(cloud_id):
                    if stopped.is_set(): return
                    try:
                        ssh=plan(entries.get(cloud_id), cloud_id)
                        observed=probe(ssh)
                        events.put(('host-key', (cloud_id,ssh.host,ssh.ssh_port,observed)))
                    except Exception as error:
                        save_failure([cloud_id], error)
                        events.put(('phone', (cloud_id, 'error', str(error) if isinstance(error,CloudError) else 'ssh-unavailable')))
                        return False
                    return True
                with ThreadPoolExecutor(max_workers=8) as pool:
                    failed = not all(list(pool.map(check_one,values)))
            except Exception as error:
                failed = True
                save_failure(values, error)
                for cloud_id in values:
                    events.put(('phone', (cloud_id, 'error', describe(error))))
                events.put(('error', describe(error)))
            finally:
                events.put(('check-done',failed))
        threading.Thread(target=check,daemon=True).start()

    def refresh():
        start.configure(state='disabled' if busy else 'normal')
        options.configure(state='disabled' if busy else 'normal')
        replies.configure(state='disabled' if busy else 'normal')
        stop.configure(state='normal' if busy else 'disabled')
        check_button.configure(state='disabled' if busy else 'normal')
        id_text.configure(state='disabled' if busy else 'normal')

    def cancel():
        stopped.set()
        status.set('Останавливаю. Выполненные действия не откатываются.')

    def worker(current, mode, fresh):
        try:
            from morelogin_supervisor import run as cloud_run
            values=fresh
            entries=api_entries(values)
            # Initialize global WAL schema once before concurrent process startup.
            from morelogin_store import SharedStore
            SharedStore(cloud_id=values[0])
            cloud_run(current,values,dict(pins),entries,mode,stopped,
                      lambda cloud_id,kind,text:events.put(('phone',(cloud_id,kind,text))))
            events.put(('cloud-done',None))
        except Exception as error:
            save_failure(values, error)
            for cloud_id in values:
                events.put(('phone', (cloud_id, 'error', describe(error))))
            events.put(('error', 'Запуск MoreLogin: ' + describe(error)))

    def begin(mode='full'):
        nonlocal busy, first_profiles_run
        if busy:
            return
        try:
            settings.check()
            values=ids_from_text(id_text.get('1.0','end'))
            save_ids(values)
            save(settings)
        except Exception as error:
            status.set(str(error) if isinstance(error, StateError) else 'Не удалось сохранить настройки. Запуск отменён.')
            return
        # The Start button itself authorizes this run. No redundant modal.
        fresh = values
        for cloud_id in values: set_phone(cloud_id,'Ожидание подключения')
        if mode == 'full':
            first_profiles_run = False
        stopped.clear()
        busy = True
        refresh()
        status.set('Запускаю Cloud Phone параллельно. Ошибка одного не останавливает остальные.')
        threading.Thread(target=worker, args=(settings, mode, fresh), daemon=True).start()

    def configure():
        nonlocal dialog
        if dialog is not None:
            dialog.lift()
            return
        w = tk.Toplevel(root)
        dialog = w
        w.title('Настройки')
        container = ttk.Frame(w, padding=12)
        container.pack(fill='both', expand=True)
        tabs = ttk.Notebook(container)
        tabs.pack(fill='both', expand=True)
        box, ai_box, tg_box, api_box = (ttk.Frame(tabs, padding=12) for _ in range(4))
        for tab, title in ((box, 'Поиск и ответы'), (ai_box, 'ИИ / ключи'), (tg_box, 'Telegram'), (api_box, 'MoreLogin API')):
            tabs.add(tab, text=title)
        api_id=tk.StringVar()
        api_key=tk.StringVar()
        ttk.Label(api_box, text='Open API: https://api.morelogin.com — не Local API.\nКлючи сохраняются только через Windows DPAPI. Пароли и команды SSH не попадают в отчёты.',wraplength=500).pack(anchor='w',pady=8)
        for label,var in (('APP ID',api_id),('Secret Key',api_key)):
            ttk.Label(api_box,text=label).pack(anchor='w')
            ttk.Entry(api_box,textvariable=var,show='*' if label=='Secret Key' else '',width=58).pack(fill='x',pady=5)
        def save_api():
            try:
                from morelogin_credentials import save as save_credentials
                save_credentials(api_id.get().strip(),api_key.get().strip())
                api_key.set('')
                note.set('MoreLogin API сохранён через DPAPI. Теперь проверь подключения в главном окне.')
            except Exception:
                note.set('Не удалось сохранить MoreLogin API. Проверь данные и доступность Windows DPAPI.')
        ttk.Button(api_box,text='Сохранить MoreLogin API',command=save_api).pack(anchor='w',pady=8)
        api_note=tk.StringVar(value='Проверка ниже использует уже сохранённые ключи. Новые значения сначала сохрани.')
        api_events=queue.Queue()
        def check_saved_api():
            api_check.configure(state='disabled')
            api_note.set('Проверяю сохранённые ключи без запуска телефонов…')
            def execute():
                try:
                    from morelogin_auth_check import check_saved
                    api_events.put(check_saved())
                except Exception:
                    api_events.put('Не удалось выполнить проверку ключей. Секреты в отчёт не записаны.')
            def collect():
                if not w.winfo_exists(): return
                try:
                    text=api_events.get_nowait()
                except queue.Empty:
                    w.after(100,collect)
                    return
                api_note.set(text)
                api_check.configure(state='normal')
            threading.Thread(target=execute,daemon=True).start()
            w.after(100,collect)
        api_check=ttk.Button(api_box,text='Проверить сохранённые ключи',command=check_saved_api)
        api_check.pack(anchor='w',pady=5)
        ttk.Label(api_box,textvariable=api_note,wraplength=580).pack(anchor='w',pady=5)
        adb = tk.StringVar(value=settings.adb)
        folder = tk.StringVar(value=settings.folder)
        limit = tk.StringVar(value=str(settings.profile_limit))
        interval = tk.StringVar(value=str(settings.reply_interval))
        profile_interval = tk.StringVar(value=str(settings.profile_interval))
        enabled = tk.BooleanVar(value=settings.contacts_enabled)
        errors_enabled = tk.BooleanVar(value=settings.errors_enabled)
        ai_enabled = tk.BooleanVar(value=settings.groq_enabled)
        ai_provider = tk.StringVar(value=settings.ai_provider)
        ai_model = tk.StringVar(value=settings.ai_model)
        models = {'groq': settings.groq_model, 'openrouter': settings.openrouter_model}
        selected_provider = [settings.ai_provider]
        ai_key = tk.StringVar(value='')
        token = tk.StringVar(value='')
        recipient = tk.StringVar(value='')
        note = tk.StringVar(value='Токен не попадает в исходники и отчёты. Пустой токен сохраняет прежние настройки бота.')
        # Do not decrypt credentials in the packaged self-check.
        if not self_check:
            try:
                _, chat = telegram_notify.load()
                recipient.set(chat)
            except telegram_notify.TelegramError:
                pass
        for label, var, picker in (('ADB', adb, lambda: filedialog.askopenfilename(filetypes=[('ADB', '*.exe')])),
                                   ('Папка test-apks', folder, filedialog.askdirectory)):
            ttk.Label(box, text=label).pack(anchor='w')
            row = ttk.Frame(box)
            row.pack(fill='x', pady=(3, 10))
            ttk.Entry(row, textvariable=var, width=58).pack(side='left', fill='x', expand=True)
            def choose(v=var, pick=picker):
                value = pick()
                if value:
                    v.set(value)
            ttk.Button(row, text='Выбрать', command=choose).pack(side='right', padx=(8, 0))
        ttk.Label(box, text='Подходящих анкет за одну порцию (1–20)').pack(anchor='w')
        ttk.Entry(box, textvariable=limit, width=8).pack(anchor='w', pady=(3, 10))
        ttk.Label(box, text='Проверка диалогов (5–3600 секунд)').pack(anchor='w')
        ttk.Entry(box, textvariable=interval, width=8).pack(anchor='w', pady=(3, 10))
        ttk.Label(box, text='Отдых в личке перед новой порцией (30–86400 секунд)').pack(anchor='w')
        ttk.Entry(box, textvariable=profile_interval, width=8).pack(anchor='w', pady=(3, 10))
        ttk.Label(box, text='Во время отдыха проверяю входящие и отвечаю. Отправка с задержкой 35 слов/мин.\nСтарт разрешает автоматические сообщения; не переключай выбранные Cloud Phone во время работы.', wraplength=500).pack(anchor='w', pady=8)
        ttk.Checkbutton(ai_box, variable=ai_enabled, text='ИИ: короткие ответы по структуре цепочки').pack(anchor='w', pady=6)
        ttk.Label(ai_box, text='Весь проверенный снимок чата (до 19 сообщений, суммарно 16 384 символа) и правила передаются выбранному сервису (для OpenRouter — также провайдеру модели). ID/имя профиля не передаются; контакты маскируются.', wraplength=500).pack(anchor='w')
        ttk.Label(ai_box, text='Сервис ИИ').pack(anchor='w', pady=(8, 0))
        provider_box=ttk.Combobox(ai_box, textvariable=ai_provider, values=tuple(assistant_ai.LABELS), state='readonly')
        provider_box.pack(fill='x')
        ttk.Label(ai_box, text='Модель (OpenRouter — только :free, без платной замены)').pack(anchor='w', pady=(8, 0))
        model_box=ttk.Combobox(ai_box, textvariable=ai_model, values=assistant_ai.PRESETS[settings.ai_provider], width=55)
        model_box.pack(fill='x')
        ttk.Label(ai_box, text='API-ключ выбранного сервиса — пустое поле сохраняет прежний').pack(anchor='w', pady=(8, 0))
        ttk.Entry(ai_box, textvariable=ai_key, show='*', width=58).pack(fill='x', pady=(3, 6))
        def switch_provider(event=None):
            current=ai_provider.get()
            if current not in assistant_ai.LABELS:
                return
            models[selected_provider[0]]=ai_model.get().strip()
            selected_provider[0]=current
            ai_model.set(models[current])
            model_box.configure(values=assistant_ai.PRESETS[current])
            ai_key.set('')  # Never carry one service's key into another service.
            note.set('Сервис изменён. Введи его ключ или оставь поле пустым для сохранённого. Несохранённое поле ключа очищено.')
        provider_box.bind('<<ComboboxSelected>>', switch_provider)
        ttk.Label(ai_box, text='Ключи сервисов хранятся отдельно через Windows DPAPI. OpenRouter: только бесплатные модели, политика провайдера data_collection=deny; доступность и лимиты не гарантируются.', wraplength=500).pack(anchor='w', pady=6)
        def save_ai_key():
            try:
                adapter=assistant_ai.module(ai_provider.get())
                if ai_key.get().strip():
                    adapter.save_key(ai_key.get())
                    ai_key.set('')
                else:
                    assistant_ai.check_saved_keys(ai_provider.get())
                note.set('Ключ ИИ сохранён/доступен. Выбор сервиса и модели сохрани общей кнопкой «Сохранить».')
            except groq_reply.GroqError as error:
                note.set(assistant_ai.explain(str(error)))
            except Exception:
                note.set('Не удалось сохранить ключ ИИ. Нужна защита Windows DPAPI; открытый текст не записывается.')
        ttk.Button(ai_box, text='Сохранить ключ ИИ', command=save_ai_key).pack(anchor='w', pady=4)
        ttk.Label(ai_box, text='Несколько ключей: заполни config/ai-keys.txt по образцу ai-keys.example.txt. Используются только ключи выбранного сервиса; при сбое — следующий. Файл содержит секреты: никому не отправляй.', wraplength=500).pack(anchor='w', pady=4)
        ttk.Checkbutton(tg_box, variable=errors_enabled, text='Telegram: причины остановок, ошибок и выхода без ответа').pack(anchor='w', pady=8)
        ttk.Checkbutton(tg_box, variable=enabled, text='Telegram: уведомлять, когда человек сам прислал контакт').pack(anchor='w', pady=8)
        for label, var, mask in (('Токен бота', token, '*'), ('Chat ID получателя', recipient, '')):
            ttk.Label(tg_box, text=label).pack(anchor='w')
            ttk.Entry(tg_box, textvariable=var, show=mask, width=58).pack(fill='x', pady=(3, 8))
        def store():
            nonlocal settings
            try:
                provider=ai_provider.get()
                models[provider]=ai_model.get().strip()
                current = Settings(adb.get(), folder.get(), enabled.get(), int(interval.get()),
                                   int(limit.get()), ai_enabled.get(), models['groq'], errors_enabled.get(),
                                   provider, models['openrouter'], int(profile_interval.get())).check()
                adapter=assistant_ai.module(provider)
                if ai_key.get().strip():
                    adapter.save_key(ai_key.get())
                elif current.groq_enabled:
                    assistant_ai.check_saved_keys(ai_provider.get())
                if token.get().strip():
                    telegram_notify.save(token.get(), recipient.get())
                elif current.contacts_enabled or current.errors_enabled:
                    _, previous = telegram_notify.load()
                    if recipient.get().strip() != previous:
                        raise StateError('Для смены получателя укажи токен бота заново.')
                save(current)
                settings = current
                token.set('')
                ai_key.set('')
                note.set('Сохранено. Проверок и тестовых отправок не выполнялось.')
            except Exception as error:
                note.set(str(error) if isinstance(error, (StateError, telegram_notify.TelegramError, groq_reply.GroqError)) else 'Не удалось сохранить настройки. Проверь поля.')
        def test_telegram():
            try:
                saved_token, saved_chat = telegram_notify.load()
                ok = telegram_notify.send(saved_token, saved_chat,
                                          '✅ DvkAssistant: тестовое уведомление. Бот настроен.')
                note.set('Telegram принял тестовое сообщение.' if ok else
                         'Telegram не подтвердил отправку. Проверь токен и Chat ID.')
            except telegram_notify.TelegramError as error:
                note.set(str(error))
            except Exception:
                note.set('Тест не выполнен. Сначала сохрани токен и Chat ID.')
        def clear():
            if not messagebox.askyesno('Очистить историю анкет',
                    'Забыть просмотренные анкеты и использованные города?\n'
                    'Журнал отправленных сообщений сохранится — это защита от повторных приветствий.',
                    parent=w):
                return
            try:
                from assistant_profiles import clear_history
                from assistant_store import Store
                clear_history(Store())
                note.set('История анкет и городов очищена. Журнал отправок сохранён.')
            except Exception:
                note.set('Не удалось очистить историю. Закрой другие окна программы.')
        test_stop=threading.Event()
        def test_groq():
            test_ai_button.configure(state='disabled')
            note.set('Тест ИИ: вопрос, предложение контакта и отказ. Только вымышленные данные…')
            results = queue.Queue()
            model, provider, entered = ai_model.get().strip(), ai_provider.get(), ai_key.get()
            test_stop.clear()
            def work():
                try:
                    assistant_ai.test_connection(provider, model, entered, test_stop.is_set)
                    results.put(assistant_ai.LABELS[provider] + ': все 3 проверки пройдены. ' +
                                ('Введённый ключ проверен, но ещё не сохранён.' if entered.strip() else 'Использован сохранённый ключ.'))
                except groq_reply.GroqError as error:
                    results.put(assistant_ai.explain(str(error)))
                except Exception:
                    results.put('ИИ: проверка не выполнена. Ключ в отчёт не записан.')
            def poll_test():
                if not w.winfo_exists():
                    return
                try:
                    note.set(results.get_nowait())
                    test_ai_button.configure(state='normal')
                except queue.Empty:
                    w.after(100, poll_test)
            threading.Thread(target=work, daemon=True).start()
            w.after(100, poll_test)
        def edit_rules():
            try:
                from assistant_config import config_directory
                path=config_directory()/'groq-rules.txt'
                if not path.is_file():
                    raise OSError()
                os.startfile(str(path))
                note.set('Правила открыты. Сохрани файл UTF-8; новые ответы прочитают изменения.')
            except Exception:
                note.set('Открой config/groq-rules.txt рядом с EXE. Файл должен быть в UTF-8.')
        ttk.Button(ai_box, text='Открыть правила ИИ', command=edit_rules).pack(anchor='w', pady=8)
        test_ai_button = ttk.Button(ai_box, text='Тест ИИ (введённый или сохранённый ключ)', command=test_groq)
        test_ai_button.pack(anchor='w', pady=8)
        actions = ttk.Frame(container)
        actions.pack(fill='x', pady=8)
        ttk.Button(actions, text='Сохранить', command=store).pack(side='left')
        ttk.Button(actions, text='Тест Telegram', command=test_telegram).pack(side='left', padx=8)
        # Shared peer/send claims are never erased by a GUI convenience button.
        ttk.Label(container, textvariable=note, wraplength=520).pack(anchor='w')
        def close_settings():
            nonlocal dialog
            test_stop.set()
            token.set('')
            ai_key.set('')
            api_key.set('')
            dialog = None
            w.destroy()
        w.protocol('WM_DELETE_WINDOW', close_settings)

    start = ttk.Button(controls, text='Старт', command=begin)
    start.pack(side='left')
    replies = ttk.Button(controls, text='Только ответы', command=lambda: begin('inbox'))
    replies.pack(side='left', padx=10)
    stop = ttk.Button(controls, text='Стоп', command=cancel, state='disabled')
    stop.pack(side='left')
    check_button=ttk.Button(controls,text='Проверить подключения',command=check_connections)
    check_button.pack(side='left',padx=8)
    options = ttk.Button(controls, text='Настройки', command=configure)
    options.pack(side='right')

    def poll():
        nonlocal busy
        while not events.empty():
            kind, value = events.get_nowait()
            if kind=='phone':
                cloud_id,phase,text=value
                messages={
                    'configuration':'Сохрани MoreLogin API / проверь настройки',
                    'ssh-key-untrusted':'Сначала проверь SSH-подключение и подтверди ключ',
                    'ssh-key-changed':'SSH-ключ изменился. Нужна ручная сверка, запуск запрещён',
                    'ssh-unavailable':'SSH недоступен. Проверь телефон, сеть и права',
                    'ssh-format':'Этот формат подключения пока не поддержан',
                    'phone-unavailable':'Телефон выключен, ADB выключен или нет доступа',
                    'phone-ambiguous':'Неоднозначное соответствие Cloud Phone ID',
                    'bundle-required':'Нужен совместимый комплект test-apks / Gadget',
                    'device-not-ready':'Устройство/приложение не готово. Проверь Gadget и отчёт',
                    'worker-stopped':'Процесс остановлен. Неизвестные отправки не повторяются',
                    'cancelled':'Остановлено пользователем',
                }
                set_phone(cloud_id, messages.get(text,text) if phase=='error' else text)
                continue
            if kind=='host-key':
                cloud_id,host,port,observed=value
                if not stopped.is_set():
                    previous=pins.get(cloud_id)
                    if previous==observed:
                        set_phone(cloud_id,'SSH-ключ совпал. Можно запускать')
                    elif messagebox.askyesno('Проверка SSH-ключа',
                        f'Cloud Phone {cloud_id}\nSSH-сервер {host}:{port}\n{observed}\n\n'+
                        ('ВНИМАНИЕ: ключ изменился! ' if previous else 'Это первое подключение. ')+
                        'Сверь отпечаток по доверенному каналу. Само получение ключа не доказывает подлинность сервера.\nСохранить этот ключ для выбранного Cloud Phone?',parent=root):
                        pins[cloud_id]=observed
                        save_ids(ids_from_text(id_text.get('1.0','end')))
                        set_phone(cloud_id,'SSH-ключ сохранён. Можно запускать')
                    else:
                        set_phone(cloud_id,'SSH-ключ не подтверждён; запуск заблокирован')
                continue
            if kind in ('cloud-done','check-done'):
                busy=False
                status.set(completion_text(value) if kind=='check-done' else 'Все процессы завершены. Смотри статусы телефонов; общая база сохранена.')
                refresh()
                continue
            if kind == 'progress':
                if not stopped.is_set():
                    status.set(value)
                continue
            busy = False
            if kind == 'error':
                status.set(value)
            elif kind == 'start-result':
                status.set(monitor_summary(value))
                if value['status'] in ('stopped', 'paused'):
                    try:
                        os.startfile(str(data_directory()))
                    except (OSError, AttributeError):
                        pass
            refresh()
        root.after(100, poll)

    def close():
        if busy:
            cancel()
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    if self_check:
        root.update()
        assert root.winfo_viewable() and all(b.winfo_viewable() for b in
                                             (start, stop, replies, options))
        assert not busy and not stopped.is_set() and events.empty()
        assert str(stop.cget('state')) == 'disabled'
        assert not phone_status.get_children()
        configure()
        root.update()
        assert dialog.winfo_viewable() and events.empty()
        root.destroy()
        return
    root.after(100, poll)
    root.mainloop()


if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['--self-check']):
        raise SystemExit(2)
    launch(self_check=sys.argv[1:] == ['--self-check'])
