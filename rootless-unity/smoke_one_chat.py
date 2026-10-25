"""Real Frida/ABI checks on local synthetic objects, never Android."""
from pathlib import Path
import json
import queue
import subprocess
import sys
import threading
import frida
import one_chat_probe as p


def one(library, mode, expected=None, *, read_latest=False, read_name=False, read_input=False):
    child=subprocess.Popen([sys.executable,'-u','-c',
      "import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\nfor _ in range(10000):\n lib.fixture_tick()\n time.sleep(.003)",
      str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        source=p.build(expected,scoped_traversal=True,read_latest=read_latest,read_name=read_name,read_input=read_input)
        if mode in (583,584):
            # Controlled native getter delay plus final identity-check overhead.
            # This is synthetic timing, not a claim about a live device's speed.
            source=source.replace('if(chunk.headers.length<first){verifyWho();return;}',
                'if(chunk.headers.length<first){{const until=Date.now()+40;while(Date.now()<until){}}verifyWho();return;}')
        if mode==584:
            source=source.replace('if(!canContinue(i,start,chunk.headerCost))break;', 'if(i>start&&Date.now()>deadline-30)break;')
            source=source.replace('if(!canContinue(i,start,chunk.bodyCost))break;', 'if(i>start&&Date.now()>deadline-30)break;')
        script=session.create_script(source+'''
        rpc.exports={root(){return probeUIKitRoot();},counts(){
          const get=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
          return {handles:get('fixture_handles'),bad:get('fixture_bad_frees'),off:get('fixture_off_thread_calls'),
          opens:get('fixture_opens'),closes:get('fixture_cancels'),sends:get('fixture_greeting_sends'),
          bodies:get('fixture_body_reads'),items:get('fixture_item_reads')};}};''')
        script.load()
        out=script.exports_sync.root()
        private=p.private_snapshot(out,expected,read_latest=read_latest,read_name=read_name,read_input=read_input)
        counts=script.exports_sync.counts()
        assert counts['handles']==counts['bad']==counts['off']==counts['opens']==counts['closes']==counts['sends']==0,(mode,out,counts)
        if expected is None and mode!=509:
            assert private==dict(identity=dict(account='100',peer='200',chat='300'),messages=None),(mode,out)
            assert counts['bodies']==counts['items']==0
        elif mode in (579,580,581):
            assert private is not None,(mode,out,counts)
            assert private['latest_message_id']==(None if mode==581 else '1001' if mode==580 else '1002'),(mode,out,counts)
            assert len(private['messages'])==2
        elif mode in (570,571,572,575,583,585,586):
            assert private is not None,(mode,out,counts)
            assert len(private['messages'])==(6 if mode==583 else 16 if mode in (585,586) else 65 if mode==575 else 18),(mode,out)
            assert [x['id'] for x in private['messages']]==[str(1001+i) for i in range(6 if mode==583 else 16 if mode in (585,586) else 65 if mode==575 else 18)]
            assert all(x['text']=='Reply' for x in private['messages'][1:])
        elif (mode in (500,507,550,560,567,568) or mode==602 and read_input) and expected['peer']=='200':
            assert private is not None,(mode,out,counts)
            assert len(private['messages'])==(0 if mode==507 else 2)
            if mode in (500,550,560,567,568):
                assert private['messages'][0 if mode==568 else 1]==dict(id='1002',sender='200',text='Reply')
        else:
            assert private is None,(mode,out,counts)
            if mode==584:
                assert out['navigation']['error']=='frame-budget',(mode,out,counts)
            if mode==551:
                assert out['navigation']['error']=='view-parent-depth-limit' and counts['bodies']==0,(mode,out,counts)
            if mode in (561,562,563,564,566,573,574,587):
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
        if mode in (577,578):
            from assistant_history_wait import verified_loading
            n=out['navigation']
            assert n['read_checkpoint']=='last-message' and verified_loading(n),(mode,out,counts)
            assert n['wait_reason']==('history-loading' if mode==577 else 'history-not-loaded'),(mode,out)
            assert private is None and counts['bodies']==counts['items']==counts['sends']==0,(mode,counts)
        if mode==576:
            from assistant_history_wait import verified_read_budget
            n=out['navigation']
            assert n['read_checkpoint']=='sample' and n['error']=='frame-budget' and verified_read_budget(n),(mode,{k:n[k] for k in ('read_checkpoint','error','scalar_checkpoint','scalar_state','identity_checkpoint')})
            assert private is None and counts['sends']==0,(mode,counts)
        if read_input and private is not None:
            assert private['input_enabled'] is (mode!=602),(mode,out,counts)
        timing_counts=dict(frames=out['navigation']['frames'],managed_calls=out['navigation']['managed_calls'],samples=out['navigation']['samples'])
        print('Synthetic one-chat',mode,'identity' if expected is None else 'read',out['navigation']['stage'],out['navigation']['error'],flush=True)
        return timing_counts
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
    for mode in (500,602):
        for names in (False,True):
            one(lib,mode,dict(account='100',peer='200',chat='300'),read_input=True,read_latest=True,read_name=names)
    who=dict(account='100',peer='200',chat='300')
    for mode in (500,501,502,503,504,506,507,509,520,521,522,523,524,525,526,527,528,529,530,531,550,551,560,561,562,563,564,565,566,567,568,570,571,572,573,574,575,576,577,578,583,584,585,586,587):one(lib,mode,who)
    for mode in (579,580,581,582):one(lib,mode,who,read_latest=True)
    one(lib,579,who,read_latest=True,read_name=True)
    one(lib,500,dict(account='100',peer='201',chat='300'))
    print('Synthetic read-only ABI passed; live Android has not been tested.')
