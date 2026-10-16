"""Package byte-identical approved city APK; never sign with a CI/random key."""
import base64
import hashlib
import json
from pathlib import Path
import runpy
import zipfile


def package(root):
    root=Path(root);pins=runpy.run_path(str(root.parent/'city_release.py'))
    for name,expected in pins['CITY_SOURCE_HASHES'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('City source changed; a reviewed signed release is required')
    encoded=(root/'pinned/city-helper.apk.base64').read_text(encoding='utf-8')
    apk=base64.b64decode(''.join(encoded.split()),validate=True)
    if hashlib.sha256(apk).hexdigest()!=pins['CITY_APK_SHA256']:
        raise ValueError('Pinned city APK checksum mismatch')
    out=root/'out';out.mkdir(exist_ok=True)
    dex=(out/'dex/classes.dex').read_bytes()
    if hashlib.sha256(dex).hexdigest()!=pins['CITY_DEX_SHA256']:
        raise ValueError('Compiled city DEX differs from approved release; do not ship')
    path=out/'city-helper.apk';path.write_bytes(apk)
    with zipfile.ZipFile(path) as z:
        if z.read('classes.dex')!=dex:raise ValueError('APK DEX mismatch')
    manifest={k:v for k,v in pins.items() if k.startswith('CITY_')}
    (out/'city-helper-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n', encoding='utf-8', newline='\n')
    return path

if __name__=='__main__':
    package(Path(__file__).resolve().parent)
    print('Pinned city-only helper packaged; exact source/DEX/APK verified')
