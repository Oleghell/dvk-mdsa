"""Explicit local plaintext copy of the latest verified bound-chat snapshot.

Never sent to GitHub/Telegram/agent. Not a complete chronological archive.
"""
from chat_limits import MAX_MESSAGES, MAX_TEXT, MAX_TOTAL_TEXT

import json
import os
import tempfile
from pathlib import Path
from one_chat_probe import identity


def validate(snapshot, expected):
    if not isinstance(snapshot,dict) or set(snapshot) != {'identity','messages'} or identity(snapshot['identity']) != identity(expected):
        raise ValueError('Wrong local transcript binding')
    messages = snapshot['messages']
    if not isinstance(messages,list) or len(messages)>MAX_MESSAGES:
        raise ValueError('Invalid local transcript size')
    seen=set()
    for m in messages:
        if not isinstance(m,dict) or set(m)!={'id','sender','text'}:
            raise ValueError('Invalid local transcript message')
        identity(dict(account=expected['account'],peer=expected['peer'],chat=m['id']))
        if m['id'] in seen or m['sender'] not in (expected['account'],expected['peer']):
            raise ValueError('Invalid local transcript identity')
        seen.add(m['id'])
        if m['text'] is not None and (not isinstance(m['text'],str) or len(m['text'])>MAX_TEXT or '\0' in m['text']):
            raise ValueError('Invalid local transcript text')
    if sum(len(m['text'] or '') for m in messages)>MAX_TOTAL_TEXT:
        raise ValueError('Local transcript limit')
    return snapshot


def presentation_messages(snapshot, expected):
    """Reverse the user-observed newest-first source for presentation ONLY.

    No timestamps are verified, IDs are not sorted, and the source is untouched.
    The reader, deduplication and manual-send guards keep the original snapshot.
    """
    validate(snapshot,expected)
    return [dict(m) for m in reversed(snapshot['messages'])]


def save(snapshot, expected, folder=None):
    validate(snapshot,expected)
    if folder is None:
        if not os.environ.get('LOCALAPPDATA'):raise ValueError('LOCALAPPDATA required')
        folder=Path(os.environ['LOCALAPPDATA'])/'DvkRootless'
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'one-chat-transcript.json'
    temp=None
    value=dict(format='owned-test-chat-latest-snapshot-v2',chronological_order_verified=False,
               presentation_order='reversed-source-collection',order_basis='user-observed-newest-first',
               identity=dict(snapshot['identity']),messages=presentation_messages(snapshot,expected))
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
    lines=['От начала к концу · обратный порядок коллекции.',
           'Порядок по времени НЕ подтверждён автоматически.','']
    for i,m in enumerate(presentation_messages(snapshot,expected),1):
        sender='Я' if m['sender']==expected['account'] else 'Мой второй аккаунт'
        lines.extend([f'{i}. {sender}', m['text'] if m['text'] is not None else '[Нетекстовое сообщение]', ''])
    return '\n'.join(lines)
