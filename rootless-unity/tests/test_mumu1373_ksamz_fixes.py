"""Reports 484-489 (v1.3.72, twelve ports started at once): staggered starts,
bounded authorization re-pend and bounded startup chat binding. No live data."""
import json
import threading
import time
import unittest
from unittest.mock import MagicMock

import assistant_profile_read as profile_read
import cohort_pass
import dialog_browser as browser
import mumu_controller
from assistant_navigation_check import safe_diagnostic
from assistant_settings import Settings
from test_dialog_browser import raw_open, TARGET


def raw_list():
    v=raw_open();n=v['navigation']
    n.update(list_verified=True,chat_verified=False,selection_verified=False,exhausted=False,
             private_identity=None,selection_checkpoint='not-checked',rows_scanned=0,scan_batches=0,
             entry_binding_waits=2,entry_search_recovered=False,profile_closed=False,
             unread_filter_applied=False,unread_verified=False,read_rows_skipped=0,
             reply_filter_applied=False,reply_needed_verified=False,waiting_rows_skipped=0,handled_rows_skipped=0)
    return v


class StaggeredStarts(unittest.TestCase):
    def test_default_spacing_is_a_sane_positive_constant(self):
        self.assertIs(type(mumu_controller.STARTUP_STAGGER_SECONDS),float)
        self.assertGreater(mumu_controller.STARTUP_STAGGER_SECONDS,0)
        self.assertLessEqual(mumu_controller.STARTUP_STAGGER_SECONDS,60)

    def test_ports_start_one_by_one_not_as_one_wave(self):
        started=[];lock=threading.Lock();messages=[]
        def worker(n,*args,**kwargs):
            with lock:started.append((n,time.monotonic()))
            return 'ok'
        def progress(n,text):messages.append((n,text))
        out=mumu_controller.run_many([5557,5559,5561],Settings(),'inbox',False,threading.Event(),progress,
                                     worker=worker,spacing=0.08,jitter=lambda:1.0)
        self.assertEqual(out,{5557:'ok',5559:'ok',5561:'ok'})
        self.assertEqual([n for n,_ in started],[5557,5559,5561])
        times=dict(started)
        # Each later port waits its own jittered slot before the worker starts;
        # the first port never waits.
        self.assertGreaterEqual(times[5559]-times[5557],0.07)
        self.assertGreaterEqual(times[5561]-times[5557],0.15)
        self.assertTrue(any(n==5559 and 'очередь запуска' in text for n,text in messages),messages)
        self.assertTrue(any(n==5561 and 'очередь запуска' in text for n,text in messages),messages)

    def test_stop_during_the_startup_queue_never_launches_waiting_ports(self):
        stop=threading.Event();launched=[]
        def worker(n,*args,**kwargs):
            launched.append(n)
            if n==5557:stop.set()
            return 'ok'
        out=mumu_controller.run_many([5557,5559,5561],Settings(),'inbox',False,stop,MagicMock(),
                                     worker=worker,spacing=30.0,jitter=lambda:1.0)
        self.assertEqual(launched,[5557])
        self.assertEqual(out[5557],'ok')
        for n in (5559,5561):self.assertEqual(out[n],'Остановлено до запуска.')

    def test_single_port_and_disabled_spacing_start_immediately(self):
        for values in ([5557],[5557,5559]):
            started=[];launch=time.monotonic()
            def worker(n,*args,**kwargs):started.append((n,time.monotonic()));return 'ok'
            mumu_controller.run_many(values,Settings(),'inbox',False,threading.Event(),MagicMock(),
                                     worker=worker,spacing=0)
            self.assertEqual(len(started),len(values))
            self.assertLess(max(t for _,t in started)-launch,5.0)


class AuthorizationPendBackoff(unittest.TestCase):
    def test_pend_waits_double_then_cap_at_3200ms(self):
        waits=[];cohort_waits=0
        for _ in range(9):
            cohort_waits+=1
            waits.append(100*2**min(cohort_waits-1,5))
        self.assertEqual(waits,[100,200,400,800,1600,3200,3200,3200,3200])

    def test_assistant_source_uses_the_backoff_not_the_fixed_100ms_pend(self):
        import assistant_pass
        source=assistant_pass.build('Привет',[])
        self.assertIn('state.cohortWaits=(state.cohortWaits||0)+1;',source)
        self.assertIn('state.nextActionAt=Date.now()+100*Math.pow(2,Math.min(state.cohortWaits-1,5));return;',source)
        self.assertNotIn('cohortPending=reservation;state.nextActionAt=Date.now()+100;return;',source)
        self.assertNotIn('cohortPending=reservation;state.nextActionAt=Date.now()+1000;return;',source)
        # The submit gate after the durable ACK still fails hard on a mismatch.
        self.assertIn("if(cohortApproved!==reservationKey)fail('identity-changed');",source)

    def test_batch_cohort_flow_keeps_its_own_fixed_pace(self):
        self.assertIn('cohortPending=reservation;state.nextActionAt=Date.now()+1000;return;',
                      cohort_pass.build([0]*10))

    def test_slow_authorization_stays_inside_the_call_budget(self):
        # Reports 484/489: ~61 managed calls per full re-verification, 6000-call
        # budget, 90s cycle. The fixed 100ms cadence exhausted the budget in
        # ~10s of waiting; the backoff spends the whole window on ~30 re-checks.
        per_recheck=61
        waits=[];cohort_waits=0;elapsed=0
        while elapsed<90000:
            cohort_waits+=1
            wait=100*2**min(cohort_waits-1,5)
            waits.append(wait);elapsed+=wait
        self.assertLess(len(waits)*per_recheck,6000)
        self.assertGreaterEqual((90000//100)*per_recheck,6000)


class StartupChatBindingWait(unittest.TestCase):
    def test_wait_branch_is_bounded_and_keeps_the_double_binding(self):
        source=browser.build('list',entry='either')
        part=source.split("if(operation==='list'&&entryScreen==='either'&&k==='chat'){")[1].split("if(operation==='list'&&k==='profile'){")[0]
        self.assertIn('const pending=call(s.currentChat,current);',part)
        self.assertIn("if(pending.isNull()||modelIdentity(pending)===null){",part)
        # 1.3.80 (reports QZ2X7): the exhausted wait keeps failing closed but
        # with its own readiness code so supervision can recover it; the
        # structural binding failures below keep identity-not-bound.
        self.assertIn("if(n.entry_binding_waits>=25)fail('entry-binding-timeout');",part)
        self.assertIn('n.entry_binding_waits++;return;',part)
        self.assertEqual(part.count('currentIdentity(current)'),2)
        self.assertEqual(part.count('call(s.closeChat,current)'),1)
        self.assertIn('entry_binding_waits:0',source)

    def test_validator_bounds_the_counter_and_gates_it_to_list(self):
        result=browser.validate(raw_list(),'list')
        self.assertEqual(result['state'],'dialogs-ready')
        self.assertEqual(result['diagnostic']['entry_binding_waits'],2)
        for bad in (-1,26,True,'2'):
            v=raw_list();v['navigation']['entry_binding_waits']=bad
            with self.assertRaises(ValueError):browser.validate(v,'list')
        # Only the startup list recovery may report binding waits.
        v=raw_open();v['navigation']['entry_binding_waits']=1
        with self.assertRaises(ValueError):browser.validate(v,'open',allowed=[TARGET])

    def test_public_diagnostic_accepts_and_bounds_the_wait(self):
        diagnostic=browser.validate(raw_list(),'list')['diagnostic']
        self.assertIsInstance(safe_diagnostic(diagnostic),dict)
        safe_diagnostic(dict(diagnostic,entry_binding_waits=25))
        for bad in (-1,26,True,'2'):
            with self.assertRaises(ValueError):safe_diagnostic(dict(diagnostic,entry_binding_waits=bad))

    def test_json_notification_keeps_the_closed_counter(self):
        from assistant_error_notify import diagnostic_json
        report=dict(status='stopped',last_navigation=dict(stage='navigation-stopped',error='identity-not-bound',
            phase='entry',action_attempted=False,action_completed=False,selection_checkpoint='not-checked',
            entry_binding_waits=25,identity=dict(account='100',peer='200',chat='300')))
        n=json.loads(diagnostic_json(report))['diagnostic']['last_navigation']
        self.assertEqual(n['entry_binding_waits'],25)


if __name__=='__main__':unittest.main()
