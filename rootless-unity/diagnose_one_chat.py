"""One owned test chat: read, optional local transcript, one confirmed fixed send."""
import json
from pathlib import Path
import queue
import sys
import threading

from one_chat_device import capture, ReadStopped
from one_chat_preview import display, fields, TEST_TEXT, QUESTION
from one_chat_session import report as session_report
from one_chat_probe import VERSION, ERRORS
from one_chat_store import TestChatStore
from one_chat_actions import Actions
from one_chat_send_device import submit
import one_chat_local as local

DEFAULT_ADB='C:/Users/XXX/Desktop/platform-tools/adb.exe'


def launch_gui(self_check=False):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title('ДругВокруг · один свой тестовый чат '+VERSION)
    root.geometry('780x750');root.minsize(760,700)
    main=ttk.Frame(root,padding=14);main.pack(fill='both',expand=True)
    ttk.Label(main,text='Один свой тестовый чат · одна подтверждённая отправка',font=('Segoe UI',12,'bold')).pack(anchor='w')
    ttk.Label(main,text='Только тестовый MuMu #4 / 5563 и прежний чат со своим вторым аккаунтом.\n'
        'Нет рассылки, фоновых ответов, смены города или Telegram. Лимит: одна попытка «Как дела?)».\n'
        'Возврат обработчика и появление исходящего НЕ доказывают доставку второму аккаунту.',wraplength=730).pack(anchor='w',pady=(8,10))
    base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    adb=tk.StringVar(value=DEFAULT_ADB);folder=tk.StringVar(value=str(base/'test-apks'));controls=[]
    for label,var,picker in [('ADB',adb,lambda:filedialog.askopenfilename(filetypes=[('ADB','*.exe')])),
                             ('Прежняя папка test-apks',folder,filedialog.askdirectory)]:
        ttk.Label(main,text=label).pack(anchor='w');row=ttk.Frame(main);row.pack(fill='x',pady=(2,8))
        entry=ttk.Entry(row,textvariable=var);entry.pack(side='left',fill='x',expand=True)
        def choose(v=var,pick=picker):
            value=pick()
            if value:v.set(value)
        button=ttk.Button(row,text='Выбрать',command=choose);button.pack(side='right',padx=(8,0));controls.extend((entry,button))
    consent=tk.BooleanVar(value=False);saving=tk.BooleanVar(value=False)
    owned=ttk.Checkbutton(main,variable=consent,text='Открытый чат — с моим вторым аккаунтом. Разрешаю чтение тестовой переписки.')
    owned.pack(anchor='w',pady=(6,4));controls.append(owned)
    save_check=ttk.Checkbutton(main,variable=saving,text='Сохранять тексты и ID локально в профиле Windows (открытый JSON, без шифрования).')
    save_check.pack(anchor='w',pady=(0,8));controls.append(save_check)
    ttk.Label(main,text='Файл: %LOCALAPPDATA%/DvkRootless/one-chat-transcript.json — только последний снимок, до 20 сообщений.\n'
        'Файл остаётся после снятия галочки. Не присылай его, базу или test-apks. Агент не видит эти файлы напрямую.',wraplength=730).pack(anchor='w')
    state=tk.StringVar(value='Привязка 0.3.31/32 сохранена. Начни с «Проверить»; заново привязывать не нужно.')
    ttk.Label(main,textvariable=state,wraplength=730).pack(anchor='w',pady=8)
    ttk.Label(main,text='Для нового черновика отправь со второго аккаунта ровно «'+TEST_TEXT+'», затем нажми «Проверить».\n'
        'Кнопка отправки отдельно запрашивает подтверждение. После резерва попытка не повторяется даже при сбое.',wraplength=730).pack(anchor='w',pady=6)
    preview=tk.StringVar(value='Черновик не загружен. Сначала проверь открытый привязанный чат.')
    preview_box=ttk.LabelFrame(main,text='Предпросмотр фиксированного тестового ответа',padding=10);preview_box.pack(fill='x',pady=8)
    preview_label=ttk.Label(preview_box,textvariable=preview,wraplength=700);preview_label.pack(anchor='w')
    events=queue.Queue();stop=threading.Event();busy=False;report_path=None;last_private=None

    def report(*args,**kwargs):
        store=TestChatStore()
        try:kwargs['submission_check']=Actions(store).diagnostic()
        finally:store.close()
        return session_report(*args,**kwargs)

    def safe_state():
        store=TestChatStore()
        try:return Actions(store).state()
        finally:store.close()

    def worker(kind,executable,directory,expected):
        try:
            if kind!='send':
                private=capture(executable,directory,stop.is_set,expected)
                events.put(('result',(kind,private,directory)));return
            # Fresh read, then durable reservation BEFORE any mutating native script.
            before=capture(executable,directory,stop.is_set,expected)
            if stop.is_set():raise ReadStopped('cancelled')
            store=TestChatStore()
            try:Actions(store).reserve(before)
            finally:store.close()
            result=submit(executable,directory,before,stop.is_set)
            store=TestChatStore()
            try:Actions(store).finish(result)
            finally:store.close()
            after=None
            if result['handler_returned'] and not stop.is_set():
                try:after=capture(executable,directory,stop.is_set,expected)
                except Exception:pass # Never repeat sending to obtain an acknowledgement.
            events.put(('sent',(after,directory)))
        except Exception as exc:
            reason=str(exc) if isinstance(exc,ReadStopped) and str(exc) in ERRORS|{'client-version','cancelled','ambiguous-process','unexpected-process','unsupported-runtime','invalid-forward','not-ready'} else 'operation-stopped'
            events.put(('failed',(directory,reason,exc.diagnostic if isinstance(exc,ReadStopped) else None)))

    def begin(kind):
        nonlocal busy,last_private
        if busy:return
        if not consent.get():messagebox.showinfo('Свой тестовый чат','Подтверди, что это твой второй аккаунт.');return
        try:
            store=TestChatStore()
            try:
                expected=store.bound();send_state=Actions(store).state()
                available=store.db.execute('SELECT code FROM test_preview WHERE singleton=1').fetchone() is not None
            finally:store.close()
            if kind=='bind' and expected is not None:
                messagebox.showinfo('Чат уже привязан','Повторная привязка отключена. Открой ранее выбранный чат.');return
            if kind!='bind' and expected is None:
                messagebox.showinfo('Нет привязки','Сначала привяжи свой тестовый чат.');return
            if kind=='send':
                if send_state!='not-reserved' or not available:
                    messagebox.showinfo('Отправка заблокирована','Нужен текущий тестовый черновик и неиспользованный лимит одной попытки. Не удаляй журнал.');return
                if not messagebox.askyesno('Одна реальная отправка',
                    'Отправить один раз «'+QUESTION+'» только своему второму аккаунту?\n\n'
                    f"Твой аккаунт: {expected['account']}\nВторой аккаунт: {expected['peer']}\nЧат: {expected['chat']}\n\n"
                    'Это реальное сообщение. При неизвестном исходе повтор будет заблокирован. Других сообщений программа не отправляет.'):
                    return
        except Exception:
            state.set('Состояние недоступно. Не удаляй журналы. Отправка не запущена.');return
        last_private=None;transcript_button.config(state='disabled')
        preview.set('Проверяю чат… Предыдущий черновик скрыт. Не переключай экран.')
        busy=True;stop.clear()
        for c in controls:c.config(state='disabled')
        for c in (bind_button,read_button,send_button):c.config(state='disabled')
        stop_button.config(state='normal')
        state.set('Проверка и чтение…' if kind!='send' else 'Проверка, резерв одной попытки и отправка… При сбое не повторяй отправку.')
        threading.Thread(target=worker,args=(kind,adb.get(),folder.get(),None if kind=='bind' else expected),daemon=True).start()

    def cancel():
        if busy:stop.set();state.set('Останавливаю. Если отправка уже началась, отмена не отзывает сообщение и не разрешает повтор.')

    def save_report(directory,value):
        nonlocal report_path
        report_path=Path(directory).resolve(strict=True).parent/('rootless-one-chat-'+VERSION+'.json')
        report_path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');report_button.config(state='normal')

    row=ttk.Frame(main);row.pack(fill='x',pady=8)
    bind_button=ttk.Button(row,text='1. Привязать открытый чат',command=lambda:begin('bind'));bind_button.pack(side='left')
    read_button=ttk.Button(row,text='2. Проверить · без отправки',command=lambda:begin('read'));read_button.pack(side='left',padx=8)
    stop_button=ttk.Button(row,text='Стоп',command=cancel,state='disabled');stop_button.pack(side='left')
    send_row=ttk.Frame(main);send_row.pack(fill='x',pady=4)
    send_button=ttk.Button(send_row,text='3. Отправить «Как дела?)» · один раз',command=lambda:begin('send'),state='disabled');send_button.pack(side='left')

    def show_transcript():
        if last_private is None:return
        top=tk.Toplevel(root);top.title('Только локально · последний снимок, не порядок по времени');top.geometry('720x520')
        text=tk.Text(top,wrap='word');text.pack(fill='both',expand=True)
        text.insert('1.0',local.display(last_private,last_private['identity']));text.config(state='disabled')
    transcript_button=ttk.Button(send_row,text='Показать переписку локально',command=show_transcript,state='disabled');transcript_button.pack(side='left',padx=8)
    def open_report():
        import os
        if report_path is not None:
            try:os.startfile(str(report_path))
            except (AttributeError,OSError):messagebox.showinfo('Отчёт',str(report_path))
    report_button=ttk.Button(main,text='Открыть обезличенный JSON-отчёт',command=open_report,state='disabled');report_button.pack(anchor='w',pady=8)

    def accept(private,directory):
        nonlocal last_private
        store=TestChatStore()
        try:
            outcome=store.consume(private,preview=True)
            send_state=Actions(store).observe(private)
            saved=False
            if saving.get():local.save(private,store.bound());saved=True
            save_report(directory,report(outcome,send_state=send_state,transcript_saved=saved))
            last_private=private;transcript_button.config(state='normal')
            preview.set(display(outcome))
            if send_state=='not-reserved' and outcome['preview_available']:send_button.config(state='normal')
            labels={'not-reserved':'Отправка ещё не резервировалась.','reserved-unknown':'Исход попытки неизвестен. Повтор запрещён; проверь второй аккаунт вручную.',
                    'handler-returned':'Обработчик вернулся, новое исходящее ещё не подтверждено снимком. Повтор запрещён.',
                    'attempted-unknown':'Отправка началась, исход неизвестен. Повтор запрещён.',
                    'not-invoked':'Вызов отправки не состоялся. Лимит попытки сохранён; нужен разбор отчёта.',
                    'outgoing-observed':'В чате наблюдается новое исходящее «Как дела?)». Доставку проверь на втором аккаунте. Повтор запрещён.'}
            state.set(f"Новых входящих: {outcome['new_incoming']}. "+labels[send_state]+(' Тексты сохранены локально.' if saved else ' Тексты на диск не сохранялись этим чтением.'))
        finally:store.close()

    def poll():
        nonlocal busy,last_private
        while not events.empty():
            kind,data=events.get_nowait();busy=False
            for c in controls:c.config(state='normal')
            bind_button.config(state='normal');read_button.config(state='normal');send_button.config(state='disabled');stop_button.config(state='disabled')
            directory=None
            try:
                if kind=='failed':
                    directory,reason,diagnostic=data;value=report(failure=True,send_state=safe_state());value['stop_reason']=reason
                    if diagnostic is not None:value['native_check']=diagnostic
                    save_report(directory,value);preview.set('Проверка остановлена. Черновик скрыт.')
                    state.set('Остановлено: '+reason+'. Если попытка зарезервирована, повтор запрещён. Пришли только обезличенный отчёт.');continue
                if kind=='sent':
                    private,directory=data
                    if private is not None and not stop.is_set():accept(private,directory)
                    else:
                        send_state=safe_state();save_report(directory,report(send_state=send_state))
                        preview.set('Попытка завершена/остановлена. Проверь чат кнопкой 2, не отправляй повторно.')
                        state.set('Состояние: '+send_state+'. Доставка не подтверждена. Проверь второй аккаунт вручную; повтор запрещён.')
                    continue
                operation,private,directory=data
                if stop.is_set():preview.set('Отменено. Результат чтения не сохранён.');continue
                if operation=='bind':
                    who=private['identity']
                    if not messagebox.askyesno('Подтверди свой тестовый чат',f"Твой аккаунт: {who['account']}\nВторой аккаунт: {who['peer']}\nЧат: {who['chat']}\n\nЭто именно твои два аккаунта?"):continue
                    store=TestChatStore()
                    try:store.bind(who)
                    finally:store.close()
                    save_report(directory,report(send_state=safe_state()));state.set('Привязано. Нажми «Проверить»; исходная история не запускает отправку.')
                else:accept(private,directory)
            except Exception:
                last_private=None;transcript_button.config(state='disabled');send_button.config(state='disabled')
                preview.set('Проверка или сохранение не завершены. Черновик скрыт.')
                state.set('Не удаляй журналы и не повторяй отправку. Нажатие «Проверить» ничего не отправляет.')
                try:
                    value=report(failure=True,send_state=safe_state(),transcript_saved=None);value['stop_reason']='state-or-report-unavailable';save_report(directory,value)
                except Exception:pass
        root.after(100,poll)

    def close():
        if busy:cancel()
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);root.update_idletasks()
    needed=main.winfo_reqheight()
    if needed>root.winfo_height():root.geometry('780x'+str(needed))
    if self_check:
        root.update()
        assert root.winfo_viewable() and read_button.winfo_viewable() and send_button.winfo_viewable()
        assert str(send_button.cget('state'))=='disabled'
        assert not consent.get() and not saving.get()
        for value in (fields(),fields('ask-how-are-you','new-test-text',True),fields('ask-how-are-you')):
            preview.set(display(value));root.update_idletasks()
            if main.winfo_reqheight()>root.winfo_height():root.geometry('780x'+str(main.winfo_reqheight()));root.update()
            assert preview.get()==display(value)
        assert main.winfo_reqheight()<=root.winfo_height()
        assert send_row.winfo_reqwidth()+28<=root.winfo_width()
        import frida
        assert frida.__version__=='17.24.1'
        root.destroy();return
    root.after(100,poll);root.mainloop()


if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'])
