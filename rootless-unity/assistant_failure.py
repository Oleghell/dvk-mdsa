"""Closed host exception categories; never export exception text/SQL/paths."""
import sqlite3
from assistant_store import StateError
CODES={'journal-busy','journal-locked','journal-readonly','journal-storage-full','journal-io-error',
       'journal-corrupt','journal-error','device-timeout','transport-error','resource-missing',
       'resource-access-denied','host-io-error','validation-failed','internal-contract-error',
       'state-check-failed','internal-error','native-transport-error','native-operation-cancelled',
       'native-script-error','native-process-unavailable','native-state-error'}
CHECKPOINTS={'chat-send','chat-contact-photo','chat-contact-notify','chat-read','chat-bind','chat-proposal','chat-contact-reconcile','inbox-targets','inbox-open','inbox-read','inbox-audit','inbox-back','inbox-exit-notify',
             'inbox-record','inbox-return','profile-start','profile-cycle','profile-journal',
             'profile-verify','city-navigation','city-journal'}

def category(error):
    from startup_failure import clean
    evidence=clean(getattr(error,'_dvk_failure',None))
    if evidence:
        from startup_failure import recoverable_adb
        if recoverable_adb(evidence):return 'native-transport-error'
        name=evidence['error_type']
        if name in {'TransportError','ServerNotRunningError','ProtocolError'}:return 'native-transport-error'
        if name=='TimedOutError':return 'device-timeout'
        if name=='OperationCancelledError':return 'native-operation-cancelled'
        if name=='RPCException':return 'native-script-error'
        if name=='ProcessNotFoundError':return 'native-process-unavailable'
        if name=='InvalidOperationError':return 'native-state-error'
    if isinstance(error,sqlite3.Error):
        code=getattr(error,'sqlite_errorcode',None)
        base=code & 255 if type(code) is int else None
        return {sqlite3.SQLITE_BUSY:'journal-busy',sqlite3.SQLITE_LOCKED:'journal-locked',
            sqlite3.SQLITE_READONLY:'journal-readonly',sqlite3.SQLITE_FULL:'journal-storage-full',
            sqlite3.SQLITE_IOERR:'journal-io-error',sqlite3.SQLITE_CORRUPT:'journal-corrupt',
            sqlite3.SQLITE_NOTADB:'journal-corrupt'}.get(base,'journal-error')
    if isinstance(error,StateError):return 'state-check-failed'
    if isinstance(error,TimeoutError):return 'device-timeout'
    if isinstance(error,ConnectionError):return 'transport-error'
    if isinstance(error,FileNotFoundError):return 'resource-missing'
    if isinstance(error,PermissionError):return 'resource-access-denied'
    if isinstance(error,OSError):return 'host-io-error'
    if isinstance(error,ValueError):return 'validation-failed'
    if isinstance(error,(KeyError,TypeError,AttributeError)):return 'internal-contract-error'
    return 'internal-error'


def evidence(error):
    from startup_failure import clean
    return clean(getattr(error,'_dvk_failure',None))
