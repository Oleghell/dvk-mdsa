"""MuMu-only endpoint configuration. No scan, fallback or implicit device."""
import json
import os
from pathlib import Path
import re

VERSION = '1.3.8'
DEFAULT_PORTS = (5557, 5559, 5561, 5563, 5565)

class MumuError(RuntimeError): pass

def port(value):
    if type(value) is int: value=str(value)
    if type(value) is not str or not re.fullmatch(r'[1-9][0-9]{3,4}', value):
        raise MumuError('Укажи локальный порт ADB, например 5557.')
    result=int(value)
    if not 1024 <= result <= 65535 or result in (5037,27042):
        raise MumuError('Недопустимый порт устройства.')
    return result

def serial(value): return '127.0.0.1:'+str(port(value))

def parse(text):
    if type(text) is not str or len(text)>16384: raise MumuError('Список портов слишком большой.')
    values=[port(x.strip().removeprefix('127.0.0.1:')) for x in text.splitlines() if x.strip()]
    if not values or len(values)>128 or len(set(values))!=len(values):
        raise MumuError('Укажи от 1 до 128 разных портов, по одному на строку.')
    return values

def root_directory():
    value=os.environ.get('LOCALAPPDATA')
    if not value: raise MumuError('Не найдена папка данных Windows.')
    return Path(value)/'DvkAssistant'

def device_directory(value):
    # Preserve legacy 5563 reports and its existing lock/journals in their original place.
    n=port(value)
    return root_directory() if n==5563 else root_directory()/'devices'/str(n)

def load_ports():
    path=root_directory()/'mumu-devices.json'
    if not path.exists():return list(DEFAULT_PORTS)
    try:
        if path.stat().st_size>16384:raise ValueError()
        value=json.loads(path.read_text(encoding='utf-8'))
        if type(value) is not dict or set(value)!={'schema','ports'} or type(value['schema']) is not int or value['schema']!=1 or type(value['ports']) is not list:raise ValueError()
        return parse('\n'.join(str(port(x)) for x in value['ports']))
    except Exception:raise MumuError('Не удалось прочитать сохранённый список MuMu. Исправь порты в окне.') from None

def save_ports(values):
    values=parse('\n'.join(str(port(x)) for x in values))
    atomic(root_directory()/'mumu-devices.json',dict(schema=1,ports=values))

def atomic(path,value):
    import tempfile
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,indent=1);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
