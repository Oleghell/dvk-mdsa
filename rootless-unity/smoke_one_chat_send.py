"""Real Frida sender ABI tests on synthetic objects only, never Android."""
from pathlib import Path
import queue
import subprocess
import sys
import threading
import frida
from unittest.mock import patch
import one_chat_send_device as transport
import one_chat_send as sender
from conversation_engine import QUESTIONS, CONTACT_TEXT
from assistant_contact_clarify import TEXT as CLARIFY_TEXT

WHO=dict(account='100',peer='200',chat='300')
BEFORE=dict(identity=WHO,messages=[dict(id='1001',sender='100',text='Hello'),dict(id='1002',sender='200',text='Reply')])


def one(library,mode,before=None,*,text=QUESTIONS[0]):
    sender.checked_reply(text)
    before=before or BEFORE
    child=subprocess.Popen([sys.executable,'-u','-c',
      "import ctypes,sys,time\nlib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nlib.fixture_init(int(sys.argv[2]))\nlib.fixture_expected_reply.argtypes=[ctypes.c_char_p]\nlib.fixture_expected_reply(bytes.fromhex(sys.argv[3]))\nprint('ready',flush=True)\nfor _ in range(10000):\n lib.fixture_tick()\n time.sleep(.003)",str(library),str(mode),text.encode('utf-8').hex()],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        q=queue.Queue();threading.Thread(target=lambda:q.put(child.stdout.readline()),daemon=True).start()
        assert q.get(timeout=10).strip()=='ready'
        session=frida.get_local_device().attach(child.pid)
        def capture(adb, folder, cancelled, expected, *, inspector):
            assert expected == before['identity']
            return inspector(12345, 'synthetic-owned-fixture', cancelled, expected)
        def inspect(port, token, cancelled, snapshot, *, text):
            assert snapshot == before
            return sender.build(snapshot, text=text)
        # Only the ADB/arm64 attach boundary is replaced: submit's real validation
        # and exact text forwarding feed the real native Frida ABI below.
        with patch.object(transport, 'capture', side_effect=capture), patch.object(transport, 'inspect_submission', side_effect=inspect):
            source = transport.submit('synthetic-adb', 'owned-fixture', before, text=text)
        script=session.create_script(source+'''
        rpc.exports={root(){return probeUIKitRoot();},counts(){const get=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
          return {handles:get('fixture_handles'),bad:get('fixture_bad_frees'),off:get('fixture_off_thread_calls'),
          sends:get('fixture_greeting_sends'),wrong:get('fixture_greeting_bad'),opens:get('fixture_opens'),closes:get('fixture_cancels')};}};''')
        script.load();out=script.exports_sync.root()
        result=sender.validate(out,before);diag=sender.diagnostic(out);counts=script.exports_sync.counts()
        assert sender.input_disabled_before_submission(dict(result,native_check=diag)) is (mode==602),(mode,diag)
        assert counts['handles']==counts['bad']==counts['off']==counts['wrong']==counts['opens']==counts['closes']==0,(mode,out,counts)
        expected_send=mode in (600,603,650) and before==BEFORE
        assert counts['sends']==int(expected_send),(mode,out,counts)
        assert result['attempted']==expected_send,(mode,out,counts)
        assert result['handler_returned']==(expected_send and mode!=603),(mode,out,counts)
        if expected_send:
            again=sender.validate(script.exports_sync.root(),before)
            assert not again['attempted'] and script.exports_sync.counts()['sends']==1,(mode,again)
        print('Synthetic manual send',mode,out['navigation']['error'],counts['sends'],flush=True)
        return result
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


def ai_chain(library):
    """Durable AI draft -> authorization -> REAL transport gate -> native invocation."""
    import copy
    import tempfile
    from threading import Event
    from unittest.mock import MagicMock
    from assistant_store import Store
    from assistant_guided_chain import GuidedChain, walk
    from assistant_authorization import RunAuthorization
    text = 'Взаимно 🙂 Как настроение?'
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = Store(root/'assistant.sqlite3', root/'old')
        model = MagicMock(return_value=dict(decision='reply', text=text))
        chain = GuidedChain(store, responder=model, seal=lambda b:b, unseal=lambda b:b)
        chain.bind(dict(identity=WHO, messages=[BEFORE['messages'][0]]), ('Hello',), approved=True)
        after = copy.deepcopy(BEFORE)
        after['messages'].append(dict(id='1003', sender='100', text=text))
        stop = Event()
        reads = MagicMock(side_effect=[BEFORE, BEFORE, after, after])
        sent = []
        def send(snapshot, draft):
            sent.append(draft)
            return one(library, 600, snapshot, text=draft)
        result = walk(chain, WHO, stop, RunAuthorization(stop), reads, send,
                      approved=True, greetings=('Hello',), pause=lambda _:False,
                      max_polls=8, until_waiting=True)
        assert result['status']=='chain-waiting' and result['stage']=='wait-mood', result
        assert result['handler_returns']==result['outgoing_observed_this_run']==1, result
        assert sent == [text] and model.call_count == 1
        again = walk(chain, WHO, stop, RunAuthorization(stop), lambda _:after, send,
                     approved=True, greetings=('Hello',), pause=lambda _:False,
                     max_polls=8, until_waiting=True)
        assert again['submission_calls']==0 and sent==[text] and model.call_count==1, again
        print('Durable AI chain -> real submit gate -> native send -> observed -> no resend: passed', flush=True)


if __name__=='__main__':
    library=Path(sys.argv[1]).resolve(strict=True)
    for mode in (600,602,603,604,605,606,501,502,503,506,520,521,650,651):one(library,mode)
    one(library,600,dict(identity=dict(WHO,peer='201'),messages=[BEFORE['messages'][0],dict(BEFORE['messages'][1],sender='201')]))
    one(library,600,dict(identity=WHO,messages=[dict(BEFORE['messages'][0],text='changed'),BEFORE['messages'][1]]))
    for text in (QUESTIONS[1],CONTACT_TEXT,CLARIFY_TEXT,'Хорошо, по какому номеру тебя найти в WhatsApp?'):one(library,600,text=text)
    one(library,603,text=CONTACT_TEXT)
    for text in ('Взаимно 🙂 Как настроение?', 'Понимаю. Обменяемся Telegram?', 'Ты написал «Привет». Как дела?'):
        one(library,600,text=text)
    one(library,603,text='Взаимно 🙂 Как дела?')
    ai_chain(library)
    print('Synthetic manual-send and whitelisted reply ABI passed. Real recipient delivery is NOT verified.')
