"""Execute actual MuMu shared-skip JS against an OWNED ABI fixture. No Android."""
from contextlib import closing
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
import frida
import assistant_pass as manual
from mumu_store import SharedStore
from greetings import get_greeting


def one(library,case):
    os.environ['DVK_MUMU_MULTI']='1'
    text=get_greeting(2)
    child=subprocess.Popen([sys.executable,'-u','-c',
        "import ctypes,sys,time\nl=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\n"
        "l.fixture_init(513);l.fixture_cohort_mode(0)\nprint('ready',flush=True)\n"
        "for _ in range(100000):\n l.fixture_tick();time.sleep(.003)",str(library)],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=thread=None;done=threading.Event();state={};approvals=[]
    with tempfile.TemporaryDirectory() as t:
        path=Path(t)/'assistant.sqlite3';legacy=Path(t)/'old'
        store=SharedStore(path,legacy,device_port=5557)
        other=SharedStore(path,legacy,device_port=5559)
        try:
            assert child.stdout.readline().strip()=='ready'
            session=frida.get_local_device().attach(child.pid)
            script=session.create_script(manual.build(text,[])+'''
rpc.exports={root(){return probeBatchProfile();},cancel(){cancelNavigation();},
 cohortpending(){return cohortReservation();},cohortack(value){return cohortAcknowledge(value);},
 counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {sends:r('fixture_auto_sends'),handles:r('fixture_handles'),off:r('fixture_off_thread_calls'),pins:r('fixture_pin_errors'),bad:r('fixture_auto_bad')};}};
''')
            script.load()
            def claim(pending):
                # Same global peer, another account and another device.
                p=dict(pending,account=str(int(pending['account'])+1))
                other.reserve(p,'Other greeting',approved=True)
                if case!='greeting-only':
                    with other.connection() as db:
                        other.record_peer_outcome(db,dict(account=p['account'],peer=p['peer'],chat='300'),'contact-refused')
            if case in ('already-claimed','greeting-only'):
                original=store.peer_claimed
                def check(pending):claim(pending);return original(pending)
                store.peer_claimed=check
            def approve(pending,*args):
                approvals.append(True)
                if case!='greeting-only':claim(pending)
                return True
            thread=threading.Thread(target=manual.monitor,args=(script,store,text,approve,done,lambda:False,state),daemon=True)
            thread.start();raw=script.exports_sync.root();done.set();thread.join(timeout=5)
            assert not thread.is_alive()
            manual.validate(raw,shared_peer_skipped=state.get('shared_peer_skipped',False))
            n=raw['navigation'];counts=script.exports_sync.counts()
            assert state=={'shared_peer_skipped':True},state
            assert n['return_verified'] is True and n['shared_peer_skipped'] is True
            assert n['history_status']=='empty' and n['send_attempted'] is False and n['send_handler_returned'] is False
            assert all(v==0 for v in counts.values()),counts
            assert len(approvals)==(case=='race-during-typing')
            assert store.summary()['reserved']==0 and other.summary()['reserved']==1
            if case=='greeting-only':
                with store.connection() as db:
                    assert db.execute('SELECT COUNT(*) FROM mumu_peer_blocks').fetchone()[0]==0
            print('MuMu shared greeting/terminal outcome:',case,'verified return; no leaked handles',flush=True)
        finally:
            done.set()
            if thread:thread.join(timeout=5)
            if script:
                try:script.unload()
                except Exception:pass
            if session:
                try:session.detach()
                except Exception:pass
            child.kill();child.communicate(timeout=5)

if __name__=='__main__':
    library=Path(sys.argv[1]).resolve(strict=True)
    for case in ('already-claimed','race-during-typing','greeting-only'):one(library,case)
