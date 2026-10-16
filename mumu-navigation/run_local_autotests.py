"""Run local device-free regression tests; never commit or call GitHub."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest


def main():
    here=Path(__file__).resolve().parent
    sys.path.insert(0,str(here))
    out=here.parent/'out'/'local-autotests'
    out.mkdir(parents=True,exist_ok=True)
    suite=unittest.defaultTestLoader.discover(str(here/'tests'))
    with (out/'tests.log').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    report={'created_at':datetime.now(timezone.utc).isoformat(),
            'tests_run':result.testsRun,'failures':len(result.failures),
            'errors':len(result.errors),'skipped':len(result.skipped),
            'passed':result.wasSuccessful(),'real_device_tested':False}
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    raise SystemExit(main())
