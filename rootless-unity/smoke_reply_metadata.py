"""Actual C ABI inventory only. No Android/accounts, body reads or sends."""
from pathlib import Path
import subprocess,sys,frida
import reply_metadata as p

def one(library,mode,uncached=False):
    child=subprocess.Popen([sys.executable,'-u','-c',"import ctypes,sys,time\nl=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nl.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\ntime.sleep(120)",str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        assert child.stdout.readline().strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        source=p.FUNCTION
        if uncached:
            original=p.base._TEMPLATE
            raw=original[original.index('  const identity=k=>'):original.index('  const queue=[],seen=new Map();')]
            assert p.IDENTITY_CACHE in source
            source=source.replace(p.IDENTITY_CACHE,raw)
        script=session.create_script(source+'''\nrpc.exports={probe(){return nativeMetadata();},counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();return {invokes:r('fixture_invokes'),values:r('fixture_values'),keeps:r('fixture_keeps'),attached:r('fixture_attached')};}};''');script.load()
        out=p.validate(script.exports_sync.probe());counts=script.exports_sync.counts()
        assert counts==dict(invokes=0,values=0,keeps=0,attached=1 if mode in (6,7) else 0),(mode,out,counts)
        if uncached:
            assert mode==100 and out['stage']=='chat-runtime-limited'
            assert out['reason']=='limits' and out['native_calls']==50000
        elif mode in (0,7,100):
            assert out['stage']=='chat-runtime-ready',(mode,out)
            assert any(t['identity']['type']=='TextMessage' for t in out['types'])
            if mode==100:
                assert sum(len(t['methods']) for t in out['types'])>=1000
                assert out['native_calls']<20000,out['native_calls']
        elif mode==99:assert out['reason']=='limits',(mode,out)
        elif mode==6:assert out['reason']=='cleanup-failed',(mode,out)
        else:assert out['stage']=='chat-runtime-stopped',(mode,out)
        print('Synthetic reply inventory',mode,out['stage'],out['reason'],
              'calls',out['native_calls'],'uncached',uncached,flush=True)
    finally:
        if script:script.unload()
        if session:session.detach()
        child.terminate();child.wait(timeout=5);child.stdout.close();child.stderr.close()
if __name__=='__main__':
    library=Path(sys.argv[1]).resolve(strict=True)
    one(library,100,uncached=True)
    for mode in (0,4,5,6,7,9,11,15,16,99,100):one(library,mode)
