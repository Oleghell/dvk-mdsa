"""Shard coverage is a multiset: no lost tests, no repeated module fixtures."""
import collections,unittest
from pathlib import Path
import run_unit_tests as runner

class Shards(unittest.TestCase):
    def examples(self):
        # Create private fixture classes; discovery must not run them itself.
        def cls(name,module):return type(name,(unittest.TestCase,),dict(__module__=module,runTest=lambda self:None))
        a,b,c=cls('Alpha','synthetic_a'),cls('Beta','synthetic_b'),cls('Gamma','synthetic_c')
        return [a(),a(),b(),c(),c(),c()]
    def test_full_multiset_preserved_including_duplicate_discovery(self):
        tests=self.examples()
        shards=runner.partition(unittest.TestSuite([unittest.TestSuite(tests[:2]),unittest.TestSuite(tests[2:])]),3)
        flat=[t for shard in shards for t in runner.cases(shard)]
        self.assertEqual(collections.Counter(map(id,flat)),collections.Counter(map(id,tests)))
        owners=collections.defaultdict(set)
        for index,shard in enumerate(shards):
            for case in runner.cases(shard):owners[type(case).__module__].add(index)
        self.assertTrue(all(len(value)==1 for value in owners.values()))
    def test_balanced_deterministic_module_assignment_not_python_hash(self):
        def assignment(tests):return [[type(t).__module__ for t in runner.cases(s)] for s in runner.partition(unittest.TestSuite(tests),3)]
        self.assertEqual(assignment(self.examples()),assignment(list(reversed(self.examples()))))
        self.assertEqual(sorted(map(len,assignment(self.examples()))),[1,2,3])
    def test_failed_import_is_kept_and_still_fails_its_shard(self):
        broken=unittest.TestLoader().loadTestsFromName('missing_ci_shard_synthetic_module')
        shards=runner.partition(broken,3)
        self.assertEqual(sum(s.countTestCases() for s in shards),1)
        result=unittest.TestResult()
        for shard in shards:shard.run(result)
        self.assertEqual(len(result.errors),1)
    def test_invalid_counts_rejected_and_extra_shards_are_explicitly_empty(self):
        for count in (0,-1,65,True,'3'):
            with self.assertRaises(ValueError):runner.partition(unittest.TestSuite(),count)
        self.assertEqual(sum(s.countTestCases() for s in runner.partition(unittest.TestSuite(self.examples()),8)),6)
    def test_release_requires_unit_native_and_package_checks(self):
        workflow=(Path(__file__).resolve().parents[2]/'.github/workflows/assistant.yml').read_text()
        self.assertIn('    - verify\n    - native\n    - package',workflow)
        self.assertIn('cancel-in-progress: true',workflow)
