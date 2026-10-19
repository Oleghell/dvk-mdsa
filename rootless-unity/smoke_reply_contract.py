"""Actual C ABI on owned definitions. Never connects to Android or reads messages."""
from pathlib import Path
import subprocess
import sys
import frida
import reply_contract as p


def one(library, mode):
    child = subprocess.Popen([sys.executable, '-u', '-c',
        "import ctypes,sys,time\nl=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\n"
        "l.fixture_init(int(sys.argv[2]))\nprint('ready',flush=True)\ntime.sleep(120)",
        str(library), str(mode)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    session = script = None
    try:
        assert child.stdout.readline().strip() == 'ready'
        session = frida.get_local_device().attach(child.pid)
        script = session.create_script(p.FUNCTION + '''
          rpc.exports={probe(){return nativeMetadata();},counts(){
            const read=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();
            return {invokes:read('fixture_invokes'),values:read('fixture_values'),
              keeps:read('fixture_keeps'),attached:read('fixture_attached'),
              detaches:read('fixture_detaches'),lookups:read('fixture_lookups')};}};
        ''')
        script.load()
        out = p.validate(script.exports_sync.probe())
        counts = script.exports_sync.counts()
        assert counts['invokes'] == counts['values'] == counts['keeps'] == 0, counts
        assert counts['attached'] == (1 if mode in (10, 11) else 0), (mode, counts)
        assert counts['detaches'] == (0 if mode in (9, 11, 12) else 1), (mode, counts)
        assert counts['lookups'] <= len(p.ROOTS), counts
        if mode in (0, 11):
            assert out['stage'] == 'contract-ready', (mode, out)
        elif mode in (1, 2, 3, 4, 5, 6, 7, 14, 21):
            assert out['stage'] == 'contract-incomplete', (mode, out)
        else:
            assert out['stage'] == 'contract-stopped', (mode, out)
        if mode == 10:
            assert out['reason'] == 'cleanup-failed'
        if mode == 3:
            item = next(c for c in out['checks'] if c['label'] == 'history_item')
            assert item['return_type']['kind'] == 19 and item['status'] == 'return-type-mismatch'
        print('Synthetic narrow contract', mode, out['stage'], out['reason'],
              'calls', out['native_calls'], flush=True)
    finally:
        if script:
            script.unload()
        if session:
            session.detach()
        child.terminate()
        child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()


if __name__ == '__main__':
    library = Path(sys.argv[1]).resolve(strict=True)
    for mode in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 20, 21, 22):
        one(library, mode)
