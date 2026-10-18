"""Read-only follow-up for the existing private Gadget APKs, fixed MuMu #4."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from test_device import (TestAdb, TestError, TARGET, WORKING, PACKAGE, EXPORTS,
                         bundle_token, preflight, recheck, find_adb)

from module_evidence import EVIDENCE_FUNCTION, validate_evidence, classify_evidence

VERSION = '0.1.2'
FIXED_MODULES = ['libfrida-gadget.so', 'libunity.so', 'libil2cpp.so', 'libmain.so']
SCRIPT = "'use strict';\n" + EVIDENCE_FUNCTION + '''
'use strict';
rpc.exports = {
  runtime() {return {frida_version: Frida.version, arch: Process.arch, platform: Process.platform};},
  evidence() { return moduleEvidence(); },
  modules() {
    const names = ['libfrida-gadget.so', 'libunity.so', 'libil2cpp.so', 'libmain.so'];
    const all = Process.enumerateModules();
    const present = {};
    for (const name of names) present[name] = Process.findModuleByName(name) !== null;
    const module = Process.findModuleByName('libil2cpp.so');
    const exports = {};
    for (const name of ['il2cpp_domain_get', 'il2cpp_domain_get_assemblies', 'il2cpp_class_from_name', 'il2cpp_thread_attach'])
      exports[name] = module !== null && module.findExportByName(name) !== null;
    return {module_count: all.length, fixed_modules: present, il2cpp_exports: exports,
      engine_name_matches: all.filter(m => /il2cpp|unity/i.test(m.name)).length};
  }
};
'''


class DiagnosticAdb(TestAdb):
    def validate(self, args):
        if args in (['-s', TARGET, 'shell', 'pidof', PACKAGE], ['-s', TARGET, 'shell', 'ss', '-ltn'],
                    ['-s', TARGET, 'shell', 'getprop', 'ro.product.cpu.abi'],
                    ['-s', TARGET, 'shell', 'getprop', 'ro.dalvik.vm.native.bridge']):
            return
        if len(args) > 2 and (args[2] == 'install-multiple' or args[2:5] == ['shell','am','start']):
            raise TestError('Эта версия только диагностирует; установка и запуск запрещены.')
        super().validate(args)


def validate_runtime(value):
    if not isinstance(value,dict) or set(value) != {'frida_version','arch','platform'}:
        raise TestError('Неожиданный формат метаданных Gadget.')
    if value['frida_version'] != '17.24.1' or value['arch'] not in ('arm64','arm','x64','ia32') or value['platform'] not in ('linux','windows','darwin'):
        raise TestError('Неожиданные метаданные Gadget.')
    return dict(value)


def validate_modules(value):
    if not isinstance(value,dict) or set(value) != {'module_count','fixed_modules','il2cpp_exports','engine_name_matches'}:
        raise TestError('Неожиданный формат списка модулей.')
    for name in ('module_count','engine_name_matches'):
        if type(value[name]) is not int or not 0 <= value[name] <= 100000:
            raise TestError('Неожиданный счётчик модулей.')
    for name,allowed in (('fixed_modules',FIXED_MODULES),('il2cpp_exports',EXPORTS)):
        result=value[name]
        if not isinstance(result,dict) or set(result) != set(allowed) or any(type(v) is not bool for v in result.values()):
            raise TestError('Неожиданные свойства модулей.')
    return value


def safe_error_type(error):
    allowed={'TransportError','ServerNotRunningError','ProcessNotFoundError','PermissionDeniedError',
             'OperationCancelledError','ProtocolError','InvalidArgumentError','TimedOutError',
             'RPCException','InvalidOperationError','NotSupportedError','TestError'}
    name=type(error).__name__
    return name if name in allowed else 'OtherError'


def process_kind(name):
    if name == 'Gadget':return 'gadget'
    if name == PACKAGE:return 'target-package'
    return 'other-name-not-recorded'


def cleanup_frida(frida, manager, address, script, session, device):
    guard=frida.Cancellable()
    timer=threading.Timer(3,guard.cancel);timer.daemon=True;timer.start()
    try:
        with guard:
            for operation in ((lambda:script.unload()) if script else None,
                              (lambda:session.detach()) if session else None,
                              (lambda:manager.remove_remote_device(address)) if device else None):
                if operation:
                    try:operation()
                    except Exception:pass
    finally:timer.cancel()


def inspect_gadget(port, token, cancelled, *, frida_api=None):
    if frida_api is None:
        import frida as frida_api
    frida=frida_api
    if frida.__version__ != '17.24.1':raise TestError('Нужен клиент Frida 17.24.1.')
    report={'client_version':'17.24.1','connected':False,'attached':False,'rpc_runtime_ok':False,
            'rpc_modules_ok':False,'rpc_evidence_ok':False,'attempts':0,'stage':'not-started','error_types':[],
            'process_count':None,'process_selection':'single-authenticated-process-by-pid'}
    manager=frida.get_device_manager();address='127.0.0.1:'+str(port)
    guard=frida.Cancellable()
    timer=threading.Timer(20,guard.cancel);timer.daemon=True;timer.start()
    device=session=script=None
    try:
        with guard:
            for attempt in range(3):
                if cancelled():
                    report['stage']='cancelled';return report
                report['attempts']=attempt+1
                try:
                    report['stage']='remote-handle'
                    if device is None:device=manager.add_remote_device(address,token=token)
                    report['stage']='enumerate-processes'
                    processes=device.enumerate_processes()
                    report['connected']=True
                    report['process_count']=min(len(processes),1000)
                    if len(processes) != 1:
                        report['stage']='not-exactly-one-process';return report
                    process=processes[0]
                    if type(process.pid) is not int or process.pid <= 0:
                        raise TestError('Неожиданный идентификатор процесса Gadget.')
                    report['process_name_kind']=process_kind(process.name)
                    report['stage']='attach-single-process'
                    # Avoid assuming that new Gadget releases enumerate a process named "Gadget".
                    session=device.attach(process.pid)
                    report['attached']=True
                    report['stage']='create-fixed-script'
                    script=session.create_script(SCRIPT,name='dvk-fixed-diagnostics-0.1.2')
                    report['stage']='load-fixed-script';script.load()
                    report['stage']='runtime-rpc'
                    report['runtime']=validate_runtime(script.exports_sync.runtime())
                    report['rpc_runtime_ok']=True
                    report['stage']='modules-rpc'
                    report['modules']=validate_modules(script.exports_sync.modules())
                    report['rpc_modules_ok']=True
                    report['stage']='evidence-rpc'
                    report['evidence']=validate_evidence(script.exports_sync.evidence())
                    report['rpc_evidence_ok']=True
                    report['stage']=classify_evidence(report['modules']['fixed_modules'],report['evidence'])
                    return report
                except Exception as error:
                    kind=safe_error_type(error)
                    report['error_types'].append({'stage':report['stage'],'type':kind})
                    # Once attached, never mask a script/RPC problem as a connection timeout.
                    if report['attached'] or kind not in ('TransportError','ServerNotRunningError','ProcessNotFoundError','TimedOutError'):
                        return report
                    if attempt < 2:threading.Event().wait(0.5)
    except Exception as error:
        report['error_types'].append({'stage':report['stage'],'type':safe_error_type(error)})
    finally:
        timer.cancel()
        cleanup_frida(frida,manager,address,script,session,device)
    return report


def listening_port(text):
    # Only a boolean leaves this parser; no unrelated addresses or socket lines are retained.
    return any(re.fullmatch(r'[0-9a-fA-F.:\[\]*]+:27042', part) for line in text.splitlines() for part in line.split())


def diagnose(adb,folder,progress=lambda text:None,cancelled=lambda:False,inspector=inspect_gadget):
    report={'tool_version':VERSION,'mode':'read-only-existing-test-app','target':TARGET,'working_instance':WORKING,
            'instances_verified_distinct':False,'install_requested':False,'app_installation_modified':False,
            'working_device_modified':False,'root_used':False,'ocr_used':False,'messages_sent':0,
            'unity_object_access':'not-tested','status':'not-run'}
    stage='bundle-check'
    try:
        token=bundle_token(folder)
        progress('Проверяю отдельное устройство #4; ничего не устанавливаю…')
        stage='device-preflight'
        identities=preflight(adb,False);recheck(adb,identities)
        report['instances_verified_distinct']=True
        if cancelled():raise TestError('Диагностика отменена.')
        stage='device-metadata'
        try:
            value=adb.run(['-s',TARGET,'shell','pidof',PACKAGE])
            report['app_process_detected']=bool(re.fullmatch(r'\d+(?:\s+\d+)*',value))
            report['app_process_query']='available'
        except TestError:
            report['app_process_detected']=None
            report['app_process_query']='unavailable-or-not-running'
        try:
            text=adb.run(['-s',TARGET,'shell','ss','-ltn'])
            report['socket_query']='available'
            report['guest_port_27042_listening']=listening_port(text)
        except TestError:
            report['socket_query']='unavailable'
            report['guest_port_27042_listening']=None
        for prop,field in (('ro.product.cpu.abi','device_primary_abi'),('ro.dalvik.vm.native.bridge','native_bridge_kind')):
            try:
                raw=adb.run(['-s',TARGET,'shell','getprop',prop])
                if prop=='ro.product.cpu.abi':
                    report[field]=raw if raw in ('x86_64','x86','arm64-v8a','armeabi-v7a','armeabi') else 'other-or-unavailable'
                else:
                    report[field]={'':'none-reported','0':'none-reported','libnb.so':'libnb','libhoudini.so':'houdini','libndk_translation.so':'ndk-translation'}.get(raw,'other-not-recorded')
            except TestError:report[field]='query-unavailable'
        progress('Проверяю Gadget, список модулей и независимые признаки загрузки Unity…')
        stage='forward-and-gadget'
        value=adb.run(['-s',TARGET,'forward','tcp:0','tcp:27042'])
        if not value.isdecimal() or not 1024 <= int(value) <= 65535:raise TestError('Некорректный порт ADB.')
        adb.forward_port=int(value)
        report['gadget']=inspector(adb.forward_port,token,cancelled)
        report['status']=report['gadget']['stage']
    except Exception as error:
        report['status']='stopped';report['failure_stage']=stage
        report['error_type']=safe_error_type(error)
        report['error']=str(error) if isinstance(error,TestError) else 'Диагностика не завершена; проверьте папку test-apks и ADB.'
    finally:
        if adb.forward_port is not None:
            try:adb.run(['-s',TARGET,'forward','--remove',f'tcp:{adb.forward_port}'],timeout=10)
            except Exception:report['forward_cleanup_failed']=True
    target=folder.parent/'rootless-diagnostics-0.1.2.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report,target


def launch_gui(self_check=False):
    import queue
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title('ДругВокруг — подробная диагностика 0.1.2, без установки')
    root.geometry('850x490');root.minsize(780,450)
    main=ttk.Frame(root,padding=18);main.pack(fill='both',expand=True)
    ttk.Label(main,text='Только диагностика #4 (5563) — APK не переустанавливается',font=('Segoe UI',12,'bold')).pack(anchor='w')
    ttk.Label(main,text='Запустите оба MuMu и оставьте тестовый ДругВокруг открытым на #4.\n'
        'Проверка: Gadget → модули → карта библиотек и глобальные IL2CPP-экспорты.\n'
        'Нет установки, запуска приложения, OCR, снимков экрана и чтения переписок.',wraplength=790).pack(anchor='w',pady=12)
    base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    binary=tk.StringVar(value=find_adb());folder=tk.StringVar(value=str(base/'test-apks'))
    for label,var,picker in (
        ('ADB из MuMu / platform-tools:',binary,lambda:filedialog.askopenfilename(title='Выберите ADB',filetypes=[('ADB','*.exe')])),
        ('Старая папка test-apks из комплекта для #4:',folder,lambda:filedialog.askdirectory(title='Выберите старую test-apks'))):
        ttk.Label(main,text=label).pack(anchor='w')
        row=ttk.Frame(main);row.pack(fill='x',pady=(2,10));ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
        def choose(v=var,pick=picker):
            value=pick()
            if value:v.set(value)
        ttk.Button(row,text='Выбрать…',command=choose).pack(side='right',padx=(8,0))
    state=tk.StringVar(value='Если EXE лежит рядом со старой test-apks, путь уже правильный.')
    ttk.Label(main,textvariable=state,wraplength=790).pack(anchor='w',pady=10)
    events=queue.Queue();stop=threading.Event();busy=False
    def worker(executable,directory):
        try:
            path=Path(directory).resolve(strict=True)
            result,report=diagnose(DiagnosticAdb(executable,path),path,lambda s:events.put(('status',s)),stop.is_set)
            events.put(('done',(result['status'],str(report))))
        except Exception as error:events.put(('error',str(error) if isinstance(error,TestError) else 'Проверьте ADB, старую папку test-apks и право записи отчёта.'))
    def start():
        nonlocal busy
        if busy:return
        busy=True;stop.clear();button.config(state='disabled')
        threading.Thread(target=worker,args=(binary.get(),folder.get()),daemon=True).start()
    row=ttk.Frame(main);row.pack(fill='x',pady=8)
    button=ttk.Button(row,text='Собрать подробный отчёт — без установки',command=start);button.pack(side='left')
    ttk.Button(row,text='Отменить',command=stop.set).pack(side='left',padx=10)
    ttk.Label(main,text='Результат: rootless-diagnostics-0.1.2.json рядом со старой папкой test-apks.\n'
        'В отчёт не попадают токены, boot ID, PID, адреса памяти, полные пути и данные приложения.',wraplength=790).pack(anchor='w',pady=10)
    def poll():
        nonlocal busy
        while not events.empty():
            kind,value=events.get_nowait()
            if kind=='status':state.set(value);continue
            busy=False;button.config(state='normal')
            if kind=='error':state.set(value);messagebox.showerror('Диагностика остановлена',value)
            else:
                status,path=value;state.set('Этап результата: '+status)
                messagebox.showinfo('Подробный отчёт готов','Прикрепите в чат:\n'+path+'\n\nЭто диагностический результат, не подтверждение доступа к UI-объектам.')
        root.after(100,poll)
    def close():
        if busy:stop.set();messagebox.showinfo('Отмена','Дождитесь завершения текущей проверки и удаления её локального forward.')
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    if self_check:
        root.update();assert root.winfo_viewable() and button.winfo_viewable()
        import frida
        assert frida.__version__=='17.24.1'
        root.destroy();return
    root.after(100,poll);root.mainloop()


if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'])
