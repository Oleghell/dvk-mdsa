"""Reports 449-454: every 1.3.68 port lost its LAST profile batch to a single
transient pooler-connect failure during the read-only shared-registry checks
(profile-peer-check, CloudDatabaseError cloud-database-unavailable/connect):
the cycle was cancelled cleanly with no send, but the whole pass stopped with
journal-error. 1.3.69 retries transport/capacity failures on the three
read-only pre-send reads (peer_claimed, peer_terminal, visited_peers) with a
short bounded budget; Stop and every other failure keep the hard cancel.
Synthetic only."""
import unittest
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import assistant_pass as native
from cloud_database import CloudDatabaseError
from test_assistant import pending
from test_search_online import OnlineFake

def transient():return CloudDatabaseError('cloud-database-unavailable')
def capacity():return CloudDatabaseError('cloud-database-capacity')
def permission():return CloudDatabaseError('cloud-database-permission')


class SharedRegistryRead(unittest.TestCase):
    def read(self,action,stopped=lambda:False,delays=None):
        pauses=[]
        value=native.shared_registry_read(action,stopped,delays=native.SHARED_READ_RETRY_DELAYS if delays is None else delays,pause=pauses.append)
        return value,pauses

    def test_transient_failure_is_retried_until_success(self):
        action=MagicMock(side_effect=[transient(),'ok'])
        value,pauses=self.read(action)
        self.assertEqual(value,'ok');self.assertEqual(action.call_count,2);self.assertEqual(pauses,[native.SHARED_READ_RETRY_DELAYS[0]])
    def test_capacity_failure_is_also_retried(self):
        action=MagicMock(side_effect=[capacity(),True])
        value,pauses=self.read(action)
        self.assertIs(value,True);self.assertEqual(pauses,[native.SHARED_READ_RETRY_DELAYS[0]])
    def test_exhaustion_reraises_after_the_full_budget(self):
        # 1.3.70 (reports 458-461): the widened window is 4 attempts with
        # pauses 2/5/10; exhaustion still re-raises the last transport error.
        action=MagicMock(side_effect=[transient() for _ in range(len(native.SHARED_READ_RETRY_DELAYS)+1)])
        with self.assertRaises(CloudDatabaseError) as raised:
            self.read(action)
        self.assertEqual(action.call_count,len(native.SHARED_READ_RETRY_DELAYS)+1)
        self.assertEqual(raised.exception.code,'cloud-database-unavailable')
    def test_non_transient_code_is_not_retried(self):
        action=MagicMock(side_effect=permission())
        with self.assertRaises(CloudDatabaseError):
            self.read(action)
        self.assertEqual(action.call_count,1)
    def test_non_cloud_error_is_not_retried(self):
        from assistant_store import StateError
        action=MagicMock(side_effect=StateError('authored'))
        with self.assertRaises(Exception):
            self.read(action)
        self.assertEqual(action.call_count,1)
    def test_stop_aborts_the_retry_without_pause(self):
        action=MagicMock(side_effect=[transient()])
        with self.assertRaises(CloudDatabaseError):
            self.read(action,stopped=lambda:True)
        self.assertEqual(action.call_count,1)


    def test_exhaustion_reraises_the_final_transport_error(self):
        # 1.3.71 (reports 468-470): the window spans 5 attempts (2/5/10/20) for
        # two-installation pooler pressure; exhaustion still re-raises the
        # last transport error with the exact pause sequence.
        self.assertEqual(native.SHARED_READ_RETRY_DELAYS,(2.0,5.0,10.0,20.0))
        action=MagicMock(side_effect=[transient() for _ in range(5)])
        pauses=[]
        with self.assertRaises(CloudDatabaseError):
            native.shared_registry_read(action,lambda:False,pause=pauses.append)
        self.assertEqual(action.call_count,5)
        self.assertEqual(pauses,[2.0,5.0,10.0,20.0])


class TransientPeerChecks(unittest.TestCase):
    def run_monitor(self,peer_claimed,peer_terminal=None,cancelled=lambda:False):
        script=MagicMock();script.exports_sync.cohortpending.return_value=pending()
        script.exports_sync.cohortack.return_value=True
        done=MagicMock();done.wait.return_value=False;done.is_set.return_value=False
        store=MagicMock();store.mumu_shared_claims=True
        store.peer_claimed=peer_claimed
        store.peer_terminal=peer_terminal if peer_terminal is not None else MagicMock(return_value=False)
        store.reserve=MagicMock(return_value=17)
        state={};failures=[]
        with patch.object(native,'SHARED_READ_RETRY_DELAYS',(0,0)):
            native.monitor(script,store,'Hi',lambda *a:True,done,cancelled,state,failures)
        return script,store,state,failures

    def test_peer_check_transient_failure_recovers_and_authorizes(self):
        peer_claimed=MagicMock(side_effect=[transient(),False])
        script,store,state,failures=self.run_monitor(peer_claimed)
        self.assertEqual(peer_claimed.call_count,2)
        self.assertFalse(failures);store.reserve.assert_called_once()
        script.exports_sync.cohortack.assert_called_once()
        script.exports_sync.cancel.assert_not_called()
        self.assertEqual(state['action_id'],17)
    def test_peer_check_exhaustion_cancels_cleanly_without_send(self):
        peer_claimed=MagicMock(side_effect=[transient() for _ in range(3)])
        script,store,state,failures=self.run_monitor(peer_claimed)
        self.assertEqual(peer_claimed.call_count,3)
        self.assertIsInstance(failures[0],CloudDatabaseError)
        self.assertEqual(state['authorization_checkpoint'],'profile-peer-check')
        script.exports_sync.cancel.assert_called_once()
        store.reserve.assert_not_called();script.exports_sync.cohortack.assert_not_called()
    def test_terminal_check_transient_failure_recovers_to_ack(self):
        peer_terminal=MagicMock(side_effect=[transient(),False])
        script,store,state,failures=self.run_monitor(MagicMock(return_value=False),peer_terminal)
        self.assertEqual(peer_terminal.call_count,2)
        self.assertFalse(failures)
        script.exports_sync.cohortack.assert_called_once();script.exports_sync.cancel.assert_not_called()
    def test_non_transient_peer_check_failure_does_not_retry(self):
        peer_claimed=MagicMock(side_effect=permission())
        script,store,state,failures=self.run_monitor(peer_claimed)
        self.assertEqual(peer_claimed.call_count,1)
        self.assertEqual(state['authorization_checkpoint'],'profile-peer-check')
        script.exports_sync.cancel.assert_called_once();store.reserve.assert_not_called()
    def test_stop_during_peer_check_retry_cancels(self):
        flag={'stop':False}
        def fail_then_stop(*args,**kwargs):
            flag['stop']=True;raise transient()
        script,store,state,failures=self.run_monitor(MagicMock(side_effect=fail_then_stop),
            cancelled=lambda:flag['stop'])
        self.assertEqual(state['authorization_checkpoint'],'profile-peer-check')
        script.exports_sync.cancel.assert_called_once();store.reserve.assert_not_called()


class SnapshotRead(unittest.TestCase):
    def run_inspect(self,visited):
        f=OnlineFake();original=f.create_script
        def create(*args,**kwargs):
            value=original(*args,**kwargs)
            f.exports_sync.preparevisited=MagicMock(return_value=True)
            return value
        f.create_script=create
        approve=MagicMock()
        store=MagicMock();store.visited_peers=visited
        try:
            native.inspect(37149,'PRIVATE',lambda:False,'Hi',store,approve,frida_api=f)
        except Exception as error:
            return error,f,store,approve
        raise AssertionError('inspect did not stop')

    def test_visited_snapshot_transient_failure_is_retried_in_place(self):
        visited=MagicMock(side_effect=[transient(),['123']])
        with patch.object(native,'SHARED_READ_RETRY_DELAYS',(0,0)):
            error,f,store,approve=self.run_inspect(visited)
        self.assertEqual(visited.call_count,2)
        self.assertIn(native.BOOTSTRAP_EXPORTS,f.script_source)
        store.reserve.assert_not_called()
    def test_visited_snapshot_non_transient_failure_stops_before_script(self):
        visited=MagicMock(side_effect=permission())
        error,f,store,approve=self.run_inspect(visited)
        self.assertEqual(visited.call_count,1)
        self.assertIsInstance(error,CloudDatabaseError)
        self.assertIs(error._dvk_profile_not_executed,True)
        self.assertEqual(error._dvk_preparation['stage'],'profile-history')
        self.assertFalse(hasattr(f,'script_source'))
    def test_reserve_and_other_writes_are_never_retried(self):
        source=(Path(__file__).resolve().parents[1]/'assistant_pass.py').read_text(encoding='utf-8')
        self.assertIn('shared_registry_read(lambda: store.visited_peers(), cancelled)',source)
        self.assertIn('lambda: store.peer_claimed(pending)',source)
        self.assertIn('lambda: store.peer_terminal(pending)',source)
        for write in ('shared_registry_read(lambda: store.reserve','shared_registry_read(lambda: store.finish'):
            self.assertNotIn(write,source)


if __name__=='__main__':unittest.main()
