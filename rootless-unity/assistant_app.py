"""DvkAssistant window: Start / Replies / Stop / Settings.

No automatic startup actions. Every outgoing message needs its own confirmation.
"""
import os
import queue
import sys
import threading
import time

from assistant_store import StateError, data_directory
from assistant_settings import Settings, load, save
from assistant_monitor import run as monitor, summary as monitor_summary
import telegram_notify
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
                          'затем одна порция анкет и мониторинг отслеживаемых диалогов. Каждое сообщение — после подтверждения.')
    try:
        settings = Settings() if self_check else load()
    except StateError as error:
        settings = Settings()
        status.set(str(error))
    ttk.Label(frame, textvariable=status, wraplength=520).pack(anchor='w', pady=(18, 12))
    ttk.Label(frame, text='Цепочка: приветствие → ответ → «Как дела?)»/«Как настроение?)» → ответ → '
              'предложение Telegram/WhatsApp → контакт → уведомление боту.\n'
              'В Telegram уходят только имя и контакт, который человек прислал сам.',
              wraplength=640).pack(anchor='w')
    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=(18, 0))
    events = queue.Queue()
    stopped = threading.Event()
    busy = False
    dialog = None
    approval_window = None
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
            result = monitor(current, stopped, ask_send,
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
        text = ('1) Открою непрочитанные чаты, где уже идёт цепочка, и предложу следующее сообщение.\n'
                '2) Затем проверю до ' + str(settings.profile_limit) + ' новых анкет: только онлайн, '
                'друзей меньше 50, пустой чат — и предложу приветствие.\n\n'
                if mode == 'full' else
                'Открою непрочитанные чаты, где уже идёт цепочка, и предложу следующее сообщение.\n\n')
        if not messagebox.askyesno('Старт' if mode == 'full' else 'Только ответы', text +
                                   'После прохода останусь в диалогах и буду проверять отслеживаемые чаты каждые '
                                   + str(settings.reply_interval) + ' сек. Новые анкеты повторно не запускаются.\n'
                                   'Каждое сообщение отправляется только после кнопки «Отправить». '
                                   'Не трогай MuMu №4 во время работы.\n\nНачать?', parent=root):
            return
        fresh = first_profiles_run and mode == 'full'
        if mode == 'full':
            first_profiles_run = False
        stopped.clear()
        busy = True
        refresh()
        status.set('Работаю. Каждая отправка требует подтверждения; «Стоп» завершает мониторинг.')
        threading.Thread(target=worker, args=(settings, mode, fresh), daemon=True).start()

    def ask_send(kind, text, cancelled):
        request = dict(kind=kind, text=text, done=threading.Event(), accepted=False,
                       expires=time.monotonic() + 60)
        events.put(('approval', request))
        while not request['done'].wait(.1):
            if cancelled() or time.monotonic() >= request['expires']:
                return False
        return request['accepted'] is True and not cancelled() and time.monotonic() < request['expires']

    def show_approval(request):
        nonlocal approval_window
        if stopped.is_set() or request['done'].is_set() or time.monotonic() >= request['expires']:
            request['done'].set()
            return
        w = tk.Toplevel(root)
        approval_window = w
        w.title('Подтвердить одно сообщение')
        box = ttk.Frame(w, padding=16)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text=('Отправить приветствие в этот пустой чат MuMu №4?'
                             if request['kind'] == 'greeting' else
                             'Отправить в открытый чат MuMu №4?'),
                  wraplength=480).pack(anchor='w')
        ttk.Label(box, text=request['text'], wraplength=480,
                  font=('Segoe UI', 12)).pack(anchor='w', pady=16)
        note = tk.StringVar()
        ttk.Label(box, textvariable=note).pack(anchor='w')
        row = ttk.Frame(box)
        row.pack(fill='x', pady=12)
        def finish(accepted=False):
            nonlocal approval_window
            if request['done'].is_set():
                return
            request['accepted'] = accepted is True
            request['done'].set()
            approval_window = None
            w.destroy()
        ttk.Button(row, text='Отправить это сообщение', command=lambda: finish(True)).pack(side='left')
        ttk.Button(row, text='Не отправлять', command=finish).pack(side='left', padx=8)
        def stop_all():
            cancel()
            finish()
        ttk.Button(box, text='Остановить всё', command=stop_all).pack(anchor='w')
        w.protocol('WM_DELETE_WINDOW', finish)
        def tick():
            seconds = max(0, int(request['expires'] - time.monotonic()))
            if request['done'].is_set():
                return
            if stopped.is_set() or seconds <= 0:
                finish()
                return
            note.set(f'Без подтверждения отправки не будет. Осталось: {seconds} сек.')
            w.after(200, tick)
        tick()
        w.lift()

    def configure():
        nonlocal dialog
        if dialog is not None:
            dialog.lift()
            return
        w = tk.Toplevel(root)
        dialog = w
        w.title('Настройки')
        box = ttk.Frame(w, padding=16)
        box.pack(fill='both', expand=True)
        adb = tk.StringVar(value=settings.adb)
        folder = tk.StringVar(value=settings.folder)
        limit = tk.StringVar(value=str(settings.profile_limit))
        interval = tk.StringVar(value=str(settings.reply_interval))
        enabled = tk.BooleanVar(value=settings.contacts_enabled)
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
        ttk.Label(box, text='Анкет за один «Старт» (1–20)').pack(anchor='w')
        ttk.Entry(box, textvariable=limit, width=8).pack(anchor='w', pady=(3, 10))
        ttk.Label(box, text='Проверка непрочитанных (30–3600 секунд)').pack(anchor='w')
        ttk.Entry(box, textvariable=interval, width=8).pack(anchor='w', pady=(3, 10))
        ttk.Checkbutton(box, variable=enabled, text='Telegram: уведомлять, когда человек сам прислал контакт').pack(anchor='w', pady=8)
        for label, var, mask in (('Токен бота', token, '*'), ('Chat ID получателя', recipient, '')):
            ttk.Label(box, text=label).pack(anchor='w')
            ttk.Entry(box, textvariable=var, show=mask, width=58).pack(fill='x', pady=(3, 8))
        def store():
            nonlocal settings
            try:
                current = Settings(adb.get(), folder.get(), enabled.get(), int(interval.get()),
                                   int(limit.get())).check()
                if token.get().strip():
                    telegram_notify.save(token.get(), recipient.get())
                elif current.contacts_enabled:
                    _, previous = telegram_notify.load()
                    if recipient.get().strip() != previous:
                        raise StateError('Для смены получателя укажи токен бота заново.')
                save(current)
                settings = current
                token.set('')
                note.set('Сохранено. Проверок и тестовых отправок не выполнялось.')
            except Exception as error:
                note.set(str(error) if isinstance(error, (StateError, telegram_notify.TelegramError)) else 'Не удалось сохранить настройки. Проверь поля.')
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
        actions = ttk.Frame(box)
        actions.pack(fill='x', pady=8)
        ttk.Button(actions, text='Сохранить', command=store).pack(side='left')
        ttk.Button(actions, text='Тест Telegram', command=test_telegram).pack(side='left', padx=8)
        ttk.Button(actions, text='Очистить историю анкет', command=clear).pack(side='left')
        ttk.Label(box, textvariable=note, wraplength=520).pack(anchor='w')
        def close_settings():
            nonlocal dialog
            token.set('')
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
            if kind == 'approval':
                show_approval(value)
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
