#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${ANDROID_JAR:?}" "${ANDROID_BUILD_TOOLS:?}" "${FIXTURE_KEYSTORE:?Synthetic CI keystore only}"
mkdir -p out/fixture/classes out/fixture/dex
javac -encoding UTF-8 -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -d out/fixture/classes fixture/drug/vokrug/CityFixtureActivity.java
"$ANDROID_BUILD_TOOLS/aapt2" link -I "$ANDROID_JAR" --manifest fixture/AndroidManifest.xml --min-sdk-version 26 --target-sdk-version 32 -o out/fixture/unsigned.apk
"$ANDROID_BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --min-api 26 --output out/fixture/dex out/fixture/classes/drug/vokrug/*.class
python3 - <<'PY'
import zipfile
with zipfile.ZipFile('out/fixture/unsigned.apk','a') as z:z.write('out/fixture/dex/classes.dex','classes.dex')
PY
"$ANDROID_BUILD_TOOLS/zipalign" -f 4 out/fixture/unsigned.apk out/fixture/aligned.apk
"$ANDROID_BUILD_TOOLS/apksigner" sign --ks "$FIXTURE_KEYSTORE" --ks-key-alias fixture --ks-pass pass:android --out out/city-fixture.apk out/fixture/aligned.apk
