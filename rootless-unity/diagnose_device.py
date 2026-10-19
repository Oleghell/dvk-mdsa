"""Metadata-only follow-up for the existing private Gadget APKs, fixed MuMu #4."""
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

from native_metadata import NATIVE_FUNCTION, validate_metadata

VERSION = '0.1.3'
FIXED_MODULES = ['libfrida-gadget.so', 'libunity.so', 'libil2cpp.so', 'libmain.so']
SCRIPT = "'use strict';\n" + EVIDENCE_FUNCTION + NATIVE_FUNCTION + '''
'use strict';
rpc.exports = {
  runtime() {return {frida_version: Frida.version, arch: Process.arch, platform: Process.platform};},
  evidence() { return moduleEvidence(); },
  native() { return nativeMetadata(); },
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
    def __init__(self,executable,folder):
        super().__init__(executable,folder)
        self.adb_events=[]

    def observe_result(self,args,returncode,text,outcome='completed'):
        from adb_evidence import MAX_EVENTS,event
        if len(self.adb_events)<MAX_EVENTS:
            self.adb_events.append(event(args,returncode,text,outcome))

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


def inspect_gadget(port, token, cancelled, *, frida_api=None, uikit_root_probe=False, uikit_tree_probe=False, navigation_probe=False, profile_probe=False, profile_metadata_probe=False, batch_probe=False, chat_runtime_probe=False, chat_state_probe=False, progress=lambda text:None):
    if frida_api is None:
        import frida as frida_api
    frida=frida_api
    if chat_state_probe and (chat_runtime_probe or profile_metadata_probe or batch_probe or profile_probe or navigation_probe or uikit_tree_probe):raise TestError('Проверка открытого чата несовместима с другими UI-режимами.')
    if chat_runtime_probe and (chat_state_probe or profile_metadata_probe or batch_probe or profile_probe or navigation_probe or uikit_tree_probe or uikit_root_probe):raise TestError('Диагностика типов чата несовместима с UI-проверками.')
    if profile_metadata_probe and (chat_state_probe or batch_probe or profile_probe or navigation_probe or uikit_tree_probe):raise TestError('Режим только метаданных несовместим с UI-проверками.')
    profile_probe=profile_probe or batch_probe
    navigation_probe=navigation_probe or profile_probe
    uikit_root_probe=uikit_root_probe or uikit_tree_probe or navigation_probe or profile_metadata_probe or chat_state_probe
    source=SCRIPT
    native_validator=validate_metadata
    if chat_runtime_probe:
        import chat_runtime_metadata as probe_module
        source=SCRIPT.replace(NATIVE_FUNCTION,probe_module.FUNCTION,1)
        native_validator=probe_module.validate
    if uikit_root_probe:
        import uikit_profile
        import uikit_root
        if chat_state_probe:
            import chat_state_probe as probe_module
        elif profile_metadata_probe:
            import profile_metadata as probe_module
        elif batch_probe:
            import profile_batch as probe_module
        elif profile_probe:
            import uikit_profile_navigation as probe_module
        elif navigation_probe:
            import uikit_navigation as probe_module
        elif uikit_tree_probe:
            import uikit_tree as probe_module
        else:probe_module=uikit_root
        source=SCRIPT.replace(NATIVE_FUNCTION,uikit_profile.SCRIPT,1)+probe_module.FUNCTION+'\nrpc.exports.root = () => probeUIKitRoot();'
        if batch_probe:source=source.replace('rpc.exports.root = () => probeUIKitRoot();','rpc.exports.root = () => probeBatchProfile();')
        if navigation_probe or chat_state_probe:source+='\nrpc.exports.cancel = () => cancelNavigation();'
        native_validator=uikit_profile.validate
    if frida.__version__ != '17.24.1':raise TestError('Нужен клиент Frida 17.24.1.')
    report={'client_version':'17.24.1','connected':False,'attached':False,'rpc_runtime_ok':False,
            'rpc_modules_ok':False,'rpc_evidence_ok':False,'rpc_native_ok':False,'attempts':0,'stage':'not-started','error_types':[],
            'process_count':None,'process_selection':'single-authenticated-process-by-pid'}
    manager=frida.get_device_manager();address='127.0.0.1:'+str(port)
    guard=frida.Cancellable()
    timer=threading.Timer(200 if batch_probe else 20,guard.cancel);timer.daemon=True;timer.start()
    device=session=script=None
    monitor_stop=threading.Event()
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
                    script=session.create_script(source,name='dvk-open-chat-state-0.3.16' if chat_state_probe else 'dvk-chat-runtime-metadata-0.3.16' if chat_runtime_probe else 'dvk-profile-batch-0.3.16' if batch_probe else 'dvk-profile-metadata-0.3.1' if profile_metadata_probe else 'dvk-uikit-profile-navigation-0.3.16' if profile_probe else 'dvk-uikit-navigation-0.2.3' if navigation_probe else 'dvk-uikit-tree-0.1.8' if uikit_tree_probe else 'dvk-uikit-root-0.1.5' if uikit_root_probe else 'dvk-fixed-diagnostics-0.1.3')
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
                    report['discovery_stage']=classify_evidence(report['modules']['fixed_modules'],report['evidence'])
                    if report['runtime']['arch']=='arm64' and report['runtime']['platform']=='linux':
                        if chat_runtime_probe and cancelled():
                            report['stage']='cancelled';return report
                        report['stage']='native-metadata-rpc'
                        report['native_metadata']=native_validator(script.exports_sync.native())
                        report['rpc_native_ok']=True
                        report['stage']=report['native_metadata']['stage']
                        if uikit_root_probe:
                            report['rpc_root_ok']=False
                            if report['stage']=='metadata-ready':
                                if (navigation_probe or chat_state_probe) and cancelled():
                                    report['stage']='cancelled';return report
                                report['stage']='uikit-root-rpc'
                                if navigation_probe or chat_state_probe:
                                    def monitor_cancel():
                                        while not monitor_stop.wait(0.1):
                                            if cancelled():
                                                try:script.exports_sync.cancel()
                                                except Exception:pass
                                                return
                                    threading.Thread(target=monitor_cancel,daemon=True).start()
                                if batch_probe:
                                    def batch_root():
                                        report['uikit_root']={}
                                        report['stage']='uikit-root-rpc'
                                        value=probe_module.validate(script.exports_sync.root())
                                        report['uikit_root']=value
                                        return value
                                    report['batch']=probe_module.run(batch_root,cancelled,progress)
                                    report['stage']=report['batch']['status']
                                    report['rpc_root_ok']=bool(report.get('uikit_root'))
                                else:
                                    report['uikit_root']=probe_module.validate(script.exports_sync.root())
                                    report['rpc_root_ok']=True
                                    report['stage']=report['uikit_root']['stage']
                                    if navigation_probe or chat_state_probe:
                                        nav=report['uikit_root']['navigation']
                                        if nav['stage']!='not-attempted':report['stage']=nav['stage']
                                monitor_stop.set()
                                if uikit_tree_probe and report['stage']=='root-ready':
                                    report['stage']=report['uikit_root']['tree']['stage']
                    else:
                        report['stage']=report['discovery_stage']
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
        monitor_stop.set();timer.cancel()
        cleanup_frida(frida,manager,address,script,session,device)
    return report


def listening_port(text):
    # Only a boolean leaves this parser; no unrelated addresses or socket lines are retained.
    return any(re.fullmatch(r'[0-9a-fA-F.:\[\]*]+:27042', part) for line in text.splitlines() for part in line.split())


def diagnose(adb,folder,progress=lambda text:None,cancelled=lambda:False,inspector=inspect_gadget,*,uikit_root_probe=False, uikit_tree_probe=False, navigation_probe=False, profile_probe=False, profile_metadata_probe=False, batch_probe=False, chat_runtime_probe=False, chat_state_probe=False):
    if chat_state_probe and (chat_runtime_probe or profile_metadata_probe or batch_probe or profile_probe or navigation_probe or uikit_tree_probe):raise TestError('Проверка открытого чата несовместима с другими UI-режимами.')
    if chat_runtime_probe and (chat_state_probe or profile_metadata_probe or batch_probe or profile_probe or navigation_probe or uikit_tree_probe or uikit_root_probe):raise TestError('Диагностика типов чата несовместима с UI-проверками.')
    if profile_metadata_probe and (chat_state_probe or batch_probe or profile_probe or navigation_probe or uikit_tree_probe):raise TestError('Режим только метаданных несовместим с UI-проверками.')
    profile_probe=profile_probe or batch_probe
    navigation_probe=navigation_probe or profile_probe
    uikit_root_probe=uikit_root_probe or uikit_tree_probe or navigation_probe or profile_metadata_probe or chat_state_probe
    version='0.3.16' if chat_state_probe else '0.3.16' if chat_runtime_probe else '0.3.1' if profile_metadata_probe else '0.3.16' if profile_probe else '0.2.3' if navigation_probe else '0.1.8' if uikit_tree_probe else '0.1.5' if uikit_root_probe else VERSION
    if (uikit_root_probe or chat_runtime_probe) and inspector is inspect_gadget:
        inspector=lambda port,token,cancel:inspect_gadget(port,token,cancel,uikit_root_probe=uikit_root_probe,uikit_tree_probe=uikit_tree_probe,navigation_probe=navigation_probe,profile_probe=profile_probe,profile_metadata_probe=profile_metadata_probe,batch_probe=batch_probe,chat_runtime_probe=chat_runtime_probe,chat_state_probe=chat_state_probe,progress=progress)
    report={'tool_version':version,'mode':('open-chat-state-read-only' if chat_state_probe else 'chat-runtime-metadata-only' if chat_runtime_probe else 'profile-metadata-only' if profile_metadata_probe else 'uikit-search-ten-profiles' if batch_probe else 'uikit-search-profile-return' if profile_probe else 'uikit-search-filter-cancel' if navigation_probe else 'uikit-structure-only' if uikit_tree_probe else 'uikit-root-presence-only' if uikit_root_probe else 'native-metadata-only-existing-test-app'),'target':TARGET,'working_instance':WORKING,
            'instances_verified_distinct':False,'install_requested':False,'app_installation_modified':False,
            'working_device_modified':False,'root_used':False,'ocr_used':False,'messages_sent':0,
            'unity_object_access':'not-tested','status':'not-run'}
    if chat_runtime_probe or chat_state_probe:
        report.update(ui_actions_attempted=False,ui_actions_performed=False,method_values_read=False,chat_opened=False,history_read=False,profile_may_remain_open=False,action_backend='metadata-only')
    if chat_state_probe:report['action_backend']='read-only-chat-state'
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
        progress('Проверяю уже открытый чат — ничего не нажимаю и не отправляю…' if chat_state_probe else 'Проверяю runtime-типы чата — без нажатий и чтения сообщений…' if chat_runtime_probe else 'Проверяю только типы и сигнатуры профиля. Нет UI-наблюдателя, открытий и нажатий…' if profile_metadata_probe else 'Проверяю до 10 видимых анкет без сообщений…' if batch_probe else 'Проверяю профиль и возврат…' if profile_probe else 'Проверяю экран поиска → открываю фильтры → отменяю без сохранения…' if navigation_probe else 'Читаю ограниченную структуру UIKit, без текста и действий…' if uikit_tree_probe else 'Проверяю главный поток и наличие окна, без UI-действий…' if uikit_root_probe else 'Проверяю IL2CPP API и метаданные классов UI. Сам UI не меняется…')
        stage='forward-and-gadget'
        value=adb.run(['-s',TARGET,'forward','tcp:0','tcp:27042'])
        if not value.isdecimal() or not 1024 <= int(value) <= 65535:raise TestError('Некорректный порт ADB.')
        adb.forward_port=int(value)
        report['gadget']=inspector(adb.forward_port,token,cancelled)
        report['status']=report['gadget']['stage']
        if uikit_root_probe:
            report['unity_object_access']='root-presence-confirmed' if report['status']=='root-ready' else 'not-confirmed'
            if uikit_tree_probe:
                root_result=report['gadget'].get('uikit_root',{})
                root_confirmed=all(root_result.get(k) is True for k in ('main_thread_confirmed','window_available','object_classes_validated'))
                report['unity_root_access']='confirmed' if root_confirmed else 'not-confirmed'
                report['unity_object_access']='structure-snapshot' if report['status'] in ('tree-ready','tree-limited') else 'root-presence-confirmed' if root_confirmed else 'not-confirmed'
            if chat_state_probe:
                nav=report['gadget'].get('uikit_root',{}).get('navigation',{})
                report['history_state_read']=bool(nav.get('chat_identity_verified'))
                report['method_values_read']=report['history_state_read']
                report['message_text_read']=False
                report['unity_object_access']='chat-state-confirmed' if report['status']=='navigation-ready' else 'not-confirmed'
                report['action_backend']='read-only-chat-state'
            report['ui_text_read']=False
            report['ui_actions_performed']=False
            if profile_metadata_probe:
                report['ui_actions_attempted']=False
                report['action_backend']='metadata-only'
                report['profile_may_remain_open']=False
            if navigation_probe:
                nav=report['gadget'].get('uikit_root',{}).get('navigation',{})
                unknown=not nav and report['gadget'].get('stage')=='uikit-root-rpc'
                report['ui_actions_attempted']=None if unknown else bool(nav.get('open_attempted'))
                report['ui_actions_performed']=None if unknown else bool(nav.get('open_completed') or nav.get('close_completed' if profile_probe else 'cancel_completed'))
                report['action_backend']='semantic-controller-handlers'
                report['unity_object_access']='navigation-confirmed' if report['status']=='navigation-ready' else 'not-confirmed'
                report['profile_may_remain_open' if profile_probe else 'filters_may_remain_open']=unknown or bool(nav.get('open_attempted') and not nav.get('return_verified'))
                if batch_probe:
                    batch=report['gadget'].get('batch',{})
                    report['profile_may_remain_open']=batch.get('profile_may_remain_open',report['profile_may_remain_open'])
                    if batch.get('attempts') and not batch.get('items'):report['ui_actions_attempted']=None
                    elif batch.get('items'):report['ui_actions_attempted']=any(item['opened'] for item in batch['items'])
                    report['ui_actions_performed']=None if batch.get('profile_may_remain_open') and not nav else bool(batch.get('visited') or nav.get('open_completed'))
    except Exception as error:
        report['status']='stopped';report['failure_stage']=stage
        report['error_type']=safe_error_type(error)
        report['error']=str(error) if isinstance(error,TestError) else 'Диагностика не завершена; проверьте папку test-apks и ADB.'
    finally:
        if adb.forward_port is not None:
            try:adb.run(['-s',TARGET,'forward','--remove',f'tcp:{adb.forward_port}'],timeout=10)
            except Exception:report['forward_cleanup_failed']=True
    events=getattr(adb,'adb_events',None)
    if events is not None:
        report['adb_checks']=events[:40]
        if report['status']=='stopped' and events:
            report['adb_last_check']=events[-1]['check']
            if stage=='device-preflight':
                failed=[e for e in events if e['status']=='failed']
                if failed:report['adb_failure']=failed[0].copy()
    target=folder.parent/f"{'rootless-open-chat-state' if chat_state_probe else 'rootless-chat-runtime-metadata' if chat_runtime_probe else 'rootless-profile-metadata' if profile_metadata_probe else 'rootless-profile-batch' if batch_probe else 'rootless-profile-navigation' if profile_probe else 'rootless-navigation' if navigation_probe else 'rootless-diagnostics'}-{version}.json"
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report,target


def launch_gui(self_check=False,*,uikit_root_probe=False, uikit_tree_probe=False):
    uikit_root_probe=uikit_root_probe or uikit_tree_probe
    version='0.1.8' if uikit_tree_probe else '0.1.5' if uikit_root_probe else VERSION
    import queue
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title(f'ДругВокруг — проверка UIKit {version}, без установки')
    root.geometry('900x560' if uikit_root_probe else '850x490');root.minsize(780,450)
    main=ttk.Frame(root,padding=18);main.pack(fill='both',expand=True)
    ttk.Label(main,text='Только диагностика #4 (5563) — APK не переустанавливается',font=('Segoe UI',12,'bold')).pack(anchor='w')
    description=('Одноразовое дерево UIKit: до 64 узлов, без текста, снимков и нажатий.\n'
        'Типы, связи и признаки доступности; лимит обхода 150 мс между вызовами.\n'
        'Возможны замедление, зависание или сбой тестового приложения. Рабочий #0 не изменяется.'
        if uikit_tree_probe else 'Наблюдение IL2CPP до 8 секунд → проверка главного потока → наличие UIKit-окна.\n'
        'Три managed-вызова: проверка потока и два getter. Тексты и переписки не читаются.\n'
        'Возможны замедление, зависание или сбой тестового приложения. Рабочий #0 не изменяется.'
        if uikit_root_probe else 'Проверка: вызов IL2CPP API → домен → метаданные классов UI (не сами объекты).\n'
        'Нет установки, UI-нажатий, OCR и чтения переписок. Возможен сбой тестового приложения.')
    ttk.Label(main,text='Запустите оба MuMu и оставьте тестовый ДругВокруг открытым на #4.\n'+description,wraplength=820).pack(anchor='w',pady=12)
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
    consent=tk.BooleanVar(value=False)
    if uikit_root_probe:
        ttk.Checkbutton(main,text=('Разрешаю одноразовое чтение структуры без текста только на #4 (5563).' if uikit_tree_probe else 'Разрешаю временное наблюдение и проверку наличия окна только на #4 (5563).'),variable=consent).pack(anchor='w',pady=4)
    state=tk.StringVar(value='Если EXE лежит рядом со старой test-apks, путь уже правильный. При ошибке ADB отчёт покажет конкретную проверку.')
    ttk.Label(main,textvariable=state,wraplength=790).pack(anchor='w',pady=10)
    events=queue.Queue();stop=threading.Event();busy=False
    def worker(executable,directory):
        try:
            path=Path(directory).resolve(strict=True)
            result,report=diagnose(DiagnosticAdb(executable,path),path,lambda s:events.put(('status',s)),stop.is_set,uikit_root_probe=uikit_root_probe,uikit_tree_probe=uikit_tree_probe)
            events.put(('done',(result['status'],str(report))))
        except Exception as error:events.put(('error',str(error) if isinstance(error,TestError) else 'Проверьте ADB, старую папку test-apks и право записи отчёта.'))
    def start():
        nonlocal busy
        if busy:return
        if uikit_root_probe and not consent.get():
            messagebox.showinfo('Подтверждение','Отметьте разрешение проверки только на #4.');return
        busy=True;stop.clear();button.config(state='disabled')
        threading.Thread(target=worker,args=(binary.get(),folder.get()),daemon=True).start()
    row=ttk.Frame(main);row.pack(fill='x',pady=8)
    button=ttk.Button(row,text=('Снять структуру UIKit — без текста и нажатий' if uikit_tree_probe else 'Проверить главный поток и окно — без нажатий' if uikit_root_probe else 'Проверить IL2CPP API — без нажатий в приложении'),command=start);button.pack(side='left')
    ttk.Button(row,text='Отменить',command=stop.set).pack(side='left',padx=10)
    ttk.Label(main,text=f'Результат: rootless-diagnostics-{version}.json рядом со старой папкой test-apks.\n'
        'В отчёт не попадают токены, boot ID, PID, адреса памяти, полные пути и тексты приложения.',wraplength=790).pack(anchor='w',pady=10)
    def poll():
        nonlocal busy
        while not events.empty():
            kind,value=events.get_nowait()
            if kind=='status':state.set(value);continue
            busy=False;button.config(state='normal')
            if kind=='error':state.set(value);messagebox.showerror('Диагностика остановлена',value)
            else:
                status,path=value;state.set('Этап результата: '+status)
                messagebox.showinfo('Подробный отчёт готов','Прикрепите в чат:\n'+path+('\n\nЭто структура интерфейса, не готовая автоматизация.' if uikit_tree_probe else '\n\nЭто проверка наличия корня, не готовая автоматизация.' if uikit_root_probe else '\n\nЭто диагностический результат, не подтверждение доступа к UI-объектам.'))
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
