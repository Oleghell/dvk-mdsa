"""Compact EXE entry: Start / Stop / Settings. No automatic startup actions."""
import json
import os
import queue
import sys
import threading
from pathlib import Path

from assistant_store import StateError, data_directory
from assistant_settings import Settings, load, save
from assistant_cycle import start as start_cycle
import telegram_notify


def launch(self_check=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk()
    root.title('ДругВокруг · MuMu №4')
    root.geometry('640x340')
    root.minsize(640, 340)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='ДругВокруг · MuMu №4', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
    status = tk.StringVar(value='Проверочная сборка 0.4.6. Открой анкеты на MuMu №4. «Старт» откроет только привязанные чаты с непрочитанными сообщениями, до пяти за проход. Отправка выключена.')
    try:
        settings = Settings() if self_check else load()
    except StateError as error:
        settings = Settings()
        status.set(str(error))
    ttk.Label(frame, textvariable=status, wraplength=520).pack(anchor='w', pady=(18, 12))
    ttk.Label(frame, text='Чтение и анализ только в памяти. Telegram и отправка выключены.\nСтарые журналы сохраняются. Не управляй экраном во время проверки.', wraplength=520).pack(anchor='w')
    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=(18, 0))
    events = queue.Queue()
    stopped = threading.Event()
    busy = False
    dialog = None

    def refresh():
        start.configure(state='disabled' if busy else 'normal')
        options.configure(state='disabled' if busy else 'normal')
        bind.configure(state='disabled' if busy else 'normal')
        stop.configure(state='normal' if busy else 'disabled')

    def cancel():
        stopped.set()
        status.set('Останавливаю. Выполненные действия не откатываются.')

    def worker(current):
        try:
            result = start_cycle(current, stopped, lambda text: events.put(('progress', text)))
            events.put(('result', result))
        except Exception as error:
            text = str(error) if isinstance(error, StateError) else 'Остановлено до продолжения. Проверь пути и локальные файлы.'
            events.put(('error', text))

    def begin():
        nonlocal busy
        if busy:
            return
        try:
            settings.check()
            save(settings)
        except Exception as error:
            status.set(str(error) if isinstance(error, StateError) else 'Не удалось сохранить настройки. Запуск отменён.')
            return
        stopped.clear()
        busy = True
        refresh()
        threading.Thread(target=worker, args=(settings,), daemon=True).start()

    def bind_current():
        nonlocal busy
        if busy:
            return
        if not messagebox.askyesno('Привязка только для чтения',
                'Вручную открой нужную переписку в MuMu №4.\n'
                'Разрешить чтение именно этого открытого чата?\n'
                'Отправка не разрешается. Текст сообщений при привязке не читается.\n'
                'Не переключай чат до завершения.', parent=root):
            return
        try:
            settings.check()
        except Exception:
            status.set('Проверь пути в настройках. Привязка не выполнена.')
            return
        stopped.clear()
        busy = True
        refresh()
        status.set('Проверяю открытый чат без чтения сообщений. Не переключай экран.')
        current = settings
        def binding_worker():
            from assistant_read_binding import bind_open_chat
            try:
                result = bind_open_chat(current, stopped, approved=True)
                events.put(('binding', result))
            except Exception:
                events.put(('error', 'Привязка не подтверждена. Проверь открытый чат и MuMu №4. Отправки не было.'))
        threading.Thread(target=binding_worker, daemon=True).start()

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
        ttk.Label(box, text='Проверять старые диалоги каждые N секунд (для будущего общего цикла)').pack(anchor='w')
        ttk.Entry(box, textvariable=interval, width=8).pack(anchor='w', pady=(3, 10))
        ttk.Checkbutton(box, variable=enabled, text='Telegram (в этой проверочной сборке не используется)').pack(anchor='w', pady=8)
        for label, var, mask in (('Токен бота', token, '*'), ('Chat ID получателя', recipient, '')):
            ttk.Label(box, text=label).pack(anchor='w')
            ttk.Entry(box, textvariable=var, show=mask, width=58).pack(fill='x', pady=(3, 8))
        def store():
            nonlocal settings
            try:
                current = Settings(adb.get(), folder.get(), enabled.get(), int(interval.get())).check()
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
        ttk.Button(box, text='Сохранить', command=store).pack(anchor='w', pady=8)
        ttk.Label(box, textvariable=note, wraplength=520).pack(anchor='w')
        def close_settings():
            nonlocal dialog
            token.set('')
            dialog = None
            w.destroy()
        w.protocol('WM_DELETE_WINDOW', close_settings)

    start = ttk.Button(controls, text='Старт', command=begin)
    start.pack(side='left')
    stop = ttk.Button(controls, text='Стоп', command=cancel, state='disabled')
    stop.pack(side='left', padx=10)
    bind = ttk.Button(controls, text='Привязать чат для чтения', command=bind_current)
    bind.pack(side='left', padx=(0, 10))
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
            if kind == 'binding':
                status.set('Чат привязан только для чтения. Вернись к анкетам и нажми «Старт». Разрешения на отправку нет.')
            elif kind == 'error':
                status.set(value)
            elif value.get('report_name'):
                if value['status'] == 'dialogs-completed':
                    count = value['dialogs_read']
                    text = (f'Прочитано чатов с непрочитанными сообщениями: {count}.' if count else
                            'Среди видимых привязанных чатов непрочитанных нет.')
                    status.set(text + ' Сообщения не отправлялись. Возврат к анкетам подтверждён. Пришли messages-pass-check.json.')
                elif value['status'] == 'dialogs-empty':
                    status.set('В журнале нет подходящих диалогов для проверки. Сообщения не отправлялись. Пришли messages-pass-check.json.')
                elif value['status'] == 'dialogs-cancelled':
                    status.set('Проход остановлен. Уже выполненные действия не откатываются. Отчёт: messages-pass-check.json.')
                else:
                    status.set('Проверка остановлена: ' + value['reason'] + '. Сообщения не отправлялись. Пришли messages-pass-check.json. Проверь экран вручную.')
                try:
                    os.startfile(str(data_directory()))
                except (OSError, AttributeError):
                    status.set(status.get() + ' Папка: %LOCALAPPDATA%/DvkAssistant/.')
            elif value['status'] == 'cancelled':
                status.set('Остановлено до запуска прохода.')
            else:
                status.set('Проход остановлен. Проверь экран и журнал. Неизвестные попытки не повторяются.')
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
        assert root.winfo_viewable() and all(b.winfo_viewable() for b in (start, stop, bind, options))
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
