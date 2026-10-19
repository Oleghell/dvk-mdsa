"""Real Frida + owned C ABI fixture. No APK, account, OCR or network actions."""
from pathlib import Path
import json,queue,subprocess,sys,threading,time
import frida
from uikit_profile_navigation import FUNCTION,validate


def one(library,mode):
    child=subprocess.Popen([sys.executable,'-u','-c',
        "import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\nfor _ in range(6000):\n lib.fixture_tick()\n time.sleep(.003)",
        str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=timer=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready','Fixture load failed'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(FUNCTION+'''
rpc.exports={probe(){return probeUIKitRoot();},cancel(){cancelNavigation();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {handles:read('fixture_handles'),bad:read('fixture_bad_frees'),off:read('fixture_off_thread_calls'),
 calls:read('fixture_calls'),opens:read('fixture_opens'),closes:read('fixture_cancels'),wrong:read('fixture_wrong_selection'),peak:read('fixture_peak_handles'),pins:read('fixture_pin_errors'),blocked:read('fixture_blocked'),iterators:read('fixture_iterator_allocations'),visible:read('fixture_visible_reads')};}};''')
        script.load()
        if mode==152:script.exports_sync.cancel()
        if mode in (148,149,194):
            def cancel():
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    if script.exports_sync.counts()['opens' if mode==148 else 'blocked' if mode==194 else 'visible']:break
                    time.sleep(.005)
                script.exports_sync.cancel()
            timer=threading.Timer(.01,cancel);timer.start()
        value=validate(script.exports_sync.probe());n=value['navigation'];c=script.exports_sync.counts()
        actual=n['stage'] if n['stage'] in ('navigation-ready','not-attempted') else n['error']
        expected={130:'navigation-ready',135:'selection-changed',138:'identity-changed',139:'unexpected-object',140:'identity-changed',141:'managed-exception',143:'managed-exception',145:'not-attempted',146:'not-attempted',147:'not-attempted',148:'cancelled',149:'cancelled',150:'navigation-ready',151:'navigation-ready',152:'cancelled',153:'selection-changed',154:'selection-limit',155:'selection-limit',156:'unexpected-object',157:'selection-changed',158:'wrong-screen',159:'identity-changed',170:'navigation-ready',171:'navigation-ready',172:'navigation-ready',173:'not-attempted',174:'not-attempted',175:'unexpected-object',176:'signature-mismatch',177:'not-attempted',178:'not-attempted',179:'not-attempted',180:'navigation-ready',182:'selection-changed',183:'navigation-ready',184:'navigation-ready',185:'navigation-ready',186:'navigation-ready',187:'selection-changed',188:'selection-changed',189:'identity-changed',190:'navigation-ready',191:'navigation-ready',193:'navigation-ready',194:'cancelled',195:'managed-exception',196:'selection-limit',197:'view-parent-cycle'}
        if mode in expected:assert actual==expected[mode],(mode,n,c,value['stage'])
        else:assert actual in ('frame-limit','call-limit','transition-timeout'),(mode,n,c)
        assert c['handles']==c['bad']==c['off']==c['wrong']==c['pins']==0,(mode,n,c)
        assert c['calls']==value['managed_calls']+n['managed_calls'],(mode,n,c)
        assert n['handles_acquired']==n['handles_released'],(mode,n,c)
        assert c['opens']<=1 and c['closes']<=1,(mode,c)
        if mode in (130,150,151,170,171,172,180,183,184,185,186,190,191,193):
            assert c['opens']==c['closes']==1,(mode,c)
            assert n['profile_verified'] and n['profile_content_verified'] and n['target_user_verified'] and n['return_verified'],n
            assert n['selection_status']=='selected',n
        if mode in (131,132,133,134,135,136,145,146,147,149,152,153,154,155,157,158,173,174,175,176,177,178,179,181,182,187,188,192,194,195,196,197):assert c['opens']==c['closes']==0,(mode,c)
        if mode in (137,138,139,140,141,142,148,189):assert c['opens']==1 and c['closes']==0,(mode,c)
        if mode in (135,153,157,182,187,188):assert n['selection_retries']==2,n
        if mode in (183,184,185,186):assert n['selection_retries']==1,n
        if mode in (180,189):assert n['selection_retries']==0,n
        if mode==180:assert n['selection_check']=='selected',n
        assert n['temporary_handles_peak']<=64 and c['peak']<=70,(mode,n,c)
        if mode in (190,191,193):
            assert n['handles_acquired']>64 and c['iterators']>=48 and n['selection_retries']==0,(mode,n,c)
        assert not any(s in json.dumps(value) for s in ('0x','private-text','token'))
        print('Synthetic profile',mode,actual,({'peak_temporary':n['temporary_handles_peak'],'allocated':n['handles_acquired'],'released':n['handles_released'],'calls':n['managed_calls']} if mode>=190 else ''),flush=True)
    finally:
        if timer:timer.cancel();timer.join(timeout=2)
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
    for mode in list(range(130,160))+list(range(170,198)):one(Path(sys.argv[1]).resolve(strict=True),mode)
    print('Synthetic profile ABI passed; live MuMu profile workflow NOT yet tested.')
