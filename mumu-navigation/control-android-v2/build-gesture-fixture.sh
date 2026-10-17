#!/usr/bin/env bash
# Synthetic UI signed with CI's fixture key; production helpers are never re-signed.
set -euo pipefail
cd "$(dirname "$0")"
: "${ANDROID_JAR:?}" "${ANDROID_BUILD_TOOLS:?}" "${FIXTURE_KEYSTORE:?}"
mkdir -p out/gesture/classes out/gesture/dex
fixture=../control-android-next/fixture
javac -encoding UTF-8 -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -d out/gesture/classes "$fixture/drug/vokrug/GestureFixtureActivity.java"
"$ANDROID_BUILD_TOOLS/aapt2" link -I "$ANDROID_JAR" --manifest "$fixture/AndroidManifest.xml" --min-sdk-version 26 --target-sdk-version 32 -o out/gesture/unsigned.apk
"$ANDROID_BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --min-api 26 --output out/gesture/dex out/gesture/classes/drug/vokrug/*.class
python3 - <<'PYZIP'
import zipfile
with zipfile.ZipFile('out/gesture/unsigned.apk','a') as z:z.write('out/gesture/dex/classes.dex','classes.dex')
PYZIP
"$ANDROID_BUILD_TOOLS/zipalign" -f 4 out/gesture/unsigned.apk out/gesture/aligned.apk
"$ANDROID_BUILD_TOOLS/apksigner" sign --ks "$FIXTURE_KEYSTORE" --ks-key-alias fixture --ks-pass pass:android --out out/gesture-fixture.apk out/gesture/aligned.apk
