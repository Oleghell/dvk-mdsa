"""Real Frida + owned C fixture; verifies at most ten unique profile visits."""
from pathlib import Path
import json,subprocess,sys,threading,queue,time
import frida
import profile_batch


def one(library,mode):
    child=subprocess.Popen([sys.executable,'-u','-c',
        "import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\nfor _ in range(60000):\n lib.fixture_tick()\n time.sleep(.003)",
        str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    script=session=timer=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(profile_batch.FUNCTION+'''
rpc.exports={root(){return probeBatchProfile();},cancel(){cancelNavigation();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {handles:read('fixture_handles'),bad:read('fixture_bad_frees'),off:read('fixture_off_thread_calls'),
 opens:read('fixture_opens'),closes:read('fixture_cancels'),wrong:read('fixture_wrong_selection'),pins:read('fixture_pin_errors')};}};''')
        script.load()
        if mode==257:
            def cancel_third():
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if script.exports_sync.counts()['opens']>=3:break
                    time.sleep(.02)
                script.exports_sync.cancel()
            timer=threading.Thread(target=cancel_third,daemon=True);timer.start()
        out=profile_batch.run(script.exports_sync.root)
        c=script.exports_sync.counts()
        assert all(c[k]==0 for k in ('handles','bad','off','wrong','pins')),(mode,out,c)
        assert c['opens']<=10 and c['closes']<=c['opens'],(mode,out,c)
        if mode==250:
            assert out['status']=='batch-completed' and out['visited']==out['checked']==10,(mode,out,c)
            assert out['eligible']==6 and out['skipped']==4,(mode,out,c)
            assert c['opens']==c['closes']==10,(mode,out,c)
        elif mode in (251,252):
            expected=1 if mode==251 else 5
            assert out['status']=='batch-exhausted' and out['checked']==expected and c['opens']==c['closes']==expected,(mode,out,c)
        elif mode in (253,254,256):
            assert out['status']=='batch-stopped' and c['opens']==c['closes']==0,(mode,out,c)
        elif mode==255:
            assert out['status']=='batch-stopped' and out['checked']==2 and c['opens']==3 and c['closes']==2 and out['profile_may_remain_open'],(mode,out,c)
        elif mode==257:
            assert out['status']=='batch-cancelled' and out['checked']==2 and c['opens']==3 and c['closes']==2 and out['profile_may_remain_open'],(mode,out,c)
        before=script.exports_sync.counts()
        try:script.exports_sync.root()
        except frida.RPCException:pass
        else:raise AssertionError('Closed batch accepted another root call')
        assert script.exports_sync.counts()==before,'A closed batch performed actions'
        assert not any(k in json.dumps(out) for k in ('identityKey','user_id','0x','private-text','token'))
        print('Synthetic batch',mode,out['status'],'checked',out['checked'],'eligible',out['eligible'],'skipped',out['skipped'],flush=True)
    finally:
        if timer:timer.join(timeout=2)
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
    for mode in range(250,258):one(Path(sys.argv[1]).resolve(strict=True),mode)
    print('Synthetic batch ABI passed; live Android batch NOT tested.')
