"""Reports 433-447: all 15 ports stopped at profile-history-upload with an
authored StateError because the production bootstrap wrapper dropped the
streaming final flag: piece #1 wrongly finalized (final===undefined), piece
#2 was rejected with assistantVisited already set. 1.3.68 forwards the second
RPC argument, and the bootstrap is now one module constant so smoke and this
suite exercise the exact string production runs. Synthetic only."""
import re,unittest
from pathlib import Path
from unittest.mock import MagicMock

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import assistant_pass as native
from test_search_online import OnlineFake


def run_inspect(visited,preparevisited):
    f=OnlineFake();original=f.create_script
    def create(*args,**kwargs):
        value=original(*args,**kwargs)
        f.exports_sync.preparevisited=preparevisited
        return value
    f.create_script=create
    approve=MagicMock()
    store=MagicMock();store.visited_peers.return_value=list(visited)
    try:
        native.inspect(37149,'PRIVATE',lambda:False,'Hi',store,approve,frida_api=f)
    except Exception as error:
        return error,store,approve,f
    raise AssertionError('inspect did not stop')


class BootstrapFinalFlag(unittest.TestCase):
    def test_bootstrap_forwards_the_streaming_final_flag(self):
        wrapper=re.search(r'preparevisited\(([^)]*)\)\{return assistantPrepareVisited\(([^)]*)\);\}',native.BOOTSTRAP_EXPORTS)
        self.assertIsNotNone(wrapper)
        self.assertEqual(wrapper.group(1),'values,final')
        self.assertEqual(wrapper.group(2),'values,final')
        self.assertNotIn('preparevisited(values){',native.BOOTSTRAP_EXPORTS)

    def test_bootstrap_keeps_every_production_export(self):
        for export in ('runtime(){','root(){return assistantPreparedRoot();}','cancel(){cancelNavigation();}',
                'selectedpeer(){return assistantSelectedPeer;}','cohortpending(){return cohortReservation();}',
                'cohortack(value){return cohortAcknowledge(value);}'):
            self.assertIn(export,native.BOOTSTRAP_EXPORTS)

    def test_inspect_builds_source_from_the_bootstrap_constant(self):
        module=(Path(__file__).resolve().parents[1]/'assistant_pass.py').read_text(encoding='utf-8')
        self.assertIn('source = prepared_source(text) + BOOTSTRAP_EXPORTS',module)
        self.assertNotIn("+ '''\nrpc.exports={runtime",module)

    def test_inspect_script_source_carries_the_forwarding_wrapper(self):
        recorder=MagicMock(return_value=True)
        error,store,approve,f=run_inspect([str(i) for i in range(1500)],recorder)
        self.assertIsNotNone(error)
        self.assertIn(native.BOOTSTRAP_EXPORTS,f.script_source)
        self.assertIn('preparevisited(values,final){return assistantPrepareVisited(values,final);}',f.script_source)
        self.assertNotIn('preparevisited(values){',f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)

    def test_state_machine_treats_false_as_non_final_and_null_padding_as_final(self):
        source=native.prepared_source('Synthetic hello')
        # false pieces accumulate; only undefined (plain call) or an explicit
        # true flag may freeze the visited set.
        self.assertIn('if(final===undefined||final===null||final===true){',source)
        self.assertIn('assistantVisitedParts.push(value);',source)
        self.assertIn('if(assistantVisited!==null||assistantRootStarted||!Array.isArray(values)||values.length>10000)return false;',source)

    def test_smoke_exercises_the_production_bootstrap_not_a_hand_copy(self):
        smoke=(Path(__file__).resolve().parents[1]/'smoke_assistant_pass.py').read_text(encoding='utf-8')
        self.assertGreaterEqual(smoke.count('manual.BOOTSTRAP_EXPORTS'),2)
        self.assertNotIn('rpc.exports={preparevisited',smoke)
        self.assertIn('exports_sync.cohortpending()',smoke)


if __name__=='__main__':unittest.main()
