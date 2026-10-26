"""Native ABI test of bound-only display-name reading on synthetic objects."""
from pathlib import Path
import queue
import subprocess
import sys
import threading
import frida
import one_chat_probe as reader

WHO = dict(account='100',peer='200',chat='300')


def one(library, mode, *, optional=False):
    child = subprocess.Popen([sys.executable,'-u','-c',
        'import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nprint("ready",flush=True)\nfor _ in range(10000):\n lib.fixture_tick()\n time.sleep(.003)',
        str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        q=queue.Queue()
        threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10)=='ready\n'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(reader.build(WHO,read_name=True,read_name_optional=optional,read_latest=optional,read_input=optional)+'''
        rpc.exports={root(){return probeUIKitRoot();},counts(){const get=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
          return {handles:get('fixture_handles'),bad:get('fixture_bad_frees'),off:get('fixture_off_thread_calls'),names:get('fixture_name_reads')};}};''')
        script.load()
        out=script.exports_sync.root()
        private=reader.private_snapshot(out,WHO,read_name=True,read_name_optional=optional,read_latest=optional,read_input=optional)
        counts=script.exports_sync.counts()
        assert counts['handles']==counts['bad']==counts['off']==0,(mode,counts)
        if mode==500:
            assert private is not None and private['peer_name']=='Анна'
            assert counts['names']>=2
        elif optional and mode in (540,541,543,544,545,546):
            assert private is not None and 'peer_name' not in private,(mode,out)
            assert len(private['messages'])==2 and private['input_enabled'] is True
            assert private['latest_message_id'] is None or private['latest_message_id'] in {m['id'] for m in private['messages']}
        else:
            assert private is None,(mode,out['navigation']['stage'])
        print('Bound name reader',mode,'ready' if private else 'stopped',flush=True)
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
    for mode in (500,540,541,542,543,544,545,546):
        one(Path(sys.argv[1]).resolve(strict=True),mode)
    for mode in (500,540,541,542,543,544,545,546,523,577):
        one(Path(sys.argv[1]).resolve(strict=True),mode,optional=True)
    print('Synthetic bound display-name tests passed; real MuMu is NOT verified.')
