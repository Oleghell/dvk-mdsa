"""Installer-only CI checks with bounded GitHub annotations."""
from pathlib import Path
import os
import unittest
suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent/'tests'),pattern='test_apk_installer.py')
result=unittest.TextTestRunner(verbosity=2).run(suite)
if os.environ.get('GITHUB_ACTIONS')=='true':
    for case,trace in result.failures+result.errors:
        value=(str(case)+'\n'+trace[-4000:]).replace('%','%25').replace('\r','%0D').replace('\n','%0A')
        print('::error::'+value,flush=True)
raise SystemExit(0 if result.wasSuccessful() else 1)
