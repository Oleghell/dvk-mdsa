#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv out/pixel-venv
. out/pixel-venv/bin/activate
python -m pip -q install Pillow==12.3.0
adb install -t -r out/helper.apk
adb install -r out/fixture.apk
component=com.dvk.navigation.v120/com.dvk.navigation.NavigationInstrumentation
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
