"""Copy a finite hashed core, never merge platform credentials/configs/journals."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def sync(source,target,check=False):
    source,target=Path(source),Path(target)
    manifest=json.loads((source/'shared-core.json').read_text(encoding='utf-8'))
    if set(manifest)!={'schema','engine_version','files'} or manifest['schema']!=1:raise ValueError('Invalid core manifest')
    if not re.fullmatch(r'\d+\.\d+\.\d+',manifest['engine_version']):raise ValueError('Invalid version')
    changes=[]
    for name,digest in manifest['files'].items():
        if (not re.fullmatch(r'rootless-unity/(?:tests/|fixtures/)?[A-Za-z0-9_.-]+\.(?:py|c|h|json)',name)
                or '..' in name or not re.fullmatch('[a-f0-9]{64}',digest)):
            raise ValueError('Invalid core path/hash')
        if Path(name).name.startswith('morelogin_') or Path(name).name in ('assistant_app.py','test_device.py','build_manifest.py'):
            raise ValueError('Platform adapter not allowed in core')
        a,b=source/name,target/name
        if a.is_symlink() or b.is_symlink():raise ValueError('Symlink forbidden')
        data=a.read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Stale core hash: '+name)
        if not b.exists() or b.read_bytes()!=data:
            changes.append(name)
            if not check:b.parent.mkdir(parents=True,exist_ok=True);b.write_bytes(data)
    if check:return changes
    # MuMu's docs are deliberately not replaced with Cloud Phone instructions.
    guide=target/'rootless-unity/ASSISTANT.md'
    text=guide.read_text(encoding='utf-8')
    text=re.sub(r'^# DvkAssistant \d+\.\d+\.\d+', '# DvkAssistant '+manifest['engine_version'],text,count=1)
    guide.write_text(text,encoding='utf-8');(target/'README.md').write_text(text,encoding='utf-8')
    (target/'shared-core.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    notes=(source/'SHARED_RELEASE_NOTES.md').read_text(encoding='utf-8')
    (target/'SHARED_RELEASE_NOTES.md').write_text(notes,encoding='utf-8')
    release=target/'RELEASE_NOTES.md'
    old=release.read_text(encoding='utf-8')
    if not old.startswith(notes):release.write_text(notes+'\n---\n\n'+old,encoding='utf-8')
    return changes

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',default='.');p.add_argument('--target',required=True);p.add_argument('--check',action='store_true');a=p.parse_args()
    changed=sync(a.source,a.target,a.check)
    print('Changed core files:',len(changed))
    if a.check and changed:raise SystemExit(1)
