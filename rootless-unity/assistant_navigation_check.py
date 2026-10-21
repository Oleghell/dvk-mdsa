"""Diagnostic entry: ONE journal-bound dialog roundtrip, no history/send adapters.

The journal is opened read-only. No Chain/Store is created, no authorization is
reserved, and no message/Telegram handler or credential loader is called.
"""
from contextlib import closing
from pathlib import Path
import sqlite3

from assistant_lock import operation_lock
from assistant_store import data_directory, StateError
from dialog_browser import (VERSION, MAX_TARGETS, ERRORS, PHASES, CHECKPOINTS,
                            SELECTION, targets, perform)
from one_chat_probe import identity


def report():
    return dict(tool_version=VERSION,mode='single-dialog-navigation-check',
                navigation_only=True,status='dialogs-stopped',reason='not-started',
                live_cycle_available=False,city_changes=0,new_greetings=0,
                all_dialogs_covered=False,device_scope='MuMu-4-only',dialog_limit=1,
                dialogs_opened=0,dialogs_processed=0,navigation_dialogs_checked=0,
                reply_submission_calls=0,reply_handler_returns=0,outgoing_observed=0,
                notifications=dict(accepted=0,unknown=0,blocked=0),states={},
                messages_sent=0,chat_content_read=False,telegram_used=False,
                journal_read_only=True,return_verified=False,ui_may_remain_open=False,
                personal_data_exported=False,last_navigation=None,last_reader=None)


def read_targets(path=None):
    path=Path(path) if path is not None else data_directory()/'assistant.sqlite3'
    if not path.exists():
        return []  # Do not create a new journal just to run diagnostics.
    with closing(sqlite3.connect(path.resolve(strict=True).as_uri()+'?mode=ro',timeout=5,uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')  # One consistent, read-only snapshot.
        return read_targets_from_db(db)


def read_targets_from_db(db):
    tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'manual_actions' not in tables:
        raise StateError('journal-schema-unavailable')
    if 'chain_dialogs' in tables:
        rows=db.execute('''SELECT m.account,m.peer,COALESCE(c.chat,m.initial_chat)
            FROM manual_actions m LEFT JOIN chain_dialogs c
              ON c.account=m.account AND c.peer=m.peer
            WHERE m.status!='not-invoked'
              AND (c.stage IS NULL OR c.stage NOT IN ('done','declined','manual-review'))
            ORDER BY m.id LIMIT ?''',(MAX_TARGETS+1,)).fetchall()
    else:
        rows=db.execute('''SELECT account,peer,initial_chat FROM manual_actions
            WHERE status!='not-invoked' ORDER BY id LIMIT ?''',(MAX_TARGETS+1,)).fetchall()
    return targets([dict(account=a,peer=p,chat=c) for a,p,c in rows])


def safe_diagnostic(value):
    keys={'stage','error','phase','metadata_checkpoint','selection_checkpoint','rows_scanned',
          'scan_batches','action_attempted','action_completed','destination_verified'}
    if not isinstance(value,dict) or set(value)!=keys:
        raise ValueError('Invalid diagnostic')
    if (value['stage'] not in {'not-attempted','navigation-ready','navigation-stopped','cleanup-failed'}
            or value['error'] not in ERRORS or value['phase'] not in PHASES
            or value['metadata_checkpoint'] not in CHECKPOINTS
            or value['selection_checkpoint'] not in SELECTION):
        raise ValueError('Invalid diagnostic category')
    for key in ('action_attempted','action_completed','destination_verified'):
        if type(value[key]) is not bool:
            raise ValueError('Invalid diagnostic flag')
    for key,limit in [('rows_scanned',128),('scan_batches',180)]:
        if type(value[key]) is not int or not 0<=value[key]<=limit:
            raise ValueError('Invalid diagnostic counter')
    return dict(value)


def walk(settings,stopped,progress=lambda _:None, *, navigator=perform,journal_path=None):
    out=report()
    def check_stop():
        if stopped.is_set():
            raise StateError('cancelled')
    def call(operation,**kwargs):
        check_stop()
        out['ui_may_remain_open']=True
        result=navigator(operation,settings.adb,settings.folder,stopped.is_set,**kwargs)
        if not isinstance(result,dict) or set(result)!={'state','identity','diagnostic'}:
            raise ValueError('Invalid navigation result')
        out['last_navigation']=safe_diagnostic(result['diagnostic'])
        n=out['last_navigation']
        if result['state']=='stopped':
            raise StateError('navigation-stopped')
        if n['stage']!='navigation-ready' or n['error']!='none' or n['destination_verified'] is not True:
            raise ValueError('Unverified navigation')
        allowed_states={'open':{'opened','exhausted'},'back':{'returned'},'return':{'search-ready'}}
        if result['state'] not in allowed_states[operation]:
            raise ValueError('Unexpected navigation state')
        bound=identity(result['identity']) if result['identity'] is not None else None
        if (result['state'] in ('opened','returned'))!=(bound is not None):
            raise ValueError('Invalid navigation binding')
        if result['state']=='opened' and not any(
                x['account']==bound['account'] and x['peer']==bound['peer']
                and (int(x['chat'])<=0 or x['chat']==bound['chat']) for x in kwargs['allowed']):
            raise StateError('untracked-dialog')
        if operation=='back' and bound!=kwargs['expected']:
            raise StateError('changed-dialog')
        return result
    try:
        check_stop()
        allowed=read_targets(journal_path)
        check_stop()
        if not allowed:
            out.update(status='dialogs-empty',reason='no-active-journal-bindings')
            return out
        progress('Проверяю один переход в диалог и обратно. Сообщения не отправляются, переписка не читается.')
        selected=call('open',allowed=allowed,entry='search')
        if selected['state']=='opened':
            out['dialogs_opened']=1
            call('back',expected=identity(selected['identity']))
            out['navigation_dialogs_checked']=1
        call('return')
        check_stop()
        out.update(status='dialogs-completed',reason='navigation-check-completed'
                   if out['navigation_dialogs_checked'] else 'visible-exhausted',
                   return_verified=True,ui_may_remain_open=False)
    except Exception:
        diagnostic=out['last_navigation']
        reason=(diagnostic['error'] if diagnostic and diagnostic['error']!='none'
                else 'navigation-check-stopped')
        out.update(status='dialogs-cancelled' if stopped.is_set() else 'dialogs-stopped',
                   reason='cancelled' if stopped.is_set() else reason)
    return out


def run_navigation_check(settings,stopped,progress=lambda _:None, *, navigator=perform,journal_path=None):
    if stopped.is_set():
        return dict(report(),status='dialogs-cancelled',reason='cancelled')
    with operation_lock():
        return walk(settings,stopped,progress,navigator=navigator,journal_path=journal_path)
