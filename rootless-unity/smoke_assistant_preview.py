"""Actual profile-only JS + durable host loop against our owned C fixture."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import threading
import time

import frida
import assistant_preview as preview
from assistant_store import Store


def one(library, case):
    mode = {'duplicates':251, 'failure':255, 'metadata':253}.get(case,250)
    child = subprocess.Popen([sys.executable,'-u','-c',
        "import ctypes,sys,time\nl=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\n"
        "l.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\n"
        "for _ in range(60000):\n l.fixture_tick();time.sleep(.003)",
        str(library),str(mode)], stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session = script = thread = None
    stopped = threading.Event()
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder)/'assistant.sqlite3',Path(folder)/'old')
        if case == 'seeded':
            for peer in ('1','2'):
                store.record_visit(peer,dict(profile_verified=True,friends_count=13,history_status='not-opened'))
        try:
            assert child.stdout.readline().strip() == 'ready'
            session = frida.get_local_device().attach(child.pid)
            for turn in range(2 if case == 'restart' else 1):
                if script:
                    script.unload()
                    script = None
                store = Store(store.path,store.legacy)  # Reopen the real SQLite journal.
                visited = store.visited_peers()
                source = preview.build(visited)
                assert 'OnMessageButton' not in source and 'OnSendText' not in source
                script = session.create_script(source + '''
rpc.exports={root(){previewSelectedPeer=null;return probeBatchProfile();},
 selectedpeer(){return previewSelectedPeer;},cancel(){cancelNavigation();},
 counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {opens:r('fixture_opens'),closes:r('fixture_cancels'),handles:r('fixture_handles'),
 off:r('fixture_off_thread_calls'),pins:r('fixture_pin_errors'),wrong:r('fixture_wrong_selection'),
 bad:r('fixture_bad_frees')};}};
''')
                script.load()
                if case == 'stop':
                    def cancel_second():
                        until = time.monotonic()+20
                        while time.monotonic()<until and not stopped.is_set():
                            if script.exports_sync.counts()['opens'] >= 2:
                                stopped.set()
                                script.exports_sync.cancel()
                                return
                            time.sleep(.01)
                    thread = threading.Thread(target=cancel_second,daemon=True)
                    thread.start()
                out = preview.walk(script.exports_sync.root,script.exports_sync.selectedpeer,
                                   store,visited,stopped.is_set)
                c = script.exports_sync.counts()
                assert all(c[k]==0 for k in ('handles','off','pins','wrong','bad')),(case,c,out)
                assert out['messages_sent']==out['chats_opened']==0 and store.summary()['reserved']==0
                if case in ('five','restart','seeded'):
                    assert out['status']=='preview-completed' and out['checked']==5,(case,out,c)
                    expected = {str(i) for i in range(1,8 if case=='seeded' else 11 if turn else 6)}
                    assert set(store.visited_peers())==expected,(case,turn,store.visited_peers())
                    assert c['opens']==c['closes']==5*(turn+1),(case,c)
                    assert (out['eligible'],out['skipped'])==((2,3) if case=='seeded' else (3,2)),out
                elif case == 'duplicates':
                    assert out['status']=='preview-exhausted' and out['checked']==1 and c['opens']==c['closes']==1,(out,c)
                elif case == 'metadata':
                    assert out['status']=='preview-stopped' and c['opens']==c['closes']==0,(out,c)
                elif case == 'failure':
                    assert out['status']=='preview-stopped' and out['checked']==2 and c['opens']==3 and c['closes']==2,(out,c)
                    assert out['profile_may_remain_open']
                elif case == 'stop':
                    assert out['status']=='preview-cancelled' and out['checked']==1 and c['opens']==2 and c['closes']==1,(out,c)
                    assert out['profile_may_remain_open']
                before = script.exports_sync.counts()
                try:
                    script.exports_sync.root()
                except frida.RPCException:
                    pass
                else:
                    raise AssertionError('A closed preview accepted another profile cycle')
                assert script.exports_sync.counts()==before
                for forbidden in ('previewSelectedPeer','PRIVATE','token','0x','peer','account'):
                    assert forbidden not in json.dumps(out)
                print('Synthetic preview',case,turn+1,out['status'],'checked',out['checked'],flush=True)
        finally:
            stopped.set()
            if thread:
                thread.join(timeout=2)
            if script:
                script.unload()
            if session:
                session.detach()
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
            child.stdout.close()
            child.stderr.close()


if __name__ == '__main__':
    for case in ('five','restart','seeded','duplicates','stop','failure','metadata'):
        one(Path(sys.argv[1]).resolve(strict=True),case)
    print('7 profile-only preview scenarios passed. Live MuMu preview is NOT verified.')