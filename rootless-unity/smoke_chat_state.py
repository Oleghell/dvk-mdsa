"""Exercise the exact read-only observer on owned native definitions and objects."""
from pathlib import Path
import json,queue,subprocess,sys,threading,time
import frida
import chat_state_probe as p

WAIT_MODES={340}

def one(library,mode):
    child=subprocess.Popen([sys.executable,'-u','-c',"import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\nfor _ in range(10000):\n lib.fixture_tick()\n time.sleep(.003)",str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=timer=None;done=threading.Event()
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(p.FUNCTION+'''
rpc.exports={probe(){return probeUIKitRoot();},cancel(){cancelNavigation();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {handles:read('fixture_handles'),bad:read('fixture_bad_frees'),off:read('fixture_off_thread_calls'),calls:read('fixture_calls'),opens:read('fixture_opens'),closes:read('fixture_cancels'),states:read('fixture_state_reads'),receiver:read('fixture_bad_receiver'),frames:read('fixture_sample_frames'),last:read('fixture_last_action')};}};''')
        script.load()
        if mode==327:script.exports_sync.cancel()
        if mode in WAIT_MODES:
            def cancel_after_sample():
                deadline=time.monotonic()+8
                while not done.is_set() and time.monotonic()<deadline:
                    if script.exports_sync.counts()['states']>=2:script.exports_sync.cancel();return
                    time.sleep(.03)
                if not done.is_set():script.exports_sync.cancel()
            timer=threading.Thread(target=cancel_after_sample,daemon=True);timer.start()
        started=time.monotonic();out=p.validate(script.exports_sync.probe());elapsed=time.monotonic()-started;done.set()
        n=out['navigation'];c=script.exports_sync.counts()
        assert c['handles']==c['bad']==c['off']==c['opens']==c['closes']==c['receiver']==0,(mode,out,c)
        assert c['calls']==out['managed_calls']+n['managed_calls'],(mode,out,c)
        assert n['handles_acquired']==n['handles_released'],(mode,out,c)
        if mode in (300,302,303,306,328,336,338,339,342,346):
            assert n['stage']=='navigation-ready' and n['history_status']==('not-empty' if mode in (303,346) else 'empty'),(mode,out,c)
            assert n['message_count']==(7 if mode in (303,346) else 0) and n['samples']==2 and elapsed>=1.9,(mode,out,c,elapsed)
            if mode==342:assert elapsed>=2.9,(mode,out,c,elapsed)
            if mode in (306,346):assert n['model_draft'] is True,(mode,out,c)
            assert n['loaded_value_owner_verified'] is True and n['loaded_value_owner_inherited']==(mode in (328,336)),(mode,out,c)
        elif mode in (315,316,317,318,329,330,331,332,333,334,335,337):
            assert n['stage']=='not-attempted' and n['history_status']=='unknown' and c['states']==0,(mode,out,c)
        else:
            assert n['stage']=='navigation-stopped' and n['history_status']=='unknown' and n['message_count'] is None,(mode,out,c)
            expected={301:'wrong-screen',309:'history-invalid',312:'identity-changed',313:'identity-changed',314:'identity-changed',319:'managed-exception',320:'unexpected-object',322:'signature-mismatch',327:'cancelled',340:'cancelled'}
            if mode in expected:assert n['error']==expected[mode],(mode,out,c)
            else:
                reasons={304:'history-loading',305:'chat-not-actual',307:'no-history-manager',308:'null-history-manager',310:'changing-count',311:'contradictory-last-message',321:'null-loaded-flag',323:'history-not-loaded',324:'history-loading',325:'changing-count',326:'contradictory-last-message',341:'model-changed',343:'history-loading',344:'no-history-manager',345:'history-not-loaded'}
                assert n['error']=='history-not-ready' and n['wait_reason']==reasons[mode],(mode,out,c)
        assert not any(t in json.dumps(out) for t in ('0x','private-text','token','user_id'))
        print('Synthetic chat state',mode,n['stage'],n['history_status'],n['error'],flush=True)
        return out
    finally:
        done.set()
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
    for mode in range(300,347):one(Path(sys.argv[1]).resolve(strict=True),mode)
    print('Read-only chat state ABI passed; Android still requires a manual test.')
