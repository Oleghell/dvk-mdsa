"""Reports 410-432: profile-history-upload InvalidOperationError on 22 of 22
ports, exhausting every 1.3.66 pre-execution retry.

The shared greeting registry backfill grew each port's visited snapshot to
~9510 peers, so the whole history left as ONE ~120KB frida RPC. On the MuMu
gadget transport that large request destroyed the session every time, while
small RPCs on the same session always passed. 1.3.67 (a) streams the snapshot
in bounded 1000-entry pieces with an explicit final flag and (b) bounds the
snapshot itself: the port's own journals stay complete, only the shared
host-authoritative sources take a recency slice. Synthetic only."""
import sqlite3,unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import MagicMock

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import assistant_pass as native
from assistant_setup_retry import retryable_profile_setup
from mumu_store import SharedStore
from test_assistant import pending
from test_mumu1326_setup_retry import setup_error
from test_search_online import OnlineFake

BASE=datetime(2026,1,1)


class ChunkedHistoryUpload(unittest.TestCase):
    def run_inspect(self,visited,preparevisited,approve=None):
        f=OnlineFake();original=f.create_script
        def create(*args,**kwargs):
            value=original(*args,**kwargs)
            f.exports_sync.preparevisited=preparevisited
            return value
        f.create_script=create
        store=MagicMock();store.visited_peers.return_value=list(visited)
        approve=approve or MagicMock()
        try:
            native.inspect(37149,'PRIVATE',lambda:False,'Hi',store,approve,frida_api=f)
        except Exception as error:
            return error,store,approve,f
        raise AssertionError('inspect did not stop')

    def test_large_history_streams_bounded_pieces_with_final_flag(self):
        recorder=MagicMock(side_effect=[True]*10)
        error,store,approve,f=self.run_inspect([str(i) for i in range(2501)],recorder)
        calls=recorder.call_args_list
        self.assertEqual([len(c.args[0]) for c in calls],[1000,1000,501])
        self.assertEqual([c.args[1] for c in calls],[False,False,True])
        self.assertTrue(all(len(piece)<1001 for piece in (c.args[0] for c in calls)))
        store.reserve.assert_not_called();store.finish.assert_not_called()
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_single_piece_keeps_the_original_one_argument_call(self):
        recorder=MagicMock(return_value=True)
        self.run_inspect(['123'],recorder)
        recorder.assert_called_once_with(['123'])
    def test_empty_history_keeps_one_empty_call(self):
        recorder=MagicMock(return_value=True)
        self.run_inspect([],recorder)
        recorder.assert_called_once_with([])
    def test_destroyed_mid_stream_stays_pre_execution_retryable(self):
        destroyed=setup_error('profile-history-upload','InvalidOperationError')
        recorder=MagicMock(side_effect=[True,destroyed])
        error,store,approve,f=self.run_inspect([str(i) for i in range(1500)],recorder)
        self.assertIs(error,destroyed)
        self.assertEqual(recorder.call_args_list[0].args[1],False)
        self.assertIs(destroyed._dvk_profile_not_executed,True)
        self.assertEqual(destroyed._dvk_failure['stage'],'profile-history-upload')
        self.assertTrue(retryable_profile_setup(destroyed))
        store.reserve.assert_not_called();store.finish.assert_not_called()
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_authored_rejection_mid_stream_is_not_retried(self):
        recorder=MagicMock(side_effect=[True,False])
        error,store,approve,f=self.run_inspect([str(i) for i in range(1500)],recorder)
        self.assertIsInstance(error,native.StateError)
        self.assertEqual(str(error),'profile-history-not-prepared')
        self.assertEqual(recorder.call_count,2)
        self.assertEqual(error._dvk_failure['stage'],'profile-history-upload')
        self.assertIs(error._dvk_profile_not_executed,True)
        self.assertFalse(retryable_profile_setup(error))
        store.reserve.assert_not_called()


class BoundedSharedSnapshot(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'assistant.sqlite3';self.legacy=Path(self.tmp.name)/'old'
        self.port=5557
    def store(self):return SharedStore(self.path,self.legacy,device_port=self.port)
    def raw(self):
        db=sqlite3.connect(self.path)
        self.addCleanup(db.close)
        return db

    def insert(self,db,table,peers,*,start=0,step=1,with_time=True):
        for offset,peer in enumerate(peers):
            stamp=(BASE+timedelta(seconds=start+offset*step)).strftime('%Y-%m-%d %H:%M:%S')
            if table=='mumu_greeting_claims':db.execute('INSERT OR IGNORE INTO mumu_greeting_claims(peer,device,account,created_at) VALUES(?,?,?,?)',(peer,'1:5557','101',stamp))
            elif table=='mumu_peer_blocks':db.execute('INSERT OR IGNORE INTO mumu_peer_blocks(peer,reason,device,account,chat,created_at) VALUES(?,?,?,?,?,?)',(peer,'contact-refused','1:5557','101','c'+peer,stamp))
            elif table=='profile_visits':db.execute('INSERT OR IGNORE INTO m'+str(self.port)+'__profile_visits(peer,friends_count,history_status,checked_at) VALUES(?,10,?,?)',(peer,'read',stamp))
            elif table=='manual_actions':db.execute('INSERT OR IGNORE INTO m'+str(self.port)+'__manual_actions(account,peer,initial_chat,text_hash,confirmed,status,created_at) VALUES(?,?,?,?,1,?,?)',('101',peer,'c','x'*64,'reserved-unknown',stamp))

    def test_shared_claims_upload_completely_when_they_fit(self):
        # 1.3.78: the whole registry (12,220 live claims, ~+1,000/day) uploads;
        # a claim invisible to the pre-filter used to cost a full
        # open-profile/open-chat cycle before the host peer-check skipped the
        # peer as already greeted ("просмотрено 20, отправлено 0").
        store=self.store()
        db=self.raw();self.insert(db,'mumu_greeting_claims',[str(5000000000+i) for i in range(2500)])
        db.commit()
        visited=set(store.visited_peers())
        self.assertEqual(len(visited),2500)
        self.assertTrue(all(str(5000000000+i) in visited for i in range(2500)))
    def test_own_journals_stay_complete_regardless_of_age(self):
        store=self.store()
        db=self.raw()
        self.insert(db,'profile_visits',[str(6000000000+i) for i in range(1300)])
        self.insert(db,'manual_actions',[str(7000000000+i) for i in range(900)])
        db.commit()
        visited=set(store.visited_peers())
        self.assertTrue(all(str(6000000000+i) in visited for i in range(1300)))
        self.assertTrue(all(str(7000000000+i) in visited for i in range(900)))
    def test_shared_blocks_upload_completely_and_dedup(self):
        store=self.store()
        db=self.raw()
        self.insert(db,'mumu_peer_blocks',[str(8000000000+i) for i in range(700)])
        self.insert(db,'profile_visits',['8000000500'])
        db.commit()
        visited=store.visited_peers();unique=set(visited)
        self.assertEqual(len(visited),len(unique))
        self.assertTrue(all(str(8000000000+i) in unique for i in range(700)))
        self.assertEqual(len(unique),700)
    def test_small_history_membership_unchanged(self):
        store=self.store()
        action=store.reserve(pending(),'Hi',approved=True)
        store.finish(action,dict(send_attempted=False,send_handler_returned=False))
        visited=store.visited_peers()
        self.assertIn(pending()['peer'],visited)
        self.assertEqual(len(visited),len(set(visited)))


if __name__=='__main__':unittest.main()
