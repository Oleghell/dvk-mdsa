"""Real fixed browser JS against owned synthetic ABI objects, no live account."""
from pathlib import Path
import queue,subprocess,sys,threading,time,shutil,tempfile
import frida
from dialog_browser import build,validate
WHO=dict(account='100',peer='200',chat='300')
TARGET=dict(WHO,chat='-1')


def one(library,mode,operation='open',entry='search',unread_only=False,start_override=None,needs_reply_only=False,local_engine=False,seen_ids=None):
    code='''import ctypes,sys,time
lib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_LOCAL if sys.argv[4]=='1' else ctypes.RTLD_GLOBAL)
lib.fixture_init(int(sys.argv[2]));lib.fixture_browser_entry(int(sys.argv[3]))
print('ready',flush=True)
for _ in range(12000):
 lib.fixture_tick();time.sleep(.003)
'''
    allowed=[] if operation!='open' or mode==816 else [TARGET]
    if mode in (829,832):allowed=[dict(account='100',peer='201',chat='301'),TARGET]
    if mode==852:allowed=[dict(TARGET,seen_ids=['1002'])]
    if seen_ids is not None:allowed=[dict(TARGET,seen_ids=seen_ids)]
    expected=(dict(WHO,peer='201') if mode==809 else WHO) if operation=='back' else None
    start=3 if operation=='back' else 1 if operation=='return' or entry=='dialogs' else 0
    if start_override is not None:start=start_override
    child=subprocess.Popen([sys.executable,'-u','-c',code,str(library),str(mode),str(start),'1' if local_engine else '0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=monitor=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start();assert q.get(timeout=10).strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(build(operation,allowed=allowed,expected=expected,entry=entry,unread_only=unread_only,needs_reply_only=needs_reply_only)+'''
rpc.exports={probe(){return probeUIKitRoot();},cancel(){cancelNavigation();},counts(){
 const read=n=>new NativeFunction(findIl2cppExport(n),'int',[])();
 return {handles:read('fixture_handles'),bad:read('fixture_bad_frees'),off:read('fixture_off_thread_calls'),
 unread_reads:read('fixture_browser_unread_reads'),clicks:read('fixture_browser_clicks'),backs:read('fixture_browser_backs'),route_bad:read('fixture_route_bad'),routes:read('fixture_route_calls')};}};''')
        script.load()
        if mode in (815,839):
            def stop():
                until=time.monotonic()+5
                while time.monotonic()<until:
                    if script.exports_sync.counts()['backs' if mode==839 else 'clicks']:script.exports_sync.cancel();return
                    time.sleep(.003)
            monitor=threading.Thread(target=stop,daemon=True);monitor.start()
        raw=script.exports_sync.probe();result=validate(raw,operation,allowed=allowed,expected=expected,unread_only=unread_only,needs_reply_only=needs_reply_only)
        if monitor:monitor.join(timeout=6)
        c=script.exports_sync.counts();n=raw['navigation']
        expected_status={930:'search-ready',931:'frame-budget',932:'opened',933:'frame-budget',934:'wrong-screen',935:'managed-exception',936:'wrong-screen',937:'returned',800:'opened' if operation=='open' else 'returned' if operation=='back' else 'dialogs-ready' if operation=='list' else 'search-ready',801:'not-attempted',802:'selection-chat-changed',803:'identity-changed',804:'not-attempted',805:'exhausted',807:'managed-exception',808:'managed-exception',809:'identity-not-bound',810:'exhausted',811:'selection-count-changed',812:'signature-mismatch',813:'screen-not-ready',814:'identity-changed',815:'cancelled',816:'exhausted',817:'opened',818:'collection-too-large',819:'opened',820:'opened' if operation=='open' else 'returned' if operation=='back' else 'dialogs-ready' if operation=='list' else 'search-ready',821:'view-parent-depth-limit',822:'exhausted',823:'opened',824:'selection-unread-changed',825:'not-attempted',826:'unread-count-invalid',827:'signature-mismatch',828:'managed-exception',829:'opened',831:'selection-unread-changed',832:'exhausted',833:'not-attempted',834:'not-attempted',835:'not-attempted',836:'returned',837:'frame-budget',838:'identity-changed',839:'cancelled',840:'managed-exception',841:'returned',842:'frame-budget',844:'exhausted',845:'opened',846:'opened',847:'exhausted',848:'selection-last-message-changed',849:'selection-last-message-changed',850:'identity-not-bound',851:'identity-not-bound',852:'exhausted',853:'not-attempted',854:'identity-not-bound',855:'selection-unread-changed'}[mode]
        if mode in (800,846) and needs_reply_only and seen_ids is not None and '1002' in seen_ids:expected_status='exhausted'
        actual=result['state'] if result['state']!='stopped' else n['stage'] if n['stage']=='not-attempted' else n['error']
        assert actual==expected_status,(mode,operation,actual,n,c)
        assert c['handles']==c['bad']==c['off']==c['route_bad']==0,(mode,n,c)
        assert c['clicks']<=1 and c['backs']<=1 and n['handles_acquired']==n['handles_released'],(mode,n,c)
        if unread_only:
            if result['state']=='opened':assert n['unread_filter_applied'] and n['unread_verified'] and c['unread_reads']>=2,(mode,n,c)
            if result['state']=='exhausted':assert n['unread_filter_applied'] and not n['unread_verified'] and c['clicks']==0,(mode,n,c)
            if mode==822:assert n['read_rows_skipped']==1 and c['unread_reads']==1,(n,c)
            if mode==829:assert n['read_rows_skipped']==1 and c['unread_reads']==3,(n,c)
            if mode==832:assert n['read_rows_skipped']==2 and c['unread_reads']==2,(n,c)
            if result['state']!='opened':assert c['clicks']==0,(mode,n,c)
        elif not needs_reply_only:assert c['unread_reads']==0 and not n['unread_filter_applied'] and not n['unread_verified'],(mode,n,c)
        if needs_reply_only:
            if result['state']=='opened':assert n['reply_filter_applied'] and n['reply_needed_verified'] and c['unread_reads']>=2,(mode,n,c)
            if result['state']=='exhausted':assert n['reply_filter_applied'] and not n['reply_needed_verified'] and c['clicks']==0,(mode,n,c)
            if result['state']!='opened':assert c['clicks']==0,(mode,n,c)
            if mode in (844,847):assert n['waiting_rows_skipped']==1,(n,c)
            if mode==852:assert n['handled_rows_skipped']==1,(n,c)
        if mode in (930,931,932,933):
            assert c['routes']==1,(mode,n,c)
            assert n['observation_budget_retries']==(3 if mode in (931,933) else 1),(mode,n,c)
        if mode==932:assert n['entry_search_recovered'],(mode,n,c)
        if mode in (934,935,936):assert c['clicks']==c['backs']==0,(mode,n,c)
        if mode==936:assert c['routes']==0 and not n['entry_search_recovered'],(mode,n,c)
        if mode==937:assert n['frames']>=4,(mode,n,c)
        if result['state']=='opened':assert result['identity']==WHO and c['clicks']==1,(result,c)
        if result['state']=='exhausted' or mode in (801,802,804,811,812,813,818,821):assert c['clicks']==0,c
        if operation=='back':assert c['clicks']==0 and c['backs']==(mode not in (809,842)),c
        if mode in (836,838,841):assert n['back_budget_retries']==1,(mode,n,c)
        if mode==837:assert n['back_budget_retries']==3,(mode,n,c)
        if mode in (840,842):assert n['back_budget_retries']==0,(mode,n,c)
        if operation in ('return','list'):assert c['clicks']==0 and c['backs']==int(operation=='list' and entry=='either' and start==3),c
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

def integration(library,mode=800,ai=False,provider='groq',cached_models=False):
    # Keep one owned process alive through open -> real Chain reservation ->
    # outgoing observation -> back -> search. Bodies and transport are synthetic.
    import tempfile
    from assistant_store import Store
    from assistant_chain import Chain
    from assistant_settings import Settings
    from assistant_dialogs import walk
    code='''import ctypes,sys,time
lib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL);lib.fixture_init(int(sys.argv[2]))
print('ready',flush=True)
for _ in range(12000):
 lib.fixture_tick();time.sleep(.003)
'''
    child=subprocess.Popen([sys.executable,'-u','-c',code,str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start();assert q.get(timeout=10).strip()=='ready'
        recovered=[]
        def latest(message):
            session=frida.get_local_device().attach(child.pid);script=None
            try:
                script=session.create_script("rpc.exports={setLast(id,mine){new NativeFunction(Module.getGlobalExportByName('fixture_browser_last_message'),'void',['int','int'])(id,mine);new NativeFunction(Module.getGlobalExportByName('fixture_browser_clear_unread_on_open'),'void',['int'])(1);}};")
                script.load();script.exports_sync.set_last(int(message['id']),int(message['sender']=='100'))
            finally:
                if script:script.unload()
                session.detach()
        def navigator(operation,*args,allowed=(),expected=None,entry='search',**kwargs):
            unread_only=kwargs.get('unread_only',False)
            needs_reply_only=kwargs.get('needs_reply_only',False)
            session=frida.get_local_device().attach(child.pid);script=None
            try:
                if cached_models and operation=='open':
                    import dialog_models
                    source=dialog_models.build(allowed=allowed,entry=entry,unread_only=unread_only,needs_reply_only=needs_reply_only)
                else:source=build(operation,allowed=allowed,expected=expected,entry=entry,unread_only=unread_only,needs_reply_only=needs_reply_only)
                script=session.create_script(source+'''
rpc.exports={probe(){return probeUIKitRoot();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return [read('fixture_handles'),read('fixture_bad_frees'),read('fixture_off_thread_calls'),read('fixture_route_bad')];}};''')
                script.load();raw=script.exports_sync.probe()
                if cached_models and operation=='open':
                    result,nxt=dialog_models.validate(raw,allowed=allowed,unread_only=unread_only,needs_reply_only=needs_reply_only)
                    assert nxt is None
                else:result=validate(raw,operation,allowed=allowed,expected=expected,unread_only=unread_only,needs_reply_only=needs_reply_only)
                assert script.exports_sync.counts()==[0,0,0,0]
                if operation=='back':recovered.append(result['diagnostic']['back_budget_retries'])
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
                    assert db.execute("SELECT status FROM chain_actions WHERE status='reserved-unknown'").fetchone()[0]=='reserved-unknown'
                messages.append(dict(id=str(1001+len(messages)),sender='100',text=kwargs['text']))
                latest(messages[-1])
                return dict(attempted=True,handler_returned=True)
            result=walk(Settings(),threading.Event(),lambda _:None,chain,navigator=navigator,reader=reader,sender=sender,pause=lambda _:False)
            assert result['status']=='dialogs-completed' and result['return_verified'],result
            assert result['dialogs_processed']==result['reply_submission_calls']==result['reply_handler_returns']==result['outgoing_observed']==1,result
            assert result['new_greetings']==result['city_changes']==0
            # Continue the SAME owned journal through the real monitoring and
            # approval layers; only the message transport is synthetic.
            from contextlib import nullcontext
            import assistant_inbox
            import assistant_monitor
            messages.append(dict(id='1004',sender='200',text='Хорошо'))
            latest(messages[-1])
            stop=threading.Event();waits=[];approvals=[]
            def approve(kind,text,cancelled):
                approvals.append(kind);return not cancelled()
            def inbox(settings,stopped,confirm,progress,**kwargs):
                return assistant_inbox.run(settings,stopped,confirm,progress,store=store,
                    navigator=navigator,reader=reader,sender=sender,greetings=(greeting,),
                    pause=lambda _:False,**kwargs)
            def wait(seconds):
                waits.append(seconds)
                if len(waits)==2:stop.set();return True
                return False
            from unittest.mock import patch
            class SyntheticAI:
                def __init__(self, **kwargs):self.calls=0
                def __call__(self,kind,snapshot):
                    assert kind=='contact'
                    self.calls+=1
                    return dict(decision='reply',text='Понимаю. Удобнее в Telegram или WhatsApp?')
            class SyntheticAIChain(assistant_inbox.InboxChain):
                def __init__(self,store,**kwargs):
                    super().__init__(store,seal=lambda b:b'E'+b[::-1],unseal=lambda b:b[1:][::-1],**kwargs)
            with (patch(('groq_reply' if provider=='groq' else 'openrouter_reply')+'.Responder',SyntheticAI) if ai else nullcontext()), \
                 (patch('assistant_inbox.InboxChain',SyntheticAIChain) if ai else nullcontext()):
                monitored=assistant_monitor.run(Settings(groq_enabled=ai,ai_provider=provider),stop,approve,mode='inbox',
                    inbox=inbox,navigator=navigator,lock=nullcontext,
                    write=lambda _: 'last-monitor.json',wait=wait)
            if ai:
                assert monitored['totals']['groq_requests' if provider=='groq' else 'openrouter_requests']==1,monitored
                assert monitored['totals']['ai_requests']==1,monitored
                assert monitored['ai_provider']==provider,monitored
                assert monitored['chat_content_exported'],monitored

            assert monitored['status']=='cancelled' and monitored['dialogs_verified'],monitored
            assert monitored['passes_completed']==3 and monitored['immediate_rechecks']==1 and approvals==['contact'],monitored
            assert monitored['totals']['submission_calls']==1,monitored
            assert monitored['totals']['handler_returns']==1,monitored
            assert monitored['totals']['outgoing_observed']==1,monitored
            assert monitored['totals']['contacts_forwarded']==0,monitored
            assert not monitored['automatic_profile_repeat'] and not monitored['delivery_confirmed']
            if mode==843:assert monitored['last_pass']['dialogs_opened']==0 and monitored['last_pass']['waiting_rows_skipped']==1,monitored
            if mode in (836,843):assert recovered and all(r==1 for r in recovered),recovered
            assert sum(m['sender']=='100' for m in messages)==3,messages
            # A direct bare-number contact response reaches the durable outbox
            # and Telegram callback without another chat reply or reopening done.
            from unittest.mock import patch
            messages.append(dict(id='1006',sender='200',text='791234567890'))
            latest(messages[-1]);delivered=[]
            if cached_models:
                # Next cached chat has a bad header. Its own identity remains
                # valid, so it must not stop the pass after the accepted photo.
                a=store.reserve(dict(attempt=2,account='100',peer='201',chat='301',variant=0),greeting,approved=True)
                store.finish(a,dict(send_attempted=True,send_handler_returned=True))
            import struct,zlib
            def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
            photo=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',300,600,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\0'*900)*600))+chunk(b'IEND',b'')
            with patch('assistant_inbox.InboxChain',SyntheticAIChain):
                contacted=assistant_inbox.run(Settings(contacts_enabled=True),threading.Event(),approve,store=store,
                    navigator=navigator,reader=reader,sender=sender,notifier=lambda payload:delivered.append(payload) or True,
                    greetings=(greeting,),pause=lambda _:False,entry='dialogs',return_to='dialogs',contact_photo=lambda who:photo)
                assert contacted['status']=='inbox-completed' and contacted['contacts_forwarded']==1 and contacted['submission_calls']==0,contacted
                assert len(delivered)==1 and delivered[0]['contacts']==['791234567890'] and delivered[0]['photo']==photo,delivered
                again=assistant_inbox.run(Settings(contacts_enabled=True),threading.Event(),approve,store=store,
                    navigator=navigator,reader=reader,sender=sender,notifier=lambda payload:delivered.append(payload) or True,
                    greetings=(greeting,),pause=lambda _:False,entry='dialogs',return_to='dialogs',contact_photo=lambda who:photo)
                assert again['status']==('inbox-completed' if cached_models else 'inbox-empty') and again['dialogs_opened']==0 and len(delivered)==1,again
                if cached_models:assert contacted['header_rows_skipped']>0 and again['header_rows_skipped']>0,(contacted,again)
            if cached_models:
                # Full MuMu mode must leave the verified, drained inbox for
                # search without spending the rest of the old 120s interval.
                stop=threading.Event();rotations=[]
                def initial_noop(*args,**kwargs):
                    return dict(status='completed',report_name='last-run.json')
                def next_profiles(*args,**kwargs):
                    assert kwargs['mode']=='profiles'
                    rotations.append('profiles');stop.set()
                    return dict(status='completed',report_name='last-run.json')
                def no_idle(seconds):raise AssertionError('Unexpected full-mode idle')
                continuous=assistant_monitor.run(Settings(contacts_enabled=False,errors_enabled=False),stop,approve,
                    mode='full',continuous=True,initial=initial_noop,repeat=next_profiles,
                    inbox=inbox,navigator=navigator,lock=nullcontext,clock=lambda:0,
                    write=lambda _: 'last-monitor.json',wait=no_idle)
                assert rotations==['profiles'] and continuous['early_profile_batches']==1,continuous
                assert continuous['totals']['submission_calls']==0,continuous
                assert continuous['status']=='cancelled',continuous
                print('Synthetic continuous MuMu: verified inbox -> search, no idle, no resend.',flush=True)
        print('Synthetic browser + durable chain + outgoing observation + return passed.',flush=True)
        print('Synthetic monitor: immediate inbox recheck, idle in dialogs, direct contact delivered once without reopening.',flush=True)
    finally:
        child.terminate()
        try:child.wait(timeout=3)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
        child.stdout.close();child.stderr.close()


if __name__=='__main__':
    lib=Path(sys.argv[1]).resolve(strict=True)
    for mode in (800,801,802,803,804,805,807,810,811,812,813,814,815,816,817,818,819,820,821):one(lib,mode)
    one(lib,800,entry='dialogs')
    one(lib,820,entry='dialogs')
    one(lib,820,'back')
    one(lib,820,'return')
    for mode in (800,808,809,836,837,838,839,840,841,842):one(lib,mode,'back')
    one(lib,800,'return')
    for mode in (822,823,824,825,826,827,828,829,831,832,833,834,835):one(lib,mode,unread_only=True)
    for mode in (800,820):
        one(lib,mode,'list')
        one(lib,mode,'list',entry='dialogs')
        one(lib,mode,'list',entry='either')
        one(lib,mode,'list',entry='either',start_override=1)
    one(lib,800,'list',entry='either',start_override=3)
    one(lib,820,'list',entry='either',start_override=3)
    one(lib,838,'list',entry='either',start_override=3)
    one(lib,840,'list',entry='either',start_override=3)
    # Named engine in a local loader namespace: no reliance on global exports.
    with tempfile.TemporaryDirectory() as temp:
        local=Path(temp)/'libil2cpp.so';shutil.copy2(lib,local)
        one(local,800,'list',entry='either',local_engine=True)
        one(local,800,'list',entry='either',start_override=1,local_engine=True)
    for mode in (930,931):one(lib,mode,operation='return')
    for mode in (932,933):one(lib,mode,entry='dialogs',start_override=0)
    one(lib,934,entry='dialogs')
    one(lib,935,operation='return')
    one(lib,936,entry='dialogs',start_override=3)
    one(lib,937,operation='back')
    for mode in range(844,856):one(lib,mode,needs_reply_only=True)
    one(lib,846,unread_only=True,needs_reply_only=True)
    for mode,ids in ((800,['1002']),(800,['9999']),(846,['1002'])):
        one(lib,mode,entry='dialogs',needs_reply_only=True,seen_ids=ids)
    integration(lib)
    integration(lib,836)
    integration(lib,836,ai=True)
    integration(lib,843,ai=True)
    integration(lib,843,ai=True,provider='openrouter')
    print('Synthetic browser cases and fixed/AI-chain integrations passed. No live dialog selection verified.')
