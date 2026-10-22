"""Check saved DPAPI API credentials only. Never query phones or publish tokens."""
from morelogin_common import root_directory, atomic_json
from morelogin_diagnostics import diagnostic, describe

def check_saved(*, loader=None, factory=None, path=None):
    if loader is None:
        from morelogin_credentials import load
        loader=load
    if factory is None:
        from morelogin_client import Client
        factory=Client
    try:
        app_id,key=loader()
        factory(app_id,key).authorize()
        report={'status':'ok', 'stage':'auth', 'result':'auth-ok'}
        text='Авторизация успешна. Сохранённые ключи приняты MoreLogin. Телефоны не запускались.'
    except Exception as error:
        report={'status':'error', **diagnostic(error)}
        text=describe(error)
    try:
        atomic_json(path or root_directory()/'last-api-check.json',report)
    except Exception:
        text += ' Не удалось сохранить last-api-check.json.'
    return text
