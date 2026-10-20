"""Explicit local plaintext copy of the latest verified bound-chat snapshot.

Never sent to GitHub/Telegram/agent. Not a complete chronological archive.
"""
import json
import os
import tempfile
from pathlib import Path
from one_chat_probe import identity


def validate(snapshot, expected):
    if not isinstance(snapshot,dict) or set(snapshot) != {'identity','messages'} or identity(snapshot['identity']) != identity(expected):
        raise ValueError('Wrong local transcript binding')
    messages = snapshot['messages']
    if not isinstance(messages,list) or len(messages)>20:
        raise ValueError('Invalid local transcript size')
    seen=set()
    for m in messages:
        if not isinstance(m,dict) or set(m)!={'id','sender','text'}:
            raise ValueError('Invalid local transcript message')
        identity(dict(account=expected['account'],peer=expected['peer'],chat=m['id']))
        if m['id'] in seen or m['sender'] not in (expected['account'],expected['peer']):
            raise ValueError('Invalid local transcript identity')
        seen.add(m['id'])
        if m['text'] is not None and (not isinstance(m['text'],str) or len(m['text'])>2048 or '\0' in m['text']):
            raise ValueError('Invalid local transcript text')
    if sum(len(m['text'] or '') for m in messages)>16384:
        raise ValueError('Local transcript limit')
    return snapshot


def save(snapshot, expected, folder=None):
    validate(snapshot,expected)
    if folder is None:
        if not os.environ.get('LOCALAPPDATA'):raise ValueError('LOCALAPPDATA required')
        folder=Path(os.environ['LOCALAPPDATA'])/'DvkRootless'
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'one-chat-transcript.json'
    temp=None
    value=dict(format='owned-test-chat-latest-snapshot-v1',chronological_order_verified=False,**snapshot)
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=folder,prefix='.one-chat-transcript-',suffix='.tmp',delete=False) as f:
            temp=Path(f.name)
            # Windows inherits the profile ACL; no extra ACL/encryption is promised.
            if os.name!='nt':os.fchmod(f.fileno(),0o600)
            json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if temp is not None:temp.unlink(missing_ok=True)
    return path


def display(snapshot, expected):
    validate(snapshot,expected)
    lines=['Последний проверенный снимок. Порядок коллекции НЕ подтверждён как время.','']
    for i,m in enumerate(snapshot['messages'],1):
        sender='Я' if m['sender']==expected['account'] else 'Мой второй аккаунт'
        lines.extend([f'{i}. {sender}', m['text'] if m['text'] is not None else '[Нетекстовое сообщение]', ''])
    return '\n'.join(lines)
