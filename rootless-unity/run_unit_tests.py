"""Synthetic unit tests, deterministic module shards and concise CI failures.

Each shard imports the same discovery tree, but executes whole modules in only
one shard. Test/class/module fixtures stay together; no tests are filtered out by
name, platform, speed or a previous green result.
"""
from pathlib import Path
from collections import defaultdict
import argparse
import json
import os
import sys
import time
import unittest


def annotation(text):
    # Workflow command escaping, not HTML; never let a traceback create commands.
    return text.replace('%','%25').replace('\r','%0D').replace('\n','%0A')


def cases(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from cases(item)
        else:yield item


def partition(suite,count):
    """Greedy module-level balancing by discovered count; stable tie breaks.

    Keep duplicate discoveries too: the partition must preserve the exact input
    multiset, including failed imports and tests inherited from other modules.
    """
    if type(count) is not int or not 1<=count<=64:raise ValueError('Invalid shard count')
    groups=defaultdict(list)
    for test in cases(suite):groups[type(test).__module__].append(test)
    buckets=[[] for _ in range(count)];loads=[0]*count
    for module,items in sorted(groups.items(),key=lambda pair:(-len(pair[1]),pair[0])):
        index=min(range(count),key=lambda i:(loads[i],i))
        buckets[index].append((module,items));loads[index]+=len(items)
    return [unittest.TestSuite(test for _,items in sorted(bucket) for test in items) for bucket in buckets]


class TimedResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.modules=defaultdict(lambda:dict(tests=0,seconds=0.0))
    def startTest(self,test):
        self._started=time.perf_counter();super().startTest(test)
    def stopTest(self,test):
        value=self.modules[type(test).__module__]
        value['tests']+=1;value['seconds']+=time.perf_counter()-self._started
        super().stopTest(test)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shard-count',type=int,default=1,choices=range(1,65))
    parser.add_argument('--shard-index',type=int,default=0)
    args=parser.parse_args(argv)
    if not 0<=args.shard_index<args.shard_count:parser.error('shard-index must be less than shard-count and nonnegative')
    suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent/'tests'))
    total=suite.countTestCases()
    if args.shard_count>1:suite=partition(suite,args.shard_count)[args.shard_index]
    print(f'Unit shard {args.shard_index+1}/{args.shard_count}: {suite.countTestCases()} of {total} discovered tests',flush=True)
    result=unittest.TextTestRunner(verbosity=2,resultclass=TimedResult).run(suite)
    print('Slowest modules in this shard:',flush=True)
    for name,value in sorted(result.modules.items(),key=lambda pair:(-pair[1]['seconds'],pair[0]))[:8]:
        print(f"  {name}: {value['seconds']:.2f}s / {value['tests']} tests",flush=True)
    if os.environ.get('GITHUB_ACTIONS')=='true':
        directory=Path('unit-test-logs');directory.mkdir(exist_ok=True)
        value=dict(shard_index=args.shard_index,shard_count=args.shard_count,discovered=total,
                   executed=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                   skipped=len(result.skipped),modules=dict(result.modules))
        (directory/f'{sys.platform}-{args.shard_index}.json').write_text(json.dumps(value,sort_keys=True,indent=2),encoding='utf-8')
        for case,trace in result.failures+result.errors:
            print('::error::'+annotation(str(case)+'\n'+trace[-2500:]),flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    raise SystemExit(main())
