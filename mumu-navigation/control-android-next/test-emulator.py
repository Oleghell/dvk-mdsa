"""Candidate gestures on ONE disposable emulator; no accounts or distribution."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import time


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Disposable CI only')
    devices=subprocess.check_output(['adb','devices'],text=True)
    serials=re.findall(r'^(emulator-\d+)\s+device$',devices,re.M)
    if len(serials)!=1:raise SystemExit('Exactly one disposable emulator required')
    prefix=['adb','-s',serials[0]]
    here=Path(__file__).resolve().parent
    def adb(*args):return subprocess.check_output(prefix+list(args),text=True,timeout=100)
    def call(payload):
        raw=base64.b64encode(json.dumps(payload,ensure_ascii=True,separators=(',',':')).encode()).decode()
        s=adb('shell','am','instrument','-w','-r','-e','request_b64',raw,'com.dvk.control.v1/com.dvk.control.ControlInstrumentation')
        status=re.findall(r'^INSTRUMENTATION_RESULT: control_status=([a-z_]+)\s*$',s,re.M)
        assert len(status)==1,'Missing/duplicate native status'
        data=re.findall(r'^INSTRUMENTATION_RESULT: report_b64=([A-Za-z0-9+/=]+)\s*$',s,re.M)
        return status[0],json.loads(base64.b64decode(data[0])) if len(data)==1 else None
    def inspect():
        status,d=call({'op':'inspect'});assert status=='inspection_ok',status
        assert d.get('gesture_editor_guard_supported') is True
        return d
    def payload(d):
        return dict(op='tap',expected_sha256=d['field_context_sha256'],x=320,y=380,x2=0,y2=0,duration_ms=0,keycode=0,
                    editor_guard={'bounds':d['bounds'],'expected_text':d['text']})
    previous=adb('shell','settings','get','secure','default_input_method').strip()
    results={}
    try:
        for name in ('control','keyboard','fixture'):
            adb('install','-t','-r',str(here/'out'/f'{name}-synthetic.apk'))
        ime='com.dvk.keyboard.v1/com.dvk.keyboard.BridgeIme'
        adb('shell','ime','enable',ime);adb('shell','ime','set',ime)
        adb('shell','am','start','-W','-n','drug.vokrug/.GestureFixtureActivity');time.sleep(1)
        first=inspect();assert first['focused'] and first['bounds']==[118,196,786,276]
        assert first['text']=='Нижнекамск'
        # The two source screenshots intentionally differ ONLY inside the editor.
        # A test loop waits for evidence of rendering, but NEVER retries an action.
        changed=False
        for _ in range(8):
            time.sleep(.09);other=inspect()
            assert other['field_context_sha256']==first['field_context_sha256']
            if other['content_sha256']!=first['content_sha256']:changed=True;break
        assert changed,'Fixture must prove changing pixels inside the editor'
        results['animated_editor_observed']=True
        stale=payload(inspect());bad=dict(stale);bad['expected_sha256']='0'*64
        assert call(bad)[0]=='denied_screen_changed'
        bad=payload(inspect());bad['editor_guard']['expected_text']='stale text'
        assert call(bad)[0]=='denied_context'
        bad=payload(inspect());bad['editor_guard']['bounds']=[118,197,786,277]
        assert call(bad)[0]=='denied_context'
        results['wrong_context_text_bounds_refused']=True
        # One request, one verified increment; no action retry of any kind.
        fresh=inspect();assert call(payload(fresh))[0]=='input_injected'
        adb('shell','uiautomator','dump','/sdcard/candidate-fixture.xml')
        tree=adb('shell','cat','/sdcard/candidate-fixture.xml');assert 'candidate_taps=1' in tree
        results['single_guarded_tap_observed']=True
        # The outside-editor counter changed; old context must not authorize tap 2.
        assert call(stale)[0]=='denied_screen_changed'
        results['outside_editor_change_refused']=True
        adb('shell','input','keyevent','3');time.sleep(.5)
        assert call({'op':'inspect'})[0]=='denied_context'
        results['foreign_package_refused']=True
        results['passed']=True
    finally:
        if previous and previous!='null':adb('shell','ime','set',previous)
        out=here/'out'/'candidate-result.json';out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    print('CURSOR_STABLE_GESTURE_CANDIDATE_PASS')


if __name__=='__main__':main()
