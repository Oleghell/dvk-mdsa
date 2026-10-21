"""Real fixed browser JS against owned synthetic ABI objects, no live account."""
from pathlib import Path
import queue,subprocess,sys,threading,time
import frida
from dialog_browser import build,validate
WHO=dict(account='100',peer='200',chat='300')
TARGET=dict(WHO,chat='-1')


def one(library,mode,operation='open',entry='search'):
    code='''import ctypes,sys,time
lib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)
lib.fixture_init(int(sys.argv[2]));lib.fixture_browser_entry(int(sys.argv[3]))
print('ready',flush=True)
for _ in range(12000):
 lib.fixture_tick();time.sleep(.003)
'''
    allowed=[] if operation!='open' or mode==816 else [TARGET]
    expected=(dict(WHO,peer='201') if mode==809 else WHO) if operation=='back' else None
    start=3 if operation=='back' else 1 if operation=='return' or entry=='dialogs' else 0
    child=subprocess.Popen([sys.executable,'-u','-c',code,str(library),str(mode),str(start)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=monitor=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start();assert q.get(timeout=10).strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(build(operation,allowed=allowed,expected=expected,entry=entry)+'''
rpc.exports={probe(){return probeUIKitRoot();},cancel(){cancelNavigation();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {handles:read('fixture_handles'),bad:read('fixture_bad_frees'),off:read('fixture_off_thread_calls'),
 clicks:read('fixture_browser_clicks'),backs:read('fixture_browser_backs'),route_bad:read('fixture_route_bad')};}};''')
        script.load()
        if mode==815:
            def stop():
                until=time.monotonic()+5
                while time.monotonic()<until:
                    if script.exports_sync.counts()['clicks']:script.exports_sync.cancel();return
                    time.sleep(.003)
            monitor=threading.Thread(target=stop,daemon=True);monitor.start()
        raw=script.exports_sync.probe();result=validate(raw,operation,allowed=allowed,expected=expected)
        if monitor:monitor.join(timeout=6)
        c=script.exports_sync.counts();n=raw['navigation']
        expected_status={800:'opened' if operation=='open' else 'returned' if operation=='back' else 'search-ready',801:'not-attempted',802:'selection-chat-changed',803:'identity-changed',804:'not-attempted',805:'exhausted',807:'managed-exception',808:'managed-exception',809:'identity-not-bound',810:'exhausted',811:'selection-count-changed',812:'signature-mismatch',813:'screen-not-ready',814:'identity-changed',815:'cancelled',816:'exhausted',817:'opened',818:'collection-too-large',819:'opened'}[mode]
        actual=result['state'] if result['state']!='stopped' else n['stage'] if n['stage']=='not-attempted' else n['error']
        assert actual==expected_status,(mode,operation,actual,n,c)
        assert c['handles']==c['bad']==c['off']==c['route_bad']==0,(mode,n,c)
        assert c['clicks']<=1 and c['backs']<=1 and n['handles_acquired']==n['handles_released'],(mode,n,c)
        if result['state']=='opened':assert result['identity']==WHO and c['clicks']==1,(result,c)
        if result['state']=='exhausted' or mode in (801,802,804,811,812,813,818):assert c['clicks']==0,c
        if operation=='back':assert c['clicks']==0 and c['backs']==(mode!=809),c
        if operation=='return':assert c['clicks']==c['backs']==0,c
        print('Synthetic dialog browser',mode,operation,entry,actual,flush=True)
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

def integration(library):
    # Keep one owned process alive through open -> real Chain reservation ->
    # outgoing observation -> back -> search. Bodies and transport are synthetic.
    import tempfile
    from assistant_store import Store
    from assistant_chain import Chain
    from assistant_settings import Settings
    from assistant_dialogs import walk
    code='''import ctypes,sys,time
lib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL);lib.fixture_init(800)
print('ready',flush=True)
for _ in range(12000):
 lib.fixture_tick();time.sleep(.003)
'''
    child=subprocess.Popen([sys.executable,'-u','-c',code,str(library)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start();assert q.get(timeout=10).strip()=='ready'
        def navigator(operation,*args,allowed=(),expected=None,entry='search',**kwargs):
            session=frida.get_local_device().attach(child.pid);script=None
            try:
                script=session.create_script(build(operation,allowed=allowed,expected=expected,entry=entry)+'''
rpc.exports={probe(){return probeUIKitRoot();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return [read('fixture_handles'),read('fixture_bad_frees'),read('fixture_off_thread_calls'),read('fixture_route_bad')];}};''')
                script.load();result=validate(script.exports_sync.probe(),operation,allowed=allowed,expected=expected)
                assert script.exports_sync.counts()==[0,0,0,0]
                return result
            finally:
                if script:script.unload()
                session.detach()
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'assistant.sqlite3',Path(temp)/'old')
            greeting='Привет 🙂'
            action=store.reserve(dict(attempt=1,account='100',peer='200',chat='-1',variant=0),greeting,approved=True)
            store.finish(action,dict(send_attempted=True,send_handler_returned=True))
            chain=Chain(store,choose=lambda:0)
            messages=[dict(id='1001',sender='100',text=greeting),dict(id='1002',sender='200',text='Привет')]
            def reader(*args,**kwargs):
                assert args[3]==WHO
                return dict(identity=dict(WHO),messages=[dict(m) for m in messages])
            def sender(*args,**kwargs):
                with store.connection() as db:
                    assert db.execute('SELECT status FROM chain_actions').fetchone()[0]=='reserved-unknown'
                messages.append(dict(id='1003',sender='100',text=kwargs['text']))
                return dict(attempted=True,handler_returned=True)
            result=walk(Settings(),threading.Event(),lambda _:None,chain,navigator=navigator,reader=reader,sender=sender,pause=lambda _:False)
            assert result['status']=='dialogs-completed' and result['return_verified'],result
            assert result['dialogs_processed']==result['reply_submission_calls']==result['reply_handler_returns']==result['outgoing_observed']==1,result
            assert result['new_greetings']==result['city_changes']==0
        print('Synthetic browser + durable chain + outgoing observation + return passed.',flush=True)
    finally:
        child.terminate()
        try:child.wait(timeout=3)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
        child.stdout.close();child.stderr.close()


if __name__=='__main__':
    lib=Path(sys.argv[1]).resolve(strict=True)
    for mode in (800,801,802,803,804,805,807,810,811,812,813,814,815,816,817,818,819):one(lib,mode)
    one(lib,800,entry='dialogs')
    for mode in (800,808,809):one(lib,mode,'back')
    one(lib,800,'return')
    integration(lib)
    print('22 synthetic browser cases and chain integration passed. No live dialog selection verified.')
