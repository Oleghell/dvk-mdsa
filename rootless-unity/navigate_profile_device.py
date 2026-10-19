"""Compact button-start UI for one profile/return on the existing MuMu #4."""
import os,sys,threading,queue
from pathlib import Path
from diagnose_device import DiagnosticAdb,diagnose,TestError


DEFAULT_ADB='C:/Users/XXX/Desktop/platform-tools/adb.exe'

def result_status(result):
    if result.get('mode')=='reply-runtime-metadata-only':
        return 'Подготовка ответов: '+str(result.get('status','неизвестно'))+'. Пришли JSON. Автоответы пока выключены.'
    if result.get('mode')=='automatic-profile-chat-pass':
        b=result.get('gadget',{}).get('batch',{})
        text=f"Анкет: {b.get('checked',0)}. Чатов: {b.get('chats_checked',0)}. Команд отправки: {b.get('handlers_returned') if b.get('handlers_returned') is not None else 'неизвестно'}."
        if b.get('status')=='batch-exhausted':text+=' Видимые анкеты закончились.'
        elif b.get('status')!='batch-completed':text+=' Стоп: '+str(b.get('reason',result.get('status')))+'.'
        if b.get('profile_may_remain_open'):text+=' Проверь экран вручную.'
        return text

    if result.get('mode')=='one-greeting-current-chat':
        n=result.get('gadget',{}).get('uikit_root',{}).get('navigation',{})
        if n.get('send_handler_returned'):return 'Команда отправки выполнена. Проверь чат. Повтор заблокирован.'
        if n.get('send_attempted') is not False:return 'Результат отправки неизвестен. Проверь чат вручную, не повторяй.'
        return 'Не отправлено: '+str(n.get('error',result.get('status')))+'.'

    if result.get('mode')=='open-chat-state-read-only':
        nav=result.get('gadget',{}).get('uikit_root',{}).get('navigation',{})
        if result.get('status')=='navigation-ready':
            return 'Доступная история пуста. Отправки нет.' if nav.get('history_status')=='empty' else 'Чат не пустой. Записей истории: '+str(nav.get('message_count'))+'.'
        waiting={'chat-not-actual':'Модель чата ещё не актуальна','chat-draft':'Чат в состоянии черновика','no-history-manager':'История для этого чата ещё не создана','null-history-manager':'Объект истории отсутствует','null-loaded-flag':'Нет флага загрузки истории','history-loading':'История загружается','history-not-loaded':'История загружена не полностью','changing-count':'Счётчик меняется','changing-last-message':'История меняется','contradictory-last-message':'Count и последнее сообщение противоречат друг другу','view-not-ready':'Экран меняется','model-changed':'Модель чата изменилась при проверке'}
        if nav.get('error')=='history-not-ready':return waiting.get(nav.get('wait_reason'),'История не готова')+'. Пустота не подтверждена.'
        if nav.get('error')=='wrong-screen':return 'На #4 открой личный чат и повтори проверку.'
        if nav.get('metadata_checkpoint') not in (None,'ready'):return 'Проверка не поддержана: '+nav['metadata_checkpoint']+'. Пришли отчёт.'
        return 'Чат: неизвестно ('+str(nav.get('error') if nav.get('error') not in (None,'none') else result.get('status','ошибка'))+'; этап '+str(nav.get('read_checkpoint','не начат'))+'). Пришли отчёт.'
    if result.get('mode')=='chat-runtime-metadata-only':
        return 'Типы чата проверены — пришли отчёт.' if result.get('status')=='chat-runtime-ready' else 'Типы чата: '+result.get('gadget',{}).get('native_metadata',{}).get('reason',result.get('status','ошибка'))
    if result.get('mode')=='offline-chat-catalog':
        return 'Метаданные чата готовы — пришли отчёт.' if result.get('status')=='catalog-ready' else 'Метаданные чата: '+result.get('reason','ошибка')
    if result.get('mode')=='offline-friends-catalog':
        return 'Метаданные готовы — пришли отчёт.' if result.get('status')=='catalog-ready' else 'Метаданные: '+result.get('reason','ошибка')
    batch=result.get('gadget',{}).get('batch')
    if batch is not None:
        text=f"Проверено: {batch['checked']}. <50: {batch['eligible']}. Пропущено: {batch['skipped']}. Ошибки: {batch['errors']}."
        if batch['status']=='batch-exhausted':text+=' Видимые анкеты закончились.'
        elif batch['status']=='batch-cancelled':text+=' Остановлено.'
        elif batch['status']=='batch-stopped':text+=' Стоп: '+batch['reason']+'.'
        if result.get('profile_may_remain_open'):text+=' Вернись в поиск вручную.'
        return text
    navigation=result.get('gadget',{}).get('uikit_root',{}).get('navigation',{})
    if result.get('status')=='navigation-ready':
        if navigation.get('friends_status')=='read':
            suffix='меньше 50' if navigation['friends_eligible'] else '50 и больше'
            return 'Возврат подтверждён. Друзей: '+str(navigation['friends_count'])+' ('+suffix+').'
        return 'Возврат подтверждён. Число друзей: неизвестно.'
    reason=navigation.get('error')
    if reason in (None,'none'):reason=result.get('status','unknown')
    text='Остановлен: '+reason
    if result.get('profile_may_remain_open'):text+=' — вернись в поиск вручную.'
    return text


def launch_gui(self_check=False):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title('ДругВокруг · 0.3.25')
    root.geometry('640x300');root.minsize(620,300)
    main=ttk.Frame(root,padding=14);main.pack(fill='both',expand=True)
    ttk.Label(main,text='MuMu #4 · профиль и друзья',font=('Segoe UI',11,'bold')).pack(anchor='w')
    ttk.Label(main,text='Для автопрохода открой на #4 поиск людей (сетку анкет).').pack(anchor='w',pady=(4,10))
    base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    binary=tk.StringVar(value=DEFAULT_ADB);folder=tk.StringVar(value=str(base/'test-apks'))
    for label,var,picker in (
        ('ADB',binary,lambda:filedialog.askopenfilename(filetypes=[('ADB','*.exe')])),
        ('Папка test-apks',folder,lambda:filedialog.askdirectory())):
        ttk.Label(main,text=label).pack(anchor='w');row=ttk.Frame(main);row.pack(fill='x',pady=(2,8))
        ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
        def choose(v=var,pick=picker):
            p=pick()
            if p:v.set(p)
        ttk.Button(row,text='Выбрать',command=choose).pack(side='right',padx=(8,0))
    state=tk.StringVar(value='Автопроход: друзья <50, пустой чат → приветствие. Паузы — 1 с.')
    ttk.Label(main,textvariable=state,wraplength=590).pack(anchor='w',pady=(4,6))
    events=queue.Queue();stop=threading.Event();busy=False;report=None
    def worker(executable,directory,batch=False,chat_runtime=False,chat_state=False,chat_send=False,automatic=False,replies=False):
        try:
            p=Path(directory).resolve(strict=True)
            if replies:
                result,path=diagnose(DiagnosticAdb(executable,p),p,lambda s:events.put(('status',s)),stop.is_set,replies_probe=True)
            elif automatic:
                from chat_batch import start as automatic_start
                result,path=automatic_start(DiagnosticAdb(executable,p),p,lambda s:events.put(('status',s)),stop.is_set)
            elif chat_send:
                from chat_send_probe import send_once
                result,path=send_once(DiagnosticAdb(executable,p),p,lambda s:events.put(('status',s)),stop.is_set)
            else:result,path=diagnose(DiagnosticAdb(executable,p),p,lambda s:events.put(('status',s)),stop.is_set,profile_probe=not (chat_runtime or chat_state),batch_probe=batch,chat_runtime_probe=chat_runtime,chat_state_probe=chat_state)
            events.put(('done',(result,path)))
        except Exception as e:
            events.put(('error',str(e) if isinstance(e,TestError) else 'Проверь ADB, test-apks и доступ к папке.'))
    def catalog_worker(directory,chat=False):
        try:
            if chat:from chat_catalog import write_report
            else:from friends_catalog import write_report
            p=Path(directory).resolve(strict=True)
            events.put(('done',write_report(p,stop.is_set)))
        except Exception:events.put(('error','Проверь test-apks и доступ к папке.'))
    def start(mode='profile'):
        nonlocal busy,report
        if busy:return
        busy=True;report=None;stop.clear();state.set('Читаю метаданные APK…' if mode in ('catalog','chat-catalog') else 'Проверка…')
        reply_button.config(state='disabled');telegram_button.config(state='disabled');automatic_button.config(state='disabled');send_button.config(state='disabled');chat_button.config(state='disabled');runtime_button.config(state='disabled');chat_metadata_button.config(state='disabled');batch_button.config(state='disabled');button.config(state='disabled');metadata_button.config(state='disabled');stop_button.config(state='normal');report_button.config(state='disabled')
        if mode=='chat-catalog':threading.Thread(target=catalog_worker,args=(folder.get(),True),daemon=True).start()
        elif mode=='catalog':threading.Thread(target=catalog_worker,args=(folder.get(),),daemon=True).start()
        elif mode=='replies':threading.Thread(target=worker,args=(binary.get(),folder.get(),False,False,False,False,False,True),daemon=True).start()
        elif mode=='automatic':threading.Thread(target=worker,args=(binary.get(),folder.get(),False,False,False,False,True),daemon=True).start()
        elif mode=='chat-send':threading.Thread(target=worker,args=(binary.get(),folder.get(),False,False,False,True),daemon=True).start()
        elif mode=='chat-state':threading.Thread(target=worker,args=(binary.get(),folder.get(),False,False,True),daemon=True).start()
        elif mode=='chat-runtime':threading.Thread(target=worker,args=(binary.get(),folder.get(),False,True),daemon=True).start()
        elif mode=='batch':threading.Thread(target=worker,args=(binary.get(),folder.get(),True),daemon=True).start()
        else:threading.Thread(target=worker,args=(binary.get(),folder.get()),daemon=True).start()
    def request_stop():
        if busy:stop.set();state.set('Остановка и очистка…')
    def open_report():
        if report is None:return
        try:os.startfile(str(report))
        except (AttributeError,OSError):messagebox.showinfo('Отчёт',str(report))
    send_row=ttk.Frame(main);send_row.pack(fill='x',pady=(2,6))
    send_button=ttk.Button(send_row,text='Случайное приветствие — один раз',command=lambda:start('chat-send'));send_button.pack(side='left')
    automatic_button=ttk.Button(send_row,text='Автопроход · до 10 анкет',command=lambda:start('automatic'));automatic_button.pack(side='left',padx=(8,0))
    reply_row=ttk.Frame(main);reply_row.pack(fill='x',pady=(2,6))
    reply_button=ttk.Button(reply_row,text='Подготовить ответы · без отправки',command=lambda:start('replies'));reply_button.pack(side='left')
    def telegram_settings():
        from telegram_notify import settings_window
        settings_window(root)
    telegram_button=ttk.Button(reply_row,text='Telegram',command=telegram_settings);telegram_button.pack(side='left',padx=8)
    diagnostics_row=ttk.Frame(main);diagnostics_row.pack(fill='x',pady=(2,6))
    chat_button=ttk.Button(diagnostics_row,text='Проверить чат',command=lambda:start('chat-state'));chat_button.pack(side='left',padx=(0,8))
    runtime_button=ttk.Button(diagnostics_row,text='Типы чата',command=lambda:start('chat-runtime'));runtime_button.pack(side='left',padx=(0,8))
    chat_metadata_button=ttk.Button(diagnostics_row,text='Метаданные чата',command=lambda:start('chat-catalog'));chat_metadata_button.pack(side='left',padx=(0,8))
    metadata_button=ttk.Button(diagnostics_row,text='Найти счётчик',command=lambda:start('catalog'));metadata_button.pack(side='left',padx=(0,8))
    row=ttk.Frame(main);row.pack(fill='x',pady=(2,6))
    batch_button=ttk.Button(row,text='Проверить 10',command=lambda:start('batch'));batch_button.pack(side='left',padx=(0,8))
    button=ttk.Button(row,text='Проверить профиль',command=start);button.pack(side='left')
    stop_button=ttk.Button(row,text='Стоп',command=request_stop,state='disabled');stop_button.pack(side='left',padx=8)
    report_button=ttk.Button(row,text='Отчёт',command=open_report,state='disabled');report_button.pack(side='left')
    ttk.Label(main,text='JSON-отчёт — рядом с test-apks.',foreground='#666666').pack(anchor='w')
    def poll():
        nonlocal busy,report
        while not events.empty():
            kind,value=events.get_nowait()
            if kind=='status':state.set(value);continue
            busy=False;reply_button.config(state='normal');telegram_button.config(state='normal');automatic_button.config(state='normal');send_button.config(state='normal');chat_button.config(state='normal');runtime_button.config(state='normal');chat_metadata_button.config(state='normal');batch_button.config(state='normal');button.config(state='normal');metadata_button.config(state='normal');stop_button.config(state='disabled')
            if kind=='error':state.set(value)
            else:
                result,report=value;state.set(result_status(result));report_button.config(state='normal')
        root.after(100,poll)
    def close():
        if busy:request_stop()
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    root.update_idletasks()
    needed=main.winfo_reqheight()
    if needed>root.winfo_height():root.geometry('640x'+str(needed));root.minsize(620,needed)
    if self_check:
        root.update();assert root.winfo_viewable() and all(w.winfo_viewable() for w in (reply_button,telegram_button,automatic_button,send_button,chat_button,runtime_button,chat_metadata_button,metadata_button,batch_button,button,stop_button,report_button))
        assert main.winfo_reqheight()<=root.winfo_height(),'Compact controls are clipped'
        assert max(row.winfo_reqwidth(),diagnostics_row.winfo_reqwidth(),send_row.winfo_reqwidth(),reply_row.winfo_reqwidth())+28<=root.winfo_width(),'Compact buttons are clipped'
        import frida
        from profile_batch import FUNCTION
        import friends_catalog,chat_catalog,chat_runtime_metadata,chat_state_probe,chat_send_probe,chat_batch,conversation_engine,telegram_notify,reply_metadata,sqlite3
        assert chat_state_probe.VERSION=='0.3.25'
        assert chat_runtime_metadata.VERSION=='0.3.25'
        assert chat_catalog.VERSION=='0.3.25'
        assert friends_catalog.VERSION=='0.3.25'
        assert frida.__version__=='17.24.1' and 'OnUserSelected' in FUNCTION
        root.destroy();return
    root.after(100,poll);root.mainloop()

if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'])
