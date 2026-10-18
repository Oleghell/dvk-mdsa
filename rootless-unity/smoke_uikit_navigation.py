"""Run exact fixed navigation JS on an owned C ABI fixture only."""
from pathlib import Path
import json,queue,subprocess,sys,threading
import frida
from uikit_navigation import FUNCTION,validate


def one(library,mode):
    code='''import ctypes,sys,time
lib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)
lib.fixture_init(int(sys.argv[2]))
print('ready',flush=True)
for _ in range(4000):
 lib.fixture_tick()
 time.sleep(.003)
'''
    child=subprocess.Popen([sys.executable,'-u','-c',code,str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready','Fixture load failed'
        session=frida.get_local_device().attach(child.pid)
        source=FUNCTION.replace("},16000);","},80);") if mode==77 else FUNCTION
        script=session.create_script(source+'''
rpc.exports={probe(){return probeUIKitRoot();},cancel(){cancelNavigation();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {handles:read('fixture_handles'),bad:read('fixture_bad_frees'),off:read('fixture_off_thread_calls'),
  calls:read('fixture_calls'),opens:read('fixture_opens'),cancels:read('fixture_cancels'),modal_reads:read('fixture_modal_reads'),virtual:read('fixture_virtual_calls')};}};''')
        script.load()
        timer=None
        if mode==78:script.exports_sync.cancel()
        if mode in (76,79,118):
            def request_cancel():
                if mode in (79,118):
                    import time
                    deadline=time.monotonic()+5
                    while time.monotonic()<deadline:
                        if script.exports_sync.counts()['modal_reads' if mode==118 else 'opens']:break
                        time.sleep(.005)
                script.exports_sync.cancel()
            timer=threading.Timer(.01 if mode==79 else .15,request_cancel);timer.start()
        try:value=validate(script.exports_sync.probe())
        finally:
            if timer:timer.cancel();timer.join(timeout=2)
        n=value['navigation'];c=script.exports_sync.counts()
        expected={60:'navigation-ready',61:'wrong-screen',62:'not-attempted',63:'frame-limit',64:'frame-limit',
                  65:'screen-not-ready',66:'managed-exception',67:'managed-exception',68:'frame-limit',
                  69:'frame-limit',70:'identity-changed',71:'unexpected-screen',72:'navigation-ready',
                  73:'frame-limit',74:'managed-exception',75:'frame-limit',76:'cancelled',77:'transition-timeout',78:'cancelled',79:'cancelled',80:'navigation-ready',81:'navigation-ready',82:'wrong-screen',83:'frame-limit',84:'controller-cycle',85:'controller-depth-limit',86:'frame-limit',87:'presentation-not-resolved',88:'wrong-screen',89:'navigation-ready',90:'not-attempted',91:'view-parent-cycle',92:'navigation-ready',93:'frame-limit',94:'view-parent-depth-limit',95:'frame-limit',96:'frame-limit',97:'navigation-ready',98:'navigation-ready',99:'unexpected-screen',100:'navigation-ready',101:'navigation-ready',102:'frame-limit',103:'modal-ambiguous',104:'modal-count-invalid',105:'modal-count-invalid',106:'modal-changed',107:'unexpected-object',108:'modal-changed',109:'not-attempted',110:'not-attempted',111:'not-attempted',112:'not-attempted',113:'not-attempted',114:'not-attempted',115:'controller-cycle',116:'frame-limit',117:'navigation-ready',118:'cancelled',119:'managed-exception',120:'identity-changed',121:'signature-mismatch'}[mode]
        actual=n['stage'] if n['stage'] in ('navigation-ready','not-attempted') else n['error']
        assert actual==expected,(mode,value,c)
        assert c['handles']==c['bad']==c['off']==0,(mode,c)
        assert c['opens']<=1 and c['cancels']<=1,c
        assert c['calls']==value['managed_calls']+n['managed_calls'],(value,c)
        if mode in (79,118):assert c['opens']==1 and c['cancels']==0,c
        if mode in (60,72,80,81,89,92,97,98,100,101,117):assert c['opens']==c['cancels']==1 and c['virtual']>=1,c
        if mode in (61,62,63,64,67,68,73,82,83,84,85,86,87,88,90,91,93,94,95,96):assert c['opens']==c['cancels']==0,c
        if mode in (99,103,104,105,106,107,108,115,118,119,120,121):assert c['opens']==1 and c['cancels']==0,c
        assert n['handles_acquired']==n['handles_released'],n
        if mode==80:assert n['controller_path']==['root','ui-navigation','main-tabs','search'],n
        if mode==81:assert n['controller_path']==['root','dv-navigation','dv-container','ui-container','main-tabs','search'],n
        assert not any(bad in json.dumps(value) for bad in ('0x','private-text','token'))
        print('Synthetic navigation',mode,actual,flush=True)
    finally:
        if script:
            try:script.unload()
            except Exception:pass
        if session:
            try:session.detach()
            except Exception:pass
        child.terminate()
        try:child.wait(timeout=3)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
        child.stdout.close();child.stderr.close()

if __name__=='__main__':
    for mode in range(60,122):one(Path(sys.argv[1]).resolve(strict=True),mode)
    print('Synthetic navigation ABI passed; live MuMu navigation NOT yet tested.')
