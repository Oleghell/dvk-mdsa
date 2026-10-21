"""DvkAssistant window: Start / Replies / Stop / Settings.

No startup actions. Explicit Start authorizes this run; Stop revokes it.
"""
import os
import queue
import sys
import threading

from assistant_authorization import RunAuthorization
from assistant_store import StateError, data_directory
from assistant_settings import Settings, load, save
from assistant_monitor import run as monitor, summary as monitor_summary
import telegram_notify
import groq_reply
from version import VERSION


def launch(self_check=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk()
    root.title('DvkAssistant ' + VERSION + ' · ДругВокруг · MuMu №4')
    root.geometry('700x520')
    root.minsize(700, 520)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='ДругВокруг · MuMu №4', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
    status = tk.StringVar(value='Версия ' + VERSION + '. «Старт»: сначала ответы в непрочитанных чатах, '
                          'затем порции анкет с паузой 2 минуты и мониторинг диалогов. Groq включается в настройках; автоматическая отправка — после явного запуска.')
    try:
        settings = Settings() if self_check else load()
    except StateError as error:
        settings = Settings()
        status.set(str(error))
    ttk.Label(frame, textvariable=status, wraplength=520).pack(anchor='w', pady=(18, 12))
    ttk.Label(frame, text='Цепочка: приветствие → ответ → «Как дела?)»/«Как настроение?)» → ответ → '
              'предложение Telegram/WhatsApp → контакт → уведомление боту.\n'
              'В Telegram уходят добровольно присланные контакты и коды ошибок. При включённом Groq часть переписки передаётся Groq.',
              wraplength=640).pack(anchor='w')
    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=(18, 0))
    events = queue.Queue()
    stopped = threading.Event()
    busy = False
    dialog = None
    first_profiles_run = True

    def refresh():
        start.configure(state='disabled' if busy else 'normal')
        options.configure(state='disabled' if busy else 'normal')
        replies.configure(state='disabled' if busy else 'normal')
        stop.configure(state='normal' if busy else 'disabled')

    def cancel():
        stopped.set()
        status.set('Останавливаю. Выполненные действия не откатываются.')

    def worker(current, mode, fresh):
        try:
            result = monitor(current, stopped, RunAuthorization(stopped),
                             lambda text: events.put(('progress', text)),
                             mode=mode, fresh_session=fresh)
            events.put(('start-result', result))
        except Exception:
            events.put(('error', 'Остановлено до продолжения. Проверь пути и локальные файлы.'))

    def begin(mode='full'):
        nonlocal busy, first_profiles_run
        if busy:
            return
        try:
            settings.check()
            save(settings)
        except Exception as error:
            status.set(str(error) if isinstance(error, StateError) else 'Не удалось сохранить настройки. Запуск отменён.')
            return
        text = ('1) Открою непрочитанные чаты, где уже идёт цепочка, и отправлю следующее сообщение цепочки.\n'
                '2) Затем наберу ' + str(settings.profile_limit) + ' подходящих анкет: только онлайн, '
                'друзей меньше 50, пустой чат — отправлю приветствие.\n\n'
                if mode == 'full' else
                'Открою непрочитанные чаты, где уже идёт цепочка, и отправлю следующее сообщение цепочки.\n\n')
        if not messagebox.askyesno('Старт' if mode == 'full' else 'Только ответы', text +
                                   'После прохода останусь в диалогах и буду проверять отслеживаемые чаты каждые '
                                   + str(settings.reply_interval) + ' сек. ' +
                                   ('В полном режиме: следующая порция в другом случайном городе через 120 секунд после предыдущей.\n' if mode == 'full' else 'Новые анкеты в режиме «Только ответы» не запускаются.\n') +
                                   ('Groq: до 12 коротких фрагментов переписки будут переданы Groq для ответа.\n' if settings.groq_enabled else 'Groq выключен: используются шаблоны цепочки.\n') +
                                   'Этот запуск разрешает автоматические приветствия и ответы цепочки без отдельных окон. '
                                   'Не трогай MuMu №4 во время работы.\n\nНачать?', parent=root):
            return
        fresh = first_profiles_run and mode == 'full'
        if mode == 'full':
            first_profiles_run = False
        stopped.clear()
        busy = True
        refresh()
        status.set('Работаю. Отправка автоматическая в рамках этого запуска; «Стоп» завершает мониторинг.')
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
        box, ai_box, tg_box = (ttk.Frame(tabs, padding=12) for _ in range(3))
        for tab, title in ((box, 'Поиск и ответы'), (ai_box, 'Groq'), (tg_box, 'Telegram')):
            tabs.add(tab, text=title)
        adb = tk.StringVar(value=settings.adb)
        folder = tk.StringVar(value=settings.folder)
        limit = tk.StringVar(value=str(settings.profile_limit))
        interval = tk.StringVar(value=str(settings.reply_interval))
        enabled = tk.BooleanVar(value=settings.contacts_enabled)
        errors_enabled = tk.BooleanVar(value=settings.errors_enabled)
        ai_enabled = tk.BooleanVar(value=settings.groq_enabled)
        ai_model = tk.StringVar(value=settings.groq_model)
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
        ttk.Label(box, text='Проверка непрочитанных (30–3600 секунд)').pack(anchor='w')
        ttk.Entry(box, textvariable=interval, width=8).pack(anchor='w', pady=(3, 10))
        ttk.Label(box, text='Полный режим: новая порция и случайный город через 120 секунд после предыдущей.\nДиалоги и поиск выполняются последовательно; пропущенные интервалы не накапливаются.', wraplength=500).pack(anchor='w', pady=8)
        ttk.Checkbutton(ai_box, variable=ai_enabled, text='Groq: короткие смысловые ответы по структуре цепочки').pack(anchor='w', pady=8)
        ttk.Label(ai_box, text='До 12 фрагментов по 300 символов из проверенного чата передаются Groq. ID и имя профиля не передаются; ссылки/номера маскируются. Не включай без согласия на такую передачу.', wraplength=500).pack(anchor='w')
        for label, var, mask in (('Модель Groq', ai_model, ''), ('API-ключ Groq (gsk_…) — пустое поле сохраняет прежний', ai_key, '*')):
            ttk.Label(ai_box, text=label).pack(anchor='w', pady=(10, 0))
            ttk.Entry(ai_box, textvariable=var, show=mask, width=58).pack(fill='x', pady=(3, 8))
        ttk.Label(ai_box, text='Ключ и готовые ИИ-черновики защищаются Windows DPAPI. Ошибка API останавливает цикл без шаблонного запасного ответа.', wraplength=500).pack(anchor='w', pady=8)
        ttk.Checkbutton(tg_box, variable=errors_enabled, text='Telegram: уведомлять о причинах остановок и ошибок').pack(anchor='w', pady=8)
        ttk.Checkbutton(tg_box, variable=enabled, text='Telegram: уведомлять, когда человек сам прислал контакт').pack(anchor='w', pady=8)
        for label, var, mask in (('Токен бота', token, '*'), ('Chat ID получателя', recipient, '')):
            ttk.Label(tg_box, text=label).pack(anchor='w')
            ttk.Entry(tg_box, textvariable=var, show=mask, width=58).pack(fill='x', pady=(3, 8))
        def store():
            nonlocal settings
            try:
                current = Settings(adb.get(), folder.get(), enabled.get(), int(interval.get()),
                                   int(limit.get()), ai_enabled.get(), ai_model.get().strip(), errors_enabled.get()).check()
                if ai_key.get().strip():
                    groq_reply.save_key(ai_key.get())
                elif current.groq_enabled:
                    groq_reply.load_key()
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
        def test_groq():
            test_ai_button.configure(state='disabled')
            note.set('Проверяю Groq на вымышленном примере, без переписки из MuMu…')
            results = queue.Queue()
            model = ai_model.get().strip()
            def work():
                try:
                    sample = dict(identity=dict(account='100', peer='200', chat='300'), messages=[
                        dict(id='1', sender='100', text='Привет'), dict(id='2', sender='200', text='Взаимно')])
                    response = groq_reply.Responder(model=model)('question', sample)
                    results.put('Groq подключён, формат ответа проверен.' if response['decision'] == 'reply' else 'Groq доступен; тестовый ответ не выбран.')
                except groq_reply.GroqError as error:
                    results.put('Groq: ' + str(error))
                except Exception:
                    results.put('Groq: проверка не выполнена.')
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
        test_ai_button = ttk.Button(ai_box, text='Тест Groq (сначала сохрани ключ)', command=test_groq)
        test_ai_button.pack(anchor='w', pady=8)
        actions = ttk.Frame(container)
        actions.pack(fill='x', pady=8)
        ttk.Button(actions, text='Сохранить', command=store).pack(side='left')
        ttk.Button(actions, text='Тест Telegram', command=test_telegram).pack(side='left', padx=8)
        ttk.Button(actions, text='Очистить историю анкет', command=clear).pack(side='left')
        ttk.Label(container, textvariable=note, wraplength=520).pack(anchor='w')
        def close_settings():
            nonlocal dialog
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

    def poll():
        nonlocal busy
        while not events.empty():
            kind, value = events.get_nowait()
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
