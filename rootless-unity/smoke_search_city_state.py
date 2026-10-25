"""Actual read-only city observer and automatic recovery against OWNED ABI."""
from pathlib import Path
import subprocess,sys,tempfile
import frida
import search_city_state as state


def observe(library,mode=360,*,source=None,cancel=False):
    code="import ctypes,sys,time\nl=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL);l.fixture_init(int(sys.argv[2]));print('ready',flush=True)\nfor i in range(10000):l.fixture_tick();time.sleep(.003)"
    child=subprocess.Popen([sys.executable,'-u','-c',code,str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        assert child.stdout.readline().strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script((source or state.build())+'''
rpc.exports={root(){return probeUIKitRoot();},cancel(){cancelNavigation();},counts(){
 const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return Object.fromEntries(['opens','cancels','city_opens','city_texts','city_searches','city_selects','online_sets','online_applies','online_refreshes','handles','bad_frees','off_thread_calls'].map(k=>[k,r('fixture_'+k)]));}};
''')
        script.load()
        if cancel:script.exports_sync.cancel()
        result=state.validate(script.exports_sync.root())
        counts=script.exports_sync.counts();assert all(n==0 for n in counts.values()),counts
        return result
    finally:
        if script:script.unload()
        if session:session.detach()
        child.terminate();child.wait(timeout=5);child.stdout.close();child.stderr.close()


def run(library):
    value=observe(library);n=value['navigation']
    assert n['state_verified'] and n['state_samples']==2 and n['online_only'] and n['observed_city']=='OldCity'
    assert observe(library,300)['navigation']['online_only'] is False
    source=state.build().replace('const k=kind(current);',"const k='other';")
    assert observe(library,source=source)['navigation']['error']=='wrong-screen'
    source=state.build().replace('const fingerprint=JSON.stringify([city,geo,region,distance,only]);',
        'const fingerprint=JSON.stringify([city,geo,region,distance,only,n.frames]);')
    assert observe(library,source=source)['navigation']['error']=='screen-not-ready'
    assert observe(library,cancel=True)['navigation']['error']=='cancelled'
    from mumu_store import SharedStore
    from mumu_cities import recover_pending,owns
    with tempfile.TemporaryDirectory() as folder:
        store=SharedStore(Path(folder)/'db',device_port=5557)
        with store.connection() as db:
            for city,device,kind in [('oldcity','5557','active'),('pskov','5557','pending'),('othercity','5559','active')]:
                db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',(city,device,kind,'legacy'))
        def forbidden_wait(_):raise AssertionError('Verified state must resume without wait')
        city=recover_pending(store,['OldCity','Pskov','OtherCity'],lambda:observe(library),wait=forbidden_wait)
        assert city=='OldCity' and owns(store,city)
        with store.connection() as db:
            assert db.execute('SELECT device FROM mumu_city_claims WHERE city=?',('othercity',)).fetchone()==('5559',)
            assert db.execute("SELECT COUNT(*) FROM mumu_city_claims WHERE state='pending'").fetchone()[0]==0
    print('PASS: 6 read-only city-state/recovery cases; ZERO UI/model actions, handles or off-thread calls',flush=True)

if __name__=='__main__':run(Path(sys.argv[1]).resolve(strict=True))
