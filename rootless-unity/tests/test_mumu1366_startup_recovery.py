"""Reports 364-373: two new startup failure classes on the second installation.

1) profile-history-upload InvalidOperationError (7 of 10 ports): the script
loaded, runtime() passed, then the script was destroyed during the visited-
history upload RPC. root() was never invoked — no navigation, no authorization
thread, no journal write — the identical provably pre-execution state that
1.3.26 already retries for failed script-create transport.
2) cloud-database-lock-timeout on the inbox chat-read writer transaction
(2 of 10 ports): one FIFO waiter can meet a journal-initialization holder far
longer than 10s when two installations share one dataset; the advisory-lock
wait now uses the wider initialization budget and restores the bounded
timeouts for the transaction body. Synthetic only."""
import itertools,json,threading,unittest
from unittest.mock import MagicMock,patch

import one_chat_device as device
from assistant_setup_retry import retryable_profile_setup,SetupRetry
from test_mumu1315 import error_at
from test_mumu1326_setup_retry import setup_error,Clock
from test_one_chat import ReadTransport,WHO
from test_target_only import BOOT


class HistoryUploadRetryProof(unittest.TestCase):
    def test_destroyed_script_before_root_is_retryable_pre_execution(self):
        for kind in ('InvalidOperationError','TransportError','ServerNotRunningError','TimedOutError'):
            with self.subTest(kind=kind):
                self.assertTrue(retryable_profile_setup(setup_error('profile-history-upload',kind)))
    def test_authored_data_and_other_states_stay_blocked(self):
        for kind in ('StateError','RPCException','ProtocolError','RuntimeError','ValueError'):
            with self.subTest(kind=kind):
                self.assertFalse(retryable_profile_setup(setup_error('profile-history-upload',kind)))
        for stage in ('script-load','runtime-check','script-run','result-validation','gadget-attach'):
            self.assertFalse(retryable_profile_setup(setup_error(stage,'InvalidOperationError')))
        self.assertFalse(retryable_profile_setup(setup_error('profile-history-upload','InvalidOperationError',proof=False)))
    def test_upload_failure_keeps_script_create_rules_unchanged(self):
        for kind in ('InvalidOperationError','RPCException'):
            self.assertFalse(retryable_profile_setup(setup_error('script-create',kind)))
        for kind in ('TransportError','ServerNotRunningError','TimedOutError'):
            self.assertTrue(retryable_profile_setup(setup_error('script-create',kind)))


class HistoryUploadCaptureRetry(ReadTransport):
    def capture(self,reader,retry,cancel=lambda:False):
        with self.patched(),patch.object(device,'TargetOnlyAdb',return_value=self.adb),patch.object(device,'bundle_token',return_value='PRIVATE'):
            return device.capture('adb',self.folder,cancel,expected=WHO,inspector=reader,preexecution_retry=retry)
    def test_upload_transport_failures_repeat_inspector_with_backoff(self):
        self.identities=itertools.repeat(BOOT)
        errors=[setup_error('profile-history-upload','InvalidOperationError') for _ in range(3)]
        reader=MagicMock(side_effect=errors+[{'ok':True}]);delays=[]
        out=self.capture(reader,lambda e,n,d:delays.append(d) or False)
        self.assertEqual(out,{'ok':True});self.assertEqual(delays,[1,2,4])
        self.assertEqual(reader.call_count,4)
        self.assertTrue(all(c.args[3]==WHO for c in reader.call_args_list))
    def test_state_error_from_upload_is_not_retried(self):
        self.identities=itertools.repeat(BOOT)
        reader=MagicMock(side_effect=setup_error('profile-history-upload','StateError'))
        retry=MagicMock(return_value=False)
        with self.assertRaises(Exception):self.capture(reader,retry)
        reader.assert_called_once();retry.assert_not_called()


class LockWindowRestore(unittest.TestCase):
    def test_observer_reports_upload_stage_without_private_details(self):
        from types import SimpleNamespace
        clock=Clock();writes=[];notifier=MagicMock(return_value='unknown')
        o=SetupRetry(SimpleNamespace(errors_enabled=True),threading.Event(),
                     write=writes.append,notify=notifier,clock=clock,wait=clock.wait)
        self.assertFalse(o(setup_error('profile-history-upload','InvalidOperationError'),1,1))
        self.assertEqual(writes[0]['last_preparation_failure']['stage'],'profile-history-upload')
        self.assertIs(writes[0]['profile_script_executed'],False)
        self.assertIs(writes[0]['send_attempted'],False)
        self.assertNotIn('PRIVATE',json.dumps(writes[0]))
        o.completed();self.assertEqual(writes[-1]['status'],'reconnected')


class HistoryUploadInspect(unittest.TestCase):
    def test_destroyed_during_upload_is_proven_pre_execution_end_to_end(self):
        import assistant_pass as native
        from test_search_online import OnlineFake
        f=OnlineFake()
        destroyed=setup_error('profile-history-upload','InvalidOperationError')
        original=f.create_script
        def create(*args,**kwargs):
            value=original(*args,**kwargs)
            f.exports_sync.preparevisited=MagicMock(side_effect=destroyed)
            return value
        f.create_script=create
        store=MagicMock();store.visited_peers.return_value=['123']
        approve=MagicMock()
        with self.assertRaises(Exception) as raised:
            native.inspect(37149,'PRIVATE',lambda:False,'Hi',store,approve,frida_api=f)
        self.assertIs(raised.exception,destroyed)
        self.assertIs(destroyed._dvk_profile_not_executed,True)
        self.assertEqual(destroyed._dvk_failure['stage'],'profile-history-upload')
        self.assertEqual(destroyed._dvk_failure['error_type'],'InvalidOperationError')
        self.assertTrue(retryable_profile_setup(destroyed))
        approve.assert_not_called();store.reserve.assert_not_called();store.finish.assert_not_called()
        self.assertTrue(f.script_unloaded and f.detached and f.removed)


if __name__=='__main__':unittest.main()
