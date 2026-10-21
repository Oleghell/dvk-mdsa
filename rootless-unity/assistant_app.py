"""Compact EXE entry: Start / Stop / Settings. No automatic startup actions."""
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

from assistant_store import StateError, data_directory
from assistant_settings import Settings, load, save
from assistant_cycle import start as start_cycle
from assistant_guided_chain import run as run_guided_chain
import telegram_notify


def launch(self_check=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk()
    root.title('ДругВокруг · MuMu №4')
    root.geometry('680x430')
    root.minsize(680, 430)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='ДругВокруг · MuMu №4', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
    status = tk.StringVar(value='Сборка 0.4.7. «Старт» — прежнее чтение непрочитанных без отправки. «Вся цепочка» — один открытый чат, оба ответа с отдельными подтверждениями и уведомление в Telegram.')
    try:
        settings = Settings() if self_check else load()
    except StateError as error:
        settings = Settings()
        status.set(str(error))
    ttk.Label(frame, textvariable=status, wraplength=520).pack(anchor='w', pady=(18, 12))
    ttk.Label(frame, text='«Старт» ничего не отправляет. В режиме цепочки не переключай открытый чат.\nПереписка, имена и контакты в Telegram и отчёт не передаются.', wraplength=600).pack(anchor='w')
    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=(18, 0))
    events = queue.Queue()
    stopped = threading.Event()
    busy = False
    dialog = None
    approval_window = None

    def refresh():
        start.configure(state='disabled' if busy else 'normal')
        options.configure(state='disabled' if busy else 'normal')
        bind.configure(state='disabled' if busy else 'normal')
        guided.configure(state='disabled' if busy else 'normal')
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
        ttk.Label(box, text='Отправить в тот же открытый чат MuMu №4?',
                  wraplength=480).pack(anchor='w')
        ttk.Label(box, text=request['text'], wraplength=480,
                  font=('Segoe UI', 12)).pack(anchor='w', pady=16)
        note = tk.StringVar()
        ttk.Label(box, textvariable=note).pack(anchor='w')
        row = ttk.Frame(box)
        row.pack(fill='x', pady=12)
        def finish(accepted=False):
            nonlocal approval_window
            request['accepted'] = accepted is True
            request['done'].set()
            approval_window = None
            w.destroy()
        ttk.Button(row, text='Отправить это сообщение', command=lambda: finish(True)).pack(side='left')
        ttk.Button(row, text='Не отправлять', command=finish).pack(side='left', padx=8)
        def stop_all():
            cancel()
            finish()
        ttk.Button(box, text='Остановить всю цепочку', command=stop_all).pack(anchor='w')
        w.protocol('WM_DELETE_WINDOW', finish)
        def tick():
            seconds = max(0, int(request['expires'] - time.monotonic()))
            if stopped.is_set() or request['done'].is_set() or seconds <= 0:
                finish()
                return
            note.set(f'Без подтверждения отправки не будет. Осталось: {seconds} сек.')
            w.after(200, tick)
        tick()
        w.lift()

    def begin_guided():
        nonlocal busy
        if busy:
            return
        try:
            settings.check()
            if not settings.contacts_enabled:
                status.set('Для всей цепочки включи Telegram и сохрани токен и Chat ID в настройках.')
                return
            save(settings)
        except Exception:
            status.set('Проверь настройки. Цепочка не запущена.')
            return
        if not messagebox.askyesno('Вся цепочка · один открытый чат',
                'Используй тестовый чат с согласным собеседником.\n'
                'При первом запуске вручную отправь приветствие из config/greetings.json '
                'и запусти цепочку до ответа собеседника.\n\n'
                'Разрешить чтение этого открытого чата и подготовку обоих следующих сообщений?\n'
                'Каждая отправка потребует отдельного подтверждения. После появления предложения '
                'перейти в мессенджер будет одно уведомление боту без переписки и контактов.\n'
                'Не переключай чат. Ожидание ограничено 30 минутами.', parent=root):
            return
        stopped.clear()
        busy = True
        refresh()
        current = settings
        def chain_worker():
            try:
                value = run_guided_chain(current, stopped, ask_send,
                                         lambda text: events.put(('progress', text)), approved=True)
                events.put(('guided-result', value))
            except Exception:
                events.put(('error', 'Цепочка остановлена. Проверь открытый чат и отчёт. Не повторяй неизвестную отправку.'))
        threading.Thread(target=chain_worker, daemon=True).start()

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
        ttk.Checkbutton(box, variable=enabled, text='Telegram для «Вся цепочка»: уведомление без переписки и контактов').pack(anchor='w', pady=8)
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
    guided = ttk.Button(frame, text='Вся цепочка · открытый чат', command=begin_guided)
    guided.pack(anchor='w', pady=(16, 0))
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
            if kind == 'guided-result':
                reason = value['reason']
                if value['status'] == 'chain-completed':
                    text = 'Оба сообщения появились в истории. Telegram подтвердил уведомление. Доставка сообщений собеседнику не подтверждена.'
                else:
                    text = {
                        'message-not-approved': 'Сообщение не подтверждено. Оно не отправлялось; цепочка на паузе.',
                        'start-before-peer-reply': 'Первый запуск: в чате должно быть только твоё приветствие из списка, ещё без ответа собеседника.',
                        'wait-timeout': 'Время ожидания истекло. Состояние сохранено; неизвестные отправки не повторяются.',
                        'telegram-outcome-unknown': 'Предложение видно в истории, но результат Telegram неизвестен. Автоповтора нет.',
                        'cancelled': 'Цепочка остановлена.',
                        'manual-review': 'Ответ или история неоднозначны. Проверь чат вручную; цепочка остановлена.',
                        'declined': 'Собеседник отказался. Цепочка остановлена.',
                    }.get(reason, 'Цепочка остановлена: ' + reason + '. Проверь чат вручную; неизвестные отправки не повторяются.')
                status.set(text + ' Отчёт: messages-chain-check.json. Чат остаётся открытым.')
            elif kind == 'binding':
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
        assert root.winfo_viewable() and all(b.winfo_viewable() for b in (start, stop, bind, guided, options))
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
