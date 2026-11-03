"""Explicit opt-in Telegram notifications. No token/plaintext in reports or repo."""
import ctypes,json,os,re,urllib.request
from pathlib import Path
from urllib.parse import urlencode
class TelegramError(Exception):pass

def credentials(token,chat_id):
    if not isinstance(token,str) or not re.fullmatch(r'[0-9]{5,16}:[A-Za-z0-9_-]{20,128}',token):raise TelegramError('Проверь токен бота.')
    if not isinstance(chat_id,str) or not re.fullmatch(r'-?[1-9][0-9]{0,18}',chat_id):raise TelegramError('Проверь Chat ID.')
    return token,chat_id

def protect(data,*,decrypt=False):
    if os.name!='nt':raise TelegramError('Защищённое хранение доступно только в Windows.')
    from ctypes import wintypes
    class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buf=ctypes.create_string_buffer(data);src=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));dst=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    f=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    f.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)];f.restype=wintypes.BOOL
    if not f(ctypes.byref(src),None,None,None,None,1,ctypes.byref(dst)):raise TelegramError('Не удалось защитить настройки Windows.')
    try:return ctypes.string_at(dst.data,dst.size)
    finally:kernel.LocalFree(dst.data)

def settings_path():
    root=os.environ.get('LOCALAPPDATA')
    if not root:raise TelegramError('Нет папки настроек Windows.')
    if os.environ.get('DVK_MORELOGIN') == '1':
        from morelogin_common import root_directory
        return root_directory()/'telegram.dpapi'
    return Path(root)/'DvkRootless'/'telegram.dpapi'


def contacts_settings_path():
    """v1.3.112: a separate optional bot for NEW CONTACTS only.

    Everything else (exit notices, error documents, statistics, tests) keeps
    the primary credentials, so a contacts-only token never widens what the
    main bot may see. Same directory, same DPAPI storage rules.
    """
    root=os.environ.get('LOCALAPPDATA')
    if not root:raise TelegramError('Нет папки настроек Windows.')
    if os.environ.get('DVK_MORELOGIN') == '1':
        from morelogin_common import root_directory
        return root_directory()/'telegram-contacts.dpapi'
    return Path(root)/'DvkRootless'/'telegram-contacts.dpapi'

def save(token,chat_id,path=None,encoder=protect):
    token,chat_id=credentials(token.strip(),chat_id.strip());data=encoder(json.dumps({'token':token,'chat_id':chat_id}).encode())
    path=Path(path) if path is not None else settings_path();path.parent.mkdir(parents=True,exist_ok=True)
    # Never fall back to plaintext when DPAPI is unavailable.
    import tempfile
    fd,tmp=tempfile.mkstemp(prefix='.telegram-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def load(path=None,decoder=lambda data:protect(data,decrypt=True)):
    try:
        path=Path(path) if path is not None else settings_path()
        if path.stat().st_size>8192:raise TelegramError('Неверный файл настроек.')
        d=json.loads(decoder(path.read_bytes()));return credentials(d['token'],d['chat_id'])
    except Exception:raise TelegramError('Настройки Telegram недоступны. Сохрани их заново.') from None


def save_contacts(token,chat_id,path=None,encoder=protect):
    token,chat_id=credentials(token.strip(),chat_id.strip());data=encoder(json.dumps({'token':token,'chat_id':chat_id}).encode())
    path=Path(path) if path is not None else contacts_settings_path();path.parent.mkdir(parents=True,exist_ok=True)
    import tempfile
    fd,tmp=tempfile.mkstemp(prefix='.telegram-contacts-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def load_contacts(path=None,decoder=lambda data:protect(data,decrypt=True)):
    try:
        path=Path(path) if path is not None else contacts_settings_path()
        if path.stat().st_size>8192:raise TelegramError('Неверный файл настроек.')
        d=json.loads(decoder(path.read_bytes()));return credentials(d['token'],d['chat_id'])
    except Exception:raise TelegramError('Бот для контактов не настроен.') from None


def remove_contacts(path=None):
    path=Path(path) if path is not None else contacts_settings_path()
    try:os.unlink(path)
    except FileNotFoundError:pass


def contacts_configured(path=None):
    try:
        path=Path(path) if path is not None else contacts_settings_path()
        return path.is_file() and 0<path.stat().st_size<=8192
    except Exception:return False


def contact_credentials():
    """New contacts ride the dedicated bot when configured; else the main one.

    The fallback keeps pre-1.3.112 behavior until the operator saves a second
    token, and a missing/unreadable second file never blocks contact delivery.
    """
    if contacts_configured():
        try:return load_contacts()
        except Exception:pass
    return load()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def cloud_label(text):
    if os.environ.get('DVK_MORELOGIN') == '1' and os.environ.get('DVK_MORELOGIN_PHONE_ID'):
        from morelogin_common import phone_id
        return 'Cloud Phone ' + phone_id(os.environ['DVK_MORELOGIN_PHONE_ID']) + '\n' + text
    return text

def send(token,chat_id,text,opener=None,*,label=True):
    token,chat_id=credentials(token,chat_id)
    if not isinstance(text,str) or not 1<=len(text)<=3500:raise TelegramError('Слишком длинное уведомление.')
    if label:text=cloud_label(text)
    body=urlencode({'chat_id':chat_id,'text':text,'disable_web_page_preview':'true'}).encode()
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',data=body,method='POST',headers={'Content-Type':'application/x-www-form-urlencoded'})
    try:
        client=opener or urllib.request.build_opener(NoRedirect)
        with client.open(request,timeout=15) as response:
            data=json.loads(response.read(65537))
        return data.get('ok') is True and isinstance(data.get('result'),dict) and type(data['result'].get('message_id')) is int
    except Exception:raise TelegramError('Результат уведомления неизвестен. Автоповтора нет; проверь Telegram.') from None


def contact_message(items):
    """v1.3.112: the contact itself and nothing else.

    Phones lose the leading plus; Telegram handles keep their mandatory @;
    several contacts ride one per line. No header, no name, no disclaimer -
    the operator asked for a copy-paste-ready message body.
    """
    lines=[]
    for item in items:
        if not isinstance(item,str):raise TelegramError('Непроверенные данные контакта: отправка запрещена.')
        value=item[1:] if item.startswith('+') else item
        if not value or value.startswith('\n') or len(value)>64:raise TelegramError('Непроверенные данные контакта: отправка запрещена.')
        lines.append(value)
    text='\n'.join(lines)
    if not 1<=len(text)<=3500:raise TelegramError('Слишком длинное уведомление.')
    return text


def send_contact(token, chat_id, payload):
    from shared_contact import payload as validate
    try:
        if not isinstance(payload, dict) or set(payload) not in ({'name', 'contacts'}, {'name','contacts','photo'}):
            raise ValueError('Invalid payload')
        data = validate(payload['name'], payload['contacts'])
    except Exception:
        raise TelegramError('Непроверенные данные контакта: отправка запрещена.') from None
    text=contact_message(data['contacts'])
    if 'photo' in payload:
        from assistant_contact_photo import crop_top
        try:
            image=crop_top(payload['photo'],0.05)
        except Exception:
            # The status bar (time/battery) must never leak uncropped: the
            # contact text still goes out, the photo is dropped for this send.
            return send(token, chat_id, text, label=False)
        return send_photo(token,chat_id,text,image,label=False)
    return send(token, chat_id, text, label=False)


def send_photo(token,chat_id,caption,image,opener=None,*,label=True):
    token,chat_id=credentials(token,chat_id)
    from assistant_contact_photo import png_size
    png_size(image)
    if not isinstance(caption,str) or not 1<=len(caption)<=1024:raise TelegramError('Недопустимая подпись фото.')
    if label:caption=cloud_label(caption)
    if len(caption)>1024:raise TelegramError('Недопустимая подпись фото.')
    import secrets
    boundary='DvkPhoto'+secrets.token_hex(24);parts=[]
    for key,value in (('chat_id',chat_id),('caption',caption)):
        parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode())
    parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="photo"; filename="profile.png"\r\nContent-Type: image/png\r\n\r\n').encode()+image+b'\r\n')
    parts.append(('--'+boundary+'--\r\n').encode())
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendPhoto',data=b''.join(parts),method='POST',headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    try:
        client=opener or urllib.request.build_opener(NoRedirect)
        with client.open(request,timeout=30) as response:data=json.loads(response.read(65537))
        return data.get('ok') is True and isinstance(data.get('result'),dict) and type(data['result'].get('message_id')) is int
    except Exception:raise TelegramError('Результат отправки фото неизвестен. Автоповтора нет.') from None


def contact_notification(payload):
    token, chat_id = contact_credentials()
    return send_contact(token, chat_id, payload)


def settings_window(parent):
    from tkinter import Toplevel,StringVar
    from tkinter import ttk
    w=Toplevel(parent);w.title('Telegram · локальные настройки');w.resizable(False,False)
    f=ttk.Frame(w,padding=12);f.pack(fill='both',expand=True)
    token=StringVar();chat=StringVar();status=StringVar(value='Токен хранится через защиту Windows. Не попадает в JSON-отчёт.')
    for label,var,show in (('Токен бота',token,'*'),('Chat ID получателя',chat,'')):
        ttk.Label(f,text=label).pack(anchor='w');ttk.Entry(f,textvariable=var,show=show,width=58).pack(fill='x',pady=(2,8))
    # v1.3.112: a separate optional bot for NEW CONTACTS. Left empty on save,
    # the contacts bot is cleared and new contacts ride the main bot again.
    ttk.Separator(f).pack(fill='x',pady=(6,6))
    configured='настроен' if contacts_configured() else 'не настроен'
    ttk.Label(f,text='Бот для новых контактов (необязательно) · сейчас: '+configured).pack(anchor='w')
    ctoken=StringVar();cchat=StringVar()
    for label,var,show in (('Токен бота для контактов',ctoken,'*'),('Chat ID для контактов',cchat,'')):
        ttk.Label(f,text=label).pack(anchor='w');ttk.Entry(f,textvariable=var,show=show,width=58).pack(fill='x',pady=(2,8))
    def store():
        try:
            save(token.get(),chat.get());token.set('')
            if ctoken.get().strip() or cchat.get().strip():
                save_contacts(ctoken.get(),cchat.get())
                status.set('Сохранено. Отчёты и уведомления идут в первого бота, новые контакты — во второго.')
            else:
                remove_contacts()
                status.set('Сохранено. Всё идёт в первого бота (бот для контактов сброшен).')
            ctoken.set('');cchat.set('')
        except TelegramError as e:status.set(str(e))
    def test():
        test_button.config(state='disabled');save_button.config(state='disabled');status.set('Отправляю одно тестовое уведомление…')
        import threading,queue
        events=queue.Queue()
        def worker():
            try:
                t,c=load();ok=send(t,c,'✅ Тест уведомлений ДругВокруг');events.put('Тест принят Telegram.' if ok else 'Telegram не подтвердил приём.')
            except TelegramError as e:events.put(str(e))
        def poll():
            try:status.set(events.get_nowait());test_button.config(state='normal');save_button.config(state='normal')
            except queue.Empty:w.after(100,poll)
        threading.Thread(target=worker,daemon=True).start();w.after(100,poll)
    def test_contacts():
        contacts_button.config(state='disabled');status.set('Отправляю тест боту контактов…')
        import threading,queue
        events=queue.Queue()
        def worker():
            try:
                t,c=contact_credentials();ok=send(t,c,'✅ Тест бота для контактов');events.put('Тест принят Telegram.' if ok else 'Telegram не подтвердил приём.')
            except TelegramError as e:events.put(str(e))
        def poll():
            try:status.set(events.get_nowait());contacts_button.config(state='normal')
            except queue.Empty:w.after(100,poll)
        threading.Thread(target=worker,daemon=True).start();w.after(100,poll)
    row=ttk.Frame(f);row.pack(fill='x')
    save_button=ttk.Button(row,text='Сохранить',command=store);save_button.pack(side='left')
    test_button=ttk.Button(row,text='Отправить один тест',command=test);test_button.pack(side='left',padx=8)
    contacts_button=ttk.Button(row,text='Тест бота контактов',command=test_contacts);contacts_button.pack(side='left')
    ttk.Label(f,textvariable=status,wraplength=440).pack(anchor='w',pady=(8,0))


def send_json_document(token, chat_id, caption, document, opener=None):
    """One fixed-name JSON attachment; unknown outcomes are never retried."""
    token, chat_id = credentials(token, chat_id)
    if not isinstance(caption, str) or not 1 <= len(caption) <= 850:
        raise TelegramError('Недопустимая подпись отчёта.')
    caption = cloud_label(caption)
    if len(caption) > 1024 or type(document) is not bytes or not 2 <= len(document) <= 262144:
        raise TelegramError('Недопустимый JSON-отчёт.')
    try:
        if not isinstance(json.loads(document), dict):
            raise ValueError()
    except Exception:
        raise TelegramError('Недопустимый JSON-отчёт.') from None
    import secrets
    boundary = 'DvkReport' + secrets.token_hex(24)
    parts = []
    for key, value in (('chat_id', chat_id), ('caption', caption)):
        parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode())
    parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="document"; filename="last-monitor.json"\r\nContent-Type: application/json\r\n\r\n').encode()+document+b'\r\n')
    parts.append(('--'+boundary+'--\r\n').encode())
    request = urllib.request.Request('https://api.telegram.org/bot'+token+'/sendDocument',
        data=b''.join(parts), method='POST', headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    try:
        client = opener or urllib.request.build_opener(NoRedirect)
        with client.open(request, timeout=15) as response:
            data = json.loads(response.read(65537))
        return data.get('ok') is True and isinstance(data.get('result'), dict) and type(data['result'].get('message_id')) is int
    except Exception:
        raise TelegramError('Результат отправки отчёта неизвестен. Автоповтора нет.') from None
