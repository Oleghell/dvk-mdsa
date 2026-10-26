"""Bounded eight-item reading and task-local, numeric-only phase diagnostics."""
import json,threading,unittest
from unittest.mock import patch
import assistant_stage_timing as timing
from assistant_error_notify import diagnostic_json
import one_chat_device as device
import one_chat_probe as probe
import test_one_chat as chat

class ReadTiming(unittest.TestCase):
    def test_inactive_scope_is_noop_and_unknown_phase_is_rejected(self):
        with patch.object(timing,'perf_counter') as counter:
            with timing.read_phase('read_snapshot'):pass
        counter.assert_not_called()
        with self.assertRaises(ValueError):
            with timing.read_phase('PRIVATE'):pass

    def test_success_failure_nested_scope_and_restore_only_record_numbers(self):
        outer={};inner={};progress=[]
        with patch.object(timing,'perf_counter',side_effect=[1,1.5,2,2.25,3,4]):
            with timing.collect_read_timings(outer,progress.append):
                with timing.read_phase('read_setup'):pass
                with timing.collect_read_timings(inner,progress.append):
                    with self.assertRaises(RuntimeError):
                        with timing.read_phase('read_snapshot'):raise RuntimeError('PRIVATE')
                with timing.read_phase('read_cleanup'):pass
        self.assertEqual(outer,dict(read_setup_calls=1,read_setup_ms=500,read_cleanup_calls=1,read_cleanup_ms=1000))
        self.assertEqual(inner,dict(read_snapshot_calls=1,read_snapshot_ms=250))
        self.assertEqual(len(progress),3)
        self.assertNotIn('PRIVATE',json.dumps([outer,inner,progress]))
        with patch.object(timing,'perf_counter') as counter:
            with timing.read_phase('read_setup'):pass
        counter.assert_not_called()

    def test_advisory_progress_failure_cannot_skip_cleanup(self):
        diagnostics={};cleaned=[]
        def progress(_):raise RuntimeError('PRIVATE')
        with timing.collect_read_timings(diagnostics,progress):
            with timing.read_phase('read_cleanup'):cleaned.append(True)
        self.assertEqual(cleaned,[True])
        self.assertEqual(diagnostics['read_cleanup_calls'],1)
        self.assertNotIn('PRIVATE',json.dumps(diagnostics))

    def test_context_does_not_leak_into_another_worker_thread(self):
        diagnostics={}
        with timing.collect_read_timings(diagnostics,lambda _:None):
            thread=threading.Thread(target=lambda:self.unscoped_phase());thread.start();thread.join()
        self.assertEqual(diagnostics,{})
    def unscoped_phase(self):
        with timing.read_phase('read_connect'):pass

    def test_real_inspector_instrumentation_keeps_snapshot_private_and_cleans_up(self):
        fake=chat.Inspector().fake();diagnostics={};progress=[]
        with timing.collect_read_timings(diagnostics,progress.append):
            result=device.inspect(37149,'a'*64,lambda:False,chat.WHO,frida_api=fake)
        self.assertIn('PRIVATE TEST TEXT',result['messages'][0]['text'])
        for stage in ('read_connect','read_script','read_snapshot','read_cleanup'):
            self.assertEqual(diagnostics[stage+'_calls'],1)
            self.assertGreaterEqual(diagnostics[stage+'_ms'],0)
        self.assertTrue(fake.script_unloaded and fake.detached and fake.removed)
        self.assertNotIn('PRIVATE',json.dumps(diagnostics))
        safe=json.loads(diagnostic_json(dict(last_chat_diagnostics=dict(diagnostics,read_snapshot_text='PRIVATE'))))
        self.assertEqual(safe['diagnostic']['last_chat_diagnostics'],diagnostics)
        self.assertNotIn('PRIVATE',json.dumps(safe))

    def test_eight_items_still_use_original_frame_deadline_and_slow_getter_yield(self):
        source=probe.build(chat.WHO,scoped_traversal=True)
        for text in ('const chunkSize=8;','const deadline=Date.now()+100;',
                     'Math.max(1,cost||0)*2<=deadline-30','if(!canContinue(i,start,chunk.headerCost))break;',
                     'if(!canContinue(i,start,chunk.bodyCost))break;','sample_interval_ms:1000',
                     'JSON.stringify(state.sample)!==JSON.stringify(sample)','n.managed_calls>=60000'):
            self.assertIn(text,source)
        self.assertLess(source.index("if(chunk.localOwn>0&&chunk.peerAnchors===0)"),source.index('const value=call(s.messageText,message)'))
