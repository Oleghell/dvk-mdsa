"""Actual fixed observer against owned native state transitions, not Android."""
from pathlib import Path
import json,subprocess,sys,threading,time,frida
import chat_batch as p

def one(library,mode):
    child=subprocess.Popen([sys.executable,'-u','-c',"import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\nfor _ in range(120000):\n lib.fixture_tick()\n time.sleep(.003)",str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=timer=None
    try:
        assert child.stdout.readline().strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(p.FUNCTION+'''
rpc.exports={root(){return probeBatchProfile();},cancel(){cancelNavigation();},counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();return {sends:r('fixture_auto_sends'),chats:r('fixture_auto_opens'),backs:r('fixture_auto_backs'),bad:r('fixture_auto_bad'),timing:r('fixture_auto_timing_bad'),opens:r('fixture_opens'),closes:r('fixture_cancels'),handles:r('fixture_handles'),off:r('fixture_off_thread_calls'),pins:r('fixture_pin_errors')};}};
''');script.load()
        if mode==511:
            def stop():
                until=time.monotonic()+40
                while time.monotonic()<until:
                    if script.exports_sync.counts()['chats']>=1:break
                    time.sleep(.03)
                script.exports_sync.cancel()
            timer=threading.Thread(target=stop,daemon=True);timer.start()
        out=p.run(script.exports_sync.root);c=script.exports_sync.counts()
        assert all(c[k]==0 for k in ('bad','handles','off','pins','timing')),(mode,out,c)
        assert 0<=c['sends']<=c['chats']<=c['opens']<=10,(mode,out,c)
        if mode==500:assert out['status']=='batch-completed' and out['checked']==10 and out['handlers_returned']==c['sends']==6 and c['opens']==c['closes']==10 and c['chats']==c['backs']==6,(mode,out,c)
        elif mode in (501,509):assert out['status']=='batch-exhausted' and out['checked']==(5 if mode==501 else 1),(mode,out,c)
        elif mode==502:assert out['status']=='batch-completed' and out['not_empty']==6 and c['sends']==0,(mode,out,c)
        elif mode==511:assert out['status']=='batch-cancelled' and c['sends']==0,(mode,out,c)
        else:
            assert out['status']=='batch-stopped' and out['errors']==1,(mode,out,c)
            assert c['sends']==(1 if mode in (505,506,507) else 0),(mode,out,c)
        before=script.exports_sync.counts()
        try:script.exports_sync.root()
        except frida.RPCException:pass
        else:raise AssertionError('Closed automatic pass accepted another cycle')
        assert script.exports_sync.counts()==before
        assert not any(t in json.dumps(out) for t in ('0x','identityKey','user_id','private-text'))
        print('Synthetic automatic pass',mode,out['status'],'profiles',out['checked'],'submissions',out['handlers_returned'],flush=True)
        return out
    finally:
        if timer:timer.join(timeout=2)
        if script:script.unload()
        if session:session.detach()
        child.terminate();child.wait(timeout=5);child.stdout.close();child.stderr.close()
if __name__=='__main__':
    modes=[int(x) for x in sys.argv[2:]] or list(range(500,513))
    from concurrent.futures import ThreadPoolExecutor
    library=Path(sys.argv[1]).resolve(strict=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda mode:one(library,mode),modes))
