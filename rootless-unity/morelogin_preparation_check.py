"""Offline packaged preflight: disposable shared DB, never phone/keys/messages."""
import os
import tempfile
import threading
from assistant_config import load
from assistant_settings import Settings
from assistant_inbox import run
from morelogin_store import SharedStore


def check():
    # Validate deployed templates before changing any environment variables.
    config=load()
    keys=('LOCALAPPDATA','DVK_MORELOGIN','DVK_MORELOGIN_PHONE_ID')
    saved={key:os.environ.get(key) for key in keys}
    def forbidden(*args,**kwargs):
        raise AssertionError('Offline preparation attempted external action')
    try:
        with tempfile.TemporaryDirectory(prefix='dvk-preparation-') as directory:
            os.environ.update(LOCALAPPDATA=directory,DVK_MORELOGIN='1',DVK_MORELOGIN_PHONE_ID='101')
            store=SharedStore()
            result=run(Settings(errors_enabled=False),threading.Event(),forbidden,
                       store=store,greetings=config.greetings,navigator=forbidden,
                       reader=forbidden,sender=forbidden,notifier=forbidden,
                       contact_photo=forbidden,exit_notifier=forbidden)
            if (result['status']!='inbox-empty' or result['submission_calls']!=0
                    or result['contacts_forwarded']!=0 or result['ai_requests']!=0):
                raise AssertionError('Offline preparation failed')
            return True
    finally:
        for key,value in saved.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
