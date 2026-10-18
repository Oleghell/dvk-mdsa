"""Offline, version-gated Gadget bootstrap. Never connects to a device.
Inputs, outputs, Gadget tokens and test keys must stay outside the public repo.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import subprocess
import zipfile

BASE_SHA256 = '8def5efdd6dfaf239fd970ff6c3180095c0ed8f430a53151025a066fa42b0f6f'
SPLIT_SHA256 = '56762d3739624f5f4d8395f903817e8d90734aeeb4b8370d6ddfc11fdd2f3e19'
LAUNCHER_SHA256 = '749232b7aa51441fb919d6a6654502d73758a41b851944b99e4fb4b6d791235e'
APKTOOL_SHA256 = 'dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423'
GADGET_XZ_SHA256 = '557feaedfee289222a666b40e9e6c2c4466f8261f77b6c4199542dab7fcb9646'
FRIDA_VERSION = '17.24.1'
METHOD = '''\n# Explicit test-only rootless instrumentation; no app method is replaced.
.method static constructor <clinit>()V
    .locals 1

    const-string v0, "frida-gadget"

    invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V

    return-void
.end method
'''


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as source:
        for data in iter(lambda: source.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def require_hash(path: Path, expected: str):
    if sha(path) != expected:
        raise ValueError(f'Unsupported or corrupted input: {path.name}')


def patch_launcher(text: str) -> str:
    if hashlib.sha256(text.encode('utf-8')).hexdigest() != LAUNCHER_SHA256:
        raise ValueError('Launcher does not match the audited 6.8.1 input; refusing blind patch')
    if '<clinit>' in text:
        raise ValueError('Existing class initializer; manual review required')
    return text + METHOD


def gadget_config(token: str) -> dict:
    if not re.fullmatch(r'[0-9a-f]{64}', token):
        raise ValueError('Expected a fresh 256-bit token')
    return {'interaction': {'type': 'listen', 'address': '127.0.0.1', 'port': 27042,
                            'token': token, 'on_port_conflict': 'fail', 'on_load': 'resume'}}


def signature_entry(name: str) -> bool:
    upper = name.upper()
    return name == 'stamp-cert-sha256' or upper == 'META-INF/MANIFEST.MF' or (
        upper.startswith('META-INF/') and upper.endswith(('.SF', '.RSA', '.DSA', '.EC')))


def rewrite_apk(source: Path, target: Path, replacements: dict[str, bytes]):
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, 'x') as dst:
        names = src.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP entries')
        for entry in src.infolist():
            if not signature_entry(entry.filename) and entry.filename not in replacements:
                dst.writestr(entry, src.read(entry.filename))
        for name, payload in replacements.items():
            if name not in ('classes5.dex', 'lib/arm64-v8a/libfrida-gadget.so',
                            'lib/arm64-v8a/libfrida-gadget.config.so'):
                raise ValueError('Unapproved replacement')
            dst.writestr(name, payload, compress_type=zipfile.ZIP_STORED)


def verify_preserved(source: Path, target: Path, allowed: set[str]) -> dict:
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target) as dst:
        if len(dst.namelist()) != len(set(dst.namelist())):
            raise ValueError('Duplicate output entries')
        src_names = {n for n in src.namelist() if not signature_entry(n)}
        dst_names = {n for n in dst.namelist() if not signature_entry(n)}
        if src_names - allowed != dst_names - allowed:
            raise ValueError('Unexpected entry added or removed')
        checked = 0
        for name in src_names - allowed:
            if src.read(name) != dst.read(name):
                raise ValueError(f'Unexpected content change: {name}')
            checked += 1
        return {'unchanged_entries_verified': checked,
                'manifest_byte_identical': src.read('AndroidManifest.xml') == dst.read('AndroidManifest.xml')}


def run(command: list[str], log: Path, *, env=None):
    with log.open('ab') as output:
        result = subprocess.run(command, shell=False, stdout=output, stderr=subprocess.STDOUT,
                                timeout=600, env=env)
    if result.returncode:
        raise RuntimeError(f'Offline tool failed ({Path(command[0]).name}); inspect private build log')


def prepare(args):
    source = args.source.resolve(strict=True)
    work = args.work.resolve()
    # Prevent accidental publication of inputs, APKs, token or keys in a working tree.
    repo = Path(__file__).resolve().parents[1]
    if work.is_relative_to(repo) or source.is_relative_to(repo):
        raise ValueError('Use private source/work directories outside the repository')
    if work.exists():
        raise ValueError('Work directory must be new; never overwrite previous builds')
    for p, digest in ((source/'base.apk', BASE_SHA256), (source/'split-001.apk', SPLIT_SHA256),
                      (args.apktool, APKTOOL_SHA256), (args.gadget, GADGET_XZ_SHA256)):
        require_hash(p, digest)
    gadget = lzma.decompress(args.gadget.read_bytes(), memlimit=256 * 1024**2)
    if len(gadget) > 128 * 1024**2 or gadget[:5] != b'\x7fELF\x02' or struct.unpack_from('<H', gadget, 18)[0] != 183:
        raise ValueError('Expected official ELF64 AArch64 Gadget')
    work.mkdir(parents=True, mode=0o700)
    private = work/'private'
    private.mkdir(mode=0o700)
    output = work/'test-apks'
    output.mkdir()
    log = private/'build.log'
    java = str(args.java_home/'bin/java')
    tools = args.build_tools.resolve(strict=True)
    env = os.environ.copy()
    env['JAVA_HOME'] = str(args.java_home.resolve(strict=True))
    env['PATH'] = str(args.java_home/'bin') + os.pathsep + env.get('PATH', '')
    # Verify original APK signatures and common signer without dumping certificates to chat.
    certificates = []
    for name in ('base.apk', 'split-001.apk'):
        certlog = private/(name+'.cert.txt')
        run([str(tools/'apksigner'), 'verify', '--print-certs', str(source/name)], certlog, env=env)
        match = re.search(r'Signer #1 certificate SHA-256 digest: ([a-f0-9]{64})', certlog.read_text(encoding='utf-8'))
        if not match:
            raise ValueError('Cannot verify source signer')
        certificates.append(match.group(1))
    if len(set(certificates)) != 1:
        raise ValueError('Base/split source signer mismatch')
    decoded = private/'decoded'
    run([java, '-Xmx3g', '-jar', str(args.apktool.resolve()), 'd', '--no-res', '-o', str(decoded), str(source/'base.apk')], log)
    launcher = decoded/'smali_classes5/drug/vokrug/activity/Launcher.smali'
    launcher.write_text(patch_launcher(launcher.read_text(encoding='utf-8')), encoding='utf-8', newline='\n')
    run([java, '-Xmx3g', '-jar', str(args.apktool.resolve()), 'b', '--no-apk', '-j', '2', str(decoded)], log)
    dex = decoded/'build/apk/classes5.dex'
    if not dex.is_file() or dex.read_bytes()[:4] != b'dex\n':
        raise ValueError('Audited DEX was not rebuilt')
    token = secrets.token_hex(32)
    # Do not print token or key password; no uploads, no MCP or network listener here.
    config = gadget_config(token)
    for name in ('base.apk', 'split-001.apk'):
        replacements = {'classes5.dex': dex.read_bytes()} if name == 'base.apk' else {
            'lib/arm64-v8a/libfrida-gadget.so': gadget,
            'lib/arm64-v8a/libfrida-gadget.config.so': json.dumps(config).encode('utf-8')}
        rewrite_apk(source/name, private/('unsigned-'+name), replacements)
    password = secrets.token_hex(32)
    env['DVK_TEST_KEY_PASSWORD'] = password
    key = private/'test-only.p12'
    run([str(args.java_home/'bin/keytool'), '-genkeypair', '-keystore', str(key), '-storetype', 'PKCS12',
         '-alias', 'rootless-test', '-storepass:env', 'DVK_TEST_KEY_PASSWORD', '-keypass:env', 'DVK_TEST_KEY_PASSWORD',
         '-keyalg', 'RSA', '-keysize', '3072', '-validity', '365', '-dname', 'CN=DVK Separate Emulator Test Only'], log, env=env)
    (private/'key-password.txt').write_text(password, encoding='utf-8')
    (private/'gadget-token.txt').write_text(token, encoding='utf-8')
    report = {'source_package': 'drug.vokrug', 'source_version': '6.8.1', 'source_version_code': 10702,
              'frida_version': FRIDA_VERSION, 'apktool_version': '3.0.3',
              'scope': 'separate-empty-test-emulator-only', 'runtime_tested': False,
              'unity_objects_available': 'not-tested', 'root_used': False, 'ocr_used': False,
              'security_settings_modified': False, 'changes': ['added Launcher static initializer loading frida-gadget',
                  'added official ARM64 Gadget and local token-authenticated resume config',
                  'replaced source signatures/stamp with separate test signing certificate'], 'files': []}
    for name in ('base.apk', 'split-001.apk'):
        aligned = private/('aligned-'+name)
        run([str(tools/'zipalign'), '-P', '16', '-f', '4', str(private/('unsigned-'+name)), str(aligned)], log, env=env)
        target = output/name
        run([str(tools/'apksigner'), 'sign', '--ks', str(key), '--ks-key-alias', 'rootless-test',
             '--ks-pass', 'env:DVK_TEST_KEY_PASSWORD', '--key-pass', 'env:DVK_TEST_KEY_PASSWORD',
             '--out', str(target), str(aligned)], log, env=env)
        certlog = private/('signed-'+name+'.txt')
        run([str(tools/'apksigner'), 'verify', '--verbose', '--print-certs', str(target)], certlog, env=env)
        run([str(tools/'zipalign'), '-c', '-P', '16', '4', str(target)], log, env=env)
        text = certlog.read_text(encoding='utf-8')
        signer = re.search(r'Signer #1 certificate SHA-256 digest: ([a-f0-9]{64})', text).group(1)
        if signer in certificates:
            raise ValueError('Test signer must differ from vendor signer')
        allowed = {'classes5.dex'} if name == 'base.apk' else {'lib/arm64-v8a/libfrida-gadget.so', 'lib/arm64-v8a/libfrida-gadget.config.so'}
        report['files'].append({'file': name, 'source_sha256': sha(source/name), 'sha256': sha(target),
                                'test_signer_sha256': signer, **verify_preserved(source/name, target, allowed)})
        # Detached signatures are not needed for manual offline installation.
        target.with_suffix(target.suffix+'.idsig').unlink(missing_ok=True)
    if len({f['test_signer_sha256'] for f in report['files']}) != 1:
        raise ValueError('Test base/split signer mismatch')
    (output/'BUILD_REPORT.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    for p in private.rglob('*'):
        if p.is_file():
            p.chmod(0o600)
    print('Offline test APKs built and verified. Runtime compatibility NOT tested.')
    print('No device was contacted. Private output:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'work', 'apktool', 'gadget', 'java-home', 'build-tools'):
        parser.add_argument('--'+name, required=True, type=Path)
    prepare(parser.parse_args())
