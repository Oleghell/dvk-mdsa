"""Actual C ABI inventory only. No Android/accounts, body reads or sends."""
from pathlib import Path
import subprocess,sys,frida
import reply_metadata as p

def one(library,mode):
    child=subprocess.Popen([sys.executable,'-u','-c',"import ctypes,sys,time\nl=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nl.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\ntime.sleep(120)",str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        assert child.stdout.readline().strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(p.FUNCTION+'''\nrpc.exports={probe(){return nativeMetadata();},counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();return {invokes:r('fixture_invokes'),values:r('fixture_values'),keeps:r('fixture_keeps'),attached:r('fixture_attached')};}};''');script.load()
        out=p.validate(script.exports_sync.probe());counts=script.exports_sync.counts()
        assert counts==dict(invokes=0,values=0,keeps=0,attached=1 if mode in (6,7) else 0),(mode,out,counts)
        if mode in (0,7):
            assert out['stage']=='chat-runtime-ready',(mode,out)
            assert any(t['identity']['type']=='TextMessage' for t in out['types'])
        elif mode==99:assert out['reason']=='limits',(mode,out)
        elif mode==6:assert out['reason']=='cleanup-failed',(mode,out)
        else:assert out['stage']=='chat-runtime-stopped',(mode,out)
        print('Synthetic reply inventory',mode,out['stage'],out['reason'],flush=True)
    finally:
        if script:script.unload()
        if session:session.detach()
        child.terminate();child.wait(timeout=5);child.stdout.close();child.stderr.close()
if __name__=='__main__':
    for mode in (0,5,6,7,9,99):one(Path(sys.argv[1]).resolve(strict=True),mode)
