"""One user-started, read-only current-profile ID check. No enrolment or sends.

The displayed footer is NOT scraped or assumed equal. An optional manually
entered footer ID is compared locally by the settings dialog.
"""
from cloud_database import connect as primary_connect, readonly as primary_readonly, available as primary_available
import json
from pathlib import Path
import sqlite3
from assistant_store import StateError
from conversation_engine import identifier


class ProfileIdError(StateError):
    def __init__(self):super().__init__('profile-id-not-verified')


def build():
    from assistant_contact_photo import profile_source
    from uikit_profile_navigation import replace_once
    # Compile-only sentinels, never inferred user/account credentials or IDs.
    seed=dict(account='1',peer='2',chat='3')
    source=profile_source(seed)
    source=replace_once(source,'expectedIdentity='+json.dumps(seed),'expectedIdentity=null')
    source=replace_once(source,"const peer=id64(s.peerId,user);if(peer!==expectedIdentity.peer)fail('identity-not-bound');",
        'const peer=id64(s.peerId,user);')
    source=replace_once(source,"   n.private_profile_peer=peer;n.stage='navigation-ready';",
        "   if(id64(s.peerId,user)!==peer||!scope(()=>resolve(candidate).equals(current))||!call(s.profileUser,content).equals(user))fail('identity-changed');\n   n.private_profile_peer=peer;n.stage='navigation-ready';")
    # Even unreachable legacy route helpers cannot mutate the application.
    source=replace_once(source,'const call=(entry,obj,params=ptr(0))=>{',
        "const call=(entry,obj,params=ptr(0))=>{if(entry.kind===1||entry.routeChecked)fail('signature-mismatch');")
    return source


def validated_peer(raw):
    if not isinstance(raw,dict) or not isinstance(raw.get('navigation'),dict):raise ProfileIdError()
    n=raw['navigation']
    exact=dict(stage='navigation-ready',error='none',phase='done',metadata_checkpoint='ready',
        destination_verified=True,action_attempted=False,action_completed=False,cleanup_failed=False)
    if any(type(n.get(k)) is not type(v) or n[k]!=v for k,v in exact.items()):raise ProfileIdError()
    acquired,released=n.get('handles_acquired'),n.get('handles_released')
    if type(acquired) is not int or type(released) is not int or not 0<=acquired<=10000 or acquired!=released:raise ProfileIdError()
    try:return identifier(n.get('private_profile_peer'))
    except Exception:raise ProfileIdError() from None


def read_profile(executable,folder,cancelled,*,capture_fn=None,inspect_fn=None):
    from one_chat_device import capture
    from search_online import inspect
    capture_fn=capture if capture_fn is None else capture_fn
    inspect_fn=inspect if inspect_fn is None else inspect_fn
    source=build()
    def inspector(port,token,cancel,binding):
        if binding is not None:raise ProfileIdError()
        if cancel():raise ProfileIdError()
        first=inspect_fn(port,token,cancel,source_function=source,validator=validated_peer)
        if cancel():raise ProfileIdError()
        second=inspect_fn(port,token,cancel,source_function=source,validator=validated_peer)
        if cancel() or first!=second:raise ProfileIdError()
        try:return identifier(first)
        except Exception:raise ProfileIdError() from None
    return capture_fn(executable,folder,cancelled,inspector=inspector)


def lookup(path,peer):
    peer=identifier(peer);path=Path(path)
    if not primary_available(path):return 'unavailable','registry-unavailable'
    db=None
    try:
        db=primary_readonly(path)
        db.execute('PRAGMA query_only=ON')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mumu_peer_blocks'").fetchone():
            return 'unavailable','registry-unavailable'
        row=db.execute('SELECT reason FROM mumu_peer_blocks WHERE peer=?',(peer,)).fetchone()
        if row is None:return 'not-blocked','none'
        if row[0] not in {'contact-received','contact-refused','manual-block'}:return 'unavailable','registry-unavailable'
        return 'blocked',row[0]
    except sqlite3.Error:return 'unavailable','registry-unavailable'
    finally:
        if db is not None:db.close()


def checked_result(value):
    if not isinstance(value,dict) or set(value)!={'peer','block_status','block_reason','samples','read_only'}:raise ProfileIdError()
    identifier(value['peer'])
    if type(value['samples']) is not int or value['samples']!=2 or value['read_only'] is not True:raise ProfileIdError()
    if (value['block_status'],value['block_reason']) not in {
        ('not-blocked','none'),('blocked','contact-received'),('blocked','contact-refused'),('blocked','manual-block'),('unavailable','registry-unavailable')}:
        raise ProfileIdError()
    return dict(value)


def run(settings,cancelled,progress=lambda _:None):
    from mumu_common import root_directory
    progress('Читаю только ID открытой анкеты. Чаты и сообщения не трогаю.')
    peer=read_profile(settings.adb,settings.folder,cancelled)
    if cancelled():raise ProfileIdError()
    status,reason=lookup(root_directory()/'assistant.sqlite3',peer)
    return checked_result(dict(peer=peer,block_status=status,block_reason=reason,samples=2,read_only=True))


def display(value,footer=''):
    value=checked_result(value)
    if footer:
        footer=identifier(footer)
        comparison='Совпадает с введённым ID внизу анкеты.' if footer==value['peer'] else 'НЕ совпадает с введённым ID. Не используй результат как подтверждение соответствия.'
    else:comparison='С ID внизу анкеты не сравнивали. При необходимости введи его вручную.'
    label={'manual-block':'ЗАПРЕТ: ID внесён вручную командой /num.','contact-received':'ЗАПРЕТ: ранее получен контакт.','contact-refused':'ЗАПРЕТ: ранее получен явный отказ.',
        'none':'В общей базе запрет не найден. Это не разрешение на отправку.',
        'registry-unavailable':'Статус запрета НЕИЗВЕСТЕН: общая база не доступна или ещё не создана.'}[value['block_reason']]
    return 'ID открытой анкеты: '+value['peer']+'\n'+comparison+'\n'+label+'\nПроверка только чтением; база и переписка не изменены.'
