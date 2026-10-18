"""Consent UI for metadata-only preflight on the existing MuMu #4, no actions."""
import sys,threading,queue
from pathlib import Path
from diagnose_device import DiagnosticAdb,diagnose,find_adb,TestError


def launch_gui(self_check=False):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title('ДругВокруг — проверка метаданных без нажатий, 0.3.1')
    root.geometry('960x670');root.minsize(900,630)
    main=ttk.Frame(root,padding=18);main.pack(fill='both',expand=True)
    ttk.Label(main,text='Только метаданные — MuMu #4 (5563), без нажатий',font=('Segoe UI',12,'bold')).pack(anchor='w')
    ttk.Label(main,text='Запустите оба MuMu. На тестовом #4 оставьте ДругВокруг открытым.\n'
        'Эта версия выясняет, на какой проверке классов/методов остановилась 0.3.0.\n'
        'Она НЕ открывает анкеты, НЕ устанавливает UI-наблюдатель и НЕ вызывает обработчики UI.\n\n'
        'Нет OCR, снимков экрана, координат, root и переустановки APK.\n'
        'Тексты, ID, переписки, токены, адреса памяти и пути в отчёт не записываются.\n'
        'Рабочий #0 / 5555 не изменяется. Старая 0.2.3 остаётся контрольной версией.\n'
        'Возможно замедление или сбой тестового приложения.',wraplength=880).pack(anchor='w',pady=12)
    base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    binary=tk.StringVar(value=find_adb());folder=tk.StringVar(value=str(base/'test-apks'))
    for label,var,picker in (
        ('ADB из MuMu / platform-tools:',binary,lambda:filedialog.askopenfilename(filetypes=[('ADB','*.exe')])),
        ('Старая папка test-apks (та же, что для успешного 0.1.8):',folder,lambda:filedialog.askdirectory())):
        ttk.Label(main,text=label).pack(anchor='w');row=ttk.Frame(main);row.pack(fill='x',pady=(2,10))
        ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
        def choose(v=var,pick=picker):
            p=pick()
            if p:v.set(p)
        ttk.Button(row,text='Выбрать…',command=choose).pack(side='right',padx=8)
    consent=tk.BooleanVar(value=False)
    ttk.Checkbutton(main,text='Разрешаю проверить только метаданные на #4 (5563), без UI-действий.',variable=consent).pack(anchor='w',pady=8)
    state=tk.StringVar(value='0.3.0 остановилась до нажатий. Эта проверка покажет точный этап, без попытки открыть профиль.')
    ttk.Label(main,textvariable=state,wraplength=880).pack(anchor='w',pady=8)
    events=queue.Queue();stop=threading.Event();busy=False
    def worker(executable,directory):
        try:
            p=Path(directory).resolve(strict=True)
            result,path=diagnose(DiagnosticAdb(executable,p),p,lambda s:events.put(('status',s)),stop.is_set,profile_metadata_probe=True)
            events.put(('done',(result,path)))
        except Exception as e:
            events.put(('error',str(e) if isinstance(e,TestError) else 'Проверьте ADB, старую test-apks и право записи отчёта.'))
    def start():
        nonlocal busy
        if busy:return
        if not consent.get():messagebox.showinfo('Подтверждение','Сначала отметьте разрешение теста на #4.');return
        busy=True;stop.clear();button.config(state='disabled')
        threading.Thread(target=worker,args=(binary.get(),folder.get()),daemon=True).start()
    row=ttk.Frame(main);row.pack(fill='x',pady=10)
    button=ttk.Button(row,text='Проверить метаданные — без нажатий',command=start);button.pack(side='left')
    ttk.Button(row,text='Остановить тест',command=stop.set).pack(side='left',padx=12)
    ttk.Label(main,text='Отчёт: rootless-profile-metadata-0.3.1.json рядом со старой папкой test-apks.\n'
        'Открытия и закрытия окон в этой версии отключены; установленный APK не меняется.\n'
        'Токены, PID, адреса памяти, полные пути, тексты и изображения в отчёт не записываются.',wraplength=880).pack(anchor='w',pady=8)
    def poll():
        nonlocal busy
        while not events.empty():
            kind,value=events.get_nowait()
            if kind=='status':state.set(value);continue
            busy=False;button.config(state='normal');consent.set(False)
            if kind=='error':state.set(value);messagebox.showerror('Тест остановлен',value)
            else:
                result,path=value;ok=result['status']=='profile-metadata-ready'
                state.set('Метаданные проверены. Открытие профиля не проверялось.' if ok else 'Тест остановлен: '+result['status'])
                messagebox.showinfo('Отчёт готов',('Метаданные готовы. Это не проверка открытия профиля.' if ok else 'Проверка остановлена; точный этап записан в отчёт.')+'\nПрикрепите в чат:\n'+str(path)+
                    ('\nПрофиль мог остаться открытым — вернитесь в поиск вручную.' if result.get('profile_may_remain_open') else ''))
        root.after(100,poll)
    def close():
        if busy:stop.set();messagebox.showinfo('Остановка','Дождитесь завершения текущего вызова и очистки подключения. UI-действий нет.')
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    if self_check:
        root.update();assert root.winfo_viewable() and button.winfo_viewable()
        import frida
        from profile_metadata import FUNCTION
        assert frida.__version__=='17.24.1' and 'profile_metadata' in FUNCTION and 'Interceptor' not in FUNCTION and 'f.invoke(' not in FUNCTION
        root.destroy();return
    root.after(100,poll);root.mainloop()

if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'])
