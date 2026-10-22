"""Run the exact Frida metadata graph against owned C ABI definitions only."""
from pathlib import Path
import json,queue,subprocess,sys,threading
import frida
import chat_runtime_metadata as p


def one(library,mode):
    child=subprocess.Popen([sys.executable,'-u','-c',"import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\ntime.sleep(60)",str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        source=p.FUNCTION
        if mode==12:source=source.replace("findIl2cppExport('il2cpp_'+n)","(n==='class_get_fields'?null:findIl2cppExport('il2cpp_'+n))")
        script=session.create_script(source+'''\nrpc.exports={probe(){return nativeMetadata();},counts(){
 const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
 return {attached:read('fixture_attached'),invokes:read('fixture_invokes'),values:read('fixture_values'),keeps:read('fixture_keeps'),detaches:read('fixture_detaches')};}};''')
        script.load();out=p.validate(script.exports_sync.probe());c=script.exports_sync.counts()
        assert c['invokes']==c['values']==c['keeps']==0,(mode,out,c)
        assert c['attached']==(1 if mode in (6,7) else 0),(mode,out,c)
        expected={0:('chat-runtime-ready','none'),1:('chat-runtime-ready','none'),2:('chat-runtime-stopped','invalid-metadata'),3:('chat-runtime-limited','limits'),4:('chat-runtime-stopped','invalid-metadata'),5:('chat-runtime-stopped','domain-unavailable'),6:('chat-runtime-stopped','cleanup-failed'),7:('chat-runtime-ready','none'),8:('chat-runtime-ready','none'),9:('chat-runtime-stopped','thread-unavailable'),10:('chat-runtime-stopped','invalid-metadata'),11:('chat-runtime-stopped','invalid-metadata'),12:('chat-runtime-stopped','api-missing'),13:('chat-runtime-limited','limits'),14:('chat-runtime-limited','limits'),15:('chat-runtime-stopped','invalid-metadata'),16:('chat-runtime-stopped','invalid-metadata')}
        assert (out['stage'],out['reason'])==expected[mode],(mode,out,c)
        if mode==0:
            cm=next(t for t in out['types'] if t['identity']['type']=='MessagesCM')
            parent=out['types'][cm['parent_index']]
            assert parent['identity']['type']=='ContentDataList`1'
            assert 'get_IsLoading' in [m['method'] for m in parent['methods']]
            base=out['types'][parent['parent_index']]
            assert 'get_Count' in [m['method'] for m in base['methods']]
            assert c['detaches']==1
        if mode==7:assert c['detaches']==0
        if mode==8:
            overlay=next(t for t in out['types'] if t['identity']['type']=='ProfileOverlayView')
            assert overlay['methods'][0]['owner_matches'] is False
        assert not any(s in json.dumps(out) for s in ('0x','PRIVATE','private-text','token'))
        print('Synthetic chat metadata',mode,out['stage'],out['reason'],flush=True)
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
    for mode in range(17):one(Path(sys.argv[1]).resolve(strict=True),mode)
    print('Metadata graph ABI passed; no Android chat/action claims.')
