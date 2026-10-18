"""Consent UI for one visible-profile navigation test on the already installed MuMu #4."""
import sys,threading,queue
from pathlib import Path
from diagnose_device import DiagnosticAdb,diagnose,find_adb,TestError


def launch_gui(self_check=False):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title('ДругВокруг — одна анкета → профиль → назад, 0.3.0')
    root.geometry('960x670');root.minsize(900,630)
    main=ttk.Frame(root,padding=18);main.pack(fill='both',expand=True)
    ttk.Label(main,text='Одна анкета, без сообщений — только MuMu #4 (5563)',font=('Segoe UI',12,'bold')).pack(anchor='w')
    ttk.Label(main,text='1. Запустите оба MuMu. На #4 откройте поиск людей (сетку анкет), закройте диалоги и фильтры.\n'
        '2. Этот тест проверит экран, откроет одну видимую обычную анкету и вернётся к тому же поиску.\n'
        'Не трогайте интерфейс #4 во время теста. При неизвестном экране тест остановится без кликов.\n\n'
        'Нет OCR, скриншотов, координат и root. Используются UIKit-контроллеры Unity и их UI-обработчики,\n'
        'а не Android Accessibility. Тексты и ID не читаются/не сохраняются. Нет сообщений, лайков и покупок.\n'
        'Посещение профиля может отобразиться в гостях — это обычный эффект открытия анкеты.\n'
        'APK не переустанавливается. Рабочий #0 (5555) не изменяется. Возможен сбой тестового приложения.',wraplength=880).pack(anchor='w',pady=12)
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
    ttk.Checkbutton(main,text='Разрешаю посетить одну анкету на #4 и вернуться; визит может быть виден в гостях. Без сообщений.',variable=consent).pack(anchor='w',pady=8)
    state=tk.StringVar(value='Фильтры уже проверены в 0.2.3. Теперь отдельно проверяем профиль; живой результат ещё не подтверждён.')
    ttk.Label(main,textvariable=state,wraplength=880).pack(anchor='w',pady=8)
    events=queue.Queue();stop=threading.Event();busy=False
    def worker(executable,directory):
        try:
            p=Path(directory).resolve(strict=True)
            result,path=diagnose(DiagnosticAdb(executable,p),p,lambda s:events.put(('status',s)),stop.is_set,profile_probe=True)
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
    button=ttk.Button(row,text='Открыть одну анкету → закрыть → проверить возврат',command=start);button.pack(side='left')
    ttk.Button(row,text='Остановить тест',command=stop.set).pack(side='left',padx=12)
    ttk.Label(main,text='Отчёт: rootless-profile-navigation-0.3.0.json рядом со старой папкой test-apks.\n'
        'При остановке профиль может остаться открытым. Вернитесь в поиск вручную, не запускайте повтор вслепую.\n'
        'Токены, PID, адреса памяти, полные пути, тексты и изображения в отчёт не записываются.',wraplength=880).pack(anchor='w',pady=8)
    def poll():
        nonlocal busy
        while not events.empty():
            kind,value=events.get_nowait()
            if kind=='status':state.set(value);continue
            busy=False;button.config(state='normal');consent.set(False)
            if kind=='error':state.set(value);messagebox.showerror('Тест остановлен',value)
            else:
                result,path=value;ok=result['status']=='navigation-ready'
                state.set('Возврат в поиск подтверждён.' if ok else 'Тест остановлен: '+result['status'])
                messagebox.showinfo('Отчёт готов',('Сценарий выполнен.' if ok else 'Успех не подтверждён. Не запускайте повторно вслепую.')+'\nПрикрепите в чат:\n'+str(path)+
                    ('\nПрофиль мог остаться открытым — вернитесь в поиск вручную.' if result.get('profile_may_remain_open') else ''))
        root.after(100,poll)
    def close():
        if busy:stop.set();messagebox.showinfo('Остановка','Дождитесь завершения текущего вызова и очистки подключения. Профиль может остаться открытым.')
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    if self_check:
        root.update();assert root.winfo_viewable() and button.winfo_viewable()
        import frida
        from uikit_profile_navigation import FUNCTION
        assert frida.__version__=='17.24.1' and 'OnUserSelected' in FUNCTION
        root.destroy();return
    root.after(100,poll);root.mainloop()

if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'])
