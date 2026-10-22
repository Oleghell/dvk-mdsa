"""Up to five journal-bound dialog reads. Analysis writes only to RAM.

No sender, notifier, Store creation, persistent stage changes, scrolling or city
cycle. The native reader receives exact authorized IDs; snapshots never leave RAM.
"""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3

from assistant_lock import operation_lock
from assistant_store import data_directory, StateError
from assistant_navigation_check import read_targets_from_db, safe_diagnostic
from assistant_dialogs import safe_reader_failure
from assistant_chain import Chain, ReviewRequired, TERMINAL
from dialog_browser import perform
from one_chat_device import capture
from one_chat_probe import identity
from assistant_read_binding import read_bindings

VERSION='0.4.6'
LIMIT=5
MAX_JOURNAL_BYTES=64*1024*1024
STAGES=TERMINAL|{'wait-reply','wait-mood','wait-contact','pending-question','pending-contact','pending-clarify'}


def report():
    return dict(tool_version=VERSION,mode='visible-journal-dialog-read-check',
                navigation_only=False,read_only_check=True,unread_only=True,read_rows_skipped=0,unread_dialogs_verified=0,status='dialogs-stopped',reason='not-started',
                live_cycle_available=False,city_changes=0,new_greetings=0,all_dialogs_covered=False,
                device_scope='MuMu-4-only',dialog_limit=LIMIT,dialogs_opened=0,dialogs_read=0,
                dialogs_processed=0,navigation_dialogs_checked=0,
                observed_messages=0,incoming_messages=0,outgoing_messages=0,nontext_messages=0,
                reply_submission_calls=0,reply_handler_returns=0,outgoing_observed=0,
                notifications=dict(accepted=0,unknown=0,blocked=0),
                states={k:0 for k in sorted(STAGES)},preview_actions=dict(question=0,contact=0,none=0),
                messages_sent=0,chat_content_read=False,chat_content_read_attempted=False,
                telegram_used=False,journal_read_only=True,analysis_in_memory=True,
                chronological_order_verified=False,return_verified=False,ui_may_remain_open=False,
                personal_data_exported=False,last_navigation=None,last_reader=None)


class MemoryStore:
    """Chain's transaction interface, backed exclusively by an ephemeral database."""
    def __init__(self, db):
        self.db=db

    @contextmanager
    def connection(self):
        with self.db:
            yield self.db


@contextmanager
def preview_chain(path=None):
    path=Path(path) if path is not None else data_directory()/'assistant.sqlite3'
    if not path.exists():
        yield None,[]
        return
    with closing(sqlite3.connect(':memory:')) as memory:
        memory.execute('PRAGMA temp_store=MEMORY')
        with closing(sqlite3.connect(path.resolve(strict=True).as_uri()+'?mode=ro',timeout=5,uri=True)) as source:
            source.execute('PRAGMA query_only=ON')
            source.execute('BEGIN')
            pages=source.execute('PRAGMA page_count').fetchone()[0]
            size=source.execute('PRAGMA page_size').fetchone()[0]
            if pages*size>MAX_JOURNAL_BYTES:
                raise StateError('journal-size-limit')
            source.backup(memory,pages=256)
        bindings=read_bindings(memory)
        has_manual=memory.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_actions'").fetchone()
        legacy=read_targets_from_db(memory) if has_manual else []
        # Explicit read-only binding takes precedence and never enters the Chain.
        pairs={(x['account'],x['peer']) for x in bindings}
        from dialog_browser import targets
        allowed=targets(bindings+[x for x in legacy if (x['account'],x['peer']) not in pairs])
        # consume() may reserve hypothetical actions ONLY inside this disposable
        # clone. Never call step(), finish(), notify() or any external adapter.
        chain=Chain(MemoryStore(memory),choose=lambda:0,contact_notifications=False)
        yield chain,allowed


def checked_snapshot(value,who):
    if not isinstance(value,dict) or set(value)!={'identity','messages'} or identity(value['identity'])!=who:
        raise ValueError('Invalid read binding')
    messages=value['messages']
    if not isinstance(messages,list) or len(messages)>20:
        raise ValueError('Invalid read size')
    seen=set()
    for m in messages:
        if not isinstance(m,dict) or set(m)!={'id','sender','text'}:
            raise ValueError('Invalid read message')
        identity(dict(who,chat=m['id']))
        if m['id'] in seen or m['sender'] not in (who['account'],who['peer']):
            raise ValueError('Invalid read identity')
        seen.add(m['id'])
        if m['text'] is not None and (not isinstance(m['text'],str) or len(m['text'])>2048 or '\0' in m['text']):
            raise ValueError('Invalid read text')
    if sum(len(m['text'] or '') for m in messages)>16384:
        raise ValueError('Invalid read text size')
    return value


def walk(settings,stopped,progress=lambda _:None, *, navigator=perform,reader=capture,journal_path=None):
    out=report();phase='journal'
    def check_stop():
        if stopped.is_set():
            raise StateError('cancelled')
    def call(operation,**kwargs):
        check_stop()
        out['ui_may_remain_open']=True
        value=navigator(operation,settings.adb,settings.folder,stopped.is_set,**kwargs)
        if not isinstance(value,dict) or set(value)!={'state','identity','diagnostic'}:
            raise ValueError('Invalid navigation result')
        out['last_navigation']=safe_diagnostic(value['diagnostic']);n=out['last_navigation']
        if value['state']=='stopped':
            raise StateError('navigation-stopped')
        if n['stage']!='navigation-ready' or n['error']!='none' or not n['destination_verified']:
            raise ValueError('Unverified navigation')
        if value['state'] not in {'open':{'opened','exhausted'},'back':{'returned'},'return':{'search-ready'}}[operation]:
            raise ValueError('Unexpected navigation state')
        if operation=='open':
            if kwargs.get('unread_only') is not True or not n['unread_filter_applied']:
                raise StateError('unread-filter-not-verified')
            if n['unread_verified'] != (value['state']=='opened'):
                raise StateError('unread-selection-not-verified')
            out['read_rows_skipped']+=n['read_rows_skipped']
            if value['state']=='opened':out['unread_dialogs_verified']+=1
        who=identity(value['identity']) if value['identity'] is not None else None
        if (value['state'] in ('opened','returned'))!=(who is not None):
            raise ValueError('Invalid navigation binding')
        if operation=='open' and who is not None and not any(
                x['account']==who['account'] and x['peer']==who['peer']
                and (int(x['chat'])<=0 or x['chat']==who['chat']) for x in kwargs['allowed']):
            raise StateError('untracked-dialog')
        if operation=='back' and who!=kwargs['expected']:
            raise StateError('changed-dialog')
        return value
    try:
        check_stop()
        with preview_chain(journal_path) as (chain,remaining):
            check_stop()
            if not remaining:
                out.update(status='dialogs-empty',reason='no-active-journal-bindings')
                return out
            entry='search';reason='visible-pass-limit'
            for number in range(1,LIMIT+1):
                check_stop();phase='navigation'
                progress(f'Читаю только непрочитанные привязанные диалоги: {number}/{LIMIT}. Отправка сообщений и Telegram выключены.')
                selected=call('open',allowed=remaining,entry=entry,unread_only=True);entry='dialogs'
                if selected['state']=='exhausted':
                    reason='visible-exhausted';break
                who=identity(selected['identity']);out['dialogs_opened']+=1
                phase='authorization';check_stop()
                readonly=any(x==who for x in read_bindings(chain.store.db))
                if not readonly:
                    chain.authorized(who)
                phase='reader';check_stop();out['chat_content_read_attempted']=True
                snapshot=checked_snapshot(reader(settings.adb,settings.folder,stopped.is_set,who),who)
                out['chat_content_read']=True;out['dialogs_read']+=1
                messages=snapshot['messages'];out['observed_messages']+=len(messages)
                out['incoming_messages']+=sum(m['sender']==who['peer'] for m in messages)
                out['outgoing_messages']+=sum(m['sender']==who['account'] for m in messages)
                out['nontext_messages']+=sum(m['text'] is None for m in messages)
                phase='analysis';check_stop()
                if readonly or not 1<=len(messages)<20:
                    stage,action='manual-review',None
                else:
                    try:
                        stage,action=chain.consume(snapshot)
                    except ReviewRequired:
                        stage,action='manual-review',None
                if stage not in STAGES:
                    raise ValueError('Invalid preview stage')
                kind='none' if action is None else action['kind']
                if kind not in out['preview_actions']:
                    raise ValueError('Invalid preview action')
                out['states'][stage]+=1;out['preview_actions'][kind]+=1
                # Drop private bodies and any hypothetical reply before navigation.
                del snapshot,messages,action
                phase='navigation';check_stop();call('back',expected=who)
                out['dialogs_processed']+=1;out['navigation_dialogs_checked']+=1
                remaining=[x for x in remaining if (x['account'],x['peer'])!=(who['account'],who['peer'])]
                if not remaining:
                    reason='active-bindings-visited';break
            phase='navigation';check_stop();call('return');check_stop()
            out.update(status='dialogs-completed',reason=reason,return_verified=True,ui_may_remain_open=False)
    except Exception as error:
        if phase=='reader':
            out['last_reader']=safe_reader_failure(error)
        n=out['last_navigation']
        reason=('cancelled' if stopped.is_set() else
                n['error'] if phase=='navigation' and n and n['error']!='none' else
                out['last_reader']['error'] if out['last_reader'] else
                {'journal':'journal-check-stopped','authorization':'journal-binding-check-stopped',
                 'reader':'history-check-stopped','analysis':'analysis-check-stopped'}.get(phase,'navigation-check-stopped'))
        out.update(status='dialogs-cancelled' if stopped.is_set() else 'dialogs-stopped',reason=reason)
    return out


def run_read_check(settings,stopped,progress=lambda _:None, *, navigator=perform,reader=capture,journal_path=None):
    if stopped.is_set():
        return dict(report(),status='dialogs-cancelled',reason='cancelled')
    with operation_lock():
        return walk(settings,stopped,progress,navigator=navigator,reader=reader,journal_path=journal_path)
