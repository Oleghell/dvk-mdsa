#!/usr/bin/env bash
# Both new packages use the same stable existing signer; never modify old APKs.
set -euo pipefail
cd "$(dirname "$0")"
: "${ANDROID_JAR:?}" "${ANDROID_BUILD_TOOLS:?}"
rm -rf out/classes out/control out/keyboard
mkdir -p out/classes out/control/dex out/keyboard/dex
javac -encoding UTF-8 -g:none -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -d out/classes src/com/dvk/control/*.java keyboard/com/dvk/keyboard/*.java
"$ANDROID_BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --min-api 26 --output out/control/dex out/classes/com/dvk/control/*.class
"$ANDROID_BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --min-api 26 --output out/keyboard/dex out/classes/com/dvk/keyboard/*.class
"$ANDROID_BUILD_TOOLS/aapt2" link -I "$ANDROID_JAR" --manifest AndroidManifest.xml --min-sdk-version 26 --target-sdk-version 32 -o out/control/unsigned.apk
"$ANDROID_BUILD_TOOLS/aapt2" compile --dir res -o out/keyboard/resources.zip
"$ANDROID_BUILD_TOOLS/aapt2" link -I "$ANDROID_JAR" --manifest KeyboardManifest.xml --min-sdk-version 26 --target-sdk-version 32 -o out/keyboard/unsigned.apk out/keyboard/resources.zip
python3 - <<'PYBUILD'
from pathlib import Path
import zipfile
for name in ('control','keyboard'):
 with zipfile.ZipFile('out/'+name+'/unsigned.apk','a') as z:z.write('out/'+name+'/dex/classes.dex','classes.dex')
PYBUILD
if [ "${CONTROL_VERIFY_ONLY:-0}" = 1 ]; then echo 'Control/keyboard compiled without signing'; exit 0; fi
: "${CITY_KEYSTORE:?Existing private key only}" "${CITY_STOREPASS_FILE:?}" "${CITY_CERT_SHA256:?}"
for name in control keyboard; do
 "$ANDROID_BUILD_TOOLS/zipalign" -f 4 "out/$name/unsigned.apk" "out/$name/aligned.apk"
 "$ANDROID_BUILD_TOOLS/apksigner" sign --ks "$CITY_KEYSTORE" --ks-key-alias dvk-city --ks-pass "file:$CITY_STOREPASS_FILE" --out "out/$name-helper.apk" "out/$name/aligned.apk"
 "$ANDROID_BUILD_TOOLS/apksigner" verify --print-certs "out/$name-helper.apk" > "out/$name/signature.txt"
done
python3 - <<'PYVERIFY'
from pathlib import Path
import os,re
for name in ('control','keyboard'):
 report=Path('out',name,'signature.txt').read_text()
 if re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-f]{64})$',report,re.M)!=[os.environ['CITY_CERT_SHA256']]:raise SystemExit('Signer mismatch')
print('Both new packages compiled with the expected stable signer')
PYVERIFY
