"""No blind per-read warm-up; all stability and send gates remain mandatory."""
import itertools
import unittest
import chat_state_probe
import one_chat_probe
import one_chat_send
from test_one_chat import WHO, message


class ImmediateReadStart(unittest.TestCase):
    def assert_immediate(self, source):
        self.assertIn('waitAt:0,nextActionAt:Date.now(),stop:null', source)
        self.assertNotIn('waitAt:0,nextActionAt:Date.now()+1000,stop:null', source)
        self.assertIn('if(Date.now()<navState.nextActionAt)return;', source)
        # Still two FULL matching observations with the original 1000ms gap.
        self.assertIn('sample_interval_ms:1000', source)
        self.assertIn("n.samples=1;n.history_status='checking';n.message_count=null;state.nextActionAt=Date.now()+1000;return;", source)
        self.assertIn('JSON.stringify(state.sample)!==JSON.stringify(sample)', source)
        self.assertIn('if(state.waitSignature===signature&&Date.now()-state.waitAt>=1000)', source)
        self.assertIn("if(expectedIdentity!==null&&JSON.stringify(who)!==JSON.stringify(expectedIdentity))fail('identity-not-bound');", source)
        self.assertIn("const deadline=Date.now()+100;", source)
        self.assertIn('n.managed_calls>=60000', source)

    def test_all_fixed_bound_reader_variants_start_without_blind_sleep(self):
        for names, latest, inputs, scoped in itertools.product((False,True), repeat=4):
            with self.subTest(names=names, latest=latest, inputs=inputs, scoped=scoped):
                self.assert_immediate(one_chat_probe.build(WHO,read_name=names,
                    read_latest=latest,read_input=inputs,scoped_traversal=scoped))

    def test_identity_only_read_is_immediate_but_still_reads_no_bodies(self):
        source=one_chat_probe.build()
        self.assert_immediate(source)
        self.assertLess(source.index('if(expectedIdentity===null){'), source.index('const messages=[]'))
        self.assertIn('n.private_result={identity:who,messages:null}',source)

    def test_submission_inherits_only_start_optimization_not_weaker_gates(self):
        source=one_chat_send.build(dict(identity=WHO,messages=[message()]))
        self.assert_immediate(source)
        for gate in ('submission-snapshot-changed', 'oneSubmissionAttempted=true',
                     "if(!bool(s.input,chat))fail('input-disabled');",
                     "if(entry===s.submit&&Date.now()>deadline)fail('frame-budget');"):
            self.assertIn(gate,source)
        self.assertLess(source.index('canonical(messages)!==canonical('),source.index('call(s.submit,current,args)'))

    def test_generic_history_diagnostic_policy_is_unchanged(self):
        self.assertIn('waitAt:0,nextActionAt:Date.now()+1000,stop:null',chat_state_probe.FUNCTION)
