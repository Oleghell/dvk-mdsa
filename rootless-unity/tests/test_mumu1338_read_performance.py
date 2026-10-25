"""Adaptive frame batches and separate stage telemetry, without relaxed checks."""
import itertools
import json
import unittest
from unittest.mock import MagicMock, patch
import one_chat_probe as probe
import assistant_stage_timing as timing
from assistant_error_notify import diagnostic_json
from one_chat_device import ReadStopped
import test_guided_chain as guide


class Batches(unittest.TestCase):
    def test_all_bound_variants_use_budget_aware_batches_and_keep_full_checks(self):
        for name, latest, inputs in itertools.product((False,True),repeat=3):
            source=probe.build(guide.WHO,read_name=name,read_latest=latest,
                               read_input=inputs,scoped_traversal=True)
            self.assertIn('const chunkSize=4;',source)
            self.assertNotIn('const chunkSize=first<=16?1:4;',source)
            self.assertIn('Math.max(1,cost||0)*2<=deadline-30',source)
            self.assertIn('if(!canContinue(i,start,chunk.headerCost))break;',source)
            self.assertIn('if(!canContinue(i,start,chunk.bodyCost))break;',source)
            self.assertIn('chunk.headerCost=Math.max(chunk.headerCost||0,Date.now()-itemStarted)',source)
            self.assertIn('chunk.bodyCost=Math.max(chunk.bodyCost||0,Date.now()-itemStarted)',source)
            self.assertIn('const deadline=Date.now()+100;',source)
            self.assertIn('n.managed_calls>=60000',source)
            self.assertIn('JSON.stringify(state.sample)!==JSON.stringify(sample)',source)
            self.assertIn('sample_interval_ms:1000',source)
            self.assertLess(source.index('if(chunk.localOwn>0&&chunk.peerAnchors===0)'),
                            source.index('const value=call(s.messageText,message)'))

    def test_deadline_prediction_gives_fast_getters_a_batch_but_slow_ones_a_yield(self):
        # Equivalent pure arithmetic of the authored JS, not a wall-time claim.
        can=lambda now,cost:now+max(1,cost)*2<=100-30
        self.assertTrue(can(20,2))
        self.assertTrue(can(25,8))
        self.assertFalse(can(42,35))
        self.assertFalse(can(69,1))


class Timings(unittest.TestCase):
    def test_success_failure_and_separate_stages_are_measured_not_swallowed(self):
        diagnostics={}
        with patch.object(timing,'perf_counter',side_effect=[10,11.25,20,20.5,30,33]):
            self.assertEqual(timing.timed(diagnostics,'read',lambda:123),123)
            with self.assertRaisesRegex(RuntimeError,'PRIVATE'):
                timing.timed(diagnostics,'read',MagicMock(side_effect=RuntimeError('PRIVATE')))
            timing.timed(diagnostics,'proposal',lambda:None)
        self.assertEqual(diagnostics,dict(read_calls=2,read_ms=1750,proposal_calls=1,proposal_ms=3000))
        self.assertNotIn('PRIVATE',str(diagnostics))

    def test_unknown_stage_cannot_execute_operation(self):
        operation=MagicMock()
        with self.assertRaises(ValueError):timing.timed({},'PRIVATE_BODY',operation)
        operation.assert_not_called()

    def test_json_has_only_closed_duration_and_counter_fields(self):
        counters={key:12 for key in timing.FIELDS}
        value=dict(last_chat_diagnostics=dict(counters,private_text='PRIVATE',read_body_ms='PRIVATE',
                                              read_identity='100'))
        encoded=diagnostic_json(value)
        self.assertEqual(json.loads(encoded)['diagnostic']['last_chat_diagnostics'],counters)
        self.assertNotIn(b'PRIVATE',encoded)


class Flow(guide.WholeChain):
    def test_ai_wait_is_not_reported_as_read_and_callback_is_restored(self):
        before=guide.snapshot(('Привет',False))
        after=guide.snapshot(('Привет',False),('Как настроение?',True))
        self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
        self.chain.responder=MagicMock(return_value=dict(decision='reply',text='Как настроение?'))
        previous=MagicMock();self.chain.ai_progress=previous
        progress=[]
        out=self.walk([before,before,after],until_waiting=True,progress=progress.append)
        self.assertEqual(out['reason'],'wait-mood')
        self.assertEqual(len(self.sent),1)
        self.assertIn('Ожидаю ответ ИИ • история уже прочитана.',progress)
        self.assertLess(progress.index('Читаю историю • проверяю текущий чат.'),
                        progress.index('Ожидаю ответ ИИ • история уже прочитана.'))
        self.assertIs(self.chain.ai_progress,previous);previous.assert_not_called()
        diagnostics=out['diagnostics']
        self.assertEqual(diagnostics['read_calls'],3)
        self.assertEqual(diagnostics['pacing_calls'],1)
        self.assertEqual(diagnostics['submit_calls'],1)
        self.assertGreaterEqual(diagnostics['proposal_calls'],2)
        for stage in ('read','proposal','pacing','submit'):
            self.assertGreaterEqual(diagnostics[stage+'_ms'],0)

    def test_failed_read_still_counts_attempt_and_restores_callback_without_send(self):
        previous=MagicMock();self.chain.ai_progress=previous
        out=self.walk([ReadStopped('identity-changed')])
        self.assertEqual(out['reason'],'bound-chat-read-failed')
        self.assertEqual(out['diagnostics']['read_calls'],1)
        self.assertFalse(self.sent)
        self.assertIs(self.chain.ai_progress,previous)


for name in dir(guide.WholeChain):
    if name.startswith('test_') and name not in Flow.__dict__:setattr(Flow,name,None)
