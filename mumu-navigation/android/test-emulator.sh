#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv out/pixel-venv
. out/pixel-venv/bin/activate
python -m pip -q install Pillow==12.3.0
adb install -t -r out/helper.apk
adb install -r out/fixture.apk
component=com.dvk.navigation.v132/com.dvk.navigation.NavigationInstrumentation
adb shell am start -W -n drug.vokrug/drug.vokrug.FixtureActivity
sleep 2
content_hash() {
 adb exec-out screencap -p > out/reference.png
 python - <<'PY'
from PIL import Image
import hashlib
im=Image.open('out/reference.png').convert('RGB');assert im.size==(900,1600),im.size
print(hashlib.sha256(im.crop((0,48,900,1600)).tobytes()).hexdigest())
PY
}
run_helper() { adb shell am instrument -w -r -e op "$1" -e expected_content_sha256 "$2" -e x "$3" -e y "$4" "$component"; }
reference=$(content_hash)
run_helper inspect "$reference" 0 0 > out/inspection.txt
cat out/inspection.txt
python - "$reference" <<'PY'
import re,base64,json,sys,pathlib
s=pathlib.Path('out/inspection.txt').read_text();assert 'navigation_status=inspection_ok' in s
r=json.loads(base64.b64decode(re.search(r'layout_b64=([A-Za-z0-9+/=]+)',s).group(1)))
assert r['content_sha256']==sys.argv[1]
n=[n for n in r['nodes'] if n['text']=='NAVIGATE'];assert len(n)==1
x1,y1,x2,y2=n[0]['bounds'];pathlib.Path('out/target.txt').write_text(f'{(x1+x2)//2} {(y1+y2)//2}')
assert any(n['text']=='KEEP_EXISTING' for n in r['nodes'])
PY
read -r x y < <(cat out/target.txt; echo)
result=$(run_helper tap "$(printf '0%.0s' {1..64})" "$x" "$y");echo "$result";grep -q navigation_status=denied_screen_changed <<< "$result"
result=$(run_helper tap "$(content_hash)" "$x" "$y");echo "$result";grep -q navigation_status=input_injected <<< "$result"
sleep 1
run_helper inspect "$(content_hash)" 0 0 > out/after.txt
python - <<'PY'
import re,base64,json,pathlib
s=pathlib.Path('out/after.txt').read_text();r=json.loads(base64.b64decode(re.search(r'layout_b64=([A-Za-z0-9+/=]+)',s).group(1)))
texts=[n['text'] for n in r['nodes']]
assert 'clicks=1' in texts,texts
assert 'KEEP_EXISTING' in texts,texts
assert 'sent=0' in texts,texts
PY
result=$(run_helper tap "$(content_hash)" 1 1);echo "$result";grep -q navigation_status=denied_coordinates <<< "$result"
result=$(run_helper back "$(content_hash)" 0 0);echo "$result";grep -q navigation_status=input_injected <<< "$result"
sleep 1
adb shell am start -W -a android.settings.SETTINGS >/dev/null
sleep 1
result=$(run_helper back "$(content_hash)" 0 0);echo "$result";grep -q navigation_status=denied_context_or_layout <<< "$result"
echo 'ANDROID_NAVIGATION_TESTS_PASSED: pixel hash equality; real injected tap and Back; stale screen/wrong app/invalid coordinates refused; fixture draft unchanged; fixture sent=0. NOT a real DrugVokrug test.'

# Fixed profile-cloud action: an animated gift must not block it or be tapped.
profile_start() {
 adb shell am force-stop drug.vokrug
 adb shell am start -W -n drug.vokrug/drug.vokrug.FixtureActivity --es scenario "$1" >/dev/null
 sleep 2
}
profile_hash() {
 adb exec-out screencap -p > out/profile.png
 PYTHONPATH=.. python - <<'PYCODE'
from pathlib import Path
from mumu_bridge import profile_guard
r=profile_guard(Path('out/profile.png').read_bytes());assert r['button_matches'],r
print(r['profile_sha256'])
PYCODE
}
profile_start profile_a
reference=$(profile_hash)
full_reference=$(content_hash)
profile_start profile_b
second=$(profile_hash)
test "$reference" = "$second"
result=$(run_helper tap "$full_reference" 321 1515);echo "$result";grep -q navigation_status=denied_screen_changed <<< "$result"
result=$(run_helper profile_chat "$reference" 800 950);echo "$result";grep -q navigation_status=denied_coordinates <<< "$result"
profile_start profile_other
result=$(run_helper profile_chat "$reference" 321 1515);echo "$result";grep -q navigation_status=denied_screen_changed <<< "$result"
profile_start profile_bad_button
result=$(run_helper profile_chat "$reference" 321 1515);echo "$result";grep -q navigation_status=denied_context_or_layout <<< "$result"
profile_start profile_animated
result=$(run_helper profile_chat "$reference" 321 1515);echo "$result";grep -q navigation_status=input_injected <<< "$result"
adb shell uiautomator dump /data/local/tmp/profile-fixture.xml >/dev/null
adb pull /data/local/tmp/profile-fixture.xml out/profile-check.xml >/dev/null
python - <<'PYCODE'
import xml.etree.ElementTree as E
r=E.parse('out/profile-check.xml')
assert any(n.get('content-desc')=='chat=1 gifts=0' for n in r.iter('node'))
PYCODE
result=$(run_helper profile_back "$(profile_hash)" 0 0);echo "$result";grep -q navigation_status=input_injected <<< "$result"
profile_start profile_corner
corner_reference=$(profile_hash)
result=$(run_helper profile_chat "$reference" 321 1515);echo "$result";grep -q navigation_status=denied_screen_changed <<< "$result"
result=$(run_helper profile_chat "$corner_reference" 321 1515);echo "$result";grep -q navigation_status=input_injected <<< "$result"
echo 'ANDROID_PROFILE_CLOUD_TESTS_PASSED: Python/Android masked hashes equal; animated gift ignored only for fixed lower cloud action; other identity/button changes refused; exact lower cloud tapped once; gift taps zero. SYNTHETIC FIXTURE ONLY.'

input_hash() {
 adb exec-out screencap -p > out/input.png
 PYTHONPATH=.. python - <<'PYCODE'
from pathlib import Path
from mumu_bridge import input_context_sha256
print(input_context_sha256(Path('out/input.png').read_bytes()))
PYCODE
}
# Approved greeting text: native readback only, never press SEND or Enter.
check_greeting_field() {
 adb shell uiautomator dump /data/local/tmp/greeting-fixture.xml >/dev/null
 adb pull /data/local/tmp/greeting-fixture.xml out/greeting-check.xml >/dev/null
 PYTHONPATH=.. python - "$1" <<'PYCODE'
import sys,xml.etree.ElementTree as E
from mumu_bridge import GREETINGS
r=E.parse('out/greeting-check.xml');fields=[n for n in r.iter('node') if n.get('class')=='android.widget.EditText']
assert len(fields)==1
expected=GREETINGS[int(sys.argv[1])] if sys.argv[1].isdigit() else sys.argv[1]
assert fields[0].get('text')==expected,fields[0].get('text')
assert fields[0].get('bounds')=='[152,1488][748,1544]',fields[0].get('bounds')
assert any(n.get('text')=='sent=0' for n in r.iter('node'))
PYCODE
}
for variant in {0..9}; do
 profile_start greeting_empty
 result=$(run_helper greeting "$(input_hash)" "$variant" 0);echo "$result";grep -q navigation_status=greeting_draft_verified <<< "$result"
 check_greeting_field "$variant"
done
profile_start greeting_nonempty
result=$(run_helper greeting "$(input_hash)" 0 0);echo "$result";grep -q navigation_status=denied_nonempty_draft <<< "$result"
check_greeting_field KEEP_EXISTING
profile_start greeting_empty
result=$(run_helper greeting "$(printf '0%.0s' {1..64})" 0 0);echo "$result";grep -q navigation_status=denied_screen_changed <<< "$result"
for scenario in greeting_duplicate greeting_password;do
 profile_start "$scenario"
 result=$(run_helper greeting "$(input_hash)" 0 0);echo "$result";grep -q navigation_status=denied_field <<< "$result"
done
profile_start greeting_empty
reference=$(input_hash)
profile_start greeting_other
result=$(run_helper greeting "$reference" 0 0);echo "$result";grep -q navigation_status=denied_screen_changed <<< "$result"
profile_start greeting_switch_after_input
result=$(run_helper greeting "$(input_hash)" 0 0);echo "$result";grep -q navigation_status=indeterminate_after_attempt <<< "$result"
adb shell am start -W -a android.settings.SETTINGS >/dev/null
sleep 1
result=$(run_helper greeting "$reference" 0 0);echo "$result";grep -q navigation_status=denied_context_or_layout <<< "$result"
echo 'ANDROID_GREETING_TESTS_PASSED: all ten exact Unicode native drafts; sent=0; nonempty preserved; stale screen/other recipient/password/multiple inputs/wrong app refused; post-input context switch indeterminate. This is NOT proof of Unity composition or real sending.'

profile_start greeting_blink
reference=$(input_hash)
sleep 1
result=$(run_helper greeting "$reference" 0 0);echo "$result";grep -q navigation_status=greeting_draft_verified <<< "$result"
check_greeting_field 0
result=$(run_helper finish_input "$(input_hash)" 1 0);echo "$result";grep -q navigation_status=denied_text <<< "$result"
result=$(run_helper finish_input "$(input_hash)" 0 0);echo "$result";grep -q navigation_status=input_injected <<< "$result"
echo 'ANDROID_CARET_TESTS_PASSED: animated caret ignored only inside independently verified native input; exact Unicode text preserved; mismatched greeting refused; Android Back accepted, not Windows Esc and not a send action. SYNTHETIC FIXTURE ONLY.'
