"""Actual Frida/C ABI metadata-only checks in owned processes; never Android."""
from pathlib import Path
import json,queue,subprocess,sys,threading
import frida
from profile_metadata import FUNCTION,validate


def one(library,mode):
    child=subprocess.Popen([sys.executable,'-u','-c',
        "import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\ntime.sleep(90)",
        str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready','Fixture failed'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(FUNCTION+'''
rpc.exports={probe(){return probeUIKitRoot();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {handles:read('fixture_handles'),bad:read('fixture_bad_frees'),off:read('fixture_off_thread_calls'),
 calls:read('fixture_calls'),opens:read('fixture_opens'),closes:read('fixture_cancels'),visible:read('fixture_visible_reads')};}};''')
        script.load();v=validate(script.exports_sync.probe());c=script.exports_sync.counts();d=v['profile_metadata']
        expected={130:('profile-metadata-ready','ready'),145:('native-call-failed','profile-method:open'),
                  146:('native-call-failed','profile-method:visibleItem'),147:('native-call-failed','profile-method:next'),
                  160:('native-call-failed','profile-rows'),161:('native-call-failed','profile-nested'),
                  162:('native-call-failed','profile-class:avatar'),163:('native-call-failed','profile-method:cellAvatar'),164:('profile-metadata-ready','ready')}
        assert (v['stage'],d['checkpoint'])==expected[mode],(mode,v,c)
        assert all(n==0 for n in c.values()),(mode,v,c)
        if mode==164:assert v['metadata_thread_attached'] and v['metadata_thread_detached'],v
        assert (not v['metadata_thread_attached'] or v['metadata_thread_detached']) and not v['cleanup_failed'],v
        assert not any(s in json.dumps(v) for s in ('0x','private-text','token')),v
        print('Synthetic metadata preflight',mode,v['stage'],d['checkpoint'],flush=True)
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
    for mode in (130,145,146,147,160,161,162,163,164):one(Path(sys.argv[1]).resolve(strict=True),mode)
    print('Read-only metadata ABI passed; live MuMu cause NOT yet confirmed.')
