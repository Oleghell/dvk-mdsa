"""Explicit installer window. Opening it does not access credentials or devices."""
import os
os.environ['DVK_MORELOGIN']='1'
os.environ.pop('DVK_MORELOGIN_PHONE_ID',None)
import json
from pathlib import Path
import queue
import sys
import threading
from morelogin_common import root_directory,phone_directory,phone_id
from morelogin_version import VERSION
from morelogin_install import run,InstallError

MESSAGES={
 'installed':'APK установлены без удаления приложения. Открой ДругВокруг вручную; проверь вход.',
 'installed-after-replacement':'Приложение заменено. Открой ДругВокруг и войди в аккаунт заново.',
 'declined':'Отменено пользователем. Следующие операции не выполнялись.',
 'cancelled':'Остановлено. Уже выполненные действия не отменяются; проверь состояние телефона.',
 'bundle-required':'Выбери папку test-apks с проверенными base.apk и split-001.apk.',
 'device-busy':'Телефон занят циклом или другим установщиком. Сначала нажми Стоп в DvkAssistant.',
 'wrong-abi':'Нужен телефон с основной архитектурой arm64-v8a. Ничего не устанавливается.',
 'wrong-android':'Эта версия установщика разрешена только для Android 14/15 (SDK 34/35).',
 'identity-changed':'Идентичность телефона изменилась. Операция остановлена.',
 'device-not-ready':'Android ещё не загружен или ADB не готов.',
 'operation-uncertain':'Результат операции неизвестен. Автоповтора нет. Проверь телефон и last-install.json.',
 'backup-failed':'Не удалось сохранить исходные APK. Удаление запрещено; нужно 4 ГБ свободного места.',
 'configuration':'Проверь сохранённые ключи, SSH-проверку телефона, путь ADB и папку test-apks.',
 'adb-failed':'Android/ADB отклонил операцию. См. код ошибки в last-install.json.',
 'delete-failed':'Не удалось подтвердить удаление. Повтор не выполнялся.',
 'not-installed':'Не удалось подтвердить наличие установленного приложения.',
 'ssh-key-changed':'Ключ SSH изменился. Замена запрещена; сначала проверь подключение в DvkAssistant.',
 'ssh-unavailable':'Не удалось подключиться к SSH. Замена не начинается.',
}

def launch(self_check=False):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox,simpledialog
    root=tk.Tk();root.title('DvkAssistant '+VERSION+' · Установка Gadget');root.geometry('780x520')
    box=ttk.Frame(root,padding=18);box.pack(fill='both',expand=True)
    ttk.Label(box,text='Установка Gadget · один Cloud Phone',font=('Segoe UI',16,'bold')).pack(anchor='w')
    ttk.Label(box,text='Только проверенный комплект ARM64. Совместимость Gadget с Android 15A ещё не подтверждена.\nЗамена магазинной версии может удалить аккаунт, переписку и настройки с телефона.\nКопия APK НЕ сохраняет данные аккаунта. Удаление — только после отдельного ввода ID.',wraplength=730).pack(anchor='w',pady=12)
    cloud=tk.StringVar();adb=tk.StringVar();folder=tk.StringVar();status=tk.StringVar(value='Готово. Никаких действий до нажатия кнопки.')
    values=[]
    if not self_check:
        try:
            data=json.loads((root_directory()/'phones.json').read_text(encoding='utf-8'));values=[phone_id(x) for x in data['ids']]
            if len(values)==1:cloud.set(values[0])
        except Exception:pass
        try:
            from assistant_settings import load
            s=load(directory=root_directory());adb.set(s.adb);folder.set(s.folder)
        except Exception:pass
    ttk.Label(box,text='Cloud Phone ID (только один)').pack(anchor='w')
    choice=ttk.Combobox(box,textvariable=cloud,values=values);choice.pack(fill='x',pady=(0,8))
    controls=[]
    def path_row(title,var,is_folder):
        ttk.Label(box,text=title).pack(anchor='w');row=ttk.Frame(box);row.pack(fill='x',pady=(0,8))
        entry=ttk.Entry(row,textvariable=var);entry.pack(side='left',fill='x',expand=True)
        def browse():
            p=filedialog.askdirectory(parent=root) if is_folder else filedialog.askopenfilename(parent=root,filetypes=[('ADB','*.exe'),('All','*')])
            if p:var.set(p)
        button=ttk.Button(row,text='Выбрать',command=browse);button.pack(side='right',padx=(8,0));controls.extend([entry,button])
    path_row('Путь к adb.exe',adb,False);path_row('Папка test-apks (оба APK внутри)',folder,True)
    ttk.Label(box,textvariable=status,wraplength=730).pack(anchor='w',pady=12)
    events=queue.Queue();stopped=threading.Event();busy=False;pending=[]
    def ask(kind,*args):
        reply=queue.Queue(maxsize=1);events.put(('ask',(kind,args,reply)))
        while not stopped.is_set():
            try:return reply.get(timeout=.2)
            except queue.Empty:pass
        return False
    def finish():
        nonlocal busy
        busy=False
        for widget in controls+[choice,begin]:widget.configure(state='normal')
        cancel.configure(state='disabled')
    def start():
        nonlocal busy
        if busy:return
        try:identifier=phone_id(cloud.get().strip())
        except Exception:status.set('Укажи один числовой Cloud Phone ID.');return
        executable=adb.get();source=folder.get()
        if not executable or not source:status.set('Выбери adb.exe и папку test-apks.');return
        busy=True;stopped.clear()
        for widget in controls+[choice,begin]:widget.configure(state='disabled')
        cancel.configure(state='normal');status.set('Проверяю комплект и подключение. На телефоне пока ничего не меняется.')
        def work():
            try:
                result=run(identifier,executable,source,stopped,
                    lambda *args:ask('install',*args),lambda *args:ask('delete',*args),
                    lambda text:events.put(('status',text)))
                events.put(('done',result))
            except Exception as error:
                events.put(('done',getattr(error,'code','configuration')))
        threading.Thread(target=work,daemon=True).start()
    def stop():
        stopped.set();status.set('Останавливаю после текущей операции. Уже выполненные действия не откатываются.')
    row=ttk.Frame(box);row.pack(fill='x')
    begin=ttk.Button(row,text='Проверить и установить Gadget',command=start);begin.pack(side='left')
    cancel=ttk.Button(row,text='Стоп',command=stop,state='disabled');cancel.pack(side='left',padx=8)
    def show_report():
        try:os.startfile(str(phone_directory(phone_id(cloud.get().strip()))))
        except Exception:status.set('Отчёт: %LOCALAPPDATA%\\DvkAssistantMoreLogin\\phones\\<ID>\\last-install.json')
    ttk.Button(row,text='Открыть папку отчёта',command=show_report).pack(side='right')
    def poll():
        while not events.empty():
            kind,value=events.get_nowait()
            if kind=='status':status.set(value)
            elif kind=='done':status.set(MESSAGES.get(value,'Операция остановлена ('+value+'). См. last-install.json.'));finish()
            elif kind=='ask':
                action,args,reply=value
                if stopped.is_set():reply.put(False);continue
                if action=='install':
                    identifier,sdk,exists=args
                    text=('Cloud Phone ID: '+identifier+'\nAndroid SDK: '+sdk+' · ARM64\n\nБудут установлены два APK с Gadget.\n'+
                        ('Сначала попробую обновление без удаления. При несовпадении подписи запрошу отдельное подтверждение замены.\n' if exists else 'Приложение drug.vokrug сейчас отсутствует.\n')+
                        '\nРабота Gadget на этом телефоне ещё не проверена. Начать установку?')
                    reply.put(messagebox.askyesno('Подтверждение установки',text,parent=root,default=messagebox.NO))
                else:
                    identifier=args[0]
                    text=('Телефон '+identifier+'\nПодпись магазинного приложения не совпадает с тестовой.\n\nДля замены нужно УДАЛИТЬ drug.vokrug. Данные приложения, вход и локальная переписка могут быть потеряны. Будет сохранена только копия APK, НЕ данные аккаунта. Новая установка может завершиться ошибкой.\n\nЕсли готов повторно войти, введи Cloud Phone ID '+identifier+'. Отмена сохранит старое приложение.')
                    reply.put(simpledialog.askstring('Удаление приложения — необратимое действие',text,parent=root))
        root.after(100,poll)
    def close():
        if busy:stop()
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    if self_check:
        root.update();assert root.winfo_viewable() and begin.winfo_viewable() and not busy and events.empty()
        assert not stopped.is_set() and str(cancel.cget('state'))=='disabled'
        root.destroy();return
    root.after(100,poll);root.mainloop()

if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch(self_check=sys.argv[1:]==['--self-check'])
