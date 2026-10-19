"""Button-start, definitions-only probe; never enrolls, reads history or sends."""
from pathlib import Path
import queue
import sys
import threading

from diagnose_device import DiagnosticAdb, diagnose
from reply_contract import VERSION

DEFAULT_ADB = 'C:/Users/XXX/Desktop/platform-tools/adb.exe'


def result_status(result):
    contract = result.get('gadget', {}).get('native_metadata', {})
    if result.get('status') == 'contract-ready':
        return 'Сигнатуры подтверждены. Это ещё не чтение входящих. Пришли JSON-отчёт.'
    if result.get('status') == 'contract-incomplete':
        missing = sum(c.get('status') != 'ready' for c in contract.get('checks', []))
        return f'Не подтверждено проверок: {missing}. Ничего не отправлено. Пришли JSON-отчёт.'
    return 'Проверка остановлена: ' + str(result.get('status', 'неизвестно')) + '. Пришли JSON-отчёт, если он создан.'


def start(executable, folder, progress=lambda text: None, cancelled=lambda: False):
    folder = Path(folder).resolve(strict=True)
    return diagnose(DiagnosticAdb(executable, folder), folder, progress, cancelled,
                    reply_contract_probe=True)


def launch_gui(self_check=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk()
    root.title('ДругВокруг · проверка сигнатур ' + VERSION)
    root.geometry('680x350')
    root.minsize(650, 350)
    main = ttk.Frame(root, padding=14)
    main.pack(fill='both', expand=True)
    ttk.Label(main, text='Только определения · MuMu #4', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
    ttk.Label(main, text='Оба MuMu включены; тестовое приложение на #4 уже запущено.\n'
              'Нет чтения переписки, нажатий, отправок, переустановки или изменений журнала.',
              wraplength=620).pack(anchor='w', pady=(6, 12))
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    adb = tk.StringVar(value=DEFAULT_ADB)
    folder = tk.StringVar(value=str(base / 'test-apks'))
    controls = []
    for label, var, pick in (
        ('ADB', adb, lambda: filedialog.askopenfilename(filetypes=[('ADB', '*.exe')])),
        ('Прежняя папка test-apks', folder, filedialog.askdirectory),
    ):
        ttk.Label(main, text=label).pack(anchor='w')
        row = ttk.Frame(main)
        row.pack(fill='x', pady=(2, 8))
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side='left', fill='x', expand=True)
        def choose(v=var, picker=pick):
            value = picker()
            if value:
                v.set(value)
        button = ttk.Button(row, text='Выбрать', command=choose)
        button.pack(side='right', padx=(8, 0))
        controls.extend((entry, button))
    state = tk.StringVar(value='Проверка начнётся только после нажатия кнопки.')
    ttk.Label(main, textvariable=state, wraplength=620).pack(anchor='w', pady=(6, 8))
    events = queue.Queue()
    stop = threading.Event()
    busy = False
    report = None

    def worker(executable, directory):
        try:
            result, path = start(executable, directory, lambda text: events.put(('status', text)), stop.is_set)
            events.put(('done', (result, path)))
        except Exception:
            # Do not expose filesystem paths, Gadget tokens or transport messages.
            events.put(('error', 'Проверь ADB, прежнюю папку test-apks и доступ к папке отчёта.'))

    def begin():
        nonlocal busy, report
        if busy:
            return
        busy = True
        report = None
        stop.clear()
        for control in controls:
            control.config(state='disabled')
        begin_button.config(state='disabled')
        stop_button.config(state='normal')
        report_button.config(state='disabled')
        state.set('Проверка…')
        threading.Thread(target=worker, args=(adb.get(), folder.get()), daemon=True).start()

    def request_stop():
        if busy:
            stop.set()
            state.set('Остановка после ограниченной операции и очистка подключения…')

    def open_report():
        if report is None:
            return
        import os
        try:
            os.startfile(str(report))
        except (AttributeError, OSError):
            messagebox.showinfo('Отчёт', str(report))

    row = ttk.Frame(main)
    row.pack(fill='x', pady=(4, 8))
    begin_button = ttk.Button(row, text='Проверить сигнатуры · без сообщений', command=begin)
    begin_button.pack(side='left')
    stop_button = ttk.Button(row, text='Стоп', command=request_stop, state='disabled')
    stop_button.pack(side='left', padx=8)
    report_button = ttk.Button(row, text='Отчёт', command=open_report, state='disabled')
    report_button.pack(side='left')
    ttk.Label(main, text='Отчёт: rootless-reply-contract-0.3.28.json рядом с папкой test-apks.',
              wraplength=620).pack(anchor='w')

    def poll():
        nonlocal busy, report
        while not events.empty():
            kind, value = events.get_nowait()
            if kind == 'status':
                state.set(value)
                continue
            busy = False
            for control in controls:
                control.config(state='normal')
            begin_button.config(state='normal')
            stop_button.config(state='disabled')
            if kind == 'done':
                result, report = value
                state.set(result_status(result))
                report_button.config(state='normal')
            else:
                state.set(value)
        root.after(100, poll)

    def close():
        if busy:
            request_stop()
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    root.update_idletasks()
    needed = main.winfo_reqheight()
    if needed > root.winfo_height():
        root.geometry('680x' + str(needed))
    if self_check:
        root.update()
        assert root.winfo_viewable() and begin_button.winfo_viewable() and report_button.winfo_viewable()
        assert main.winfo_reqheight() <= root.winfo_height(), 'Controls are clipped'
        assert row.winfo_reqwidth() + 28 <= root.winfo_width(), 'Buttons are clipped'
        import frida
        import reply_contract, diagnose_device
        assert frida.__version__ == '17.24.1' and reply_contract.VERSION == VERSION
        root.destroy()
        return
    root.after(100, poll)
    root.mainloop()


if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['--self-check']):
        raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:] == ['--self-check'])
