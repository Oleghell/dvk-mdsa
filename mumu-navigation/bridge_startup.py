"""Local one-button startup: no remote opt-in, reset, messages or shell access."""
import os
from pathlib import Path
import shutil
from mumu_bridge import BridgeError, content_pixel_sha256, install_helper_with_local_consent

STARTUP_CONSENT = (
    'Включить строгий нативный доступ к ДругВокруг?\n\n'
    'Текст и свойства доступных Android-элементов передаются агенту через Cloudflare с секретным ключом. '
    'Скриншоты, OCR, CV и координатные клики запрещены.\n\n'
    'Разрешаются только именованные нативные действия. Отправка сообщений и платные действия не предоставляются. '
    'Установится один проверенный APK; ДругВокруг и журналы не удаляются. Клавиатура не меняется.\n\n'
    'Лимиты сохраняются; тест сам не стартует. Это не доступ ко всему ПК. '
    '«Остановить доступ» закроет новые команды; начатое действие может завершиться.'
)


def discover_adb(base, *, environ=None, which=None):
    """Look in finite known local locations. Never run candidates or scan disks."""
    env=os.environ if environ is None else environ
    find=shutil.which if which is None else which
    base=Path(base)
    candidates=[base/'adb.exe',base/'adb_server.exe']
    for name in ('adb.exe','adb_server.exe'):
        found=find(name)
        if found:candidates.append(Path(found))
    roots=[Path(env[key]) for key in ('ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA') if env.get(key)]
    for root in roots:
        for product in ('MuMuPlayer-12.0','MuMuPlayerGlobal-12.0','MuMuPlayer','MuMu'):
            for vendor in ('Netease','NetEase',''):
                folder=root/vendor/product if vendor else root/product
                candidates.extend((folder/'shell'/'adb.exe',folder/'shell'/'adb_server.exe',folder/'adb.exe'))
    home=Path(env.get('USERPROFILE',str(Path.home())))
    candidates.extend((home/'Desktop'/'platform-tools'/'adb.exe',home/'AppData'/'Local'/'Android'/'Sdk'/'platform-tools'/'adb.exe'))
    for candidate in candidates:
        if candidate.is_file():return str(candidate.resolve())
    return None


def prepare_device(facade,base,cancelled,progress,*,consent):
    """Finish all device setup before exposing a server or a public URL."""
    from universal_control import enable_locally,stop_locally,UniversalControl
    if consent is not True:raise BridgeError('Локальное разрешение не получено. Действий не было.')
    reader=facade.inner
    def check():
        if cancelled.is_set():raise BridgeError('Запуск отменён. Доступ закрыт.')
    try:
        check();progress('Подключаюсь к MuMu…');facade.connect()
        if getattr(reader,'native_only',False) is True:
            from universal_control import enable_native_locally
            from ui_backend import NativeBackend
            check();progress('Проверяю приложение без захвата экрана…');reader._foreground()
            check();progress('Устанавливаю один нативный помощник; клавиатура не меняется…')
            enable_native_locally(reader,facade.ledger,base)
            check();progress('Проверяю Accessibility без изображений и действий…')
            NativeBackend(reader,facade.ledger).diagnostics()
            check();return
        check();progress('Проверяю ДругВокруг и экран 900×1600…')
        content_pixel_sha256(reader.screen())
        check();progress('Проверяю и устанавливаю помощники…')
        install_helper_with_local_consent(reader,base,lambda:consent is True and not cancelled.is_set())
        check();progress('Включаю клавиатуру для ввода по буквам…')
        enable_locally(reader,facade.ledger,base)
        check();progress('Проверяю готовность управления — без нажатий и ввода…')
        UniversalControl(reader,facade.ledger).inspect()
        check()
    except BaseException:
        if getattr(reader,'control_enabled',False):
            try:stop_locally(reader,facade.ledger)
            except Exception:raise BridgeError('Запуск остановлен. Верните обычную клавиатуру через настройки Android → Язык и ввод.') from None
        raise


def confirm_startup(parent):
    """One bounded, scrollable consent dialog; action buttons never scroll away."""
    import tkinter as tk
    accepted=False
    dialog=tk.Toplevel(parent,name='startup_consent')
    dialog.title('Включить MuMu и разрешить доступ?')
    dialog.transient(parent)
    width=min(680,max(300,parent.winfo_screenwidth()-80))
    height=min(500,max(260,parent.winfo_screenheight()-100))
    x=max(0,(parent.winfo_screenwidth()-width)//2)
    y=max(0,(parent.winfo_screenheight()-height)//2)
    dialog.geometry(f'{width}x{height}+{x}+{y}')
    actions=tk.Frame(dialog);actions.pack(side='bottom',fill='x',padx=12,pady=12)
    def finish(value):
        nonlocal accepted
        accepted=value
        dialog.destroy()
    tk.Button(actions,text='Отмена',command=lambda:finish(False),width=14).pack(side='right',padx=6)
    tk.Button(actions,text='Разрешить',command=lambda:finish(True),width=14).pack(side='right',padx=6)
    frame=tk.Frame(dialog);frame.pack(fill='both',expand=True,padx=14,pady=14)
    scrollbar=tk.Scrollbar(frame);scrollbar.pack(side='right',fill='y')
    text=tk.Text(frame,wrap='word',yscrollcommand=scrollbar.set,relief='flat',font=('Arial',11))
    text.insert('1.0',STARTUP_CONSENT);text.configure(state='disabled')
    text.pack(side='left',fill='both',expand=True);scrollbar.configure(command=text.yview)
    dialog.protocol('WM_DELETE_WINDOW',lambda:finish(False))
    dialog.bind('<Escape>',lambda event:finish(False))
    dialog.grab_set()
    parent.wait_window(dialog)
    return accepted
