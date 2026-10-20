"""Execute the actual online settings JS against our owned native ABI fixture."""
from pathlib import Path
import json
import queue
import subprocess
import sys
import threading
import time

import frida
from search_city import build, validate
FUNCTION=build('Pskov')


def one(library, mode):
    code = '''import ctypes,sys,time
lib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)
lib.fixture_init(int(sys.argv[2]))
print('ready',flush=True)
for _ in range(5000):
 lib.fixture_tick()
 time.sleep(.003)
'''
    child = subprocess.Popen([sys.executable, '-u', '-c', code, str(library), str(mode)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    session = script = timer = None
    try:
        q = queue.Queue()
        threading.Thread(target=lambda: q.put(child.stdout.readline()), daemon=True).start()
        assert q.get(timeout=10).strip() == 'ready'
        session = frida.get_local_device().attach(child.pid)
        script = session.create_script(FUNCTION + '''
rpc.exports={probe(){return probeUIKitRoot();},cancel(){cancelNavigation();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {handles:read('fixture_handles'),bad:read('fixture_bad_frees'),off:read('fixture_off_thread_calls'),
 calls:read('fixture_calls'),opens:read('fixture_opens'),cancels:read('fixture_cancels'),
 cityopens:read('fixture_city_opens'),searches:read('fixture_city_searches'),selects:read('fixture_city_selects'),
 sets:read('fixture_online_sets'),refreshes:read('fixture_online_refreshes'),applies:read('fixture_online_applies')};}};''')
        script.load()
        if mode == 322:
            script.exports_sync.cancel()
        if mode == 323:
            def cancel_during_setter():
                until = time.monotonic() + 4
                while time.monotonic() < until:
                    if script.exports_sync.counts()['selects']:
                        script.exports_sync.cancel()
                        return
                    time.sleep(.003)
            timer = threading.Thread(target=cancel_during_setter, daemon=True)
            timer.start()
        result = validate(script.exports_sync.probe())
        if timer:
            timer.join(timeout=5)
        n = result['navigation']
        c = script.exports_sync.counts()
        expected = {300:'navigation-ready',301:'not-attempted',302:'not-attempted',303:'not-attempted',
                    304:'managed-exception',305:'unexpected-screen',306:'city-query-changed',307:'managed-exception',
                    308:'frame-limit',309:'navigation-ready',310:'frame-limit',311:'frame-limit',
                    312:'navigation-ready',313:'identity-changed',314:'screen-not-ready',315:'frame-budget',
                    316:'managed-exception',317:'screen-not-ready',318:'screen-not-ready',319:'navigation-ready',320:'city-results-incomplete',321:'managed-exception',322:'cancelled',323:'cancelled',324:'navigation-ready',325:'navigation-ready'}[mode]
        actual = n['stage'] if n['stage'] in ('navigation-ready','not-attempted') else n['error']
        assert actual == expected, (mode, result, c)
        assert c['handles'] == c['bad'] == c['off'] == c['cancels'] == 0, (mode,c)
        assert n['handles_acquired'] == n['handles_released'], (mode,n)
        assert c['calls'] == result['managed_calls'] + n['managed_calls'], (mode,c,n)
        assert all(c[k]<=1 for k in ('opens','cityopens','searches','selects','sets','applies','refreshes')),c
        if mode in (300,309,312,319,324,325):
            assert c['cityopens']==c['searches']==c['selects']==c['applies']==1,c
            assert n['city_verified'] and n['online_verified'] and n['city_matches']==(2 if mode==309 else 1),n
            assert c['sets']==(mode!=324),c
        else:assert not n['city_verified'],n
        if mode in (301,302,303):assert c['opens']==c['cityopens']==c['selects']==c['applies']==0,c
        if mode in (306,307,308,310,311,317,320):assert c['selects']==c['applies']==0,c
        print('Synthetic city', mode, actual, flush=True)
        for private in ('0x','private-text','token','GeoCode','RegionCode','actual-returned-code','old-code','Pskov'):
            assert private not in json.dumps(result)
    finally:
        if script:
            try: script.unload()
            except Exception: pass
        if session:
            try: session.detach()
            except Exception: pass
        child.terminate()
        try: child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)
        child.stdout.close()
        child.stderr.close()


if __name__ == '__main__':
    for mode in range(300,326):
        one(Path(sys.argv[1]).resolve(strict=True), mode)
    print('25 synthetic city cases passed. Live city selection on MuMu is NOT verified.')
