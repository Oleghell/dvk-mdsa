"""Finite #4 test installer/probe. No arbitrary ADB, scripts, UI actions or messages."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from apk_export import find_adb

VERSION = '0.1.0'
TARGET = '127.0.0.1:5563'
WORKING = '127.0.0.1:5555'
PACKAGE = 'drug.vokrug'
LAUNCHER = 'drug.vokrug/drug.vokrug.activity.Launcher'
HASHES = {'base.apk': 'c80c992beaea72912e1fdc4a57011d2c8d7567fe9bea31f4d94acb9ccd7575b5',
          'split-001.apk': '2bcda72196ee83ff4513a3477cbf791788b9a951a90c8c5cffea8f14982772a6'}
BOOT_ID = '/proc/sys/kernel/random/boot_id'
EXPORTS = ['il2cpp_domain_get', 'il2cpp_domain_get_assemblies', 'il2cpp_class_from_name', 'il2cpp_thread_attach']
# Fixed metadata-only probe: no NativeFunction, Interceptor, Java bridge or app-object reads.
PROBE_SCRIPT = '''
'use strict';
rpc.exports = {
  probe() {
    const module = Process.findModuleByName('libil2cpp.so');
    const names = ['il2cpp_domain_get', 'il2cpp_domain_get_assemblies', 'il2cpp_class_from_name', 'il2cpp_thread_attach'];
    const exports = {};
    for (const name of names) exports[name] = module !== null && module.findExportByName(name) !== null;
    return {frida_version: Frida.version, arch: Process.arch, platform: Process.platform,
      unity_loaded: Process.findModuleByName('libunity.so') !== null,
      il2cpp_loaded: module !== null, il2cpp_exports: exports};
  }
};
'''


class TestError(RuntimeError):
    pass


def bundle_token(folder: Path) -> str:
    for name, expected in HASHES.items():
        h = hashlib.sha256()
        try:
            with (folder/name).open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b''):
                    h.update(chunk)
        except OSError as exc:
            raise TestError('Не найдены тестовые APK. Выберите папку test-apks из частного комплекта.') from exc
        if h.hexdigest() != expected:
            raise TestError('Контрольная сумма тестового APK не совпала. Установка запрещена.')
    with zipfile.ZipFile(folder/'split-001.apk') as archive:
        entry = archive.getinfo('lib/arm64-v8a/libfrida-gadget.config.so')
        if entry.file_size > 4096:
            raise TestError('Некорректный конфиг Gadget.')
        config = json.loads(archive.read(entry))
    i = config.get('interaction', {})
    token = i.get('token', '')
    expected = {'type': 'listen', 'address': '127.0.0.1', 'port': 27042,
                'on_port_conflict': 'fail', 'on_load': 'resume', 'token': token}
    if set(config) != {'interaction'} or i != expected or not re.fullmatch('[0-9a-f]{64}', token):
        raise TestError('Конфиг Gadget не соответствует ограниченному тестовому режиму.')
    return token


class TestAdb:
    def __init__(self, executable: str, folder: Path):
        self.executable = str(Path(executable).resolve(strict=True))
        if Path(self.executable).name.lower() not in ('adb.exe', 'adb_server.exe', 'adb'):
            raise TestError('Выберите доверенный adb.exe / adb_server.exe из MuMu.')
        self.folder = folder.resolve(strict=True)
        self.forward_port = None

    def validate(self, args):
        if args == ['version']:
            return
        if len(args) == 2 and args[0] == 'connect' and args[1] in (TARGET, WORKING):
            return
        if args in (['-s', TARGET, 'get-state'], ['-s', WORKING, 'get-state'],
                    ['-s', TARGET, 'shell', 'cat', BOOT_ID], ['-s', WORKING, 'shell', 'cat', BOOT_ID]):
            return
        if args[:2] != ['-s', TARGET]:
            raise TestError('Любые изменения рабочего устройства запрещены.')
        operation = args[2:]
        if operation in (['shell', 'getprop', 'sys.boot_completed'],
                         ['shell', 'pm', 'list', 'packages', PACKAGE],
                         ['shell', 'am', 'start', '-n', LAUNCHER],
                         ['forward', 'tcp:0', 'tcp:27042'],
                         ['install-multiple', str(self.folder/'base.apk'), str(self.folder/'split-001.apk')]):
            return
        if self.forward_port is not None and operation == ['forward', '--remove', f'tcp:{self.forward_port}']:
            return
        raise TestError('Команда вне разрешённого тестового списка.')

    def run(self, args, timeout=30):
        self.validate(args)
        env = os.environ.copy()
        for key in ('ADB_SERVER_SOCKET', 'ANDROID_ADB_SERVER_PORT', 'ANDROID_SERIAL'):
            env.pop(key, None)
        env['ADB_SERVER_SOCKET'] = 'tcp:localhost:5037'
        try:
            with tempfile.TemporaryFile() as output:
                result = subprocess.run([self.executable, *args], shell=False, env=env, stdout=output,
                    stderr=subprocess.STDOUT, timeout=timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                output.seek(0)
                text = output.read(65537).decode('utf-8', errors='replace').strip()
            if len(text) > 65536:
                raise TestError('Слишком длинный ответ ADB.')
            if result.returncode != 0:
                match = re.search(r'Failure \[([A-Z][A-Z0-9_]+)', text)
                suffix = ' Код: '+match.group(1) if match else ''
                raise TestError('ADB не выполнил операцию.'+suffix+' Ничего не удаляйте и не включайте root.')
            return text
        except subprocess.TimeoutExpired as exc:
            raise TestError('ADB не ответил вовремя. Установка могла уже завершиться; автоматически повторять её нельзя.') from exc
        except OSError as exc:
            raise TestError('Не удалось запустить выбранный ADB.') from exc


def boot_id(adb, serial):
    value = adb.run(['-s', serial, 'shell', 'cat', BOOT_ID]).strip()
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value):
        raise TestError('Не удалось безопасно различить устройства. Проверка остановлена; root не нужен.')
    return value


def package_present(adb):
    value = adb.run(['-s', TARGET, 'shell', 'pm', 'list', 'packages', PACKAGE])
    if value == '':
        return False
    if value == 'package:'+PACKAGE:
        return True
    raise TestError('Неоднозначный ответ списка пакетов. Установка остановлена.')


def preflight(adb, install):
    adb.run(['version'])
    for serial in (WORKING, TARGET):
        adb.run(['connect', serial])
        if adb.run(['-s', serial, 'get-state']) != 'device':
            raise TestError('Запустите оба MuMu: рабочий #0 и тестовый #4; разрешите обычный ADB.')
    original, target = boot_id(adb, WORKING), boot_id(adb, TARGET)
    if original == target:
        raise TestError('Порты ведут на одно устройство! Любая установка запрещена.')
    if adb.run(['-s', TARGET, 'shell', 'getprop', 'sys.boot_completed']) != '1':
        raise TestError('Тестовый Android ещё не загрузился.')
    present = package_present(adb)
    if install and present:
        raise TestError('На #4 уже установлен ДругВокруг. Замена/удаление запрещены. Если это наша тестовая копия, используйте «Только проверка Gadget».')
    if not install and not present:
        raise TestError('На #4 ещё нет тестового приложения. Сначала установите тестовый комплект.')
    return original, target


def recheck(adb, identities):
    current = boot_id(adb, WORKING), boot_id(adb, TARGET)
    if current != identities or current[0] == current[1]:
        raise TestError('Устройство/перенаправление ADB изменилось. Операция остановлена.')


def validate_probe(value):
    keys = {'frida_version', 'arch', 'platform', 'unity_loaded', 'il2cpp_loaded', 'il2cpp_exports'}
    if not isinstance(value, dict) or set(value) != keys:
        raise TestError('Неожиданный формат ответа Gadget.')
    if value['frida_version'] != '17.24.1' or value['arch'] != 'arm64' or value['platform'] != 'linux':
        raise TestError('Неожиданная версия или архитектура Gadget.')
    if any(type(value[k]) is not bool for k in ('unity_loaded','il2cpp_loaded')):
        raise TestError('Неожиданный формат модулей Gadget.')
    exports = value['il2cpp_exports']
    if not isinstance(exports, dict) or set(exports) != set(EXPORTS) or any(type(v) is not bool for v in exports.values()):
        raise TestError('Неожиданный формат списка экспортов.')
    return value


def gadget_probe(port, token, cancelled):
    import frida
    if frida.__version__ != '17.24.1':
        raise TestError('Нужен клиент Frida 17.24.1.')
    manager = frida.get_device_manager()
    address = '127.0.0.1:'+str(port)
    cancel = frida.Cancellable()
    timer = threading.Timer(25, cancel.cancel)
    timer.daemon = True
    timer.start()
    device = session = script = None
    deadline = time.monotonic()+22
    try:
        with cancel:
            while time.monotonic() < deadline:
                if cancelled():
                    raise TestError('Проверка отменена. Тестовое приложение не удалено.')
                try:
                    if device is None:
                        device = manager.add_remote_device(address, token=token)
                    session = device.attach('Gadget')
                    script = session.create_script(PROBE_SCRIPT, name='dvk-fixed-metadata-only')
                    script.load()
                    result = validate_probe(script.exports_sync.probe())
                    if result['unity_loaded'] and result['il2cpp_loaded']:
                        return result
                    script.unload();script = None
                    session.detach();session = None
                except (frida.TransportError, frida.ServerNotRunningError, frida.ProcessNotFoundError):
                    pass
                threading.Event().wait(0.5)
        raise TestError('Gadget не подтвердил загрузку Unity/IL2CPP за отведённое время. Не обходите проверки приложения; пришлите отчёт.')
    except TestError:
        raise
    except Exception as exc:
        # Deliberately no repr(exc): remote errors can contain authentication values/paths.
        raise TestError('Gadget недоступен или несовместим с ARM-переводчиком MuMu. Нужен отчёт; root и обходы не используются.') from exc
    finally:
        timer.cancel()
        cleanup = frida.Cancellable()
        watchdog = threading.Timer(3, cleanup.cancel)
        watchdog.daemon = True
        watchdog.start()
        try:
            with cleanup:
                for operation in ((lambda: script.unload()) if script else None,
                                  (lambda: session.detach()) if session else None,
                                  (lambda: manager.remove_remote_device(address)) if device else None):
                    if operation:
                        try:operation()
                        except Exception:pass
        finally:
            watchdog.cancel()


def execute(adb, folder, install, progress=lambda text: None, cancelled=lambda: False, probe=gadget_probe):
    report = {'tool_version': VERSION, 'target': TARGET, 'working_instance': WORKING,
        'instances_verified_distinct': False, 'install_requested': bool(install),
        'test_apks_installed': False, 'working_device_modified': False,
        'root_used': False, 'ocr_used': False, 'messages_sent': 0,
        'unity_object_access': 'not-tested', 'probe_status': 'not-run'}
    stage = 'bundle-check'
    try:
        token = bundle_token(folder)
        progress('Проверяю, что #4 и рабочий MuMu — разные устройства…')
        stage = 'device-preflight'
        identities = preflight(adb, install)
        report['instances_verified_distinct'] = True
        if cancelled():raise TestError('Отменено до установки.')
        recheck(adb, identities)
        if install:
            if package_present(adb):raise TestError('Приложение появилось на #4; установка запрещена.')
            stage = 'install-test-apks'
            progress('Устанавливаю только на #4: 127.0.0.1:5563. Рабочий #0 не меняется…')
            response = adb.run(['-s', TARGET, 'install-multiple', str(folder/'base.apk'), str(folder/'split-001.apk')], timeout=240)
            if not re.search(r'^Success\s*$', response, re.M):
                raise TestError('Android не подтвердил установку. Автоматического удаления/повторной установки нет.')
            report['test_apks_installed'] = True
            recheck(adb, identities)
            stage = 'launch-test-app'
            response = adb.run(['-s', TARGET, 'shell', 'am', 'start', '-n', LAUNCHER])
            if re.search(r'(^|\n)(Error|Exception)', response):
                raise TestError('Android не подтвердил запуск тестового приложения.')
        if cancelled():raise TestError('Проверка отменена. Уже установленная тестовая копия остаётся на #4.')
        stage = 'probe-gadget'
        progress('Проверяю Gadget и наличие модулей Unity/IL2CPP; без чтения переписок…')
        value = adb.run(['-s', TARGET, 'forward', 'tcp:0', 'tcp:27042'])
        if not value.isdecimal() or not 1024 <= int(value) <= 65535:
            raise TestError('ADB вернул некорректный локальный порт.')
        adb.forward_port = int(value)
        report['gadget'] = validate_probe(probe(adb.forward_port, token, cancelled))
        report['probe_status'] = 'passed' if report['gadget']['unity_loaded'] and report['gadget']['il2cpp_loaded'] else 'modules-not-ready'
    except Exception as exc:
        report['probe_status'] = 'failed'
        report['failure_stage'] = stage
        report['error'] = str(exc) if isinstance(exc, TestError) else 'Локальная операция не завершена; проверьте комплект и ADB.'
    finally:
        if adb.forward_port is not None:
            try:adb.run(['-s', TARGET, 'forward', '--remove', f'tcp:{adb.forward_port}'], timeout=10)
            except Exception:report['forward_cleanup_failed'] = True
    # No boot IDs, tokens, package data, profile names or chat text are written.
    destination = folder.parent/'rootless-test-result.json'
    with destination.open('w', encoding='utf-8') as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report, destination


def launch_gui(self_check=False):
    import queue
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('ДругВокруг — тест Gadget только на MuMu #4')
    root.geometry('820x540')
    root.minsize(760, 500)
    main = ttk.Frame(root, padding=18);main.pack(fill='both', expand=True)
    ttk.Label(main,text='Только #4 / 127.0.0.1:5563 — без root и OCR',font=('Segoe UI',13,'bold')).pack(anchor='w')
    ttk.Label(main,text='Запустите оба MuMu: рабочий #0 (5555) и тестовый #4 (5563).\n'
        'Если на #4 уже есть ДругВокруг, установка остановится. Ничего не удаляйте.\n'
        'Проверка читает только наличие модулей/экспортов; не профили и не переписки.\n'
        'Аккаунт не переносится. Обход проверок приложения не выполняется.',wraplength=760).pack(anchor='w',pady=12)
    base = Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    adb_path = tk.StringVar(value=find_adb())
    folder = tk.StringVar(value=str(base/'test-apks'))
    for label, variable, picker in (
        ('ADB из MuMu:',adb_path,lambda:filedialog.askopenfilename(title='ADB из MuMu',filetypes=[('ADB','*.exe')])),
        ('Папка test-apks из частного комплекта:',folder,lambda:filedialog.askdirectory(title='Выберите test-apks'))):
        ttk.Label(main,text=label).pack(anchor='w')
        row=ttk.Frame(main);row.pack(fill='x',pady=(3,10))
        ttk.Entry(row,textvariable=variable).pack(side='left',fill='x',expand=True)
        def choose(var=variable,pick=picker):
            value=pick()
            if value:var.set(value)
        ttk.Button(row,text='Выбрать…',command=choose).pack(side='right',padx=(8,0))
    consent=tk.BooleanVar(value=False)
    ttk.Checkbutton(main,text='Разрешаю тест только на #4 (5563). Рабочий #0 (5555) не изменять.',variable=consent).pack(anchor='w',pady=8)
    state=tk.StringVar(value='Первый запуск: «Установить и проверить». Для повторного теста откройте приложение на #4.')
    ttk.Label(main,textvariable=state,wraplength=760).pack(anchor='w',pady=8)
    events=queue.Queue();stop=threading.Event();busy=False
    buttons=ttk.Frame(main);buttons.pack(fill='x',pady=10)
    def worker(binary, directory, install):
        try:
            selected=Path(directory).resolve(strict=True)
            reader=TestAdb(binary,selected)
            report,path=execute(reader,selected,install,lambda s:events.put(('status',s)),stop.is_set)
            events.put(('done',(report,str(path))))
        except Exception as exc:
            events.put(('error',str(exc) if isinstance(exc,TestError) else 'Проверьте папку тестовых APK, ADB и право записи отчёта.'))
    def start(install):
        nonlocal busy
        if busy:return
        if not consent.get():
            messagebox.showwarning('Нужно согласие','Подтвердите тест только на #4.');return
        busy=True;stop.clear()
        for b in actions:b.config(state='disabled')
        threading.Thread(target=worker,args=(adb_path.get(),folder.get(),install),daemon=True).start()
    actions=[ttk.Button(buttons,text='Установить и проверить на #4',command=lambda:start(True)),
             ttk.Button(buttons,text='Только проверка Gadget',command=lambda:start(False))]
    for b in actions:b.pack(side='left',padx=(0,10))
    ttk.Button(buttons,text='Отменить',command=stop.set).pack(side='left')
    ttk.Label(main,text='Отмена не удаляет уже установленную тестовую копию.\n'
        'Отчёт: rootless-test-result.json — прикрепите его в чат.',wraplength=760).pack(anchor='w',pady=8)
    def poll():
        nonlocal busy
        while not events.empty():
            kind,value=events.get_nowait()
            if kind=='status':state.set(value);continue
            busy=False
            for b in actions:b.config(state='normal')
            if kind=='error':state.set(value);messagebox.showerror('Проверка остановлена',value)
            else:
                report,path=value
                ok=report['probe_status']=='passed'
                message=('Gadget и модули Unity/IL2CPP доступны. Доступ к UI-объектам пока не проверен.' if ok else report.get('error','Проверка модулей не завершена.'))
                state.set(message)
                messagebox.showinfo('Результат теста',message+'\n\nПрикрепите в чат:\n'+path)
        root.after(100,poll)
    def close():
        if busy:
            stop.set();messagebox.showinfo('Отмена','Дождитесь завершения текущей ADB-операции. Она могла уже установить тестовую копию на #4.')
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    if self_check:
        root.update();assert root.winfo_viewable() and all(b.winfo_viewable() for b in actions)
        assert not consent.get()
        import frida
        assert frida.__version__=='17.24.1'
        root.destroy();return
    root.after(100,poll);root.mainloop()


if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'])
