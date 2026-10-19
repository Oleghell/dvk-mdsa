"""Compact button-start UI for one profile/return on the existing MuMu #4."""
import os,sys,threading,queue
from pathlib import Path
from diagnose_device import DiagnosticAdb,diagnose,TestError


DEFAULT_ADB='C:/Users/XXX/Desktop/platform-tools/adb.exe'

def result_status(result):
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
    root=tk.Tk();root.title('ДругВокруг · 0.3.12')
    root.geometry('640x300');root.minsize(620,300)
    main=ttk.Frame(root,padding=14);main.pack(fill='both',expand=True)
    ttk.Label(main,text='MuMu #4 · профиль и друзья',font=('Segoe UI',11,'bold')).pack(anchor='w')
    ttk.Label(main,text='До 10 видимых анкет из поиска #4. Без сообщений и прокрутки.').pack(anchor='w',pady=(4,10))
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
    state=tk.StringVar(value='Визиты видны в гостях. Без повторов в одном запуске. Паузы — 1 с.')
    ttk.Label(main,textvariable=state,wraplength=590).pack(anchor='w',pady=(4,6))
    events=queue.Queue();stop=threading.Event();busy=False;report=None
    def worker(executable,directory,batch=False):
        try:
            p=Path(directory).resolve(strict=True)
            result,path=diagnose(DiagnosticAdb(executable,p),p,lambda s:events.put(('status',s)),stop.is_set,profile_probe=True,batch_probe=batch)
            events.put(('done',(result,path)))
        except Exception as e:
            events.put(('error',str(e) if isinstance(e,TestError) else 'Проверь ADB, test-apks и доступ к папке.'))
    def catalog_worker(directory):
        try:
            from friends_catalog import write_report
            p=Path(directory).resolve(strict=True)
            events.put(('done',write_report(p,stop.is_set)))
        except Exception:events.put(('error','Проверь test-apks и доступ к папке.'))
    def start(mode='profile'):
        nonlocal busy,report
        if busy:return
        busy=True;report=None;stop.clear();state.set('Читаю метаданные APK…' if mode=='catalog' else 'Проверка…')
        batch_button.config(state='disabled');button.config(state='disabled');metadata_button.config(state='disabled');stop_button.config(state='normal');report_button.config(state='disabled')
        if mode=='catalog':threading.Thread(target=catalog_worker,args=(folder.get(),),daemon=True).start()
        elif mode=='batch':threading.Thread(target=worker,args=(binary.get(),folder.get(),True),daemon=True).start()
        else:threading.Thread(target=worker,args=(binary.get(),folder.get()),daemon=True).start()
    def request_stop():
        if busy:stop.set();state.set('Остановка и очистка…')
    def open_report():
        if report is None:return
        try:os.startfile(str(report))
        except (AttributeError,OSError):messagebox.showinfo('Отчёт',str(report))
    row=ttk.Frame(main);row.pack(fill='x',pady=(2,6))
    metadata_button=ttk.Button(row,text='Найти счётчик',command=lambda:start('catalog'));metadata_button.pack(side='left',padx=(0,8))
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
            busy=False;batch_button.config(state='normal');button.config(state='normal');metadata_button.config(state='normal');stop_button.config(state='disabled')
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
        root.update();assert root.winfo_viewable() and all(w.winfo_viewable() for w in (metadata_button,batch_button,button,stop_button,report_button))
        assert main.winfo_reqheight()<=root.winfo_height(),'Compact controls are clipped'
        assert row.winfo_reqwidth()+28<=root.winfo_width(),'Compact buttons are clipped'
        import frida
        from profile_batch import FUNCTION
        import friends_catalog
        assert friends_catalog.VERSION=='0.3.12'
        assert frida.__version__=='17.24.1' and 'OnUserSelected' in FUNCTION
        root.destroy();return
    root.after(100,poll);root.mainloop()

if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'])
