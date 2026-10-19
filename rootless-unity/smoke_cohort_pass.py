"""Fixed reserve/ACK handshake against owned C ABI, with real durable SQLite."""
from pathlib import Path
import json,subprocess,sys,threading,time,tempfile,frida
import cohort_pass as p

def one(library,case):
    mode=505 if case=='send-error' else 513
    flag={'zero-account':1,'self':2,'draft':3,'identity-change':4,'slow-return':5,'stuck-return':6}.get(case,0)
    child=subprocess.Popen([sys.executable,'-u','-c',"import ctypes,sys,time\nl=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nl.fixture_init(int(sys.argv[2]));l.fixture_cohort_mode(int(sys.argv[3]))\nprint('ready',flush=True)\nfor _ in range(100000):\n l.fixture_tick();time.sleep(.003)",str(library),str(mode),str(flag)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=thread=None;stop=threading.Event();failed=threading.Event()
    with tempfile.TemporaryDirectory() as directory:
        store=p.Store(Path(directory)/'bindings.sqlite3');store.create()
        try:
            assert child.stdout.readline().strip()=='ready'
            session=frida.get_local_device().attach(child.pid)
            script=session.create_script(p.build(list(range(10)))+'''
rpc.exports={root(){return probeBatchProfile();},cancel(){cancelNavigation();},cohortpending(){return cohortReservation();},cohortack(value){return cohortAcknowledge(value);},counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();return {sends:r('fixture_auto_sends'),handles:r('fixture_handles'),off:r('fixture_off_thread_calls'),pins:r('fixture_pin_errors'),bad:r('fixture_auto_bad'),timing:r('fixture_auto_timing_bad'),backs:r('fixture_auto_backs')};}};
''');script.load()
            if case=='disk-failure':
                def reserve(_):raise OSError('synthetic disk failure')
                store.reserve=reserve
            if case=='cancel-after-reserve':
                original=store.reserve
                def reserve(value):original(value);stop.set()
                store.reserve=reserve
            if case!='no-ack':
                thread=threading.Thread(target=p.monitor,args=(script,store,stop,lambda:False,failed),daemon=True);thread.start()
            out=p.run(script.exports_sync.root)
            stop.set()
            if thread:thread.join(timeout=6);assert not thread.is_alive()
            store.finish(out);summary=store.summary();counts=script.exports_sync.counts()
            assert all(counts[k]==0 for k in ('handles','off','pins','bad','timing')),(case,out,counts)
            if case in ('normal','draft','slow-return'):
                assert out['status']=='batch-completed' and counts['sends']==summary['reserved']==summary['handlers_returned']==6,(case,out,counts,summary)
            elif case=='stuck-return':
                assert out['status']=='batch-stopped' and out['reason']=='transition-timeout'
                assert counts['sends']==counts['backs']==summary['reserved']==3
                assert out['items'][-1]['returned'] is False
            elif case=='send-error':
                assert out['status']=='batch-stopped' and counts['sends']==summary['reserved']==1 and summary['handlers_returned']==0
            else:assert counts['sends']==0,(case,out,counts)
            if case in ('disk-failure','zero-account','self','no-ack'):assert summary['reserved']==0
            if case=='cancel-after-reserve':assert summary['reserved']==1
            if case=='disk-failure':assert failed.is_set()
            assert not any(x in json.dumps(out)+json.dumps(summary) for x in ('9999','identityKey','initial_chat','account','peer'))
            with store.connection() as db:
                if case=='draft':assert all(r[0]=='-1' for r in db.execute('SELECT initial_chat FROM bindings'))
            try:p.Store(store.path).create()
            except p.CohortError:pass
            else:raise AssertionError('Restart silently created a second cohort')
            print('Synthetic cohort',case,out['status'],'reservations',summary['reserved'],'submissions',counts['sends'],flush=True)
        finally:
            stop.set()
            if thread:thread.join(timeout=6)
            if script:script.unload()
            if session:session.detach()
            child.terminate();child.wait(timeout=5);child.stdout.close();child.stderr.close()

if __name__=='__main__':
    from concurrent.futures import ThreadPoolExecutor
    lib=Path(sys.argv[1]).resolve(strict=True)
    cases=sys.argv[2:] or ['normal','draft','zero-account','self','identity-change','send-error','disk-failure','cancel-after-reserve','no-ack','slow-return','stuck-return']
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda case:one(lib,case),cases))
