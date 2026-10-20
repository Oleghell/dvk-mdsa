"""Single DvkAssistant entry point. No operation is started when the window opens."""
import json
from pathlib import Path
import queue
import sys
import threading
import time

from assistant_config import ConfigError, load
from assistant_pass import APPROVAL_SECONDS, run
from assistant_store import StateError, data_directory


def launch(self_check=False):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('ДругВокруг · помощник')
    root.geometry('740x570')
    root.minsize(700, 550)
    pane = ttk.Frame(root, padding=22)
    pane.pack(fill='both', expand=True)
    ttk.Label(pane, text='Помощник · MuMu №4', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
    ttk.Label(pane, text='Одна анкета за запуск. Каждое сообщение — только с твоего подтверждения.',
              wraplength=660).pack(anchor='w', pady=(8, 18))
    adb = tk.StringVar()
    folder = tk.StringVar()
    status = tk.StringVar(value='Готов к работе')
    consent = tk.BooleanVar(value=False)
    settings_path = None
    if not self_check:
        try:
            settings_path = data_directory() / 'settings.json'
            if settings_path.exists():
                settings = json.loads(settings_path.read_text(encoding='utf-8'))
                if set(settings) == {'adb', 'test_apks'} and all(isinstance(v, str) and len(v) <= 4096 for v in settings.values()):
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
    ttk.Label(pane, text='Перед запуском: открой поиск анкет в №4. Пока выставь город и «Только онлайн» вручную. '
              'Не переключай экран во время работы. Закрой другие инструменты управления MuMu.',
              wraplength=660).pack(anchor='w', pady=(8, 12))
    check = ttk.Checkbutton(pane, variable=consent, text='Разрешаю проверку анкет и состояния чатов на №4')
    check.pack(anchor='w')
    controls.append(check)
    ttk.Label(pane, textvariable=status, wraplength=660, font=('Segoe UI', 12)).pack(anchor='w', pady=18)
    events = queue.Queue()
    stopped = threading.Event()
    busy = False
    approval = None
    reject_approval = None

    def worker(executable, directory, greeting):
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
            value = run(executable, directory, greeting, approve, stopped.is_set)
            events.put(('result', value))
        except Exception as error:
            text = str(error) if isinstance(error, (StateError, ConfigError)) else 'Операция остановлена. Проверь ADB, папку test-apks и экран MuMu №4.'
            events.put(('error', text))

    def refresh():
        for control in controls:
            control.configure(state='disabled' if busy else 'normal')
        start.configure(state='disabled' if busy else 'normal')
        stop.configure(state='normal' if busy else 'disabled')

    def begin():
        nonlocal busy
        if busy:
            return
        if not consent.get():
            messagebox.showinfo('Разрешение', 'Подтверди проверку анкет и состояния чатов на №4.')
            return
        try:
            config = load()
            if not adb.get() or not folder.get():
                raise ConfigError('Выбери ADB и прежнюю папку test-apks.')
            if settings_path is not None:
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                temp = settings_path.with_suffix('.tmp')
                temp.write_text(json.dumps(dict(adb=adb.get(), test_apks=folder.get()), ensure_ascii=False), encoding='utf-8')
                temp.replace(settings_path)
            greeting = config.greeting()
        except Exception as error:
            status.set(str(error) if isinstance(error, ConfigError) else 'Не удалось сохранить настройки. Запуск отменён.')
            return
        stopped.clear()
        busy = True
        status.set('Проверяю анкету и чат. Сообщения без отдельного подтверждения не отправляются.')
        refresh()
        threading.Thread(target=worker, args=(adb.get(), folder.get(), greeting), daemon=True).start()

    def cancel():
        stopped.set()
        status.set('Останавливаю. Уже начатую отправку отменить нельзя; повторять её программа не будет.')

    row = ttk.Frame(pane)
    row.pack(fill='x', pady=10)
    start = ttk.Button(row, text='Проверить одну анкету', command=begin)
    start.pack(side='left')
    stop = ttk.Button(row, text='Стоп', command=cancel, state='disabled')
    stop.pack(side='left', padx=10)
    ttk.Label(pane, text='Журнал попыток сохраняется между запусками. Не удаляй старые базы и lock-файлы. '
              'Настройка городов, обход ленты и наблюдение за ответами пока не подключены к этому окну.',
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
        nonlocal busy
        while not events.empty():
            kind, value = events.get_nowait()
            if kind == 'approval':
                ask(value)
                continue
            busy = False
            if reject_approval is not None:
                reject_approval()
            if kind == 'error':
                status.set(value)
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
    if self_check:
        root.update()
        assert root.winfo_viewable() and start.winfo_viewable()
        assert not busy and not consent.get() and not stopped.is_set()
        assert str(stop.cget('state')) == 'disabled'
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
