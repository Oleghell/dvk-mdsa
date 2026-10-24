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
    flag = 7 if case in ('input-disabled','input-disabled-back-identity','input-disabled-back-unknown') else 4 if case == 'identity-change' else 3 if case == 'draft' else 0
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
            if case=='combined-frame-baseline':
                from unittest.mock import patch
                with patch('assistant_profile_read.specialize',side_effect=lambda value:value):
                    source=manual.build(text,visited)
                source=source.replace('r.navigation=emptyNavigation();','r.navigation=emptyNavigation();r.navigation.profile_read_budget_retries=0;r.navigation.greeting_frame_splits=0;r.navigation.profile_ready_waits=0;')
            if case in ('combined-frame','combined-frame-baseline'):
                source=source.replace("n.read_checkpoint='identity';","{const until=Date.now()+65;while(Date.now()<until){}}n.read_checkpoint='identity';")
                source=source.replace('const manager=call(s.cohortManager,chat);',"{const until=Date.now()+45;while(Date.now()<until){}}const manager=call(s.cohortManager,chat);")
            if case in ('read-budget-once','read-budget-always','identity-after-budget'):
                cond="n.profile_read_budget_retries===0" if case!='read-budget-always' else 'true'
                inject="if("+cond+")fail('frame-budget');"
                if case=='identity-after-budget':inject+="fail('identity-changed');"
                source=source.replace("n.read_checkpoint='identity';",inject+"n.read_checkpoint='identity';")
            if case in ('actual-late','actual-never','actual-identity-change','actual-back-identity','actual-back-unknown'):
                guard='true' if case in ('actual-never','actual-back-identity','actual-back-unknown') else 'n.profile_ready_waits===0'
                source=source.replace('n.model_actual=bool(s.actual,chat);',
                    'n.model_actual=bool(s.actual,chat);if('+guard+')n.model_actual=false;')
                if case=='actual-identity-change':
                    source=source.replace("n.read_checkpoint='identity';",
                        "if(n.profile_ready_waits>0)fail('identity-changed');n.read_checkpoint='identity';")
            if case=='actual-back-identity':
                source=source.replace("if(n.phase==='close-chat'){", "if(n.phase==='close-chat'){if(n.profile_read_skipped)fail('identity-changed');")
            if case=='actual-back-unknown':
                source=source.replace('call(s.chatBack,current);n.chat_back_completed=true;', "call(s.chatBack,current);fail('frame-budget');n.chat_back_completed=true;")
            if case=='read-budget-pinned':
                source=source.replace("n.read_checkpoint='model';", "n.read_checkpoint='model';fail('frame-budget');")
            if case in ('history-loading-skip','history-not-loaded-skip'):
                source=source.replace('const all=bool(s.value,field);', 'const all=false;')
                if case=='history-loading-skip':
                    source=source.replace('const loading=bool(s.historyLoading,cm),', 'const loading=true,')
            if case=='input-disabled-prepare':
                source=source.replace('n.profile_input_enabled=bool(s.input,chat);',
                    "n.profile_input_enabled=n.phase==='prepare-greeting'?false:bool(s.input,chat);")
            if case=='input-disabled-after-approval':
                source=source.replace("if(n.phase==='submit-greeting'){",
                    "if(n.phase==='submit-greeting'){fail('input-disabled');")
            if case=='input-disabled-back-identity':
                source=source.replace("if(n.phase==='close-chat'){",
                    "if(n.phase==='close-chat'){fail('identity-changed');")
            if case=='input-disabled-back-unknown':
                source=source.replace('call(s.chatBack,current);n.chat_back_completed=true;',
                    "call(s.chatBack,current);fail('frame-budget');n.chat_back_completed=true;")
            if case=='history-after-approval':
                source=source.replace("if(n.phase==='submit-greeting'){","if(n.phase==='submit-greeting'){fail('history-not-ready');")
            if case=='send-return-budget':
                source=source.replace('call(s.send,current,args);n.send_handler_returned=true;',"call(s.send,current,args);fail('frame-budget');n.send_handler_returned=true;")
            if case=='slow-profile-baseline':
                source=source.replace("if(n.phase==='wait-profile'||n.phase==='confirm-profile'||n.phase==='wait-return')state.nextActionAt=Date.now()+100;",'')
            script = session.create_script(source + '''
rpc.exports={root(){return probeBatchProfile();},cancel(){cancelNavigation();},
 cohortpending(){return cohortReservation();},cohortack(value){return cohortAcknowledge(value);},
 selectedpeer(){return assistantSelectedPeer;},
 counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {sends:r('fixture_auto_sends'),opens:r('fixture_opens'),backs:r('fixture_auto_backs'),handles:r('fixture_handles'),
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
            sends = 1 if case in ('approve', 'draft', 'handler-error', 'skip-visited', 'slow-profile','combined-frame','read-budget-once','send-return-budget','actual-late') else 0
            assert counts['sends'] == sends, (case, counts, n['error'])
            assert counts['opens'] == (0 if case == 'crowded-search' else 1), (case, counts)
            if case == 'crowded-search':
                assert n['error']=='call-limit' and n['phase']=='search' and n['managed_calls']==6000, n
                assert not n['open_attempted'] and not n['chat_open_attempted'] and not approvals
            if case in ('actual-late','actual-never','actual-identity-change','actual-back-identity','actual-back-unknown'):
                assert n['profile_ready_waits']==(1 if case in ('actual-late','actual-identity-change') else 4),(case,n)
                if case!='actual-late':
                    assert not approvals and store.summary()['reserved']==0 and not n['send_attempted'],(case,n)
                    if case=='actual-never':
                        assert n['stage']=='navigation-ready' and n['error']=='none' and n['return_verified'] and n['profile_read_skipped'],(case,n)
                        assert counts['backs']==1 and peer in store.visited_peers(),(case,n,counts)
                    else:
                        assert n['stage']=='navigation-stopped' and n['error']==('frame-budget' if case=='actual-back-unknown' else 'identity-changed'),(case,n)
                        assert counts['backs']==(1 if case=='actual-back-unknown' else 0),(case,counts)
            if case=='slow-profile-baseline':
                assert n['stage']=='navigation-stopped' and n['error'] in ('frame-limit','call-limit') and not approvals, n
            if case == 'slow-profile':
                assert n['stage']=='navigation-ready' and n['managed_calls']<6000, n
            if case in ('read-budget-once','read-budget-always','identity-after-budget'):
                assert n['profile_read_budget_retries']==(4 if case=='read-budget-always' else 1),(case,n)
            if case in ('read-budget-always','identity-after-budget','combined-frame-baseline'):
                assert not approvals and store.summary()['reserved']==0,(case,n,state)
                assert n['error']==('identity-changed' if case=='identity-after-budget' else 'frame-budget'),(case,n)
            if case in ('read-budget-pinned','history-loading-skip','history-not-loaded-skip'):
                assert n['stage']=='navigation-ready' and n['error']=='none' and n['profile_read_skipped'] and n['return_verified'],(case,n)
                assert n['samples']==0 and n['message_count'] is None and n['history_status']=='not-ready',(case,n)
                assert counts['backs']==1 and not approvals and store.summary()['reserved']==0 and peer in store.visited_peers(),(case,n,counts)
            if case in ('input-disabled-back-identity','input-disabled-back-unknown'):
                assert n['stage']=='navigation-stopped' and n['profile_read_skipped'] and not n['return_verified'],(case,n)
                assert not approvals and store.summary()['reserved']==0 and not n['send_attempted'],(case,n)
                assert counts['backs']==int(case=='input-disabled-back-unknown'),(case,counts)
            if case=='input-disabled-after-approval':
                assert n['stage']=='navigation-stopped' and not n['profile_read_skipped'] and not n['send_attempted'],(case,n)
                assert len(approvals)==1 and store.summary()['reserved']==1 and counts['backs']==0,(case,n)
            if case=='history-after-approval':
                assert len(approvals)==1 and store.summary()['reserved']==1 and not n['send_attempted'],(case,n,state)
            if case=='send-return-budget':
                assert len(approvals)==1 and store.summary()['reserved']==1 and n['send_attempted'] and not n['send_handler_returned'],(case,n,state)
            if sends:
                assert len(approvals) == 1 and store.summary()['reserved'] == 1
                with Store(store.path, store.legacy).connection() as db:
                    row = db.execute('SELECT status,confirmed FROM manual_actions').fetchone()
                    assert row[1] == 1
                    if case=='send-return-budget':assert row[0]=='attempted-unknown',row
                try:
                    Store(store.path, store.legacy).reserve(approvals[0], text, approved=True)
                except StateError:
                    pass
                else:
                    raise AssertionError('Restart permitted duplicate send')
            if case in ('input-disabled','input-disabled-prepare'):
                assert n['stage']=='navigation-ready' and n['error']=='none' and n['return_verified'],(case,n)
                assert n['profile_read_skipped'] and n['profile_read_skip_reason']=='input-disabled' and n['profile_input_enabled'] is False,(case,n)
                assert not approvals and store.summary()['reserved']==0 and counts['backs']==1 and peer in store.visited_peers(),(case,n,counts)
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
    cases = sys.argv[2:] or ['approve', 'reject', 'nonempty', 'friends-50', 'skip-visited', 'draft', 'identity-change', 'handler-error', 'disk-failure', 'crowded-search', 'slow-profile', 'slow-profile-baseline','combined-frame','combined-frame-baseline','read-budget-once','read-budget-always','identity-after-budget','history-after-approval','send-return-budget','actual-late','actual-never','actual-identity-change','actual-back-identity','actual-back-unknown','read-budget-pinned','history-loading-skip','history-not-loaded-skip','input-disabled','input-disabled-prepare','input-disabled-after-approval','input-disabled-back-identity','input-disabled-back-unknown']
    # Baseline construction patches a module function: keep it outside workers.
    if 'combined-frame-baseline' in cases:
        one(library,'combined-frame-baseline');cases.remove('combined-frame-baseline')
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda case: one(library, case), cases))
