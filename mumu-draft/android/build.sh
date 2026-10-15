#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${ANDROID_HOME:?Android SDK required}"
SDK="$ANDROID_HOME"; BT="$SDK/build-tools/35.0.0"; JAR="$SDK/platforms/android-35/android.jar"
mkdir -p out
keytool -genkeypair -keystore out/test-signing.jks -storepass android -keypass android -alias fixture -dname 'CN=DraftOnlyDevelopment' -keyalg RSA -validity 3650 -noprompt >/dev/null 2>&1
build() {
 local name="$1" source="$2" manifest="$3"
 mkdir -p "out/$name/classes" "out/$name/dex"
 javac -encoding UTF-8 -source 8 -target 8 -bootclasspath "$JAR" -d "out/$name/classes" "$source"
 "$BT/aapt2" link -I "$JAR" --manifest "$manifest" --min-sdk-version 26 --target-sdk-version 32 -o "out/$name/unsigned.apk"
 "$BT/d8" --lib "$JAR" --min-api 26 --output "out/$name/dex" $(find "out/$name/classes" -name '*.class')
 (cd "out/$name/dex" && zip -q -j ../unsigned.apk classes.dex)
 "$BT/zipalign" -f 4 "out/$name/unsigned.apk" "out/$name/aligned.apk"
 "$BT/apksigner" sign --ks out/test-signing.jks --ks-key-alias fixture --ks-pass pass:android --key-pass pass:android --out "out/$name.apk" "out/$name/aligned.apk"
 "$BT/apksigner" verify "out/$name.apk"
}
build helper src/com/dvk/drafthelper/DraftInstrumentation.java AndroidManifest.xml
build fixture fixture/drug/vokrug/FixtureActivity.java fixture/AndroidManifest.xml
python3 - <<'PY'
import hashlib,json,pathlib
p=pathlib.Path('out/helper.apk')
pathlib.Path('out/helper-manifest.json').write_text(json.dumps({'helper_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))
PY
