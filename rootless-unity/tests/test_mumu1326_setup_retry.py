"""Uploaded script-create TransportErrors: no whole-pass restart or send replay."""
import itertools,json,threading,unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import assistant_pass as native
import one_chat_device as device
import assistant_profiles as profiles
from assistant_setup_retry import retryable_profile_setup,SetupRetry
from assistant_error_notify import diagnostic_json,notify_json
from startup_failure import record
from test_mumu1315 import error_at
from test_one_chat import ReadTransport,WHO
from test_target_only import BOOT,OTHER_BOOT
from test_search_online import OnlineFake
from test_device import TestError


def setup_error(stage='script-create',name='TransportError',proof=True):
    e=error_at(stage,name);e._dvk_profile_not_executed=proof;return e


class Proof(unittest.TestCase):
    def test_only_fixed_transport_stage_and_inspector_proof_may_repeat(self):
        for stage in ('script-create','script-load','script-run','result-validation','gadget-connect'):
            for kind in ('TransportError','TimedOutError','ServerNotRunningError','ProtocolError','RPCException','PermissionDeniedError','RuntimeError'):
                for proof in (False,True,1):
                    with self.subTest(stage=stage,kind=kind,proof=proof):
                        self.assertEqual(retryable_profile_setup(setup_error(stage,kind,proof)),
                            stage=='script-create' and kind in ('TransportError','TimedOutError','ServerNotRunningError') and proof is True)
    def test_actual_inspector_marks_only_create_before_load_and_authorization(self):
        for method,stage,expected in [('create_script','script-create',True),('load','script-load',False)]:
            f=OnlineFake();e=setup_error(stage,proof=True);setattr(f,method,MagicMock(side_effect=e))
            store=MagicMock();store.visited_peers.return_value=[];approve=MagicMock()
            with self.assertRaises(Exception) as raised:
                native.inspect(37149,'PRIVATE',lambda:False,'Hi',store,approve,frida_api=f)
            self.assertIs(raised.exception,e);self.assertIs(e._dvk_profile_not_executed,expected)
            self.assertEqual(retryable_profile_setup(e),expected)
            approve.assert_not_called();store.reserve.assert_not_called();store.finish.assert_not_called()
            self.assertTrue(f.detached and f.removed)
            if expected:self.assertFalse(f.script_unloaded) # no script handle existed
    def test_root_failure_cannot_reuse_stale_create_proof(self):
        f=OnlineFake();original=f.create_script;e=setup_error()
        def create(*args,**kwargs):
            value=original(*args,**kwargs);f.exports_sync.root=MagicMock(side_effect=e);return value
        f.create_script=create;store=MagicMock();store.visited_peers.return_value=[]
        with self.assertRaises(Exception):native.inspect(37149,'PRIVATE',lambda:False,'Hi',store,lambda *a:False,frida_api=f)
        self.assertIs(e._dvk_profile_not_executed,False);self.assertFalse(retryable_profile_setup(e))


class Capture(ReadTransport):
    def capture(self,reader,retry,cancel=lambda:False):
        with self.patched(),patch.object(device,'TargetOnlyAdb',return_value=self.adb),patch.object(device,'bundle_token',return_value='PRIVATE'):
            return device.capture('adb',self.folder,cancel,expected=WHO,inspector=reader,preexecution_retry=retry)
    def test_six_create_failures_one_cycle_then_success_same_boot_forward(self):
        self.identities=itertools.repeat(BOOT)
        read=MagicMock(side_effect=[setup_error() for _ in range(6)]+[{'ok':True}])
        delays=[];retry=lambda e,n,d:delays.append(d) or False
        self.assertEqual(self.capture(read,retry),{'ok':True})
        self.assertEqual(delays,[1,2,4,8,16,30]);self.assertEqual(read.call_count,7)
        self.assertEqual(len([x for x in self.calls if 'tcp:0' in x]),1)
        self.assertEqual(len([x for x in self.calls if '--remove' in x]),1)
        self.assertTrue(all(c.args[3]==WHO for c in read.call_args_list))
    def test_changed_boot_never_starts_second_script(self):
        self.identities=iter([BOOT,BOOT,OTHER_BOOT]);read=MagicMock(side_effect=setup_error())
        with self.assertRaises(TestError):self.capture(read,lambda *a:False)
        read.assert_called_once();self.assertEqual(len([x for x in self.calls if '--remove' in x]),1)
    def test_cancel_during_backoff_no_second_script_or_send(self):
        self.identities=itertools.repeat(BOOT);read=MagicMock(side_effect=setup_error())
        with self.assertRaises(device.ReadStopped) as raised:self.capture(read,lambda *a:True)
        self.assertEqual(str(raised.exception),'cancelled');self.assertIs(raised.exception._dvk_profile_not_executed,True)
        read.assert_called_once();self.assertEqual(len([x for x in self.calls if '--remove' in x]),1)
    def test_no_auto_retry_for_unproven_create_load_root_or_protocol(self):
        for error in (setup_error(proof=False),setup_error('script-load'),setup_error('script-run'),setup_error(name='ProtocolError')):
            self.identities=itertools.repeat(BOOT);reader=MagicMock(side_effect=error);retry=MagicMock(return_value=False)
            with self.assertRaises(Exception):self.capture(reader,retry)
            reader.assert_called_once();retry.assert_not_called()
    def test_without_explicit_callback_keep_legacy_bounded_behavior(self):
        self.identities=itertools.repeat(BOOT);reader=MagicMock(side_effect=setup_error())
        with self.assertRaises(Exception):self.run_capture(reader)
        reader.assert_called_once()


class Clock:
    def __init__(self):self.now=0
    def __call__(self):return self.now
    def wait(self,seconds):self.now+=seconds;return False

class Observe(unittest.TestCase):
    def observer(self,**kwargs):
        clock=Clock();stopped=threading.Event();writes=[];notifier=MagicMock(return_value='unknown')
        o=SetupRetry(SimpleNamespace(errors_enabled=True),stopped,write=writes.append,notify=notifier,clock=clock,wait=clock.wait,**kwargs)
        return o,clock,stopped,writes,notifier
    def test_backoff_keeps_work_and_sends_one_json_per_episode(self):
        o,clock,stop,writes,notifier=self.observer()
        for n in range(1,10):self.assertFalse(o(setup_error(),n,min(30,2**min(n-1,5))))
        self.assertEqual(notifier.call_count,1);self.assertEqual(len(writes),9)
        self.assertGreaterEqual(clock.now,100)
        for r in writes:
            self.assertIs(r['profile_script_executed'],False);self.assertIs(r['send_attempted'],False)
            self.assertEqual(r['last_preparation_failure']['stage'],'script-create')
            self.assertNotIn('PRIVATE',json.dumps(r))
        o.completed();self.assertEqual(writes[-1]['status'],'reconnected')
        self.assertEqual(notifier.call_count,1) # unknown TG delivery is NOT retried
    def test_error_delays_cancel_and_pause_are_cooperative(self):
        o,clock,stop,writes,n=self.observer()
        def cancel(seconds):stop.set();return True
        o.wait=cancel;self.assertTrue(o(setup_error(),1,1));self.assertEqual(n.call_count,0)
        from assistant_pause import PortResumed
        from mumu_pause import PauseGate
        gate=PauseGate(threading.Event());gate.restart_on_resume=True;gate.pause_checkpoint=MagicMock(return_value=True)
        o.stopped=gate
        with self.assertRaises(PortResumed):o(setup_error(),1,1)
    def test_separate_ports_do_not_share_retry_or_alert_state(self):
        a,*_=self.observer();b,_,_,_,alert=self.observer()
        a(setup_error(),3,4);self.assertFalse(b.alerted);self.assertEqual(b.attempts,0);alert.assert_not_called()
    def test_caption_and_cloud_diagnostics_do_not_claim_chat_was_skipped(self):
        o,_,_,_,_=self.observer();o(setup_error(),3,4);sender=MagicMock(return_value=True)
        self.assertEqual(notify_json(o.report('reconnecting',4),loader=lambda:('PRIVATE','PRIVATE'),sender=sender),'accepted')
        caption=sender.call_args.args[2]
        self.assertNotIn('Проблемный чат',caption);self.assertNotIn('пропускается',caption)
        raw=sender.call_args.args[3];self.assertNotIn(b'PRIVATE',raw)
        d=json.loads(raw)['diagnostic'];self.assertEqual(d['setup_retry_attempts'],3)
        self.assertIs(d['profile_script_executed'],False)
        bad=o.report('reconnecting');bad['profile_script_executed']=True
        self.assertEqual(notify_json(bad,loader=lambda:('x','x'),sender=sender),'not-needed')


class ProfilesIntegration(unittest.TestCase):
    def test_wait_does_not_restart_pass_or_clear_completed_cycles_and_journal(self):
        import os,tempfile
        from pathlib import Path
        from assistant_store import Store
        from test_inbox_profiles import Config,cycle_result
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/'db',Path(t)/'legacy');profiles.Session(store).set('city','Pskov')
            action=store.reserve(dict(attempt=1,account='100',peer='200',chat='300',variant=0),'Hi',approved=True)
            with store.connection() as db:before=db.execute('SELECT * FROM manual_actions').fetchall()
            captured=[];alerts=MagicMock();reports=[]
            def factory(settings,stop,progress):
                clock=Clock();return SetupRetry(settings,stop,progress,write=reports.append,notify=alerts,clock=clock,wait=clock.wait)
            def capture(*args,**kwargs):
                captured.append(1)
                if len(captured)==2:
                    for n in range(1,7):self.assertFalse(kwargs['preexecution_retry'](setup_error(),n,min(30,2**min(n-1,5))))
                return cycle_result(send_attempted=True,send_handler_returned=True)
            with patch.dict(os.environ,DVK_MUMU_MULTI='1'),patch('one_chat_device.capture',side_effect=capture),patch('assistant_setup_retry.SetupRetry',side_effect=factory):
                out=profiles.run(SimpleNamespace(adb='adb',folder=t,errors_enabled=True),threading.Event(),MagicMock(return_value=True),
                    store=store,config=Config(),limit=2)
            self.assertEqual(out['status'],'profiles-completed');self.assertEqual(out['qualified_profiles'],2)
            self.assertEqual(out['search_cycles'],2);self.assertEqual(out['handlers_returned'],2)
            self.assertFalse(out['send_attempts_unknown']);self.assertEqual(len(captured),2)
            self.assertEqual(alerts.call_count,1);self.assertEqual(reports[-1]['status'],'reconnected')
            with store.connection() as db:self.assertEqual(db.execute('SELECT * FROM manual_actions').fetchall(),before)
    def test_proven_pre_execution_error_is_not_an_unknown_send(self):
        import tempfile
        from pathlib import Path
        from assistant_store import Store
        from test_inbox_profiles import Config
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/'db',Path(t)/'legacy');profiles.Session(store).set('city','Pskov')
            out=profiles.walk(SimpleNamespace(adb='adb',folder=t,errors_enabled=False),threading.Event(),MagicMock(),lambda _:None,
                store,cycle=MagicMock(side_effect=setup_error(name='RuntimeError')),config=Config(),limit=1)
            self.assertEqual(out['status'],'profiles-stopped') # non-transient configuration stays blocked
            self.assertFalse(out['send_attempts_unknown']);self.assertEqual(out['send_attempts'],0)
