"""Real Frida/ABI checks on local synthetic objects, never Android."""
from pathlib import Path
import json
import queue
import subprocess
import sys
import threading
import frida
import one_chat_probe as p


def one(library, mode, expected=None):
    child=subprocess.Popen([sys.executable,'-u','-c',
      "import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\nfor _ in range(10000):\n lib.fixture_tick()\n time.sleep(.003)",
      str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(p.build(expected,scoped_traversal=True)+'''
        rpc.exports={root(){return probeUIKitRoot();},counts(){
          const get=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
          return {handles:get('fixture_handles'),bad:get('fixture_bad_frees'),off:get('fixture_off_thread_calls'),
          opens:get('fixture_opens'),closes:get('fixture_cancels'),sends:get('fixture_greeting_sends'),
          bodies:get('fixture_body_reads'),items:get('fixture_item_reads')};}};''')
        script.load()
        out=script.exports_sync.root()
        private=p.private_snapshot(out,expected)
        counts=script.exports_sync.counts()
        assert counts['handles']==counts['bad']==counts['off']==counts['opens']==counts['closes']==counts['sends']==0,(mode,out,counts)
        if expected is None and mode!=509:
            assert private==dict(identity=dict(account='100',peer='200',chat='300'),messages=None),(mode,out)
            assert counts['bodies']==counts['items']==0
        elif mode in (500,507,550,560,567,568) and expected['peer']=='200':
            assert private is not None,(mode,out,counts)
            assert len(private['messages'])==(0 if mode==507 else 2)
            if mode in (500,550,560,567,568):
                assert private['messages'][0 if mode==568 else 1]==dict(id='1002',sender='200',text='Reply')
        else:
            assert private is None,(mode,out,counts)
            if mode==551:
                assert out['navigation']['error']=='view-parent-depth-limit' and counts['bodies']==0,(mode,out,counts)
            if mode in (561,562,563,564,566):
                assert counts['bodies']==0,(mode,out,counts)
            if mode==564:
                assert out['navigation']['error']=='local-own-message-unanchored',(mode,out)
            if mode==565:
                assert out['navigation']['error'] in ('frame-limit','frame-budget','transition-timeout'),(mode,out)
            if 520<=mode<=531:
                label=['message-id','message-sender-id','message-chat-id','account-id','peer-id','chat-id'][(mode-520)//2]
                n=out['navigation']
                assert n['scalar_checkpoint']==label and n['scalar_state']==('zero' if mode%2==0 else 'negative'),(mode,out)
                expected_error='nonpositive-'+label if mode<526 else 'identity-not-bound'
                assert n['error']==expected_error,(mode,out)
                assert counts['bodies']==0,(mode,counts)
            if expected and expected['peer']=='201':
                assert counts['bodies']==counts['items']==0
        print('Synthetic one-chat',mode,'identity' if expected is None else 'read',out['navigation']['stage'],out['navigation']['error'],flush=True)
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
    lib=Path(sys.argv[1]).resolve(strict=True)
    one(lib,500)
    who=dict(account='100',peer='200',chat='300')
    for mode in (500,501,502,503,504,506,507,509,520,521,522,523,524,525,526,527,528,529,530,531,550,551,560,561,562,563,564,565,566,567,568):one(lib,mode,who)
    one(lib,500,dict(account='100',peer='201',chat='300'))
    print('Synthetic read-only ABI passed; live Android has not been tested.')
