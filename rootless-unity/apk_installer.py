"""Standalone APK installer. No accounts, cloud DB, root or uninstall."""
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
VERSION = '1.0.0'


def parse_ports(text):
    if not isinstance(text,str) or len(text)>16384:raise ValueError('Список портов слишком большой.')
    ports=[]
    for word in re.split(r'[\s,;]+',text.strip()):
        if not word:continue
        word=word.removeprefix('127.0.0.1:')
        if not re.fullmatch(r'[1-9][0-9]{3,4}',word):raise ValueError('Пример портов: 5557, 5559, 5567.')
        p=int(word)
        if not 1024<=p<=65535 or p in (5037,27042):raise ValueError(f'Недопустимый порт: {p}.')
        if p not in ports:ports.append(p)
    if not ports or len(ports)>128:raise ValueError('Нужно от 1 до 128 разных портов.')
    return tuple(ports)


def make_plan(adb,folder,ports):
    exe=Path(adb).expanduser().resolve(strict=True);folder=Path(folder).expanduser().resolve(strict=True)
    if not exe.is_file() or exe.name.lower()!='adb.exe':raise ValueError('Выбери файл adb.exe из platform-tools.')
    if not folder.is_dir():raise ValueError('Выбери папку с APK.')
    files=(folder/'base.apk',*sorted(folder.glob('split-*.apk')))
    if len(files)<2 or len(files)>128 or any(not p.is_file() for p in files):
        raise ValueError('В папке нужны base.apk и split-*.apk, например split-001.apk.')
    return exe,files,parse_ports(ports)


def execute(args,timeout):
    return subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',
                          timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def install(plan,stopped,emit,*,command=execute):
    adb,files,ports=plan;results=[]
    for port in ports:
        if stopped.is_set():break
        serial=f'127.0.0.1:{port}';phase='connect';emit(f'\n=== {serial} ===')
        try:
            value=command([str(adb),'connect',serial],20)
            if value.stdout.strip():emit(value.stdout.strip())
            if stopped.is_set():break
            phase='state';value=command([str(adb),'-s',serial,'get-state'],20)
            if value.returncode!=0 or value.stdout.strip()!='device':
                results.append((port,'unavailable'));emit('Порт недоступен — пропущен. '+(value.stderr or value.stdout).strip());continue
            if stopped.is_set():break
            phase='install';emit('Устанавливаю APK. Дождись завершения текущего порта…')
            value=command([str(adb),'-s',serial,'install-multiple','-r',*map(str,files)],240)
            output='\n'.join(x.strip() for x in (value.stdout,value.stderr) if x.strip())
            if output:emit(output)
            ok=value.returncode==0 and any(x.strip()=='Success' for x in value.stdout.splitlines())
            results.append((port,'installed' if ok else 'failed'))
            emit('Установлено ✅' if ok else 'Установка не подтверждена ❌ — см. вывод выше.')
        except subprocess.TimeoutExpired:
            results.append((port,'unknown' if phase=='install' else 'unavailable'))
            emit('Время ожидания истекло. '+('Результат установки неизвестен; повтора нет.' if phase=='install' else 'Установка не запускалась.'))
        except OSError:
            results.append((port,'failed'));emit('Не удалось запустить ADB. Проверь путь и доступ к файлу.')
    return results


def main():
    if sys.argv[1:]==['--self-check']:
        assert parse_ports('5557\n127.0.0.1:5567,5557')==(5557,5567);return 0
    if sys.argv[1:]==['--version']:print(VERSION);return 0
    gui_check=sys.argv[1:]==['--gui-self-check']
    if sys.argv[1:] and not gui_check:return 2
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    from tkinter.scrolledtext import ScrolledText
    root=tk.Tk();root.title('Dvk APK Installer '+VERSION);root.geometry('780x650');root.minsize(650,520)
    root.columnconfigure(0,weight=1);root.rowconfigure(0,weight=1)
    f=ttk.Frame(root,padding=16);f.grid(sticky='nsew');f.columnconfigure(1,weight=1);f.rowconfigure(7,weight=1)
    ttk.Label(f,text='Установка APK на несколько MuMu',font=('Segoe UI',15,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,14))
    home=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    adb=tk.StringVar(value=str(home/'platform-tools'/'adb.exe') if (home/'platform-tools'/'adb.exe').is_file() else '')
    apks=tk.StringVar(value=str(home/'test-apks') if (home/'test-apks').is_dir() else '')
    inputs=[]
    def choose_adb():
        value=filedialog.askopenfilename(title='Выбери adb.exe',filetypes=[('ADB','adb.exe'),('Программы','*.exe')])
        if value:adb.set(value)
    def choose_apks():
        value=filedialog.askdirectory(title='Папка с base.apk и split-*.apk')
        if value:apks.set(value)
    for row,label,var,callback in [(1,'Файл adb.exe:',adb,choose_adb),(2,'Папка с APK:',apks,choose_apks)]:
        ttk.Label(f,text=label).grid(row=row,column=0,sticky='w',padx=(0,10))
        entry=ttk.Entry(f,textvariable=var);entry.grid(row=row,column=1,sticky='ew',pady=5);inputs.append(entry)
        button=ttk.Button(f,text='Выбрать…',command=callback);button.grid(row=row,column=2,padx=(8,0));inputs.append(button)
    ttk.Label(f,text='Порты — по одному на строку, через пробел или запятую:').grid(row=3,column=0,columnspan=3,sticky='w',pady=(12,4))
    ports=tk.Text(f,height=5,font=('Consolas',11));ports.grid(row=4,column=0,columnspan=3,sticky='ew');inputs.append(ports)
    ttk.Label(f,text='Укажи только свои порты. MuMu должен быть запущен. Установка по очереди, с ключом -r.').grid(row=5,column=0,columnspan=3,sticky='w',pady=(5,10))
    bar=ttk.Frame(f);bar.grid(row=6,column=0,columnspan=3,sticky='ew',pady=(0,10))
    status=tk.StringVar(value='Выбери файлы, вставь порты и нажми «Установить».')
    log=ScrolledText(f,height=12,state='disabled',wrap='word',font=('Consolas',10));log.grid(row=7,column=0,columnspan=3,sticky='nsew')
    ttk.Label(f,textvariable=status,wraplength=730).grid(row=8,column=0,columnspan=3,sticky='w',pady=(8,0))
    messages=queue.Queue();stopped=threading.Event();busy=False
    def worker(plan):
        try:result=install(plan,stopped,lambda text:messages.put(('line',text)))
        except Exception:messages.put(('line','Ошибка установщика. Автоматического повтора нет.'));result=[]
        messages.put(('done',result))
    def start():
        nonlocal busy
        if busy:return
        try:plan=make_plan(adb.get().strip().strip('"'),apks.get().strip().strip('"'),ports.get('1.0','end'))
        except (ValueError,OSError) as error:messagebox.showerror('Проверь настройки',str(error),parent=root);return
        stopped.clear();busy=True
        for control in inputs:control.configure(state='disabled')
        start_button.configure(state='disabled');stop_button.configure(state='normal')
        status.set('Идёт установка. Результат каждого порта появится в журнале.')
        messages.put(('line',f'Начало: {len(plan[2])} портов, {len(plan[1])} APK. Приложение автоматически не запускается.'))
        threading.Thread(target=worker,args=(plan,),daemon=True).start()
    def stop():
        stopped.set();status.set('Остановка после текущей операции. Уже начатая установка не прерывается.');stop_button.configure(state='disabled')
    start_button=ttk.Button(bar,text='Установить',command=start);start_button.pack(side='left')
    stop_button=ttk.Button(bar,text='Стоп после текущего порта',command=stop,state='disabled');stop_button.pack(side='left',padx=8)
    def drain():
        nonlocal busy
        try:
            while True:
                kind,value=messages.get_nowait()
                if kind=='line':
                    log.configure(state='normal');log.insert('end',value+'\n');log.see('end');log.configure(state='disabled')
                else:
                    busy=False
                    for control in inputs:control.configure(state='normal')
                    start_button.configure(state='normal');stop_button.configure(state='disabled')
                    good=sum(s=='installed' for _,s in value)
                    status.set(f'{"Остановлено" if stopped.is_set() else "Готово"}: установлено {good}; других результатов {len(value)-good}. См. журнал.')
        except queue.Empty:pass
        root.after(100,drain)
    def close():
        if busy:
            stop();messagebox.showinfo('Дождись текущей операции','Запрошена остановка. Закрой окно после завершения текущей операции ADB.',parent=root)
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);root.after(100,drain)
    if gui_check:root.after(300,root.destroy)
    root.mainloop();return 0

if __name__=='__main__':raise SystemExit(main())
