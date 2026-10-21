"""Execute actual route JS on synthetic C objects only, never an emulator."""
from pathlib import Path
import json
import queue
import subprocess
import sys
import threading
import time
import frida
from dialog_navigation import FUNCTION, validate


def one(library, mode):
    code = '''import ctypes,sys,time
lib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)
lib.fixture_init(int(sys.argv[2]))
print('ready',flush=True)
for _ in range(12000):
 lib.fixture_tick()
 time.sleep(.003)
'''
    child = subprocess.Popen([sys.executable,'-u','-c',code,str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=monitor=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(FUNCTION+'''
rpc.exports={probe(){return probeUIKitRoot();},cancel(){cancelNavigation();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {handles:read('fixture_handles'),bad:read('fixture_bad_frees'),off:read('fixture_off_thread_calls'),
 calls:read('fixture_route_calls'),route_bad:read('fixture_route_bad')};}};''')
        script.load()
        if mode==709:script.exports_sync.cancel()
        if mode==714:
            def stop():
                until=time.monotonic()+5
                while time.monotonic()<until:
                    if script.exports_sync.counts()['calls']:
                        script.exports_sync.cancel();return
                    time.sleep(.003)
            monitor=threading.Thread(target=stop,daemon=True);monitor.start()
        result=validate(script.exports_sync.probe())
        if monitor:monitor.join(timeout=6)
        n=result['navigation'];c=script.exports_sync.counts()
        expected={700:'navigation-ready',701:'not-attempted',702:'managed-exception',703:'screen-not-ready',704:'screen-not-ready',705:'identity-changed',706:'call-limit',707:'unexpected-screen',708:'wrong-screen',709:'cancelled',710:'signature-mismatch',711:'call-limit',712:'call-limit',713:'managed-exception',714:'cancelled',715:'navigation-ready',716:'navigation-ready'}[mode]
        actual=n['stage'] if n['stage'] in ('navigation-ready','not-attempted') else n['error']
        assert actual==expected,(mode,actual,n,c)
        assert c['handles']==c['bad']==c['off']==c['route_bad']==0,(mode,n,c)
        assert c['calls']<=2 and n['handles_acquired']==n['handles_released'],(mode,n,c)
        if mode in (700,715,716):assert c['calls']==2 and n['dialogs_verified'] and n['return_verified'],(n,c)
        if mode in (701,708,709,710):assert c['calls']==0,(mode,c)
        if mode in (702,703,706,707,711,712,714):assert c['calls']==1,(mode,c)
        assert not n['ui_text_read']
        for private in ('0x','private-text','token','chat_id','peer_name'):
            assert private not in json.dumps(result)
        print('Synthetic dialog navigation',mode,actual,flush=True)
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
    for mode in range(700,717):one(Path(sys.argv[1]).resolve(strict=True),mode)
    print('17 synthetic route cases passed. Live MuMu is NOT verified.')
