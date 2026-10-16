#!/usr/bin/env bash
# Explicit release signing only. NEVER generate a key or replace the old helper.
set -euo pipefail
cd "$(dirname "$0")"
: "${ANDROID_JAR:?Android 35 android.jar required}"
: "${ANDROID_BUILD_TOOLS:?Android build-tools 35.0.0 required}"
rm -rf out/classes out/dex
mkdir -p out/classes out/dex
javac -encoding UTF-8 -g:none -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -d out/classes src/com/dvk/city/*.java
"$ANDROID_BUILD_TOOLS/aapt2" link -I "$ANDROID_JAR" --manifest AndroidManifest.xml --min-sdk-version 26 --target-sdk-version 32 -o out/unsigned.apk
"$ANDROID_BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --min-api 26 --output out/dex out/classes/com/dvk/city/*.class
python3 - <<'PY'
import zipfile
with zipfile.ZipFile('out/unsigned.apk','a') as z:z.write('out/dex/classes.dex','classes.dex')
PY
if [ "${CITY_VERIFY_ONLY:-0}" = 1 ]; then
  echo 'City sources compiled for comparison; no signing key used'
  exit 0
fi
: "${CITY_KEYSTORE:?Existing stable keystore required; no automatic key generation}"
: "${CITY_STOREPASS_FILE:?Private password file required}"
: "${CITY_CERT_SHA256:?Expected stable signer certificate digest required}"
case "$CITY_CERT_SHA256" in *[!0-9a-f]*|'') echo 'Invalid signer digest' >&2; exit 1;; esac
[ "${#CITY_CERT_SHA256}" -eq 64 ]
"$ANDROID_BUILD_TOOLS/zipalign" -f 4 out/unsigned.apk out/aligned.apk
"$ANDROID_BUILD_TOOLS/apksigner" sign --ks "$CITY_KEYSTORE" --ks-key-alias dvk-city --ks-pass "file:$CITY_STOREPASS_FILE" --out out/city-helper.apk out/aligned.apk
"$ANDROID_BUILD_TOOLS/apksigner" verify --verbose --print-certs out/city-helper.apk > out/signature-report.txt
python3 - <<'PY'
import os,re
from pathlib import Path
s=Path('out/signature-report.txt').read_text()
found=re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-f]{64})$',s,re.M)
if found != [os.environ['CITY_CERT_SHA256']]:raise SystemExit('Signer mismatch; do not distribute')
print('City-only APK compiled; exact stable signer verified')
PY
