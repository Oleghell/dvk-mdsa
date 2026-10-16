"""Native tests ONLY on the disposable CI emulator and synthetic fixture."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import time

COMPONENT='com.dvk.control.v1/com.dvk.control.ControlInstrumentation'
IME='com.dvk.keyboard.v1/com.dvk.keyboard.BridgeIme'

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('CI synthetic emulator only')
    devices=subprocess.check_output(['adb','devices'],text=True)
    serials=re.findall(r'^(emulator-\d+)\s+device$',devices,re.M)
    if len(serials)!=1:raise SystemExit('Exactly one synthetic emulator required')
    prefix=['adb','-s',serials[0]]
    def adb(*args):return subprocess.check_output(prefix+list(args),text=True,timeout=100)
    last={}
    def call(payload):
        raw=base64.b64encode(json.dumps(payload,separators=(',',':'),ensure_ascii=True).encode()).decode()
        output=adb('shell','am','instrument','-w','-r','-e','request_b64',raw,COMPONENT)
        statuses=re.findall(r'^INSTRUMENTATION_RESULT: control_status=([a-z_]+)\s*$',output,re.M)
        last.clear();last['operation']=payload.get('op');last['statuses']=statuses
        for label in ('code','phase'):
            values=re.findall(r'^INSTRUMENTATION_RESULT: control_diagnostic_'+label+r'=([a-z_]+)\s*$',output,re.M)
            if len(values)==1:last[label]=values[0]
        assert len(statuses)==1,last
        report=re.findall(r'^INSTRUMENTATION_RESULT: report_b64=([A-Za-z0-9+/=]+)\s*$',output,re.M)
        return statuses[0],json.loads(base64.b64decode(report[0])) if report else None
    def inspect():
        status,data=call({'op':'inspect'});assert status=='inspection_ok',dict(last)
        return data
    def expect(payload,wanted):
        status,data=call(payload);assert status==wanted,(status,wanted)
        return data
    def start(scenario):
        adb('shell','am','force-stop','drug.vokrug')
        adb('shell','am','start','-W','-n','drug.vokrug/.CityFixtureActivity','--es','scenario',scenario)
        time.sleep(1)
    def gesture(d,op='tap',**kwargs):
        p=dict(op=op,expected_sha256=d['content_sha256'],x=200,y=230,x2=0,y2=0,duration_ms=0,keycode=0);p.update(kwargs);return p
    def perform_gesture(op='tap',**kwargs):
        # Cursor/IME animations can invalidate full-screen hashes. Only a known
        # pre-injection stale-screen refusal allows a fresh observation/retry.
        for attempt in range(6):
            status,_=call(gesture(inspect(),op=op,**kwargs))
            if status=='input_injected':return
            if status!='denied_screen_changed':raise AssertionError(status)
        raise AssertionError('Synthetic screen did not settle')
    def text(d,op,value):return dict(op=op,expected_sha256=d['field_context_sha256'],bounds=d['bounds'],expected_text=d['text'],text=value,delay_ms=20)
    previous=adb('shell','settings','get','secure','default_input_method').strip()
    try:
        for name in ('keyboard-helper.apk','control-helper.apk'):
            adb('install','-t','-r',os.path.join(os.path.dirname(__file__),'out',name))
        adb('shell','ime','enable',IME);adb('shell','ime','set',IME)
        start('city_empty')
        perform_gesture();time.sleep(1)
        d=inspect();assert d['focused'] and d['text']==''
        expect(text(d,'type','Нальчик'),'text_verified')
        d=inspect();assert d['text']=='Нальчик'
        # The fixture's TextWatcher proves a sequence of seven commits, not SET_TEXT.
        tree=adb('shell','uiautomator','dump','/sdcard/control-fixture.xml')
        tree=adb('shell','cat','/sdcard/control-fixture.xml')
        assert 'changes=7' in tree,tree
        expect(text(d,'clear',''),'text_verified')
        d=inspect();assert d['text']==''
        expect(text(d,'type','Я 🙂'),'text_verified')
        d=inspect();assert d['text']=='Я 🙂'
        bad=text(d,'clear','');bad['expected_text']='not-current'
        expect(bad,'denied_screen_changed')
        bad=text(d,'clear','');bad['expected_sha256']='0'*64
        expect(bad,'denied_screen_changed')
        # Known stale gesture refused before injection.
        bad=gesture(d);bad['expected_sha256']='0'*64
        expect(bad,'denied_screen_changed')
        expect({'op':'shell'},'denied_context')
        expect(text(d,'clear',''),'text_verified')
        d=inspect();expect(text(d,'type','bad\ntext'),'denied_arguments')
        perform_gesture(op='hold',duration_ms=300)
        perform_gesture(op='swipe',x=450,y=1100,x2=450,y2=1000,duration_ms=150)
        perform_gesture(op='key',x=0,y=0,keycode=4)
        # A real foreign window must still be rejected, never accepted after waiting.
        adb('shell','input','keyevent','3');time.sleep(1)
        expect({'op':'inspect'},'denied_context');assert last.get('code')=='wrong_package',dict(last)
        start('city_password');assert not inspect()['focused']
        # Wrong IME is a known refusal, not a silently successful insertion.
        adb('shell','ime','set',previous)
        start('city_empty');perform_gesture();time.sleep(1)
        d=inspect();expect(text(d,'type','Нальчик'),'denied_ime')
        assert inspect()['text']==''
        print('UNIVERSAL_CONTROL_NATIVE_FIXTURE_PASS')
    except BaseException:
        # Disposable synthetic emulator only; never collect a user's MuMu data.
        diagnostics=Path(__file__).resolve().parent/'out'/'ci-diagnostics'
        diagnostics.mkdir(parents=True,exist_ok=True)
        (diagnostics/'control-last.json').write_text(json.dumps(last,indent=2)+'\n')
        for name,args,binary in (
            ('screen.png',['exec-out','screencap','-p'],True),
            ('window.txt',['shell','dumpsys','window'],False)):
            try:
                result=subprocess.run(prefix+args,capture_output=True,timeout=15)
                (diagnostics/name).write_bytes(result.stdout)
            except Exception:pass
        raise
    finally:
        if previous and previous!='null':adb('shell','ime','set',previous)

if __name__=='__main__':main()
