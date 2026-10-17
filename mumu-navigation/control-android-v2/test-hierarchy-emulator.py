"""Hierarchy/actions/OCR tests ONLY against disposable CI fixture, never MuMu."""
import base64,json,os,re,subprocess,sys,time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ui_backend import NativeBackend
from ui_runtime import AndroidUI
from ui_ocr import TesseractFallback
from ui_model import AmbiguousElement,ElementNotFound
from ui_protocol import valid_native

COMPONENT='com.dvk.control.v2/com.dvk.control.ControlInstrumentation'

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Disposable CI synthetic emulator only')
    devices=subprocess.check_output(['adb','devices'],text=True)
    serials=re.findall(r'^(emulator-\d+)\s+device$',devices,re.M)
    if len(serials)!=1:raise SystemExit('One synthetic emulator required')
    prefix=['adb','-s',serials[0]]
    def adb(*args):return subprocess.check_output(prefix+list(args),timeout=60)
    def call(req):
        assert valid_native(req),req.get('op')
        payload=base64.b64encode(json.dumps(req,ensure_ascii=True,separators=(',',':')).encode()).decode()
        out=adb('shell','am','instrument','-w','-r','-e','request_b64',payload,COMPONENT).decode('utf-8')
        statuses=re.findall(r'^INSTRUMENTATION_RESULT: control_status=([a-z_]+)\s*$',out,re.M)
        assert len(statuses)==1,statuses
        return statuses[0],out
    def expect(req,status):
        actual,out=call(req);assert actual==status,(req['op'],actual,status)
        return NativeBackend.report(out) if 'report_b64=' in out else {}
    backend=NativeBackend.__new__(NativeBackend);backend.reader=SimpleNamespace(control_enabled=True);backend.control=SimpleNamespace(instrument=call)
    captures=[0]
    def capture():captures[0]+=1;return adb('exec-out','screencap','-p')
    def mutate(e,op,**kw):return backend.perform(e,op,**kw)
    ui=AndroidUI(backend,mutation=mutate,ocr=TesseractFallback(capture))
    def start(scenario='native'):
        adb('shell','am','force-stop','drug.vokrug')
        adb('shell','am','start','-W','-n','drug.vokrug/.HierarchyFixtureActivity','--es','scenario',scenario)
        # Condition wait, not a fixed screen-loading sleep.
        if scenario=='native':ui.wait_for_element(resource_id='android:id/button1',timeout=10)
        else:ui.wait_for_element(description='visual-clicks=0',timeout=10)
    original_rotation=adb('shell','settings','get','system','user_rotation').decode().strip()
    original_auto=adb('shell','settings','get','system','accelerometer_rotation').decode().strip()
    try:
        adb('install','-t','-r',str(Path(__file__).parent/'out/control-helper.apk'))
        for w,h,dpi in ((720,1280,240),(1080,1920,320),(1600,900,240),(900,1600,240)):
            adb('shell','wm','size',f'{w}x{h}');adb('shell','wm','density',str(dpi));start()
            t=backend.snapshot();assert (t.width,t.height)==(w,h),(t.width,t.height,w,h)
            assert t.density_dpi==dpi,t.density_dpi
            assert any(n['password'] for n in t.nodes)
            assert all(not n['text'] for n in t.nodes if n['password'])
            assert 'SECRET_PASSWORD' not in json.dumps(list(t.nodes))
            assert captures[0]==0,'Native path must not capture screenshots'
            labels=[n['text'] for n in t.nodes if n['resource_id'] in ('android:id/button1','android:id/button2')]
            assert labels==['Написать','Написать'],('Synthetic fixture labels',labels)
            try:ui.find_element(text='Написать')
            except AmbiguousElement:pass
            else:raise AssertionError('Duplicate native labels must not silently select first')
            e=ui.find_element(resource_id='android:id/button1')
            state,_=e.click(action_id='b'*32,purpose='synthetic');assert state=='input_injected',state
            ui.wait_for_element(text='clicks=1',timeout=3)
            expect({'op':'ui_click','selector':{'resource_id':'android:id/button1'},'expected_tree_sha256':e.context,'allow_coordinate_fallback':False},'denied_screen_changed')
            field=ui.find_element(resource_id='android:id/edit',editable=True)
            state,_=field.set_text('Нальчик 🙂',action_id='c'*32,purpose='synthetic',expected_text='');assert state=='text_verified',state
            ui.wait_for_element(resource_id='android:id/edit',text='Нальчик 🙂',timeout=3)
            t=backend.snapshot()
            expect({'op':'ui_set_text','selector':{'resource_id':'android:id/text2'},'expected_tree_sha256':t.context,'expected_text':'','text':'never'},'denied_not_found')
            print('HIERARCHY_SIZE_DPI_NATIVE_CLICK_SETTEXT_PASS',w,h,dpi,flush=True)
        start('visual')
        try:ui.find_element(text='Написать')
        except ElementNotFound:pass
        else:raise AssertionError('Drawn label unexpectedly appeared in hierarchy')
        e=ui.find_element(text='Написать',allow_fallback=True)
        assert e.method=='ocr' and captures[0]==1,(e.method,captures[0])
        state,_=e.click(action_id='d'*32,purpose='synthetic');assert state=='input_injected',state
        ui.wait_for_element(description='visual-clicks=1',timeout=3)
        print('HIERARCHY_MISS_LOCAL_OCR_VISUAL_BOUNDS_CLICK_PASS',flush=True)
        adb('shell','settings','put','system','accelerometer_rotation','0')
        adb('shell','settings','put','system','user_rotation','1')
        start();t=backend.snapshot();assert t.rotation==1,t.rotation
        ui.find_element(resource_id='android:id/button1')
        print('HIERARCHY_LANDSCAPE_ROTATION_PASS',flush=True)
    finally:
        adb('shell','settings','put','system','user_rotation',original_rotation if original_rotation in ('0','1','2','3') else '0')
        adb('shell','settings','put','system','accelerometer_rotation',original_auto if original_auto in ('0','1') else '0')
        adb('shell','wm','size','reset');adb('shell','wm','density','reset')
        adb('shell','am','force-stop','drug.vokrug')

if __name__=='__main__':main()
