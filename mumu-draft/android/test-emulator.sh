#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
adb install -t -r out/helper.apk
adb install -r out/fixture.apk
name=$(printf TEST_RECIPIENT | base64 -w0)
start_fixture() {
 adb shell am force-stop drug.vokrug
 adb shell am start -W -n drug.vokrug/drug.vokrug.FixtureActivity --es scenario "$1"
 sleep 2
}
run_helper() {
 adb shell am instrument -w -r -e op draft -e expected_name_b64 "$1" com.dvk.drafthelper/com.dvk.drafthelper.DraftInstrumentation
}
check_ui() {
 adb shell uiautomator dump /data/local/tmp/draft-fixture.xml >/dev/null
 adb pull /data/local/tmp/draft-fixture.xml out/check.xml >/dev/null
 python3 - "$1" <<'PY'
import sys,xml.etree.ElementTree as E
r=E.parse('out/check.xml')
fields=[n for n in r.iter('node') if n.get('class')=='android.widget.EditText']
assert len(fields)==1
assert fields[0].get('text')==sys.argv[1], fields[0].get('text')
assert any(n.get('text')=='sent=0' for n in r.iter('node'))
PY
}
start_fixture empty
result=$(run_helper "$name"); echo "$result"; grep -q 'draft_status=draft_set_verified' <<< "$result"
check_ui 'Как настроение?)'
start_fixture nonempty
result=$(run_helper "$name"); echo "$result"; grep -q 'draft_status=denied_nonempty_draft' <<< "$result"
check_ui KEEP_EXISTING
start_fixture empty
wrong=$(printf WRONG_RECIPIENT | base64 -w0)
result=$(run_helper "$wrong"); echo "$result"; grep -q 'draft_status=denied_context_or_field' <<< "$result"
# Empty EditText may expose its hint as text in uiautomator; verify no phrase inserted and send count remains zero.
adb shell uiautomator dump /data/local/tmp/draft-fixture.xml >/dev/null
adb pull /data/local/tmp/draft-fixture.xml out/check.xml >/dev/null
python3 - <<'PY'
import xml.etree.ElementTree as E
r=E.parse('out/check.xml');assert not any(n.get('text')=='Как настроение?)' for n in r.iter('node'))
assert any(n.get('text')=='sent=0' for n in r.iter('node'))
PY
adb shell am start -W -a android.settings.SETTINGS >/dev/null
sleep 2
result=$(run_helper "$name"); echo "$result"; grep -q 'draft_status=denied_context_or_field' <<< "$result"
echo 'ANDROID_DRAFT_TESTS_PASSED: Cyrillic exact text, no SEND click, existing draft preserved, wrong name and wrong app refused.'
