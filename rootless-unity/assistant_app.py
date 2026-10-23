"""DvkAssistant window: Start / Replies / Stop / Settings.

No startup actions. Explicit Start authorizes this run; Stop revokes it.
"""
import sys
if __name__ == '__main__' and sys.argv[1:] in (['--mumu-worker'], ['--mumu-worker-self-check']):
    from mumu_worker import main
    raise SystemExit(main())

import os
from dataclasses import replace
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
from mumu_version import VERSION
from mumu_common import load_ports, save_ports, parse as parse_ports, MumuError, device_directory
from mumu_controller import run_many


def launch(self_check=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk()
    root.title('DvkAssistant ' + VERSION + ' · ДругВокруг · MuMu · несколько устройств')
    root.geometry('760x430')
    root.minsize(680, 380)
    frame = ttk.Frame(root, padding=12)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='ДругВокруг · MuMu', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
    status = tk.StringVar(value='Готово • версия ' + VERSION)
    try:
        settings = replace(Settings() if self_check else load(),profile_interval=120,reply_interval=5)
    except StateError as error:
        settings = Settings()
        status.set(str(error))
    ttk.Label(frame, textvariable=status, wraplength=700).pack(anchor='w', pady=(8, 6))
    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=(8, 0))
    events = queue.Queue()
    stopped = threading.Event()
    busy = False
    dialog = None
    first_profiles_run = True

    def refresh():
        start.configure(state='disabled' if busy else 'normal')
        ports_box.configure(state='disabled' if busy else 'normal')
        options.configure(state='disabled' if busy else 'normal')
        replies.configure(state='disabled' if busy else 'normal')
        stop.configure(state='normal' if busy else 'disabled')

    def cancel():
        stopped.set()
        status.set('Останавливаю. Выполненные действия не откатываются.')

    def worker(current, mode, fresh, ports):
        results=run_many(ports,current,mode,fresh,stopped,
            lambda n,text:events.put(('device-progress',(n,text))))
        events.put(('devices-finished',results))

    def begin(mode='full'):
        nonlocal busy, first_profiles_run
        if busy:
            return
        try:
            settings.check()
            ports = parse_ports(ports_box.get('1.0','end'))
            save_ports(ports)
            save(settings)
        except Exception as error:
            status.set(str(error) if isinstance(error, StateError) else 'Не удалось сохранить настройки. Запуск отменён.')
            return
        # The Start button itself authorizes this run. No redundant modal.
        fresh = first_profiles_run and mode == 'full'
        if mode == 'full':
            first_profiles_run = False
        stopped.clear()
        busy = True
        refresh()
        device_table.delete(*device_table.get_children())
        for n in ports:device_table.insert('', 'end', iid=str(n), values=(n,'Запускаю'))
        status.set('Запускаю выбранные MuMu параллельно. Ошибка одного не останавливает другие.')
        threading.Thread(target=worker, args=(settings, mode, fresh, ports), daemon=True).start()

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
        box, ai_box, tg_box = (ttk.Frame(tabs, padding=12) for _ in range(3))
        for tab, title in ((box, 'Поиск и ответы'), (ai_box, 'ИИ / ключи'), (tg_box, 'Telegram')):
            tabs.add(tab, text=title)
        adb = tk.StringVar(value=settings.adb)
        folder = tk.StringVar(value=settings.folder)
        limit = tk.StringVar(value=str(settings.profile_limit))
        interval = tk.StringVar(value='5')
        profile_interval = tk.StringVar(value='120')
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
        ttk.Label(box, text='Опрос лички во время ожидания: каждые 5 секунд').pack(anchor='w')
        ttk.Entry(box, textvariable=interval, width=8, state='readonly').pack(anchor='w', pady=(3, 10))
        ttk.Label(box, text='Работа с личкой между порциями: 120 секунд').pack(anchor='w')
        ttk.Entry(box, textvariable=profile_interval, width=8, state='readonly').pack(anchor='w', pady=(3, 10))
        ttk.Label(box, text='Во время отдыха проверяю входящие и отвечаю. Отправка с задержкой 35 слов/мин.\nСтарт разрешает автоматические сообщения; не трогай выбранные MuMu во время работы.', wraplength=500).pack(anchor='w', pady=8)
        ttk.Checkbutton(ai_box, variable=ai_enabled, text='ИИ: короткие ответы по структуре цепочки').pack(anchor='w', pady=6)
        ttk.Label(ai_box, text='Весь проверенный снимок чата (до 19 сообщений, суммарно 16 384 символа) и правила передаются Groq, а при недоступности его ключей — OpenRouter и провайдеру модели. ID/имя профиля не передаются; контакты маскируются.', wraplength=500).pack(anchor='w')
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
        ttk.Label(ai_box, text='Несколько ключей: заполни config/ai-keys.txt по образцу ai-keys.example.txt. MuMu: сначала ключи Groq, затем резерв OpenRouter; после всех отказов — пропуск текущего чата. Файл содержит секреты: никому не отправляй.', wraplength=500).pack(anchor='w', pady=4)
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
                                   provider, models['openrouter'], 120).check()
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
        ttk.Button(actions, text='Очистить историю анкет', command=clear).pack(side='left')
        ttk.Label(container, textvariable=note, wraplength=520).pack(anchor='w')
        def close_settings():
            nonlocal dialog
            test_stop.set()
            token.set('')
            ai_key.set('')
            dialog = None
            w.destroy()
        w.protocol('WM_DELETE_WINDOW', close_settings)

    start = ttk.Button(controls, text='Старт', command=begin)
    start.pack(side='left')
    replies = ttk.Button(controls, text='Только ответы', command=lambda: begin('inbox'))
    replies.pack(side='left', padx=10)
    stop = ttk.Button(controls, text='Стоп', command=cancel, state='disabled')
    stop.pack(side='left')
    options = ttk.Button(controls, text='Настройки', command=configure)
    options.pack(side='right')

    devices_box=ttk.LabelFrame(frame,text='Порты MuMu ADB — по одному на строку',padding=8)
    devices_box.pack(fill='both',expand=True,pady=12)
    ports_box=tk.Text(devices_box,width=9,height=6)
    ports_box.pack(side='left',fill='y')
    try:initial_ports=load_ports() if not self_check else [5557,5559,5561,5563,5565]
    except MumuError as error:
        initial_ports=[];status.set(str(error))
    ports_box.insert('1.0','\n'.join(map(str,initial_ports)))
    device_table=ttk.Treeview(devices_box,columns=('port','status'),show='headings',height=6)
    device_table.heading('port',text='ADB порт');device_table.heading('status',text='Состояние')
    device_table.column('port',width=80,stretch=False);device_table.column('status',width=510)
    scroll=ttk.Scrollbar(devices_box,orient='vertical',command=device_table.yview)
    device_table.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y');device_table.pack(side='left',fill='both',expand=True,padx=(8,0))
    ttk.Label(frame,text='Общая база · 35 слов/мин · 2 минуты в личке между порциями').pack(anchor='w')
    def show_reports():
        try:
            selected=device_table.selection()
            path=device_directory(int(selected[0])) if selected else data_directory()
            path.mkdir(parents=True,exist_ok=True);os.startfile(str(path))
        except (OSError,AttributeError,ValueError):status.set('Отчёты: %LOCALAPPDATA%/DvkAssistant; остальные порты — devices/<порт>.')
    ttk.Button(frame,text='Отчёты выбранного MuMu',command=show_reports).pack(anchor='w',pady=6)

    def poll():
        nonlocal busy
        while not events.empty():
            kind, value = events.get_nowait()
            if kind == 'device-progress':
                n,text=value
                if device_table.exists(str(n)):device_table.item(str(n),values=(n,text))
                continue
            if kind == 'devices-finished':
                busy=False
                status.set('Все выбранные процессы завершены. Причины — в таблице и отчётах каждого MuMu.')
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

    statistics_stop = None

    def close():
        if busy:
            cancel()
        else:
            if statistics_stop is not None:statistics_stop.set()
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    if self_check:
        root.update()
        assert root.winfo_viewable() and all(b.winfo_viewable() for b in
                                             (start, stop, replies, options))
        assert not busy and not stopped.is_set() and events.empty()
        assert str(stop.cget('state')) == 'disabled'
        configure()
        root.update()
        assert dialog.winfo_viewable() and events.empty()
        root.destroy()
        return
    import telegram_statistics
    statistics_stop=telegram_statistics.start()
    root.after(100, poll)
    root.mainloop()
    statistics_stop.set()


if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['--self-check']):
        raise SystemExit(2)
    launch(self_check=sys.argv[1:] == ['--self-check'])
