#!/usr/bin/env bash
# ONLY the fresh synthetic GitHub Actions emulator, never a user's MuMu.
set -euo pipefail
cd "$(dirname "$0")"
adb install -t -r out/city-helper.apk >/dev/null
adb install -t -r -d out/city-fixture.apk >/dev/null
COMPONENT=com.dvk.city.v1/com.dvk.city.CityInstrumentation
ZERO=$(printf '%064d' 0)
start_case(){ adb shell am force-stop drug.vokrug; adb shell am start -W -n drug.vokrug/.CityFixtureActivity --es scenario "$1" >/dev/null; sleep 1; }
call(){ adb shell am instrument -w -r -e op "$1" -e expected_content_sha256 "$2" -e x "$3" -e y "$4" "$COMPONENT"; }
expect(){ if ! grep -q "navigation_status=$2" <<<"$1"; then echo "Synthetic city check failed; wanted $2" >&2; exit 1; fi; }
inspect_hash(){
 local result; result=$(call inspect_city "$ZERO" 0 0); expect "$result" city_inspection_ok
 printf '%s' "$result" | python3 -c 'import sys,re,base64,json; s=sys.stdin.read(); m=re.search(r"layout_b64=([A-Za-z0-9+/=]+)",s); print(json.loads(base64.b64decode(m[1]))["city_context_sha256"])'
}
start_case city_empty
HASH=$(inspect_hash)
expect "$(call city_input "$HASH" 0 0)" city_input_native_verified
# Exact previous query is mandatory; writing a second city requires previous=0 encoded as1.
HASH=$(inspect_hash)
expect "$(call city_input "$HASH" 1 0)" denied_field
expect "$(call city_input "$HASH" 1 1)" city_input_native_verified
for scenario in city_unfocused city_nonempty; do
 start_case "$scenario"; HASH=$(inspect_hash); expect "$(call city_input "$HASH" 0 0)" denied_field
done
snapshot_hash(){
 adb exec-out screencap -p | python3 -c 'from PIL import Image; import sys,hashlib; im=Image.open(sys.stdin.buffer).convert("RGB"); assert im.size==(900,1600); im.paste((0,0,0),(118,196,786,276)); print(hashlib.sha256(im.crop((0,48,900,1600)).tobytes()).hexdigest())'
}
for scenario in city_badbounds city_duplicate city_password city_badanchor; do
 start_case "$scenario"; expect "$(call inspect_city "$ZERO" 0 0)" denied_context_or_layout
 case "$scenario" in
  city_badbounds) REASON=editor_bounds;;
  city_duplicate|city_password) REASON=editor_invalid;;
  city_badanchor) REASON=title_anchor;;
 esac
 DIAG=$(call inspect_city "$ZERO" 0 0)
 expect "$DIAG" denied_context_or_layout
 grep -q "city_diagnostic_code=$REASON" <<<"$DIAG" || { echo 'Missing fixed diagnostic code' >&2; exit 1; }
 HASH=$(snapshot_hash); expect "$(call city_input "$HASH" 0 0)" denied_context_or_layout
done
start_case city_empty
HASH=$(inspect_hash)
expect "$(call city_input "$ZERO" 0 0)" denied_screen_changed
expect "$(call city_input "$HASH" 30 0)" denied_arguments
expect "$(call city_input "$HASH" 0 31)" denied_arguments
expect "$(call greeting "$HASH" 0 0)" denied_arguments
expect "$(call tap "$HASH" 0 0)" denied_arguments
start_case city_switch_after_input
HASH=$(inspect_hash)
expect "$(call city_input "$HASH" 0 0)" indeterminate_after_attempt
printf 'CITY_NATIVE_FIXTURE_PASS\n'
