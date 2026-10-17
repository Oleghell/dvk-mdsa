"""Candidate gestures on ONE disposable emulator; no accounts or distribution."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import time



def safe_native_diagnostic(output, operation, report=None):
    """Only bounded machine codes; never echo arbitrary instrumentation output."""
    statuses={'inspection_ok','input_injected','text_verified','denied_arguments',
              'denied_field','denied_screen_changed','denied_context','denied_ime',
              'indeterminate_after_attempt'}
    codes={'root_not_ready','node_not_ready','wrong_package','screenshot_unavailable',
           'screen_dimensions','internal_error','invalid_editor_guard','editor_changed'}
    phases={'startup','startup_root','arguments','inspect_screen','inspect_field',
            'validate_field','ime_input','gesture_guard','gesture_inject'}
    result={'operation':operation if operation in {'inspect','tap','hold','swipe','key','type','clear'} else 'other'}
    for key,allowed in (('status',statuses),('diagnostic_code',codes),('diagnostic_phase',phases)):
        values=re.findall(r'^INSTRUMENTATION_RESULT: control_'+key+r'=([a-z_]+)\s*$',output,re.M)
        if len(values)==1 and values[0] in allowed:result[key]=values[0]
    if isinstance(report,dict):
        if type(report.get('guard_check')) is int and report['guard_check'] in (0,1):result['guard_check']=report['guard_check']
        if type(report.get('masked_context_match')) is bool:result['masked_context_match']=report['masked_context_match']
        if type(report.get('diff_pixels')) is int and 0<=report['diff_pixels']<=900*1552:result['diff_pixels']=report['diff_pixels']
        b=report.get('diff_bounds')
        if isinstance(b,list) and len(b)==4 and all(type(v) is int for v in b) and 0<=b[0]<b[2]<=900 and 48<=b[1]<b[3]<=1600:result['diff_bounds']=b
    return result


def failure_annotation(last):
    # Everything passed to Actions annotations came through the fixed allowlist.
    return '::error title=Candidate native action failed::'+json.dumps(last,ensure_ascii=True,sort_keys=True)

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Disposable CI only')
    devices=subprocess.check_output(['adb','devices'],text=True)
    serials=re.findall(r'^(emulator-\d+)\s+device$',devices,re.M)
    if len(serials)!=1:raise SystemExit('Exactly one disposable emulator required')
    prefix=['adb','-s',serials[0]]
    here=Path(__file__).resolve().parent
    def adb(*args):return subprocess.check_output(prefix+list(args),text=True,timeout=100)
    last={}
    def call(payload):
        raw=base64.b64encode(json.dumps(payload,ensure_ascii=True,separators=(',',':')).encode()).decode()
        s=adb('shell','am','instrument','-w','-r','-e','request_b64',raw,'com.dvk.control.v2/com.dvk.control.ControlInstrumentation')
        status=re.findall(r'^INSTRUMENTATION_RESULT: control_status=([a-z_]+)\s*$',s,re.M)
        data=re.findall(r'^INSTRUMENTATION_RESULT: report_b64=([A-Za-z0-9+/=]+)\s*$',s,re.M)
        report=json.loads(base64.b64decode(data[0])) if len(data)==1 else None
        last.clear();last.update(safe_native_diagnostic(s,payload.get('op'),report))
        assert len(status)==1,'Missing/duplicate native status'
        return status[0],report
    def inspect():
        status,d=call({'op':'inspect'});assert status=='inspection_ok',status
        assert d.get('gesture_editor_guard_supported') is True
        return d
    def settled_inspect():
        # Observe rendering only; never re-send an input action after refusal.
        previous=inspect()
        for _ in range(8):
            time.sleep(.15)
            current=inspect()
            keys=('focused','bounds','text','field_context_sha256')
            if all(current.get(k)==previous.get(k) for k in keys):return current
            previous=current
        raise AssertionError('Synthetic outside-editor rendering did not settle')
    def payload(d):
        return dict(op='tap',expected_sha256=d['field_context_sha256'],x=320,y=380,x2=0,y2=0,duration_ms=0,keycode=0,
                    editor_guard={'bounds':d['bounds'],'expected_text':d['text']})
    diagnostics=here/'out'/'synthetic-diagnostics'
    def capture(name):
        # Only the disposable synthetic emulator; never run against a real device.
        diagnostics.mkdir(parents=True,exist_ok=True)
        image=subprocess.check_output(prefix+['exec-out','screencap','-p'],timeout=15)
        (diagnostics/(name+'.png')).write_bytes(image)
        return image
    results={}
    try:
        for name in ('control-helper.apk','keyboard-helper.apk','gesture-fixture.apk'):
            adb('install','-t','-r',str(here/'out'/name))
        # This tests taps, not typing: do not switch the OS keyboard.
        adb('shell','am','start','-W','-n','drug.vokrug/.GestureFixtureActivity');time.sleep(1)
        first=settled_inspect();capture('first');assert first['focused'] and first['bounds']==[118,196,786,276]
        assert first['text']=='Нижнекамск'
        # The two source screenshots intentionally differ ONLY inside the editor.
        # A test loop waits for evidence of rendering, but NEVER retries an action.
        changed=False
        for _ in range(8):
            time.sleep(.09);other=inspect()
            if other['field_context_sha256']!=first['field_context_sha256']:
                capture('changed')
                results['failure_stage']='animated_editor_outside_context_changed'
                raise AssertionError('Synthetic pixels outside the native editor changed; see synthetic-diagnostics')
            if other['content_sha256']!=first['content_sha256']:changed=True;break
        assert changed,'Fixture must prove changing pixels inside the editor'
        results['animated_editor_observed']=True
        stale=payload(settled_inspect());bad=dict(stale);bad['expected_sha256']='0'*64
        assert call(bad)[0]=='denied_screen_changed'
        bad=payload(settled_inspect());bad['editor_guard']['expected_text']='stale text'
        assert call(bad)[0]=='denied_context'
        bad=payload(settled_inspect());bad['editor_guard']['bounds']=[118,197,786,277]
        assert call(bad)[0]=='denied_context'
        results['wrong_context_text_bounds_refused']=True
        # One request, one verified increment; no action retry of any kind.
        fresh=settled_inspect();tap_status,_=call(payload(fresh))
        assert tap_status=='input_injected',json.dumps(last,sort_keys=True)
        adb('shell','uiautomator','dump','/sdcard/candidate-fixture.xml')
        tree=adb('shell','cat','/sdcard/candidate-fixture.xml');assert 'candidate_taps=1' in tree
        results['single_guarded_tap_observed']=True
        # Distinct actions with a fresh observation each, NOT retries of a refusal.
        for count in (2,3):
            fresh=settled_inspect();tap_status,_=call(payload(fresh))
            assert tap_status=='input_injected',json.dumps(last,sort_keys=True)
            adb('shell','uiautomator','dump','/sdcard/candidate-fixture.xml')
            assert 'candidate_taps='+str(count) in adb('shell','cat','/sdcard/candidate-fixture.xml')
        results['three_distinct_guarded_taps_observed']=True
        # The outside-editor counter changed; old context must not authorize tap 2.
        assert call(stale)[0]=='denied_screen_changed'
        results['outside_editor_change_refused']=True
        adb('shell','input','keyevent','3');time.sleep(.5)
        assert call({'op':'inspect'})[0]=='denied_context'
        results['foreign_package_refused']=True
        results['passed']=True
    except BaseException:
        try:
            capture('failure')
            (diagnostics/'window.txt').write_text(adb('shell','dumpsys','window'),encoding='utf-8')
            adb('shell','uiautomator','dump','/sdcard/candidate-failure.xml')
            (diagnostics/'hierarchy.xml').write_text(adb('shell','cat','/sdcard/candidate-failure.xml'),encoding='utf-8')
        except Exception:
            results['diagnostic_capture_failed']=True
        results['passed']=False
        results['native_last']=dict(last)
        print(failure_annotation(last),flush=True)
        raise
    finally:
        out=here/'out'/'guarded-release-result.json';out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    print('CURSOR_STABLE_SIGNED_V2_PASS')


if __name__=='__main__':main()
