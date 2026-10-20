"""Compact owned-chat UI; opt-in serial reads, never automatic sending."""
import json
from pathlib import Path
import queue
import sys
import threading
from datetime import datetime

from one_chat_device import capture, ReadStopped
from one_chat_preview import TEST_TEXT, QUESTION
from one_chat_session import report as session_report
from one_chat_probe import VERSION, ERRORS
from one_chat_store import TestChatStore
from one_chat_actions import Actions
from one_chat_send_device import submit
from one_chat_monitor import ReadLoop
import one_chat_local as local

DEFAULT_ADB='C:/Users/XXX/Desktop/platform-tools/adb.exe'


def launch_gui(self_check=False):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title('ДругВокруг · тестовый чат '+VERSION)
    root.geometry('680x530');root.minsize(660,530);root.configure(background='#F9F8F7')
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',font=('Segoe UI',11),background='#F9F8F7',foreground='#2C2C2B')
    style.configure('TButton',padding=(12,10))
    style.configure('Primary.TButton',background='#236DB4',foreground='white')
    style.map('Primary.TButton',background=[('disabled','#E6E5E3'),('active','#19568F')],foreground=[('disabled','#686661')])
    style.configure('Title.TLabel',font=('Segoe UI',20,'bold'))
    style.configure('Muted.TLabel',foreground='#686661')
    style.configure('Card.TFrame',background='white')
    style.configure('Card.TLabel',background='white')
    style.configure('Status.TLabel',font=('Segoe UI',13,'bold'),background='white')
    main=ttk.Frame(root,padding=24);main.pack(fill='both',expand=True)
    header=ttk.Frame(main);header.pack(fill='x')
    ttk.Label(header,text='Тестовый чат',style='Title.TLabel').pack(side='left')
    base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    adb=tk.StringVar(value=DEFAULT_ADB);folder=tk.StringVar(value=str(base/'test-apks'))
    consent=tk.BooleanVar(value=False);saving=tk.BooleanVar(value=False)
    state=tk.StringVar(value='Готов к проверке')
    detail=tk.StringVar(value='Открой привязанный чат в MuMu №4.')
    metrics=tk.StringVar(value='Сообщений: —    Входящих: —    Новых: —')
    preview=tk.StringVar(value='Нет предпросмотра')
    binding=tk.StringVar(value='Один привязанный чат · без автоматической отправки')
    events=queue.Queue();stop=threading.Event();busy=False;report_path=None;last_private=None
    controls=[];settings_window=None;details_window=None;transcript_window=None

    def report(*args,**kwargs):
        store=TestChatStore()
        try:kwargs['submission_check']=Actions(store).diagnostic()
        finally:store.close()
        return session_report(*args,**kwargs)

    def safe_state():
        store=TestChatStore()
        try:return Actions(store).state()
        finally:store.close()

    def details():
        nonlocal details_window
        if details_window is not None and details_window.winfo_exists():details_window.lift();return
        top=tk.Toplevel(root);details_window=top;top.title('О режиме');top.geometry('620x430')
        text=tk.Text(top,wrap='word',font=('Segoe UI',11),padx=20,pady=20)
        scroll=ttk.Scrollbar(top,orient='vertical',command=text.yview);scroll.pack(side='right',fill='y')
        text.config(yscrollcommand=scroll.set);text.pack(fill='both',expand=True)
        text.insert('1.0',
            'Один свой тестовый чат · MuMu №4 / 5563\n\n'
            'Старт включает только повторное чтение открытого привязанного чата. '
            'Следующая проверка — через 5 секунд после завершения предыдущей. '
            'Стоп отменяет ожидание и запрашивает остановку текущего чтения. '
            'При любой ошибке наблюдение останавливается. После запуска программы нужен новый Старт.\n\n'
            'Нет автоматической отправки, навигации, поиска, смены города, Telegram или сбора контактов. '
            'Тестовый предпросмотр появляется только для фразы «'+TEST_TEXT+'».\n\n'
            'Ручная тестовая отправка в настройках: одна подтверждённая попытка «'+QUESTION+'» '
            'для прежней привязки. Перезапуск и новая версия не снимают лимит. '
            'Не удаляй журнал. Стоп после начала отправки не отзывает сообщение. '
            'Появление исходящего не доказывает доставку.\n\n'
            'Сохранение выключено по умолчанию. При включении тексты и ID записываются '
            'без шифрования в %LOCALAPPDATA%/DvkRootless/one-chat-transcript.json. '
            'Это последний снимок, до 20 сообщений, не полный архив. '
            'Снятие галочки не удаляет файл. Не присылай его, SQLite-базу или test-apks. '
            'JSON-отчёт не содержит текстов и ID.\n\n'
            'Порядок для просмотра — обратный порядок коллекции; время сообщений автоматически не проверяется.')
        text.config(state='disabled')

    def refresh_controls():
        locked=busy or monitor.active
        for control in controls:control.config(state='disabled' if locked else 'normal')
        start_button.config(state='disabled' if locked else 'normal')
        read_button.config(state='disabled' if locked else 'normal')
        settings_button.config(state='disabled' if locked else 'normal')
        stop_button.config(state='normal' if locked else 'disabled')

    def worker(kind,executable,directory,expected):
        try:
            if kind!='send':
                private=capture(executable,directory,stop.is_set,expected)
                events.put(('result',(kind,private,directory)));return
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
                except Exception:pass
            events.put(('sent',(after,directory)))
        except Exception as exc:
            reason=str(exc) if isinstance(exc,ReadStopped) and str(exc) in ERRORS|{'client-version','cancelled','ambiguous-process','unexpected-process','unsupported-runtime','invalid-forward','not-ready'} else 'operation-stopped'
            events.put(('failed',(directory,reason,exc.diagnostic if isinstance(exc,ReadStopped) else None)))

    def begin(kind):
        nonlocal busy,last_private
        if busy or (monitor.active and kind!='read'):return False
        if not consent.get():messagebox.showinfo('Свой тестовый чат','Подтверди чтение своего тестового чата.');return False
        try:
            store=TestChatStore()
            try:
                expected=store.bound();send_state=Actions(store).state()
                available=store.db.execute('SELECT code FROM test_preview WHERE singleton=1').fetchone() is not None
            finally:store.close()
            if kind=='bind' and expected is not None:
                messagebox.showinfo('Чат уже привязан','Открой ранее привязанный чат. Заново привязывать его не нужно.');return False
            if kind!='bind' and expected is None:
                messagebox.showinfo('Нет привязки','Открой настройки и привяжи свой тестовый чат.');return False
            if kind=='send':
                if send_state!='not-reserved' or not available:
                    messagebox.showinfo('Отправка заблокирована','Нужен тестовый предпросмотр и неиспользованный лимит. Не удаляй журнал.');return False
                if not messagebox.askyesno('Одна реальная отправка',
                    'Отправить один раз «'+QUESTION+'» своему второму аккаунту?\n\n'
                    f"Твой аккаунт: {expected['account']}\nВторой аккаунт: {expected['peer']}\nЧат: {expected['chat']}\n\n"
                    'Это реальное сообщение. При неизвестном исходе повтор запрещён.'):
                    return False
        except Exception:
            state.set('Состояние недоступно');detail.set('Не удаляй журнал. Отправка не запущена.');return False
        last_private=None;transcript_button.config(state='disabled')
        if transcript_window is not None and transcript_window.winfo_exists():transcript_window.destroy()
        preview.set('Проверяю…');busy=True;stop.clear();refresh_controls()
        state.set('Читаю чат…' if kind!='send' else 'Тестовая отправка…')
        detail.set('Не переключай чат.' if kind!='send' else 'Одна попытка. При сбое не повторяй.')
        threading.Thread(target=worker,args=(kind,adb.get(),folder.get(),None if kind=='bind' else expected),daemon=True).start()
        return True

    monitor=ReadLoop(root.after,root.after_cancel,lambda:begin('read'))

    def start_monitor():
        if busy:return
        monitor.start();refresh_controls()

    def cancel():
        monitor.stop()
        if busy:stop.set();state.set('Останавливаю…');detail.set('Ожидаю завершения текущей операции.')
        else:state.set('Остановлено');detail.set('Для продолжения нажми «Старт».')
        refresh_controls()

    def save_report(directory,value):
        nonlocal report_path
        report_path=Path(directory).resolve(strict=True).parent/('rootless-one-chat-'+VERSION+'.json')
        report_path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');report_button.config(state='normal')

    def show_transcript():
        nonlocal transcript_window
        if last_private is None:return
        if transcript_window is not None and transcript_window.winfo_exists():transcript_window.destroy()
        top=tk.Toplevel(root);transcript_window=top;top.title('Переписка · только локально');top.geometry('720x520')
        text=tk.Text(top,wrap='word',font=('Segoe UI',11));text.pack(fill='both',expand=True)
        text.insert('1.0',local.display(last_private,last_private['identity']));text.config(state='disabled')

    def open_report():
        import os
        if report_path is not None:
            try:os.startfile(str(report_path))
            except (AttributeError,OSError):messagebox.showinfo('Отчёт',str(report_path))

    def settings():
        nonlocal settings_window
        if busy or monitor.active:return
        if settings_window is not None and settings_window.winfo_exists():settings_window.lift();return
        top=tk.Toplevel(root);settings_window=top;top.title('Настройки');top.geometry('660x520');top.minsize(640,520)
        pane=ttk.Frame(top,padding=24);pane.pack(fill='both',expand=True)
        local_controls=[]
        for label,var,picker in [('ADB',adb,lambda:filedialog.askopenfilename(parent=top,filetypes=[('ADB','*.exe')])),
                                 ('Папка test-apks',folder,lambda:filedialog.askdirectory(parent=top))]:
            ttk.Label(pane,text=label).pack(anchor='w')
            row=ttk.Frame(pane);row.pack(fill='x',pady=(4,16))
            entry=ttk.Entry(row,textvariable=var);entry.pack(side='left',fill='x',expand=True)
            def choose(v=var,pick=picker):
                value=pick()
                if value:v.set(value)
            button=ttk.Button(row,text='Выбрать',command=choose);button.pack(side='right',padx=(8,0));local_controls.extend((entry,button))
        save_check=ttk.Checkbutton(pane,variable=saving,text='Сохранять переписку локально (тексты и ID)')
        save_check.pack(anchor='w',pady=(0,8));local_controls.append(save_check)
        ttk.Label(pane,text='Открытый JSON без шифрования. Снятие галочки не удаляет файл.',style='Muted.TLabel',wraplength=580).pack(anchor='w')
        actions=ttk.Frame(pane);actions.pack(fill='x',pady=(24,12))
        bind_button=ttk.Button(actions,text='Привязать открытый чат',command=lambda:begin('bind'));bind_button.pack(side='left');local_controls.append(bind_button)
        send_button=ttk.Button(pane,text='Тестовая отправка · один раз',command=lambda:begin('send'));send_button.pack(anchor='w');local_controls.append(send_button)
        ttk.Button(pane,text='О режиме и ограничениях',command=details).pack(anchor='w',pady=(16,0))
        controls.extend(local_controls)
        def closed():
            for c in local_controls:controls.remove(c)
            top.destroy()
        top.protocol('WM_DELETE_WINDOW',closed);refresh_controls()
        top.update_idletasks()
        top.geometry(f'{max(660,pane.winfo_reqwidth())}x{max(520,pane.winfo_reqheight())}')
        top.minsize(max(640,pane.winfo_reqwidth()),max(520,pane.winfo_reqheight()))

    settings_button=ttk.Button(header,text='Настройки',command=settings);settings_button.pack(side='right')
    ttk.Label(main,textvariable=binding,style='Muted.TLabel').pack(anchor='w',pady=(8,20))
    card=ttk.Frame(main,style='Card.TFrame',padding=20);card.pack(fill='x')
    ttk.Label(card,textvariable=state,style='Status.TLabel',wraplength=580).pack(anchor='w')
    ttk.Label(card,textvariable=detail,style='Card.TLabel',wraplength=580).pack(anchor='w',pady=(8,16))
    ttk.Label(card,textvariable=metrics,style='Card.TLabel').pack(anchor='w')
    ttk.Label(main,textvariable=preview,style='Muted.TLabel',wraplength=600).pack(anchor='w',pady=(16,12))
    owned=ttk.Checkbutton(main,variable=consent,text='Разрешаю чтение чата со своим вторым аккаунтом')
    owned.pack(anchor='w');controls.append(owned)
    row=ttk.Frame(main);row.pack(fill='x',pady=(20,12))
    start_button=ttk.Button(row,text='Старт',style='Primary.TButton',command=start_monitor);start_button.pack(side='left')
    stop_button=ttk.Button(row,text='Стоп',command=cancel,state='disabled');stop_button.pack(side='left',padx=8)
    read_button=ttk.Button(row,text='Проверить один раз',command=lambda:begin('read'));read_button.pack(side='left')
    footer=ttk.Frame(main);footer.pack(fill='x')
    transcript_button=ttk.Button(footer,text='Переписка',command=show_transcript,state='disabled');transcript_button.pack(side='left')
    report_button=ttk.Button(footer,text='Отчёт',command=open_report,state='disabled');report_button.pack(side='left',padx=8)
    ttk.Button(footer,text='О режиме',command=details).pack(side='right')

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
            metrics.set(f"Сообщений: {outcome['observed_messages']}    Входящих: {outcome['incoming_messages']}    Новых: {outcome['new_incoming']}")
            preview.set('Предпросмотр: «'+QUESTION+'» · не отправлен' if outcome['preview_available'] else 'Нет предпросмотра ответа')
            state.set('Наблюдение включено' if monitor.active else 'Чат прочитан')
            suffix=' · отправка заблокирована' if send_state!='not-reserved' else ''
            detail.set('Проверено в '+datetime.now().strftime('%H:%M:%S')+suffix)
        finally:store.close()

    def poll():
        nonlocal busy,last_private
        while not events.empty():
            kind,data=events.get_nowait();busy=False;success=False;directory=None
            try:
                if kind=='failed':
                    directory,reason,diagnostic=data
                    value=report(failure=True,send_state=safe_state());value['stop_reason']=reason
                    if diagnostic is not None:value['native_check']=diagnostic
                    save_report(directory,value)
                    state.set('Открыт другой чат' if reason=='identity-not-bound' else 'Проверка остановлена')
                    detail.set('Вернись в привязанный чат и нажми «Старт».' if reason=='identity-not-bound' else 'Причина: '+reason+'. Подробности — в отчёте.')
                    preview.set('Предпросмотр скрыт');metrics.set('Сообщений: —    Входящих: —    Новых: —')
                elif kind=='sent':
                    private,directory=data
                    if private is not None and not stop.is_set():accept(private,directory)
                    else:
                        save_report(directory,report(send_state=safe_state()))
                        state.set('Попытка завершена');detail.set('Доставку проверь на втором аккаунте. Повтор запрещён.');preview.set('Отправка заблокирована')
                else:
                    operation,private,directory=data
                    if stop.is_set():
                        state.set('Остановлено');detail.set('Результат отменённого чтения не сохранён.');preview.set('Предпросмотр скрыт')
                    elif operation=='bind':
                        who=private['identity']
                        if messagebox.askyesno('Подтверди свой тестовый чат',f"Твой аккаунт: {who['account']}\nВторой аккаунт: {who['peer']}\nЧат: {who['chat']}\n\nЭто именно твои два аккаунта?"):
                            store=TestChatStore()
                            try:store.bind(who)
                            finally:store.close()
                            save_report(directory,report(send_state=safe_state()));state.set('Чат привязан');detail.set('Нажми «Старт» или «Проверить один раз».');preview.set('Нет предпросмотра')
                    else:accept(private,directory);success=True
            except Exception:
                last_private=None;transcript_button.config(state='disabled');preview.set('Предпросмотр скрыт')
                state.set('Проверка не завершена');detail.set('Состояние или отчёт недоступны. Не удаляй журнал.')
                try:
                    value=report(failure=True,send_state=safe_state(),transcript_saved=None);value['stop_reason']='state-or-report-unavailable';save_report(directory,value)
                except Exception:pass
            finally:
                monitor.complete(success);refresh_controls()
        refresh_controls();root.after(100,poll)

    def close():
        monitor.stop()
        if busy:cancel()
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);root.update_idletasks()
    root.geometry(f'{max(680,main.winfo_reqwidth())}x{max(530,main.winfo_reqheight())}')
    root.minsize(max(660,main.winfo_reqwidth()),max(530,main.winfo_reqheight()))
    if self_check:
        root.update()
        assert root.winfo_viewable() and start_button.winfo_viewable() and read_button.winfo_viewable()
        assert not monitor.active and monitor.pending is None
        assert str(stop_button.cget('state'))=='disabled'
        assert not consent.get() and not saving.get()
        assert main.winfo_reqheight()<=root.winfo_height()
        assert main.winfo_reqwidth()<=root.winfo_width()
        sample=dict(identity=dict(account='100',peer='200',chat='300'),messages=[
            dict(id='9',sender='200',text='NEW_SYNTHETIC'),dict(id='10',sender='100',text='OLD_SYNTHETIC')])
        last_private=sample;show_transcript();root.update()
        content=[w for w in transcript_window.winfo_children() if isinstance(w,tk.Text)][0].get('1.0','end-1c')
        assert content.index('OLD_SYNTHETIC')<content.index('NEW_SYNTHETIC')
        assert sample['messages'][0]['text']=='NEW_SYNTHETIC'
        transcript_window.destroy();settings();root.update()
        assert settings_window.winfo_viewable()
        assert settings_window.winfo_children()[0].winfo_reqheight()<=settings_window.winfo_height()
        details();root.update();assert details_window.winfo_viewable()
        # Exercise the actual GUI event queue with a disposable owned-chat store.
        # No ADB, Gadget, user journal, or real send is reachable in this test.
        import tempfile
        import time
        from unittest.mock import patch
        real_store=TestChatStore
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)/'test-apks';directory.mkdir()
            path=Path(temp)/'one-chat-check.sqlite3'
            def factory():return real_store(path)
            store=factory()
            try:store.bind(sample['identity']);store.consume(sample)
            finally:store.close()
            def fake_read(executable,directory,cancelled,expected):
                assert expected==sample['identity']
                return sample
            def wait_idle():
                deadline=time.monotonic()+5
                while busy and time.monotonic()<deadline:
                    root.update();time.sleep(.01)
                assert not busy
                root.update()
            consent.set(True);folder.set(str(directory))
            with patch.object(sys.modules[__name__],'TestChatStore',factory), \
                 patch.object(sys.modules[__name__],'capture',side_effect=fake_read) as reader, \
                 patch.object(sys.modules[__name__],'submit') as sender:
                root.after(0,poll)
                start_monitor();wait_idle()
                assert monitor.active and monitor.pending is not None
                assert reader.call_count==1
                assert 'Новых: 0' in metrics.get()
                assert str(settings_button.cget('state'))=='disabled'
                cancel();assert not monitor.active and monitor.pending is None
                assert str(start_button.cget('state'))=='normal'
                reader.side_effect=ReadStopped('identity-not-bound')
                start_monitor();wait_idle()
                assert not monitor.active and monitor.pending is None
                assert state.get()=='Открыт другой чат'
                assert last_private is None
                assert str(transcript_button.cget('state'))=='disabled'
                def cancellable(*args):
                    deadline=time.monotonic()+3
                    while not args[2]() and time.monotonic()<deadline:time.sleep(.01)
                    raise ReadStopped('cancelled')
                reader.side_effect=cancellable
                start_monitor();cancel();wait_idle()
                assert not monitor.active and monitor.pending is None
                sender.assert_not_called()
            consent.set(False)
        import frida
        assert frida.__version__=='17.24.1'
        root.destroy();return
    root.after(100,poll);root.mainloop()


if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'])
