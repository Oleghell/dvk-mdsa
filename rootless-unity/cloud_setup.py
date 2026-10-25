"""Explicit Windows cutover; never performs an automatic background migration."""
import json,hashlib,sqlite3,uuid
from pathlib import Path
from contextlib import ExitStack,closing
from cloud_database import validate,save,raw_connect,SCHEMA,PROTOCOL,CloudDatabaseError,settings_path,check_selection
from cloud_sql import ident
from cloud_migration import import_source

def install(config_path):
    from mumu_common import root_directory,device_directory,load_ports,DEFAULT_PORTS
    from assistant_lock import operation_lock
    from telegram_notify import protect
    config_path=Path(config_path)
    if config_path.stat().st_size>16384:raise CloudDatabaseError('cloud-database-config-invalid')
    cfg=validate(json.loads(config_path.read_text(encoding='utf-8')))
    check_selection(cfg)
    # Check DPAPI before changing remote state. No plaintext fallback.
    protect(b'database-setup-check')
    root=root_directory();ports=set(load_ports())|set(DEFAULT_PORTS)
    devices=root/'devices'
    if devices.exists():
        for item in devices.iterdir():
            if item.is_dir() and item.name.isdigit():ports.add(int(item.name))
    with ExitStack() as stack:
        stack.enter_context(operation_lock(root/'database-cutover.lock'))
        for n in sorted(ports):
            for name in ('worker.lock','device.lock'):
                stack.enter_context(operation_lock(device_directory(n)/name))
        with raw_connect(cfg) as raw:
            raw.execute('SET search_path TO '+ident(SCHEMA)+',pg_catalog')
            meta=raw.execute('SELECT protocol,dataset,ready FROM _dvk_meta WHERE singleton=1').fetchone()
            if not meta or meta[:2]!=(PROTOCOL,cfg['dataset']):raise CloudDatabaseError('cloud-dataset-mismatch')
            if settings_path().exists():
                from cloud_database import load
                current=load()
                if (current['host'],current['dataset'])!=(cfg['host'],cfg['dataset']):raise CloudDatabaseError('cloud-dataset-mismatch')
            if meta[2] is not True:
                local=root/'assistant.sqlite3'
                if not local.is_file():raise CloudDatabaseError('cloud-latest-local-database-required')
                # Keep the local journal + WAL unchanged, and retain a verified
                # consistent backup before changing remote state.
                backup=root/('assistant-pre-supabase-'+uuid.uuid4().hex+'.sqlite3')
                guard=stack.enter_context(closing(sqlite3.connect(local.resolve().as_uri()+'?mode=rw',uri=True,timeout=5,isolation_level=None)))
                guard.execute('BEGIN IMMEDIATE')
                # A separate reader may back up while the guard excludes writers.
                with closing(sqlite3.connect(local.resolve().as_uri()+'?mode=ro',uri=True)) as reader,closing(sqlite3.connect(backup)) as dest:
                    reader.backup(dest)
                cfg['source_sha256']=hashlib.sha256(backup.read_bytes()).hexdigest()
                # Persist fail-closed cloud selection BEFORE remote activation.
                # A disk/DPAPI failure after COMMIT must not restart old SQLite.
                save(cfg)
                manifest=import_source(raw,cfg,backup,activate=True)
            else:manifest=None # Existing live cloud data must NEVER be replaced.
            save(cfg)
    return manifest

def launch(parent=None):
    import tkinter as tk
    from tkinter import filedialog,messagebox,ttk
    import threading,queue
    window=tk.Toplevel(parent) if parent else tk.Tk()
    window.title('Supabase — переключение базы');window.geometry('560x230')
    box=ttk.Frame(window,padding=15);box.pack(fill='both',expand=True)
    ttk.Label(box,text='Полная облачная база Supabase',font=('Segoe UI',12,'bold')).pack(anchor='w')
    ttk.Label(box,text='Останови все MuMu и закрой другие копии DvkAssistant.\nНа первом подключении переносится свежая локальная база.\nСтарая база остаётся резервной копией, не второй рабочей базой.\nНе используй старые версии после переключения.',wraplength=525).pack(anchor='w',pady=12)
    text=tk.StringVar(value='Выбери личный JSON-файл подключения. Не публикуй его.')
    ttk.Label(box,textvariable=text,wraplength=525).pack(anchor='w')
    events=queue.Queue();busy=[False]
    def start():
        path=filedialog.askopenfilename(parent=window,title='Личный файл подключения Supabase',filetypes=[('JSON','*.json')])
        if not path:return
        if not messagebox.askyesno('Подтверждение','Все MuMu остановлены? Подключить Supabase как основную базу?',parent=window):return
        busy[0]=True;button.configure(state='disabled');text.set('Проверка и перенос… Не закрывай это окно.')
        def work():
            try:
                manifest=install(path);events.put(('ok',manifest))
            except Exception as e:
                from assistant_store import StateError
                value=str(e) if isinstance(e,(CloudDatabaseError,StateError)) else 'cloud-setup-failed'
                events.put(('error',value))
        threading.Thread(target=work,daemon=False).start()
    def poll():
        try:
            kind,value=events.get_nowait();busy[0]=False;button.configure(state='normal')
            if kind=='ok':
                text.set('Supabase подключён. Перезапусти DvkAssistant. Удали скачанный JSON после сохранения.');messagebox.showinfo('Готово','Облачная база включена. Перезапусти программу.\nПри недоступности облака операции остановятся, без перехода на старую SQLite.',parent=window)
            else:text.set('Подключение не завершено: '+value)
        except queue.Empty:pass
        window.after(150,poll)
    button=ttk.Button(box,text='Выбрать файл и подключить',command=start);button.pack(anchor='w',pady=8)
    window.protocol('WM_DELETE_WINDOW',lambda:None if busy[0] else window.destroy())
    poll()
    if parent is None:window.mainloop()
