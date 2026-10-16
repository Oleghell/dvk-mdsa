"""Package only reviewed, byte-identical control + IME binaries. No signing keys."""
import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
import zipfile


def verified(root,check_compiled=True):
    root=Path(root);manifest=json.loads((root/'pinned/release.json').read_text(encoding='utf-8'))
    for rel,expected in manifest['sources'].items():
        if hashlib.sha256((root/rel).read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=expected:raise ValueError('Control sources changed; review and repin deliberately')
    result={}
    for name,meta in manifest['packages'].items():
        raw=base64.b64decode(''.join((root/'pinned'/(name+'.base64')).read_text(encoding='utf-8').split()),validate=True)
        if hashlib.sha256(raw).hexdigest()!=meta['apk_sha256']:raise ValueError('Control APK mismatch')
        with zipfile.ZipFile(BytesIO(raw)) as z:
            if hashlib.sha256(z.read('classes.dex')).hexdigest()!=meta['dex_sha256']:raise ValueError('Control DEX mismatch')
        compiled=root/'out'/name.removesuffix('-helper.apk')/'dex/classes.dex'
        if check_compiled and (not compiled.exists() or hashlib.sha256(compiled.read_bytes()).hexdigest()!=meta['dex_sha256']):raise ValueError('Rebuilt DEX mismatch')
        result[name]=raw
    return result


def package(root):
    root=Path(root)
    for name,raw in verified(root).items():(root/'out'/name).write_bytes(raw)
    print('Control + keyboard: exact source/DEX/APK verified')

if __name__=='__main__':package(Path(__file__).resolve().parent)
