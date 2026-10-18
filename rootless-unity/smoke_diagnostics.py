"""Run both diagnostic RPC methods only in an owned synthetic child, never Android."""
import sys
import frida
from diagnose_device import SCRIPT, validate_runtime, validate_modules
from module_evidence import validate_evidence


def main():
    device=frida.get_local_device();pid=session=script=None
    try:
        pid=device.spawn([sys.executable,'-c','import time; time.sleep(30)'])
        session=device.attach(pid)
        script=session.create_script(SCRIPT,name='owned-synthetic-diagnostics-smoke');script.load()
        runtime=validate_runtime(script.exports_sync.runtime())
        modules=validate_modules(script.exports_sync.modules())
        assert runtime['frida_version']=='17.24.1'
        assert modules['module_count']>0
        assert modules['fixed_modules']['libunity.so'] is False
        assert modules['fixed_modules']['libil2cpp.so'] is False
        evidence=validate_evidence(script.exports_sync.evidence())
        if sys.platform.startswith('linux'):
            assert evidence['maps_available'] and evidence['maps_complete'], evidence
            assert evidence['map_line_count']>0
        elif sys.platform=='win32':
            assert evidence['maps_available'] is False
        print('All fixed diagnostic RPC methods passed on owned synthetic child. NO Android compatibility claim.')
    finally:
        if script:
            try:script.unload()
            except Exception:pass
        if session:
            try:session.detach()
            except Exception:pass
        if pid:
            try:device.kill(pid)
            except Exception:pass


if __name__=='__main__':main()
