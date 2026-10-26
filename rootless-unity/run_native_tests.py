"""All release ABI suites; parallel independent fixture children, never Android.

Compile each fixture once. Separate Python processes isolate monkeypatches and
Frida managers; fixture libraries contain code, each child owns its mutable data.
Keep per-suite logs so one failure never hides another completed suite.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import os
import subprocess
import sys
import time

SUITES = (
 ('automatic_fixture', ('assistant_pass', 'mumu_claims')),
 ('profile_navigation_fixture', ('assistant_preview',)),
 ('search_online_fixture', ('search_online',)),
 ('search_city_fixture', ('search_city', 'search_city_state')),
 ('one_chat_fixture', ('one_chat', 'one_chat_send', 'one_chat_name')),
 ('dialog_navigation_fixture', ('dialog_navigation',)),
 ('dialog_browser_fixture', ('dialog_browser', 'contact_profile', 'dialog_models')),
)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,choices=range(1,5),default=3)
    args=parser.parse_args(argv)
    root=Path(__file__).resolve().parent
    logs=Path('native-test-logs').resolve();logs.mkdir(exist_ok=True)
    windows=os.name=='nt';suffix='.dll' if windows else '.so'
    tasks=[]
    for fixture,suites in SUITES:
        source=root/'fixtures'/(fixture+'.c');library=logs/(fixture+suffix)
        command=(['cl','/nologo','/LD','/Od','/std:c11',str(source),'/Fe:'+str(library)] if windows
            else ['cc','-shared','-fPIC','-O0','-pthread',str(source),'-o',str(library)])
        with (logs/(fixture+'-compile.log')).open('wb') as stream:
            subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        tasks.extend((suite,library) for suite in suites)
    # Schedule long suites first to avoid leaving one long tail on the last
    # worker. These are conservative local fixture weights, not time promises.
    priority=('assistant_pass','search_city','assistant_preview','one_chat',
              'dialog_browser','one_chat_name','one_chat_send','mumu_claims',
              'dialog_models','dialog_navigation','search_city_state','contact_profile','search_online')
    rank={name:index for index,name in enumerate(priority)}
    tasks.sort(key=lambda task:rank[task[0]])
    def run(task):
        suite,library=task;started=time.monotonic();path=logs/(suite+'.log')
        try:
            with path.open('wb') as stream:
                result=subprocess.run([sys.executable,str(root/('smoke_'+suite+'.py')),str(library)],
                    stdout=stream,stderr=subprocess.STDOUT,timeout=1200)
            ok=result.returncode==0
        except subprocess.TimeoutExpired:
            ok=False
        print(('PASS' if ok else 'FAIL')+f' {suite} ({time.monotonic()-started:.1f}s)',flush=True)
        if not ok:
            print(path.read_text(errors='replace')[-6000:],flush=True)
        return ok
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results=list(pool.map(run,tasks))
    return 0 if all(results) else 1


if __name__=='__main__':
    raise SystemExit(main())
