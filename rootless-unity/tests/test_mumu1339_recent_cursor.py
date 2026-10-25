"""Position hints are circular priorities, never cached identity/authorization."""
import unittest
from unittest.mock import patch,MagicMock
import dialog_models as models
from test_inbox_profiles import WHO,nav


class CircularPosition(unittest.TestCase):
    def test_every_current_row_is_visited_once_even_after_shrink_or_reordering(self):
        for count in (0,1,2,17,50,120):
            end=min(count,50)
            for start in (0,1,29,49):
                indices=[end-1-((i+start)%end) for i in range(end)]
                self.assertEqual(set(indices),set(range(end)))
                self.assertEqual(len(indices),len(set(indices)))
        source=models.build(allowed=[WHO],recent_limit=50,reverse=True,start=29,needs_reply_only=True)
        for gate in ('const modelIndex=scanEnd-1-((state.scanIndex+modelStart)%scanEnd)',
                     'stableModels(current,manager,cm,count,modelIndex,chat)',
                     'const again=modelIdentity(chat)', 'headerOrSkip(chat,model.who)',
                     'n.private_model_scan.resume=n.action_completed&&n.chat_verified?state.scanResume:null'):
            self.assertIn(gate,source)
        self.assertNotIn('get_Text',source)

    def test_static_50_target_case_avoids_quadratic_prefix_rescanning(self):
        def checks(resume):
            remaining=set(range(50));start=0;total=0
            while remaining:
                for scanned in range(50):
                    index=49-((scanned+start)%50);total+=1
                    if index in remaining:
                        remaining.remove(index)
                        start=(start+scanned+1)%50 if resume else 0
                        break
            return total
        self.assertEqual(checks(False),1275)
        self.assertEqual(checks(True),50)  # Static positional simulation, not MuMu timing.

    def test_hint_is_private_bounded_and_mathematically_bound_to_completed_scan(self):
        def raw(resume=1):return dict(navigation=dict(rows_scanned=2,
            private_model_scan=dict(next=None,count=50,skipped_headers=0,budget_yields=0,resume=resume)))
        with patch.object(models.browser,'validate',return_value=nav('opened',WHO)) as validate:
            result,nxt=models.validate(raw(),recent_limit=50,reverse=True,start=49)
            self.assertIsNone(nxt);self.assertNotIn('private_model_scan',validate.call_args.args[0]['navigation'])
            for value in (True,-1,50,None,2,'PRIVATE'):
                with self.assertRaises(ValueError):models.validate(raw(value),recent_limit=50,reverse=True,start=49)
        for start in (True,-1,50,1.5,'1'):
            with self.assertRaises(ValueError):models.build(recent_limit=50,reverse=True,start=start)
        with self.assertRaises(ValueError):models.build(start=1)

    def test_instance_remembers_only_position_and_new_pass_resets(self):
        navigator=models.RecentNavigator(limit=50)
        starts=[]
        def perform(operation,*args,**kw):
            starts.append(kw['start'])
            if operation=='open':kw['position_observer'](17)
            return nav('opened',WHO) if operation=='open' else nav('returned',WHO)
        with patch.object(models,'perform',side_effect=perform):
            navigator('open','adb','folder',allowed=[WHO])
            navigator('back','adb','folder',expected=WHO)
            navigator('open','adb','folder',allowed=[WHO])
        self.assertEqual(starts,[0,17,17])
        self.assertEqual(models.RecentNavigator().position,0)
        self.assertEqual(set(vars(navigator)),{'progress','limit','position'})

    def test_observer_updates_only_after_capture_boot_recheck_and_cleanup_complete(self):
        raw=dict(navigation=dict(rows_scanned=2,private_model_scan=dict(
            next=None,count=50,skipped_headers=0,budget_yields=0,resume=1)))
        observer=MagicMock()
        def inspect(*args,validator,**kwargs):return validator(raw)
        def capture(*args,inspector,**kwargs):
            value=inspector(1234,'synthetic',lambda:False,None)
            if fail[0]:raise RuntimeError('boot recheck failed')
            return value
        fail=[True]
        with patch('search_online.inspect',side_effect=inspect),patch('one_chat_device.capture',side_effect=capture),patch.object(models.browser,'validate',return_value=nav('opened',WHO)):
            with self.assertRaises(RuntimeError):models.perform('open','adb','folder',recent_limit=50,reverse=True,start=49,position_observer=observer)
            observer.assert_not_called()
            fail[0]=False
            models.perform('open','adb','folder',recent_limit=50,reverse=True,start=49,position_observer=observer)
        observer.assert_called_once_with(1)
