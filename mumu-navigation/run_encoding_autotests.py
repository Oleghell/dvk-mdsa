"""Exercise all device-free tests with legacy Windows cp1252 defaults.

Not a Windows emulator: this simulates implicit cp1252 file encoding and CRLF
text writes, even when the interpreter itself was started in UTF-8 mode.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


@contextmanager
def legacy_cp1252_io(*,windows_newlines=False):
    real_open=io.open
    def text_encoding(encoding,stacklevel=2):
        return 'cp1252' if encoding in (None,'locale') else encoding
    def windows_open(file,mode='r',buffering=-1,encoding=None,errors=None,
                     newline=None,closefd=True,opener=None):
        if 'b' not in mode:
            encoding=text_encoding(encoding)
            if windows_newlines and newline is None and any(c in mode for c in 'wax'):
                newline='\r\n'
        return real_open(file,mode,buffering,encoding,errors,newline,closefd,opener)
    with patch('io.text_encoding',text_encoding),patch('io.open',windows_open):
        yield


def main():
    here=Path(__file__).resolve().parent
    sys.path.insert(0,str(here))
    out=here.parent/'out'/'encoding-autotests';out.mkdir(parents=True,exist_ok=True)
    with (out/'tests.log').open('w',encoding='utf-8') as stream:
        with legacy_cp1252_io(windows_newlines=True):
            suite=unittest.defaultTestLoader.discover(str(here/'tests'))
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    report={'created_at':datetime.now(timezone.utc).isoformat(),
            'implicit_file_encoding':'cp1252','text_write_newline':'CRLF','tests_run':result.testsRun,
            'failures':len(result.failures),'errors':len(result.errors),
            'skipped':len(result.skipped),'passed':result.wasSuccessful(),
            'windows_runtime_tested':sys.platform=='win32','real_device_tested':False}
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    if not result.wasSuccessful():
        # Keep the summary small on success, but make failures visible in Actions.
        for test,traceback in result.failures+result.errors:
            print(f'\nFAILED TEST: {test}\n{traceback}',file=sys.stderr)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
