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
import cohort_pass
from mumu_store import SharedStore
from greetings import get_greeting


class claimed_snapshot:
    """Stand-in for the pass-start visited snapshot monitor() receives (v1.3.79).

    inspect() loads every shared claim, block and own-journal peer once,
    streams the same list into the native selection pre-filter and hands the
    frozenset to monitor(), so the pre-approval claimed check costs no pooled
    database roundtrip. Registering the foreign claim exactly when monitor()
    consults snapshot membership reproduces the lazy semantics of the former
    store.peer_claimed() monkeypatch at the new boundary: the peer was already
    claimed by another installation when THIS pass started, so approval must
    never be requested and the skip stays a verified no-send Back.
    """

    def __init__(self, script, claim):
        self._script = script
        self._claim = claim

    def __contains__(self, peer):
        # cohortReservation() is a pure getter and stays stable until the ACK,
        # so re-reading it here returns the same pending the monitor polled.
        pending = self._script.exports_sync.cohortpending()
        if pending is None:
            return False
        self._claim(dict(cohort_pass.Store.check(pending)))
        return True


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
        store=SharedStore(path,legacy,device_port=5557,installation_id='a'*32)
        other=SharedStore(path,legacy,device_port=5557,installation_id='b'*32)
        try:
            assert child.stdout.readline().strip()=='ready'
            session=frida.get_local_device().attach(child.pid)
            source=manual.build(text,[])
            if case=='skip-cancel-before-observation':
                source += '''
const originalSkipAck=cohortAcknowledge;
cohortAcknowledge=function(value){
 if(value!==null&&value.skip===true)cancelNavigation();
 return originalSkipAck(value);
};
'''
            script=session.create_script(source+'''
rpc.exports={root(){return probeBatchProfile();},cancel(){cancelNavigation();},
 cohortpending(){return cohortReservation();},cohortack(value){return cohortAcknowledge(value);},
 counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {sends:r('fixture_auto_sends'),handles:r('fixture_handles'),off:r('fixture_off_thread_calls'),pins:r('fixture_pin_errors'),bad:r('fixture_auto_bad')};}};
''')
            script.load()
            def claim(pending):
                # Same global peer, another account and another installation, SAME port.
                p=dict(pending,account=str(int(pending['account'])+1))
                other.reserve(p,'Other greeting',approved=True)
                if case!='greeting-only':
                    with other.connection() as db:
                        other.record_peer_outcome(db,dict(account=p['account'],peer=p['peer'],chat='300'),'contact-refused')
            def approve(pending,*args):
                approvals.append(True)
                if case!='greeting-only':claim(pending)
                return True
            # v1.3.79 contract: the pre-approval check consults the pass-start
            # snapshot instead of a live store.peer_claimed() read. Peers claimed
            # before the pass are skipped without approval; the race case claims
            # during typing (after the snapshot missed it) and reserve()'s atomic
            # blocked() re-check stays the cross-account dedup authority.
            preclaimed=frozenset() if case=='race-during-typing' else claimed_snapshot(script,claim)
            thread=threading.Thread(target=manual.monitor,args=(script,store,text,approve,done,lambda:False,state),kwargs={'preclaimed':preclaimed},daemon=True)
            thread.start();raw=script.exports_sync.root();done.set();thread.join(timeout=5)
            assert not thread.is_alive()
            manual.validate(raw,shared_peer_skipped=state.get('shared_peer_skipped',False))
            n=raw['navigation'];counts=script.exports_sync.counts()
            assert state=={'shared_peer_skipped':True},state
            if case=='skip-cancel-before-observation':
                assert n['stage']=='navigation-stopped' and n['error']=='cancelled',n
                assert n['shared_peer_skipped'] is False and n['return_verified'] is False,n
                assert not n['send_attempted'] and not n['send_handler_returned'],n
                assert all(v==0 for v in counts.values()),counts
                assert not approvals and store.summary()['reserved']==0
                print('MuMu shared skip: interrupted ACK remains a validated STOP, no send/return claim',flush=True)
                return
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
    for case in ('already-claimed','race-during-typing','greeting-only','skip-cancel-before-observation'):one(library,case)
