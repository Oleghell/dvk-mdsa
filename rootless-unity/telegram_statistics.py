"""One local consumer per bot; aggregate queries and explicit MuMu deny commands from configured chat ID.

No remote Start/Stop, no device actions, no contacts in replies. Update IDs are
committed BEFORE sending: an uncertain Telegram response is never retried.
"""
import hashlib
import json
import os
from pathlib import Path
import threading
import urllib.request
from urllib.parse import urlencode
import telegram_notify as telegram
from assistant_statistics import COMMANDS,render


def fetch(token,offset,opener=None):
    telegram.credentials(token,'1')
    body=urlencode(dict(offset=offset,timeout=10,limit=30,allowed_updates=json.dumps(['message']))).encode()
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/getUpdates',data=body,method='POST')
    with (opener or urllib.request.build_opener(telegram.NoRedirect)).open(request,timeout=15) as response:
        raw=response.read(262145)
    if len(raw)>262144:raise ValueError('Updates too large')
    value=json.loads(raw)
    if not isinstance(value,dict) or value.get('ok') is not True or not isinstance(value.get('result'),list):raise ValueError('Invalid updates')
    updates=value['result']
    if len(updates)>30 or any(not isinstance(u,dict) or type(u.get('update_id')) is not int or u['update_id']<0 for u in updates):raise ValueError('Invalid update IDs')
    return sorted(updates,key=lambda u:u['update_id'])


def command(update,chat):
    message=update.get('message')
    if not isinstance(message,dict) or not isinstance(message.get('chat'),dict):return None
    # int only: no coercion of malicious JSON objects or boolean IDs.
    cid=message['chat'].get('id')
    if type(cid) is not int or str(cid)!=chat:return None
    text=message.get('text')
    if type(text) is not str or len(text)>100:return None
    import re
    found=re.fullmatch(r'(/today|/yesterday|/week|/month|/city)(?:@[A-Za-z0-9_]{5,32})?\s*',text)
    if found:return found[1]
    # Mutating commands require the configured PRIVATE chat and its own sender.
    # Forwarded/channel/group messages cannot write the shared deny registry.
    sender=message.get('from')
    if (cid <= 0 or message['chat'].get('type') != 'private'
        or not isinstance(sender,dict) or type(sender.get('id')) is not int
        or sender['id'] != cid or sender.get('is_bot') is not False
        or any(k in message for k in ('forward_origin','forward_from','forward_from_chat','forward_date','sender_chat'))):
        return None
    found=re.fullmatch(r'/num(?:@[A-Za-z0-9_]{5,32})?(?:\s+([^\r\n]+?))?\s*',text)
    return ('/num' + ((' ' + found[1].strip()) if found[1] else '')) if found else None


def cycle(token,chat,offset,commit,*,fetcher=fetch,sender=telegram.send,renderer=render,blocker=None):
    updates=fetcher(token,offset)
    for update in updates:
        uid=update['update_id']
        if uid<offset:continue
        commit(uid+1)  # Failure here means NO reply, never a duplicate on restart.
        offset=uid+1
        action=command(update,chat)
        if action:
            if action == '/num' or action.startswith('/num '):
                text=manual_reply(action,blocker=blocker)
            else:
                try:text=renderer(action)
                except Exception:text='Статистика временно недоступна. Рабочая база не изменена.'
            try:sender(token,chat,text)
            except Exception:pass  # May have been accepted, no resend.
    return offset



def manual_reply(action, *, blocker=None):
    """Acknowledge only a committed deny; malformed IDs never reach SQLite."""
    from conversation_engine import identifier
    try:
        parts=action.split()
        if len(parts) != 2 or parts[0] != '/num':raise ValueError()
        peer=identifier(parts[1])
    except Exception:
        return 'Использование: /num <ID пользователя ДругВокруг>. Только положительный числовой ID, не номер телефона и не Chat ID.'
    try:
        if blocker is None:
            from mumu_peer_policy import manual_block
            blocker=manual_block
        inserted=blocker(peer)
        if type(inserted) is not bool:raise ValueError()
    except Exception:
        return 'Запрет не подтверждён. Проверь общую базу MuMu и права доступа. Автоматического повтора команды нет.'
    return ('ID '+peer+(': ручной запрет сохранён.' if inserted else ': запрет уже существует.')+
        ' Новые сообщения запрещены на всех портах MuMu. Уже начавшуюся отправку отменить нельзя; журналы неизвестных отправок не изменены.')


def serve(stop):
    # GUI process only; workers do not start a Telegram reader.
    while not stop.is_set():
        try:
            token,chat=telegram.load()
            root=Path(os.environ['LOCALAPPDATA'])/'DvkTelegramStatistics';root.mkdir(parents=True,exist_ok=True)
            key=hashlib.sha256(token.encode()).hexdigest()
            # Windows file lock coordinates MuMu/MoreLogin and multiple GUIs.
            import msvcrt
            with (root/(key+'.lock')).open('a+b') as guard:
                guard.seek(0,2)
                if not guard.tell():guard.write(b'0');guard.flush()
                guard.seek(0);msvcrt.locking(guard.fileno(),msvcrt.LK_NBLCK,1)
                try:
                    path=root/(key+'.json')
                    def commit(offset):
                        temporary=path.with_suffix('.tmp')
                        temporary.write_text(json.dumps(dict(offset=offset)),encoding='utf-8');os.replace(temporary,path)
                    if path.exists():
                        if path.stat().st_size>128:raise ValueError('Invalid state')
                        offset=json.loads(path.read_text(encoding='utf-8'))['offset']
                        if type(offset) is not int or offset<0:raise ValueError('Invalid offset')
                    else:
                        # Drop pending old commands once, don't answer ancient messages.
                        updates=fetch(token,-1);offset=max((u['update_id']+1 for u in updates),default=0);commit(offset)
                    while not stop.is_set():
                        try:
                            if telegram.load()!=(token,chat):break
                            offset=cycle(token,chat,offset,commit)
                        except Exception:
                            if stop.wait(10):break
                        if stop.wait(1):break
                finally:
                    guard.seek(0);msvcrt.locking(guard.fileno(),msvcrt.LK_UNLCK,1)
        except Exception:
            stop.wait(10)


def start():
    stop=threading.Event()
    threading.Thread(target=serve,args=(stop,),name='telegram-statistics',daemon=True).start()
    return stop
