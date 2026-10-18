"""Read-only installed APK export. No image, root, install or app-data API."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone

PACKAGE = 'drug.vokrug'
SERIAL = '127.0.0.1:5555'
VERSION = '0.1.0'
MAX_APKS = 33
MAX_APK_BYTES = 1024 ** 3
MAX_TOTAL_BYTES = 2 * 1024 ** 3


class ExportError(RuntimeError):
    pass


def parse_apk_paths(text: str) -> list[str]:
    if len(text) > 32768:
        raise ExportError('Слишком длинный ответ ADB.')
    paths = []
    for line in text.splitlines():
        if not line:
            continue
        if not line.startswith('package:'):
            raise ExportError('ADB вернул неожиданный ответ вместо путей APK.')
        path = line[len('package:'):]
        if not re.fullmatch(r'/data/app/[A-Za-z0-9_+=.@~/-]+', path):
            raise ExportError('Небезопасный или неподдерживаемый путь APK.')
        parts = path.split('/')
        if any(p in ('.', '..', '') for p in parts[1:]):
            raise ExportError('Некорректный путь APK.')
        # Android layouts: /data/app/package-token/base.apk or /data/app/~~token/package-token/base.apk
        if len(parts) not in (5, 6) or (len(parts) == 6 and not parts[3].startswith('~~')):
            raise ExportError('Неизвестное расположение установленных APK.')
        if not re.fullmatch(re.escape(PACKAGE) + r'-[A-Za-z0-9_+=.@~-]+', parts[-2]):
            raise ExportError('Путь не принадлежит установленному ДругВокруг.')
        if parts[-1] != 'base.apk' and not re.fullmatch(r'split_[A-Za-z0-9_.-]+\.apk', parts[-1]):
            raise ExportError('Неожиданное имя APK.')
        paths.append(path)
    if not paths or len(paths) > MAX_APKS or len(paths) != len(set(paths)):
        raise ExportError('Список APK пуст, содержит повторы или слишком велик.')
    if sum(PurePosixPath(p).name == 'base.apk' for p in paths) != 1:
        raise ExportError('Не найден единственный base.apk.')
    if len({str(PurePosixPath(p).parent) for p in paths}) != 1:
        raise ExportError('APK находятся в разных каталогах установки.')
    return sorted(paths, key=lambda p: (PurePosixPath(p).name != 'base.apk', p))


class AdbReader:
    """All subprocess commands pass a finite allowlist; never shell=True."""
    def __init__(self, executable: str):
        self.executable = str(Path(executable).resolve(strict=True))
        if Path(self.executable).name.lower() not in ('adb.exe', 'adb_server.exe', 'adb'):
            raise ExportError('Выберите adb.exe или adb_server.exe из MuMu/platform-tools.')

    @staticmethod
    def validate_args(args: list[str]) -> None:
        if args in (['version'], ['connect', SERIAL], ['-s', SERIAL, 'get-state'],
                    ['-s', SERIAL, 'shell', 'pm', 'path', PACKAGE]):
            return
        if len(args) == 5 and args[:3] == ['-s', SERIAL, 'pull']:
            # Reuse the complete path parser, including package ownership.
            remote = args[3]
            basename = PurePosixPath(remote).name
            base = str(PurePosixPath(remote).with_name('base.apk'))
            parse_apk_paths('package:' + remote + ('\npackage:' + base if basename != 'base.apk' else ''))
            local = Path(args[4])
            if not local.is_absolute() or not re.fullmatch(r'(base|split-\d{3})\.apk', local.name):
                raise ExportError('Недопустимый локальный путь APK.')
            if local.exists():
                raise ExportError('Перезапись файлов запрещена.')
            return
        raise ExportError('Команда не входит в разрешённый read-only список.')

    def run(self, args: list[str], timeout: int = 30) -> str:
        self.validate_args(args)
        env = os.environ.copy()
        for key in ('ADB_SERVER_SOCKET', 'ANDROID_ADB_SERVER_PORT', 'ANDROID_SERIAL'):
            env.pop(key, None)
        env['ADB_SERVER_SOCKET'] = 'tcp:localhost:5037'
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        try:
            with tempfile.TemporaryFile() as out:
                result = subprocess.run([self.executable, *args], shell=False, env=env,
                                        stdout=out, stderr=subprocess.STDOUT,
                                        timeout=timeout, creationflags=flags)
                out.seek(0)
                data = out.read(65537)
            if len(data) > 65536:
                raise ExportError('Слишком длинный ответ ADB.')
            if result.returncode:
                raise ExportError('ADB завершил операцию с ошибкой. Проверьте MuMu и разрешение ADB; root не нужен.')
            return data.decode('utf-8', errors='replace').strip()
        except subprocess.TimeoutExpired as exc:
            raise ExportError('ADB не ответил вовремя. Проверьте подключение MuMu.') from exc
        except OSError as exc:
            raise ExportError('Не удалось запустить выбранный ADB.') from exc


def validate_apk(path: Path) -> dict:
    size = path.stat().st_size
    if size <= 0 or size > MAX_APK_BYTES:
        raise ExportError('Недопустимый размер APK.')
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 150000 or sum(e.filename == 'AndroidManifest.xml' for e in entries) != 1:
                raise ExportError('APK не содержит единственный AndroidManifest.xml.')
            if any(e.flag_bits & 1 for e in entries):
                raise ExportError('Зашифрованные APK не поддерживаются.')
    except zipfile.BadZipFile as exc:
        raise ExportError('Полученный файл не является APK/ZIP.') from exc
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'size_bytes': size, 'sha256': digest.hexdigest()}


def export_apks(reader: AdbReader, destination: Path, progress=lambda text: None,
                cancelled=lambda: False) -> Path:
    destination = destination.resolve(strict=True)
    if not destination.is_dir():
        raise ExportError('Выберите существующую папку для архива.')
    # Source staging + ZIP need space; do not risk filling the user's system disk.
    if shutil.disk_usage(destination).free < 2 * MAX_TOTAL_BYTES + 256 * 1024 ** 2:
        raise ExportError('Для безопасного экспорта нужно не менее 4,25 ГБ свободного места.')
    def check():
        if cancelled():
            raise ExportError('Экспорт отменён. Рабочее приложение не изменено.')
    check()
    progress('Подключение к MuMu; только чтение установочных APK…')
    reader.run(['version'])
    reader.run(['connect', SERIAL])
    if reader.run(['-s', SERIAL, 'get-state']) != 'device':
        raise ExportError('MuMu недоступен на 127.0.0.1:5555. Проверьте разрешение ADB.')
    paths = parse_apk_paths(reader.run(['-s', SERIAL, 'shell', 'pm', 'path', PACKAGE]))
    manifest = {'format': 'dvk-apk-source-v1', 'exporter_version': VERSION, 'package': PACKAGE,
                'package_identity': 'adb-pm-path-not-yet-offline-verified',
                'app_version': 'not-checked', 'files': [], 'app_data_included': False,
                'apk_modified': False, 'root_used': False}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    result = destination / f'Dvk-apk-source-{stamp}-{uuid.uuid4().hex[:12]}.zip'
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix='.dvk-apks-', dir=destination) as temp:
            staging = Path(temp)
            total = 0
            for index, remote in enumerate(paths):
                check()
                name = 'base.apk' if index == 0 else f'split-{index:03}.apk'
                progress(f'Копирую установочный файл {index + 1}/{len(paths)}…')
                local = staging / name
                reader.run(['-s', SERIAL, 'pull', remote, str(local)], timeout=180)
                check()
                info = validate_apk(local)
                total += info['size_bytes']
                if total > MAX_TOTAL_BYTES:
                    raise ExportError('Установочный комплект превышает лимит 2 ГБ.')
                manifest['files'].append({'file': name, 'original_basename': PurePosixPath(remote).name, **info})
            # Detect an app update racing with the export; no stale mixed-install set.
            current = parse_apk_paths(reader.run(['-s', SERIAL, 'shell', 'pm', 'path', PACKAGE]))
            if current != paths:
                raise ExportError('Приложение обновилось во время копирования. Повторите экспорт.')
            check()
            with result.open('xb') as raw:
                created = True
                with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                    for item in manifest['files']:
                        check()
                        archive.write(staging / item['file'], item['file'])
                    archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        progress('Готово. Передайте ZIP в чат; автоматической отправки нет.')
        return result
    except BaseException:
        if created:
            result.unlink(missing_ok=True)
        raise


def find_adb() -> str:
    candidates = []
    for var in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if not os.environ.get(var):
            continue
        root = Path(os.environ[var])
        for product in ('MuMuPlayer-12.0', 'MuMuPlayerGlobal-12.0', 'MuMuPlayer', 'MuMu'):
            for parent in (root, root / 'Netease', root / 'MuMu'):
                for name in ('adb.exe', 'adb_server.exe'):
                    candidates.extend((parent / product / 'shell' / name, parent / product / name))
    candidates.append(Path.home() / 'AppData/Local/Android/Sdk/platform-tools/adb.exe')
    return next((str(p) for p in candidates if p.is_file()), '')


def launch_gui(self_check=False):
    import queue
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('ДругВокруг — экспорт APK без root / OCR')
    root.geometry('760x440')
    root.minsize(700, 400)
    main = ttk.Frame(root, padding=18)
    main.pack(fill='both', expand=True)
    ttk.Label(main, text='Подготовка rootless-теста: только установочные файлы',
              font=('Segoe UI', 12, 'bold')).pack(anchor='w')
    ttk.Label(main, text='Рабочее приложение не удаляется и не изменяется.\n'
              'Нет OCR, снимков экрана, чтения переписок, установки APK и root.\n'
              'Запустите рабочий MuMu с ADB на 127.0.0.1:5555.', wraplength=700).pack(anchor='w', pady=10)
    adb = tk.StringVar(value=find_adb())
    destination = tk.StringVar(value=str(Path.home() / 'Desktop' if (Path.home() / 'Desktop').is_dir() else Path.home()))
    for label, variable, picker in (
        ('ADB из MuMu / platform-tools:', adb, lambda: filedialog.askopenfilename(title='Выберите adb.exe из MuMu', filetypes=[('ADB', '*.exe')])),
        ('Папка для ZIP:', destination, lambda: filedialog.askdirectory(title='Папка для ZIP')),
    ):
        ttk.Label(main, text=label).pack(anchor='w')
        row = ttk.Frame(main)
        row.pack(fill='x', pady=(2, 8))
        ttk.Entry(row, textvariable=variable).pack(side='left', fill='x', expand=True)
        def choose(var=variable, get=picker):
            value = get()
            if value:
                var.set(value)
        ttk.Button(row, text='Выбрать…', command=choose).pack(side='right', padx=(8, 0))
    consent = tk.BooleanVar(value=False)
    ttk.Checkbutton(main, text='Разрешаю скопировать только APK ДругВокруг в локальный ZIP.', variable=consent).pack(anchor='w', pady=8)
    status = tk.StringVar(value='Архив может быть большим. Требуется 4,25 ГБ свободного места.')
    ttk.Label(main, textvariable=status, wraplength=700).pack(anchor='w', pady=8)
    events = queue.Queue()
    stop = threading.Event()
    busy = False
    def worker(binary, folder):
        try:
            result = export_apks(AdbReader(binary), Path(folder), lambda s: events.put(('status', s)), stop.is_set)
            events.put(('done', str(result)))
        except Exception as exc:
            events.put(('error', str(exc) if isinstance(exc, ExportError) else 'Не удалось создать ZIP. Проверьте доступ к папке и свободное место.'))
    def start():
        nonlocal busy
        if busy:
            return
        if not consent.get():
            messagebox.showwarning('Нужно согласие', 'Подтвердите копирование установочных APK.')
            return
        busy = True
        stop.clear()
        start_button.config(state='disabled')
        threading.Thread(target=worker, args=(adb.get(), destination.get()), daemon=True).start()
    buttons = ttk.Frame(main)
    buttons.pack(fill='x', pady=8)
    start_button = ttk.Button(buttons, text='Скопировать APK в ZIP', command=start)
    start_button.pack(side='left')
    ttk.Button(buttons, text='Отменить', command=stop.set).pack(side='left', padx=10)
    def poll():
        nonlocal busy
        while not events.empty():
            kind, text = events.get_nowait()
            status.set(text)
            if kind in ('done', 'error'):
                busy = False
                start_button.config(state='normal')
                if kind == 'done':
                    messagebox.showinfo('ZIP создан', 'Прикрепите в чат этот файл:\n' + text + '\n\nПриложение в MuMu не изменено.')
                else:
                    messagebox.showerror('Экспорт не завершён', text)
        root.after(100, poll)
    def close():
        if busy:
            stop.set()
            messagebox.showinfo('Отмена', 'Дождитесь окончания текущего копирования; временные файлы будут удалены.')
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    if self_check:
        root.update()
        assert root.winfo_viewable() and start_button.winfo_viewable()
        assert not consent.get()
        root.destroy()
        return
    root.after(100, poll)
    root.mainloop()


if __name__ == '__main__':
    import sys
    if sys.argv[1:] not in ([], ['--self-check']):
        raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:] == ['--self-check'])
