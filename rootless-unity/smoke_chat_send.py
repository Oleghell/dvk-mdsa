"""Exercise fixed submission against an owned synthetic native object only."""
from pathlib import Path
import subprocess,sys,time,frida
import chat_send_probe as p

def one(library,mode):
    child=subprocess.Popen([sys.executable,'-u','-c',"import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\nfor _ in range(10000):\n lib.fixture_tick()\n time.sleep(.003)",str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        assert child.stdout.readline().strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(p.FUNCTION+"""
rpc.exports={probe(){return probeUIKitRoot();},counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();return {sends:r('fixture_greeting_sends'),bad:r('fixture_greeting_bad'),handles:r('fixture_handles'),off:r('fixture_off_thread_calls'),opens:r('fixture_opens'),closes:r('fixture_cancels')};}};
""");script.load();out=p.validate(script.exports_sync.probe());n=out['navigation'];c=script.exports_sync.counts()
        assert c['bad']==c['handles']==c['off']==c['opens']==c['closes']==0,(mode,out,c)
        assert c['sends']==(1 if mode in (400,403) else 0),(mode,out,c)
        if mode==400:assert n['send_handler_returned'] and n['messages_sent'] is None and n['history_status']=='empty',(mode,out,c)
        elif mode==403:assert n['send_attempted'] and not n['send_handler_returned'] and n['messages_sent'] is None,(mode,out,c)
        else:assert not n['send_attempted'],(mode,out,c)
        if mode==400:
            again=p.validate(script.exports_sync.probe());assert script.exports_sync.counts()['sends']==1,again
        print('Synthetic greeting',mode,n['stage'],n['error'],c['sends'],flush=True)
    finally:
        if script:script.unload()
        if session:session.detach()
        child.terminate();child.wait(timeout=5);child.stdout.close();child.stderr.close()
if __name__=='__main__':
    for mode in range(400,408):one(Path(sys.argv[1]).resolve(strict=True),mode)
