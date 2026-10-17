"""Verify actual signer of both pinned signed APKs; never signs or installs."""
import json,os,re,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
meta=json.loads((root/'pinned/release.json').read_text(encoding='utf-8'))
for name in meta['packages']:
    out=subprocess.check_output([str(Path(os.environ['ANDROID_BUILD_TOOLS'])/'apksigner'),'verify','--verbose','--print-certs',str(root/'out'/name)],text=True)
    actual=re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-f]{64})$',out,re.M)
    if actual!=[meta['signer_sha256']]:raise SystemExit('V2 signer mismatch')
print('V2_RELEASE_SIGNATURES_VERIFIED')
