#!/usr/bin/env python3
"""Package the exact previously tested v1.3.2 APK, never a new per-run signer.

The private signing key is neither needed nor included. Source and compiled DEX
must agree with the pinned release before distribution. A native source change
requires a deliberate new helper release, not silent reuse of a stale binary.
"""
import base64
import hashlib
import json
from pathlib import Path
import zipfile
from io import BytesIO

APK_SHA256 = '700d240c6adbf08066f5de2314d447381b4303d6c76aef5bc0a06d722a2c8cd1'
DEX_SHA256 = 'cbbcd3d047ff6f13bba03d14cce728a7d252c21054fbcac3c1f38185311f17ad'
SOURCE_SHA256 = {
 'src/com/dvk/navigation/NavigationInstrumentation.java': '4ab6409e83e31e86d78d5f66d80f34e6d308c76ccce77302355399cf2057f0b0',
 'AndroidManifest.xml': '15708c231cf62d580562069af7daa195f0b487ef5a0c6b5eedc7f3ea6a2aacd2',
}


def validated_apk(root, compiled_dex=None):
    root = Path(root)
    for relative, expected in SOURCE_SHA256.items():
        if hashlib.sha256((root/relative).read_bytes()).hexdigest() != expected:
            raise ValueError('Native sources changed. Publish/review a new pinned helper; do not silently reuse this APK.')
    raw = base64.b64decode(''.join((root/'pinned/helper-v132.apk.base64').read_text().split()), validate=True)
    if hashlib.sha256(raw).hexdigest() != APK_SHA256:
        raise ValueError('Pinned APK checksum mismatch')
    with zipfile.ZipFile(BytesIO(raw)) as z:
        if hashlib.sha256(z.read('classes.dex')).hexdigest() != DEX_SHA256:
            raise ValueError('Pinned DEX checksum mismatch')
    if compiled_dex is not None and hashlib.sha256(Path(compiled_dex).read_bytes()).hexdigest() != DEX_SHA256:
        raise ValueError('Rebuilt DEX differs from pinned runtime. Stop packaging; inspect compiler/source differences.')
    return raw


def package(root):
    root=Path(root); raw=validated_apk(root,root/'out/helper/dex/classes.dex')
    (root/'out/helper.apk').write_bytes(raw)
    (root/'out/helper-manifest.json').write_text(json.dumps({'helper_sha256':APK_SHA256}))

if __name__=='__main__':
    package(Path(__file__).resolve().parent)
    print('Pinned helper APK packaged; source + compiled DEX + release checksums verified.')
