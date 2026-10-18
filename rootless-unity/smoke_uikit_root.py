"""Execute exact root observer on synthetic C API; never use a real app/device."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import frida
from uikit_root import FUNCTION,validate


def one(library,mode):
    code='''import ctypes,sys,time,threading
lib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)
lib.fixture_init(int(sys.argv[2]))
lib.il2cpp_class_from_name.restype=ctypes.c_void_p
lib.il2cpp_class_from_name.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char_p]
# Test-only export obtains the fixture's fixed Update handle, not a code pointer.
lib.fixture_tick.argtypes=[]
print('ready',flush=True)
for i in range(1500):
 if int(sys.argv[2])==7:
  t=threading.Thread(target=lib.fixture_tick);t.start();t.join()
 elif int(sys.argv[2])!=5:lib.fixture_tick()
 time.sleep(.02)
'''
    child=subprocess.Popen([sys.executable,'-u','-c',code,str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready','Fixture failed to load'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(FUNCTION+'''
rpc.exports={probe(){return probeUIKitRoot();},counts(){
 const read=name=>new NativeFunction(Module.getGlobalExportByName(name),'int',[])();
 return {handles:read('fixture_handles'),calls:read('fixture_calls'),off:read('fixture_off_thread_calls')};
}};''',name='synthetic-uikit-root')
        script.load();value=validate(script.exports_sync.probe())
        expected={0:'root-ready',1:'off-main-thread',2:'runtime-not-ready',3:'window-not-ready',4:'managed-exception',5:'callback-timeout',6:'signature-mismatch',7:'off-main-thread',8:'object-class-mismatch',9:'original-frame-exception'}[mode]
        assert value['stage']==expected,value
        counts=script.exports_sync.counts()
        assert counts['handles']==0,counts
        assert counts['off']==(1 if mode==7 else 0),counts
        assert counts['calls']=={0:3,1:1,2:2,3:3,4:1,5:0,6:0,7:1,8:2,9:0}[mode],(counts,value)
        assert value['managed_calls']==counts['calls'],(counts,value)
        if mode!=6:assert value['hooks_detached'],value
        assert not value['cleanup_failed'],value
        assert not any(x in json.dumps(value) for x in ('0x','token','private-text'))
        print('Root observer synthetic case',mode,expected,flush=True)
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
    library=Path(sys.argv[1]).resolve(strict=True)
    for mode in range(10):one(library,mode)
    print('All root observer cases passed on synthetic C fixture only; MuMu NOT tested.')
