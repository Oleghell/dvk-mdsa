"""Compile/run the fixed metadata probe in an owned synthetic Python child, never MuMu."""
import sys
import frida
from test_device import PROBE_SCRIPT, EXPORTS


def main():
    device=frida.get_local_device()
    pid=session=script=None
    try:
        pid=device.spawn([sys.executable,'-c','import time; time.sleep(30)'])
        session=device.attach(pid)
        script=session.create_script(PROBE_SCRIPT,name='synthetic-metadata-probe-smoke')
        script.load()
        result=script.exports_sync.probe()
        assert result['frida_version']=='17.24.1'
        assert result['arch'] in ('x64','ia32','arm64')
        assert result['platform'] in ('linux','windows','darwin')
        assert result['unity_loaded'] is False and result['il2cpp_loaded'] is False
        assert result['il2cpp_exports']=={n:False for n in EXPORTS}
        # Validate the instance API even though this synthetic child does not load IL2CPP.
        check=session.create_script('rpc.exports={check(){return typeof Process.enumerateModules()[0].findExportByName === "function";}};')
        check.load()
        assert check.exports_sync.check() is True
        check.unload()
        print('Fixed Frida metadata script executed successfully on synthetic child; NO Android/Gadget runtime claim.')
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
