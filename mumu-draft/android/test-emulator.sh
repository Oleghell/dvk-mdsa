#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv out/pixel-venv
. out/pixel-venv/bin/activate
python -m pip -q install Pillow==12.3.0
adb install -t -r out/helper.apk
adb install -r out/fixture.apk
component=com.dvk.drafthelper.visual/com.dvk.drafthelper.DraftInstrumentation
start_fixture() {
 adb shell am force-stop drug.vokrug
 adb shell am start -W -n drug.vokrug/drug.vokrug.FixtureActivity --es scenario "$1"
 sleep 2
}
header_hash() {
 adb exec-out screencap -p > out/reference.png
 python - <<'PY'
from PIL import Image
import hashlib
im=Image.open('out/reference.png').convert('RGB');assert im.size==(900,1600), im.size
print(hashlib.sha256(im.crop((0,48,900,224)).tobytes()).hexdigest())
PY
}
run_helper() { adb shell am instrument -w -r -e op draft -e expected_header_sha256 "$1" "$component"; }
check_ui() {
 adb shell uiautomator dump /data/local/tmp/draft-fixture.xml >/dev/null
 adb pull /data/local/tmp/draft-fixture.xml out/check.xml >/dev/null
 python - "$1" <<'PY'
import sys,xml.etree.ElementTree as E
r=E.parse('out/check.xml');fields=[n for n in r.iter('node') if n.get('class')=='android.widget.EditText']
assert len(fields)==1
if sys.argv[1]=='EMPTY':assert fields[0].get('text') in ('','Message')
else:assert fields[0].get('text')==sys.argv[1],fields[0].get('text')
assert any(n.get('text')=='sent=0' for n in r.iter('node'))
PY
}
start_fixture empty
reference=$(header_hash)
inspection=$(adb shell am instrument -w -r -e op inspect -e expected_header_sha256 "$reference" "$component")
echo "$inspection";grep -q 'draft_status=inspection_ok' <<< "$inspection";grep -q 'field_empty=true' <<< "$inspection"
grep -q "visual_header_sha256=$reference" <<< "$inspection"
result=$(run_helper "$reference");echo "$result";grep -q 'draft_status=draft_set_verified' <<< "$result"
check_ui 'Как настроение?)'
start_fixture nonempty
result=$(run_helper "$(header_hash)");echo "$result";grep -q 'draft_status=denied_nonempty_draft' <<< "$result"
check_ui KEEP_EXISTING
start_fixture empty
result=$(run_helper "$(printf '0%.0s' {1..64})");echo "$result";grep -q 'draft_status=denied_header_changed' <<< "$result"
check_ui EMPTY
start_fixture other
result=$(run_helper "$reference");echo "$result";grep -q 'draft_status=denied_header_changed' <<< "$result"
check_ui EMPTY
adb shell am start -W -a android.settings.SETTINGS >/dev/null
sleep 2
result=$(run_helper "$reference");echo "$result";grep -q 'draft_status=denied_context_or_field' <<< "$result"
echo 'ANDROID_VISUAL_DRAFT_TESTS_PASSED: ADB/UiAutomation RGB hashes equal; inaccessible name supported; exact Cyrillic; send count zero; existing draft preserved; stale or different header and wrong app refused.'
