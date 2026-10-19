"""Run synthetic unit tests and expose concise CI failure annotations."""
from pathlib import Path
import os
import sys
import unittest


def annotation(text):
    # Workflow command escaping, not HTML; never let a traceback create commands.
    return text.replace('%','%25').replace('\r','%0D').replace('\n','%0A')


def main():
    suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent/'tests'))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if os.environ.get('GITHUB_ACTIONS')=='true':
        for case,trace in result.failures+result.errors:
            print('::error::'+annotation(str(case)+'\n'+trace[-2500:]),flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    raise SystemExit(main())
