"""Run the actual manual-gate JS against an owned C ABI fixture, not Android."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import threading
import time

import frida
import assistant_pass as manual
from assistant_store import Store, StateError
from greetings import get_greeting


def one(library, case):
    mode = 518 if case == 'crowded-search' else 519 if case in ('slow-profile','slow-profile-baseline') else 502 if case == 'nonempty' else 505 if case == 'handler-error' else 513
    flag = 4 if case == 'identity-change' else 3 if case == 'draft' else 0
    visited = list(map(str,range(1,25))) if case == 'crowded-search' else ['1', '2'] if case == 'friends-50' else ['1'] if case == 'skip-visited' else []
    child = subprocess.Popen([sys.executable, '-u', '-c',
        "import ctypes,sys,time\nl=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\n"
        "l.fixture_init(int(sys.argv[2]));l.fixture_cohort_mode(int(sys.argv[3]))\n"
        "print('ready',flush=True)\nfor _ in range(100000):\n l.fixture_tick();time.sleep(.003)",
        str(library), str(mode), str(flag)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    session = script = thread = None
    done = threading.Event()
    state = {}
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / 'assistant.sqlite3', Path(directory) / 'legacy')
        text = get_greeting(2)
        approvals = []
        try:
            assert child.stdout.readline().strip() == 'ready'
            session = frida.get_local_device().attach(child.pid)
            source=manual.build(text, visited)
            if case=='slow-profile-baseline':
                source=source.replace("if(n.phase==='wait-profile'||n.phase==='confirm-profile'||n.phase==='wait-return')state.nextActionAt=Date.now()+100;",'')
            script = session.create_script(source + '''
rpc.exports={root(){return probeBatchProfile();},cancel(){cancelNavigation();},
 cohortpending(){return cohortReservation();},cohortack(value){return cohortAcknowledge(value);},
 selectedpeer(){return assistantSelectedPeer;},
 counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {sends:r('fixture_auto_sends'),opens:r('fixture_opens'),handles:r('fixture_handles'),
 off:r('fixture_off_thread_calls'),pins:r('fixture_pin_errors'),bad:r('fixture_auto_bad'),timing:r('fixture_auto_timing_bad')};}};
''')
            script.load()
            def approve(pending, selected_text, cancelled):
                assert script.exports_sync.counts()['sends'] == 0, 'Sent before approval'
                assert store.summary()['reserved'] == 0, 'Reserved before approval'
                assert selected_text == text
                approvals.append(pending)
                # Exercise a real delay with no authorization sent during it.
                time.sleep(.2)
                assert script.exports_sync.counts()['sends'] == 0
                return case != 'reject'
            if case == 'disk-failure':
                def reserve(*args, **kwargs):
                    raise OSError('PRIVATE simulated disk failure')
                store.reserve = reserve
            thread = threading.Thread(target=manual.monitor,
                args=(script, store, text, approve, done, lambda: False, state), daemon=True)
            thread.start()
            result = manual.validate(script.exports_sync.root())
            done.set()
            thread.join(timeout=5)
            assert not thread.is_alive()
            n = result['navigation']
            peer = script.exports_sync.selectedpeer()
            if peer is not None:
                store.record_visit(peer, n)
            if state.get('action_id') is not None:
                store.finish(state['action_id'], n)
            counts = script.exports_sync.counts()
            assert all(counts[k] == 0 for k in ('handles', 'off', 'pins', 'bad', 'timing')), (case, counts)
            sends = 1 if case in ('approve', 'draft', 'handler-error', 'skip-visited', 'slow-profile') else 0
            assert counts['sends'] == sends, (case, counts, n['error'])
            assert counts['opens'] == (0 if case == 'crowded-search' else 1), (case, counts)
            if case == 'crowded-search':
                assert n['error']=='call-limit' and n['phase']=='search' and n['managed_calls']==6000, n
                assert not n['open_attempted'] and not n['chat_open_attempted'] and not approvals
            if case=='slow-profile-baseline':
                assert n['stage']=='navigation-stopped' and n['error'] in ('frame-limit','call-limit') and not approvals, n
            if case == 'slow-profile':
                assert n['stage']=='navigation-ready' and n['managed_calls']<6000, n
            if sends:
                assert len(approvals) == 1 and store.summary()['reserved'] == 1
                with Store(store.path, store.legacy).connection() as db:
                    row = db.execute('SELECT status,confirmed FROM manual_actions').fetchone()
                    assert row[1] == 1
                try:
                    Store(store.path, store.legacy).reserve(approvals[0], text, approved=True)
                except StateError:
                    pass
                else:
                    raise AssertionError('Restart permitted duplicate send')
            if case == 'nonempty':
                assert not approvals and n['history_status'] == 'not-empty'
            if case == 'friends-50':
                assert not approvals and n['friends_count'] == 50 and n['friends_eligible'] is False
            if case == 'skip-visited':
                assert peer == '2'
            if case == 'reject':
                assert state['declined'] and store.summary()['reserved'] == 0
            assert 'PRIVATE' not in json.dumps(state)
            assert not any(x in json.dumps(result) for x in ('9999', 'initial_chat', 'peer', 'account', text))
            before = script.exports_sync.counts()
            try:
                script.exports_sync.root()
            except frida.RPCException:
                pass
            else:
                raise AssertionError('Second cycle was not blocked')
            assert before == script.exports_sync.counts()
            print('Manual assistant:', case, 'native sends:', counts['sends'], 'status:', n['stage'], flush=True)
        finally:
            done.set()
            if thread:
                thread.join(timeout=5)
            if script:
                script.unload()
            if session:
                session.detach()
            child.terminate()
            child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()


if __name__ == '__main__':
    library = Path(sys.argv[1]).resolve(strict=True)
    cases = sys.argv[2:] or ['approve', 'reject', 'nonempty', 'friends-50', 'skip-visited', 'draft', 'identity-change', 'handler-error', 'disk-failure', 'crowded-search', 'slow-profile', 'slow-profile-baseline']
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda case: one(library, case), cases))
