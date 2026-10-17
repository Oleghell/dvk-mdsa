"""Package only a verified flat Windows artifact. No signing credentials."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import zipfile
from control_release import PACKAGES,SIGNER_SHA256,VERSION


def package(source):
    source=Path(source).resolve()
    if not source.is_dir():raise ValueError('Windows artifact missing')
    files={p.name:p for p in source.iterdir() if p.is_file()}
    if len(files)!=len(list(source.iterdir())):raise ValueError('Unexpected nested artifact')
    required={'MuMu-navigation.exe','cloudflared.exe','helper.apk','helper-manifest.json','city-helper.apk','city-helper-manifest.json','control-helper.apk','keyboard-helper.apk','BUILD_INFO.json','README.md','START-HERE.md','SHA256SUMS.txt'}
    if not required<=files.keys():raise ValueError('Incomplete Windows artifact')
    if any(re.search(r'(?i)(\.jks$|\.keystore$|\.p12$|\.pfx$|storepass|private.signing)',n) for n in files):raise ValueError('Private signing material forbidden')
    sums={}
    for line in files['SHA256SUMS.txt'].read_text(encoding='utf-8').lstrip('\ufeff').splitlines():
        match=re.fullmatch(r'([0-9a-fA-F]{64})  ([A-Za-z0-9_.-]+)',line)
        if not match or match[2] in sums:raise ValueError('Invalid checksum inventory')
        sums[match[2]]=match[1].lower()
    if set(sums)!=set(files)-{'SHA256SUMS.txt'}:raise ValueError('Checksum inventory incomplete')
    for name,sha in sums.items():
        if hashlib.sha256(files[name].read_bytes()).hexdigest()!=sha:raise ValueError('Artifact checksum mismatch: '+name)
    for name,sha in PACKAGES.items():
        if sums[name]!=sha:raise ValueError('Wrong signed v2 APK')
    info=json.loads(files['BUILD_INFO.json'].read_text(encoding='utf-8').lstrip('\ufeff'))
    if not (info.get('bridge_version')==VERSION and info.get('cursor_stable_runtime_included') is True and info.get('control_package')=='com.dvk.control.v2' and info.get('keyboard_package')=='com.dvk.keyboard.v2' and info.get('control_signer_sha256')==SIGNER_SHA256):raise ValueError('Release metadata mismatch')
    if os.environ.get('GITHUB_SHA') and info.get('source_commit')!=os.environ['GITHUB_SHA']:raise ValueError('Wrong source commit')
    for name in ('MuMu-navigation.exe','cloudflared.exe'):
        if files[name].read_bytes()[:2]!=b'MZ':raise ValueError('Windows executable missing')
    dest=source.parent/f'MuMu-navigation-{VERSION}-windows-x64.zip'
    if dest.exists():raise ValueError('Refusing to overwrite release archive')
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,path in sorted(files.items()):
            item=zipfile.ZipInfo('MuMu-navigation-windows-x64/'+name,date_time=(2026,1,1,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED;item.external_attr=0o644<<16
            archive.writestr(item,path.read_bytes())
    (source.parent/'SHA256SUMS.txt').write_text(hashlib.sha256(dest.read_bytes()).hexdigest()+'  '+dest.name+'\n',encoding='ascii')
    return dest

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: package-release.py WINDOWS_ARTIFACT_DIRECTORY')
    print(package(sys.argv[1]).name)
