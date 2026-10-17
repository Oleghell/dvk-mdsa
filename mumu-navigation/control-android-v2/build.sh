#!/usr/bin/env bash
# Compile v2 for source/DEX verification. Signing keys are NEVER required in CI.
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
echo 'V2 unsigned binaries compiled; pack-control.py restores the pinned signed release'
