"""Standalone GUI: explicitly bind one owned test dialog, then read only."""
import json
from pathlib import Path
import queue
import sys
import threading

from one_chat_device import capture, report, ReadStopped
from one_chat_probe import VERSION, ERRORS
from one_chat_store import TestChatStore

DEFAULT_ADB = 'C:/Users/XXX/Desktop/platform-tools/adb.exe'


def launch_gui(self_check=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk()
    root.title('ДругВокруг · один тестовый чат ' + VERSION)
    root.geometry('760x560')
    root.minsize(740, 530)
    main = ttk.Frame(root, padding=14)
    main.pack(fill='both', expand=True)
    ttk.Label(main, text='Один открытый чат · только чтение', font=('Segoe UI',12,'bold')).pack(anchor='w')
    ttk.Label(main, text='Только тестовый MuMu #4 / 5563. Открой переписку со своим вторым аккаунтом.\n'
      'Нет отправки, поиска анкет, смены города, Telegram или изменений старого журнала.\n'
      'Читается загруженная история (до 20 сообщений). Тексты и ID не попадают в JSON-отчёт.',
      wraplength=710).pack(anchor='w', pady=(8,10))
    base = Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    adb = tk.StringVar(value=DEFAULT_ADB)
    folder = tk.StringVar(value=str(base / 'test-apks'))
    controls = []
    for label,var,picker in [('ADB',adb,lambda:filedialog.askopenfilename(filetypes=[('ADB','*.exe')])),
                              ('Прежняя папка test-apks',folder,filedialog.askdirectory)]:
        ttk.Label(main,text=label).pack(anchor='w')
        row=ttk.Frame(main);row.pack(fill='x',pady=(2,8))
        entry=ttk.Entry(row,textvariable=var);entry.pack(side='left',fill='x',expand=True)
        def choose(v=var,pick=picker):
            value=pick()
            if value:v.set(value)
        button=ttk.Button(row,text='Выбрать',command=choose);button.pack(side='right',padx=(8,0))
        controls.extend((entry,button))
    consent=tk.BooleanVar(value=False)
    owned=ttk.Checkbutton(main,variable=consent,text='Открытый чат — с моим вторым аккаунтом. Разрешаю чтение его тестовых сообщений.')
    owned.pack(anchor='w',pady=(8,10));controls.append(owned)
    state=tk.StringVar(value='Сначала привяжи открытый тестовый чат. Привязка не читает сообщения.')
    ttk.Label(main,textvariable=state,wraplength=710).pack(anchor='w',pady=8)
    ttk.Label(main,text='Первое чтение запоминает текущую историю как исходную. Затем отправь новый ответ\n'
       'со второго аккаунта и нажми «Проверить» ещё раз. Повторное чтение не создаёт новое событие.',wraplength=710).pack(anchor='w',pady=8)
    events=queue.Queue();stop=threading.Event();busy=False;report_path=None

    def worker(kind,executable,directory,expected):
        try:
            private=capture(executable,directory,stop.is_set,expected)
            events.put(('result',(kind,private,directory)))
        except Exception as exc:
            reason=str(exc) if isinstance(exc,ReadStopped) and str(exc) in ERRORS|{'client-version','cancelled','ambiguous-process','unexpected-process','unsupported-runtime','invalid-forward','not-ready'} else 'operation-stopped'
            events.put(('failed',(directory,reason,exc.diagnostic if isinstance(exc,ReadStopped) else None)))

    def begin(kind):
        nonlocal busy
        if busy:return
        if not consent.get():
            messagebox.showinfo('Тестовый аккаунт','Подтверди, что открыт чат со своим вторым аккаунтом.');return
        expected=None
        try:
            store=TestChatStore()
            try:expected=store.bound()
            finally:store.close()
            if kind=='bind' and expected is not None:
                messagebox.showinfo('Чат уже привязан','Перепривязка отключена. Открой ранее выбранный тестовый чат и нажми «Проверить».');return
            if kind=='read' and expected is None:
                messagebox.showinfo('Нет привязки','Сначала нажми «Привязать открытый чат».');return
        except Exception:
            state.set('Не удалось открыть отдельное тестовое состояние. Старые журналы не изменялись.');return
        busy=True;stop.clear()
        for control in controls:control.config(state='disabled')
        bind_button.config(state='disabled');read_button.config(state='disabled');stop_button.config(state='normal')
        state.set('Проверка открытого чата… Не переключай экран до завершения.')
        threading.Thread(target=worker,args=(kind,adb.get(),folder.get(),expected if kind=='read' else None),daemon=True).start()

    def cancel():
        if busy:stop.set();state.set('Останавливаю чтение и закрываю временное подключение…')

    def save_report(directory,value):
        nonlocal report_path
        report_path=Path(directory).resolve(strict=True).parent/'rootless-one-chat-0.3.30.json'
        report_path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        report_button.config(state='normal')

    row=ttk.Frame(main);row.pack(fill='x',pady=8)
    bind_button=ttk.Button(row,text='1. Привязать открытый чат',command=lambda:begin('bind'));bind_button.pack(side='left')
    read_button=ttk.Button(row,text='2. Проверить · без отправки',command=lambda:begin('read'));read_button.pack(side='left',padx=8)
    stop_button=ttk.Button(row,text='Стоп',command=cancel,state='disabled');stop_button.pack(side='left')
    def open_report():
        import os
        if report_path is not None:
            try:os.startfile(str(report_path))
            except (AttributeError,OSError):messagebox.showinfo('Отчёт',str(report_path))
    report_button=ttk.Button(main,text='Открыть обезличенный JSON-отчёт',command=open_report,state='disabled')
    report_button.pack(anchor='w',pady=8)

    def poll():
        nonlocal busy
        while not events.empty():
            kind,data=events.get_nowait();busy=False
            for control in controls:control.config(state='normal')
            bind_button.config(state='normal');read_button.config(state='normal');stop_button.config(state='disabled')
            try:
                if kind=='failed':
                    directory,reason,diagnostic=data
                    value=report(failure=True);value['stop_reason']=reason
                    if diagnostic is not None:value['native_check']=diagnostic
                    save_report(directory,value)
                    state.set('Чтение остановлено: '+reason+'. Пришли только JSON-отчёт; не присылай базы или test-apks.');continue
                operation,private,directory=data
                if stop.is_set():
                    state.set('Отменено. Полученные данные не записаны.');continue
                store=TestChatStore()
                try:
                    if operation=='bind':
                        who=private['identity']
                        if not messagebox.askyesno('Подтверди тестовый чат',
                          f"Твой текущий аккаунт: {who['account']}\nСобеседник (второй аккаунт): {who['peer']}\nЧат: {who['chat']}\n\nЭто именно твои два аккаунта? Сообщения ещё не читались."):
                            state.set('Привязка отменена. Ничего не отправлено.');continue
                        store.bind(who);save_report(directory,report())
                        state.set('Чат привязан. Нажми «Проверить»: первое чтение запомнит текущую историю.')
                    else:
                        outcome=store.consume(private);save_report(directory,report(outcome))
                        if outcome['status']=='baseline-recorded':
                            state.set(f"Исходная история сохранена без текстов. Входящих: {outcome['incoming_messages']}. Теперь отправь со второго аккаунта новую реплику и нажми «Проверить».")
                        else:
                            state.set(f"Новых входящих: {outcome['new_incoming']}. Всего входящих: {outcome['incoming_messages']}. Ничего не отправлено. Для проверки повторов нажми ещё раз или перезапусти программу.")
                finally:store.close()
            except Exception:
                state.set('Проверка/сохранение остановлены. Возможна другая привязка или изменившаяся история. Не удаляй журналы. Ничего не отправлено.')
                try:
                    value=report(failure=True);value['stop_reason']='state-or-report-unavailable';save_report(directory,value)
                except Exception:pass
        root.after(100,poll)

    def close():
        if busy:cancel()
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    root.update_idletasks()
    needed=main.winfo_reqheight()
    if needed>root.winfo_height():root.geometry('760x'+str(needed))
    if self_check:
        root.update()
        assert root.winfo_viewable() and bind_button.winfo_viewable() and read_button.winfo_viewable()
        assert main.winfo_reqheight()<=root.winfo_height()
        assert row.winfo_reqwidth()+28<=root.winfo_width()
        import frida
        assert frida.__version__=='17.24.1'
        root.destroy();return
    root.after(100,poll);root.mainloop()


if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'])
