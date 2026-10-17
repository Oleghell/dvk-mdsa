#!/usr/bin/env bash
# Synthetic CI only: ephemeral test signing, never a distributable user release.
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo 'Disposable CI only'; exit 1; }
cd "$(dirname "$0")"
: "${ANDROID_JAR:?}" "${ANDROID_BUILD_TOOLS:?}"
workspace="$(cd ../.. && pwd)"
candidate="$workspace/out/cursor-stable-ci-source"
python3 prepare_candidate.py "$candidate"
CONTROL_VERIFY_ONLY=1 bash "$candidate/build.sh"
mkdir -p out/fixture/classes out/fixture/dex
javac -encoding UTF-8 -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -d out/fixture/classes fixture/drug/vokrug/GestureFixtureActivity.java
"$ANDROID_BUILD_TOOLS/aapt2" link -I "$ANDROID_JAR" --manifest fixture/AndroidManifest.xml --min-sdk-version 26 --target-sdk-version 32 -o out/fixture/unsigned.apk
"$ANDROID_BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --min-api 26 --output out/fixture/dex out/fixture/classes/drug/vokrug/*.class
python3 - <<'PY'
import zipfile
with zipfile.ZipFile('out/fixture/unsigned.apk','a') as z:z.write('out/fixture/dex/classes.dex','classes.dex')
PY
keytool -genkeypair -keystore out/synthetic-ci.jks -storepass android -keypass android -alias candidate-ci -dname 'CN=SyntheticCandidateCIOnly' -keyalg RSA -validity 2 -noprompt >/dev/null 2>&1
for name in control keyboard fixture; do
  input="$candidate/out/$name/unsigned.apk"
  if [ "$name" = fixture ]; then input=out/fixture/unsigned.apk; fi
  "$ANDROID_BUILD_TOOLS/zipalign" -f 4 "$input" "out/$name-aligned.apk"
  "$ANDROID_BUILD_TOOLS/apksigner" sign --ks out/synthetic-ci.jks --ks-key-alias candidate-ci --ks-pass pass:android --key-pass pass:android --out "out/$name-synthetic.apk" "out/$name-aligned.apk"
  "$ANDROID_BUILD_TOOLS/apksigner" verify "out/$name-synthetic.apk"
done
