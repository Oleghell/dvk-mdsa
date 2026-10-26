"""Persistent non-secret machine-bound installation identity, never a send permit."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
from mumu_common import MumuError, atomic, root_directory


def checked(value):
    if type(value) is not str or not re.fullmatch('[a-f0-9]{32}',value):
        raise MumuError('installation-id-invalid')
    return value


def machine_fingerprint():
    try:
        if os.name=='nt':
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Cryptography',0,
                                winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
                value=winreg.QueryValueEx(key,'MachineGuid')[0]
        else:
            paths=(Path('/etc/machine-id'),Path('/var/lib/dbus/machine-id'))
            value=next((p.read_text().strip() for p in paths if p.is_file()),
                       'linux-host:'+os.uname().nodename)
        if type(value) is not str or not 16<=len(value)<=128:raise ValueError()
        return hashlib.sha256(('dvk-installation-v1:'+value).encode()).hexdigest()
    except Exception:raise MumuError('installation-machine-id-unavailable') from None


def load(folder=None):
    from assistant_lock import operation_lock
    from assistant_store import StateError
    folder=root_directory() if folder is None else Path(folder)
    fingerprint=machine_fingerprint();path=folder/'installation.json'
    # Only the local file lock is retried. Never regenerate a malformed identity,
    # retry database writes or borrow an ID from the exported cloud configuration.
    deadline=time.monotonic()+5
    while True:
        scope=operation_lock(folder/'installation.lock')
        try:scope.__enter__();break
        except StateError:
            if time.monotonic()>=deadline:raise MumuError('installation-id-busy') from None
            time.sleep(.02)
    try:
        if not path.exists():
            value=dict(schema=1,installation_id=secrets.token_hex(16),machine=fingerprint)
            atomic(path,value)
        else:
            try:
                if path.stat().st_size>1024:raise ValueError()
                value=json.loads(path.read_text(encoding='utf-8'))
                if (type(value) is not dict or set(value)!={'schema','installation_id','machine'}
                    or type(value['schema']) is not int or value['schema']!=1):raise ValueError()
                checked(value['installation_id'])
                if value['machine']!=fingerprint:
                    raise MumuError('installation-id-copied-from-another-computer')
            except MumuError:raise
            except Exception:raise MumuError('installation-id-invalid') from None
        return checked(value['installation_id'])
    finally:scope.__exit__(None,None,None)
