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
    return Path(root)/'DvkRootless'/'telegram.dpapi'

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

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def send(token,chat_id,text,opener=None):
    token,chat_id=credentials(token,chat_id)
    if not isinstance(text,str) or not 1<=len(text)<=3500:raise TelegramError('Слишком длинное уведомление.')
    body=urlencode({'chat_id':chat_id,'text':text,'disable_web_page_preview':'true'}).encode()
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',data=body,method='POST',headers={'Content-Type':'application/x-www-form-urlencoded'})
    try:
        client=opener or urllib.request.build_opener(NoRedirect)
        with client.open(request,timeout=15) as response:
            data=json.loads(response.read(65537))
        return data.get('ok') is True and isinstance(data.get('result'),dict) and type(data['result'].get('message_id')) is int
    except Exception:raise TelegramError('Результат уведомления неизвестен. Автоповтора нет; проверь Telegram.') from None

def send_contact(token, chat_id, payload):
    from shared_contact import payload as validate
    try:
        if not isinstance(payload, dict) or set(payload) != {'name', 'contacts'}:
            raise ValueError('Invalid payload')
        data = validate(payload['name'], payload['contacts'])
    except Exception:
        raise TelegramError('Непроверенные данные контакта: отправка запрещена.') from None
    return send(token, chat_id, '🔥 Собеседник поделился контактом\nИмя: ' + data['name'] + '\nКонтакт: ' + ', '.join(data['contacts']))


def contact_notification(payload):
    token, chat_id = load()
    return send_contact(token, chat_id, payload)


def settings_window(parent):
    from tkinter import Toplevel,StringVar
    from tkinter import ttk
    w=Toplevel(parent);w.title('Telegram · локальные настройки');w.resizable(False,False)
    f=ttk.Frame(w,padding=12);f.pack(fill='both',expand=True)
    token=StringVar();chat=StringVar();status=StringVar(value='Токен хранится через защиту Windows. Не попадает в JSON-отчёт.')
    for label,var,show in (('Токен бота',token,'*'),('Chat ID получателя',chat,'')):
        ttk.Label(f,text=label).pack(anchor='w');ttk.Entry(f,textvariable=var,show=show,width=58).pack(fill='x',pady=(2,8))
    def store():
        try:save(token.get(),chat.get());token.set('');status.set('Сохранено. Уведомления включаются отдельной галочкой в окне автоцепочки.')
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
    row=ttk.Frame(f);row.pack(fill='x')
    save_button=ttk.Button(row,text='Сохранить',command=store);save_button.pack(side='left')
    test_button=ttk.Button(row,text='Отправить один тест',command=test);test_button.pack(side='left',padx=8)
    ttk.Label(f,textvariable=status,wraplength=440).pack(anchor='w',pady=(8,0))
