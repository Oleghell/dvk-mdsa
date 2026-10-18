"""Run exact bounded tree probe against an owned C fixture, never Android."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import frida
from uikit_tree import FUNCTION,validate


def one(library,mode):
    child=subprocess.Popen([sys.executable,'-u','-c','''import ctypes,sys,time
lib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)
lib.fixture_init(int(sys.argv[2]))
print('ready',flush=True)
for i in range(1500):
 lib.fixture_tick()
 time.sleep(.02)
''',str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready','Fixture failed to load'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(FUNCTION+'''
rpc.exports={probe(){return probeUIKitRoot();},counts(){
 const read=name=>new NativeFunction(Module.getGlobalExportByName(name),'int',[])();
 return {handles:read('fixture_handles'),bad_frees:read('fixture_bad_frees'),high:read('fixture_high_handles'),wrong_index:read('fixture_wrong_index'),off:read('fixture_off_thread_calls')};
}};''',name='synthetic-uikit-tree')
        script.load();value=validate(script.exports_sync.probe());tree=value['tree']
        assert value['stage']=='root-ready',value
        expected={20:('tree-ready','none'),21:('tree-limited','none'),22:('tree-error','collection-count-out-of-range'),23:('tree-limited','none'),24:('tree-error','unsupported-collection'),25:('tree-limited','none'),26:('tree-error','unsupported-collection'),27:('tree-error','managed-exception'),28:('tree-limited','none'),29:('tree-limited','none')}[mode]
        assert (tree['stage'],tree['error'])==expected,tree
        if mode==20:assert len(tree['nodes'])==4 and tree['complete'],tree
        if mode in (21,23,25,28,29):assert {28:'node-limit',29:'time-budget',21:'repeated-reference',23:'children-limit',25:'depth-limit'}[mode] in tree['truncated_reasons'],tree
        counts=script.exports_sync.counts()
        assert counts=={'handles':0,'bad_frees':0,'high':1,'wrong_index':0,'off':0},counts
        assert tree['handles_acquired']==tree['handles_released'] and not value['cleanup_failed'],value
        assert not any(s in json.dumps(value) for s in ('0x','private-text','token'))
        print('Tree synthetic case',mode,*expected,'nodes',len(tree['nodes']),flush=True)
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
    library=Path(sys.argv[1]).resolve(strict=True)
    for mode in range(20,30):one(library,mode)
    print('Tree C ABI checks passed; real MuMu graph NOT yet tested.')
