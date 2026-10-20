"""Execute the actual online settings JS against our owned native ABI fixture."""
from pathlib import Path
import json
import queue
import subprocess
import sys
import threading
import time

import frida
from search_online import FUNCTION, validate


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
 sets:read('fixture_online_sets'),refreshes:read('fixture_online_refreshes'),applies:read('fixture_online_applies')};}};''')
        script.load()
        if mode == 218:
            script.exports_sync.cancel()
        if mode == 210:
            def cancel_during_setter():
                until = time.monotonic() + 4
                while time.monotonic() < until:
                    if script.exports_sync.counts()['sets']:
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
        expected = {200:'navigation-ready',201:'navigation-ready',202:'not-attempted',203:'not-attempted',
                    204:'screen-not-ready',205:'screen-not-ready',206:'managed-exception',207:'screen-not-ready',
                    208:'managed-exception',209:'screen-not-ready',210:'cancelled',211:'identity-changed',
                    212:'managed-exception',213:'screen-not-ready',214:'screen-not-ready',215:'screen-not-ready',
                    216:'not-attempted',217:'unexpected-object',218:'cancelled',219:'navigation-ready',220:'screen-not-ready',221:'signature-mismatch',222:'signature-mismatch',223:'signature-mismatch'}[mode]
        actual = n['stage'] if n['stage'] in ('navigation-ready','not-attempted') else n['error']
        assert actual == expected, (mode, result, c)
        assert c['handles'] == c['bad'] == c['off'] == c['cancels'] == 0, (mode, c)
        assert n['handles_acquired'] == n['handles_released'], (mode,n)
        assert c['calls'] == result['managed_calls'] + n['managed_calls'], (mode,c,n)
        assert c['opens'] <= 1 and c['sets'] <= 1 and c['applies'] <= 1 and c['refreshes'] <= 1, c
        if mode in (200,201,219):
            assert c['opens'] == c['applies'] == c['refreshes'] == 1
            assert c['sets'] == (mode != 201)
            assert n['online_verified'] and n['location_preserved']
        else:
            assert not n['online_verified'] and not n['location_preserved']
        if mode in (202,203,216,218):
            assert c['opens'] == c['sets'] == c['applies'] == 0
        if mode in (204,205,206,207,210,212,213,214,217):
            assert c['applies'] == 0
        for private in ('0x','private-text','token','GeoCode','RegionCode'):
            assert private not in json.dumps(result)
        print('Synthetic online-only', mode, actual, flush=True)
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
    for mode in range(200,224):
        one(Path(sys.argv[1]).resolve(strict=True), mode)
    print('24 synthetic online-only cases passed. Live MuMu is NOT verified.')
