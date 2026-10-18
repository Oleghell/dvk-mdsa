"""Exercise the exact IL2CPP metadata bindings against a synthetic C ABI library."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import frida
from native_metadata import NATIVE_FUNCTION, validate_metadata


def one(library,mode):
    code='''import ctypes,sys,time
lib=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)
lib.fixture_set_mode(int(sys.argv[2]))
print('ready',flush=True)
time.sleep(45)
'''
    child=subprocess.Popen([sys.executable,'-u','-c',code,str(library),str(mode)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    session=script=None
    try:
        ready=queue.Queue()
        threading.Thread(target=lambda:ready.put(child.stdout.readline()),daemon=True).start()
        assert ready.get(timeout=10).strip()=='ready','Synthetic child could not load fixture'
        session=frida.get_local_device().attach(child.pid)
        source="'use strict';\n"+NATIVE_FUNCTION+"\nrpc.exports={probe(){return nativeMetadata();},attached(){return new NativeFunction(Module.getGlobalExportByName('fixture_is_attached'),'int',[])();}};"
        script=session.create_script(source,name='synthetic-native-metadata-smoke');script.load()
        value=validate_metadata(script.exports_sync.probe())
        expected={0:'metadata-ready',1:'domain-not-ready',2:'unsafe-assembly-count',3:'assemblies-not-ready',4:'metadata-ready'}[mode]
        assert value['stage']==expected,value
        assert script.exports_sync.attached()==(1 if mode==4 else 0),value
        if mode==0:
            assert value['assembly_count']==4 and value['assemblies_scanned']==4
            assert value['known_types']['UnityEngine.UI.Button'] is True
            assert value['known_types']['UnityEngine.UI.InputField'] is False
            assert value['known_methods']['UnityEngine.UI.Button.get_onClick/0'] is True
            assert value['known_methods']['UnityEngine.Resources.FindObjectsOfTypeAll/1'] is True
            assert value['thread_attach_performed'] and value['thread_detach_confirmed']
        if mode==4:
            assert value['current_thread_initially_attached'] is True
            assert not value['thread_attach_performed'] and not value['thread_detach_confirmed']
        text=json.dumps(value)
        assert 'PRIVATE_UNKNOWN_ASSEMBLY' not in text
        return expected
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


def main():
    library=Path(sys.argv[1]).resolve(strict=True)
    for mode in (0,1,2,3,4):print('Synthetic C ABI case',mode,one(library,mode))
    print('Native bindings and thread cleanup passed on owned synthetic process; NO Android/ARM translation claim.')


if __name__=='__main__':main()
