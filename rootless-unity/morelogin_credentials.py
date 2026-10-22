"""MoreLogin API credentials: Windows DPAPI only, separate from device reports."""
import json
from pathlib import Path
from morelogin_common import root_directory, CloudError
from telegram_notify import protect


def save(app_id, key, *, path=None, encoder=protect):
    from morelogin_client import Client
    Client(app_id, key)  # Validate without network.
    from morelogin_common import atomic_json
    path = root_directory()/'morelogin.dpapi' if path is None else Path(path)
    data = encoder(json.dumps({'app_id':app_id,'key':key}).encode())
    if not isinstance(data,bytes) or not data: raise CloudError('configuration')
    # Reuse the proven atomic DPAPI file writer; this does not treat the data as TG.
    import os,tempfile
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.morelogin-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def load(*, path=None, decoder=lambda data:protect(data,decrypt=True)):
    path=root_directory()/'morelogin.dpapi' if path is None else Path(path)
    try:
        if not 1<=path.stat().st_size<=16384:raise ValueError()
        value=json.loads(decoder(path.read_bytes()))
        if set(value)!={'app_id','key'}:raise ValueError()
        from morelogin_client import Client
        Client(value['app_id'],value['key'])
        return value['app_id'],value['key']
    except Exception:
        raise CloudError('configuration') from None
