"""Real Frida sender ABI tests on synthetic objects only, never Android."""
from pathlib import Path
import queue
import subprocess
import sys
import threading
import frida
import one_chat_send as sender
from conversation_engine import QUESTIONS, CONTACT_TEXT

WHO=dict(account='100',peer='200',chat='300')
BEFORE=dict(identity=WHO,messages=[dict(id='1001',sender='100',text='Hello'),dict(id='1002',sender='200',text='Reply')])


def one(library,mode,before=None,*,text=QUESTIONS[0]):
    variant=(*QUESTIONS,CONTACT_TEXT).index(text)
    before=before or BEFORE
    child=subprocess.Popen([sys.executable,'-u','-c',
      "import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nlib.fixture_reply_variant(int(sys.argv[3]))\nprint('ready',flush=True)\nfor _ in range(10000):\n lib.fixture_tick()\n time.sleep(.003)",str(library),str(mode),str(variant)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        script=session.create_script(sender.build(before,text=text)+'''
        rpc.exports={root(){return probeUIKitRoot();},counts(){const get=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
          return {handles:get('fixture_handles'),bad:get('fixture_bad_frees'),off:get('fixture_off_thread_calls'),
          sends:get('fixture_greeting_sends'),wrong:get('fixture_greeting_bad'),opens:get('fixture_opens'),closes:get('fixture_cancels')};}};''')
        script.load();out=script.exports_sync.root()
        result=sender.validate(out,before);sender.diagnostic(out);counts=script.exports_sync.counts()
        assert counts['handles']==counts['bad']==counts['off']==counts['wrong']==counts['opens']==counts['closes']==0,(mode,out,counts)
        expected_send=mode in (600,603,650) and before==BEFORE
        assert counts['sends']==int(expected_send),(mode,out,counts)
        assert result['attempted']==expected_send,(mode,out,counts)
        assert result['handler_returned']==(expected_send and mode!=603),(mode,out,counts)
        if expected_send:
            again=sender.validate(script.exports_sync.root(),before)
            assert not again['attempted'] and script.exports_sync.counts()['sends']==1,(mode,again)
        print('Synthetic manual send',mode,out['navigation']['error'],counts['sends'],flush=True)
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
    library=Path(sys.argv[1]).resolve(strict=True)
    for mode in (600,602,603,604,605,606,501,502,503,506,520,521,650,651):one(library,mode)
    one(library,600,dict(identity=dict(WHO,peer='201'),messages=[BEFORE['messages'][0],dict(BEFORE['messages'][1],sender='201')]))
    one(library,600,dict(identity=WHO,messages=[dict(BEFORE['messages'][0],text='changed'),BEFORE['messages'][1]]))
    for text in (QUESTIONS[1],CONTACT_TEXT):one(library,600,text=text)
    one(library,603,text=CONTACT_TEXT)
    print('Synthetic manual-send and whitelisted reply ABI passed. Real recipient delivery is NOT verified.')
