"""Diagnostic entry: ONE journal-bound dialog roundtrip, no history/send adapters.

The journal is opened read-only. No Chain/Store is created, no authorization is
reserved, and no message/Telegram handler or credential loader is called.
"""
from cloud_database import connect as primary_connect, readonly as primary_readonly, available as primary_available
from contextlib import closing
from pathlib import Path
import sqlite3

from assistant_lock import operation_lock
from assistant_store import data_directory, StateError
from dialog_browser import (VERSION, MAX_TARGETS, ERRORS, PHASES, CHECKPOINTS,
                            SELECTION, KINDS, MAX_BACK_BUDGET_RETRIES, MAX_OBSERVATION_BUDGET_RETRIES, MAX_ENTRY_READ_BUDGET_RETRIES, MAX_ENTRY_BINDING_WAITS, targets, perform)
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
    if not primary_available(path):
        return []  # Do not create a new journal just to run diagnostics.
    with closing(primary_readonly(path)) as db:
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
          'scan_batches','action_attempted','action_completed','destination_verified',
          'unread_filter_applied','unread_verified','read_rows_skipped'}
    if not isinstance(value,dict) or not keys<=set(value) or set(value)-keys-{'back_budget_retries','reply_filter_applied','reply_needed_verified','waiting_rows_skipped','handled_rows_skipped','header_rows_skipped','root_probe','observation_budget_retries','entry_read_budget_retries','entry_binding_waits','entry_search_recovered','root_top_kind','last_presented_kind','controller_path'}:
        raise ValueError('Invalid diagnostic')
    if (value['stage'] not in {'not-attempted','navigation-ready','navigation-stopped','cleanup-failed'}
            or value['error'] not in ERRORS or value['phase'] not in PHASES
            or value['metadata_checkpoint'] not in CHECKPOINTS
            or value['selection_checkpoint'] not in SELECTION):
        raise ValueError('Invalid diagnostic category')
    for key in ('action_attempted','action_completed','destination_verified','unread_filter_applied','unread_verified'):
        if type(value[key]) is not bool:
            raise ValueError('Invalid diagnostic flag')
    for key,limit in [('rows_scanned',128),('scan_batches',180),('read_rows_skipped',128)]:
        if type(value[key]) is not int or not 0<=value[key]<=limit:
            raise ValueError('Invalid diagnostic counter')
    if value['read_rows_skipped']>value['rows_scanned'] or (not value['unread_filter_applied'] and (value['unread_verified'] or value['read_rows_skipped'])):
        raise ValueError('Invalid unread diagnostic')
    retries=value.get('back_budget_retries',0)
    if type(retries) is not int or not 0<=retries<=MAX_BACK_BUDGET_RETRIES:
        raise ValueError('Invalid back recovery counter')
    if retries and (value['phase'] not in ('wait-back','done') or not value['action_completed']):
        raise ValueError('Invalid back recovery diagnostic')
    entry_retries=value.get('entry_read_budget_retries',0)
    if type(entry_retries) is not int or not 0<=entry_retries<=MAX_ENTRY_READ_BUDGET_RETRIES:
        raise ValueError('Invalid entry read recovery counter')
    binding_waits=value.get('entry_binding_waits',0)
    if type(binding_waits) is not int or not 0<=binding_waits<=MAX_ENTRY_BINDING_WAITS:
        raise ValueError('Invalid startup binding wait counter')
    retries=value.get('observation_budget_retries',0)
    if type(retries) is not int or not 0<=retries<=MAX_OBSERVATION_BUDGET_RETRIES:
        raise ValueError('Invalid observation recovery counter')
    if retries and (value['phase'] not in ('wait-list','wait-chat','wait-search','scan','done') or not value['action_completed']):
        raise ValueError('Invalid observation recovery diagnostic')
    if 'entry_search_recovered' in value and type(value['entry_search_recovered']) is not bool:
        raise ValueError('Invalid search reentry flag')
    for key in ('root_top_kind','last_presented_kind'):
        if key in value and value[key] not in KINDS:raise ValueError('Invalid screen category')
    if 'controller_path' in value and (not isinstance(value['controller_path'],list) or len(value['controller_path'])>12 or any(x not in KINDS for x in value['controller_path'])):
        raise ValueError('Invalid controller path')
    for key in ('reply_filter_applied','reply_needed_verified'):
        if key in value and type(value[key]) is not bool:raise ValueError('Invalid reply diagnostic')
    for key in ('waiting_rows_skipped','handled_rows_skipped'):
        if key in value and (type(value[key]) is not int or not 0<=value[key]<=value['rows_scanned']):raise ValueError('Invalid reply count')
    if 'header_rows_skipped' in value and (type(value['header_rows_skipped']) is not int or not 0<=value['header_rows_skipped']<=100000):raise ValueError('Invalid header count')
    if 'root_probe' in value:
        from navigation_root_diagnostic import clean
        clean(value['root_probe'])
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
