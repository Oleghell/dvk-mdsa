"""188: host finalization preserves native evidence, never replays sends."""
import json, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import assistant_pass as native
from assistant_store import StateError
from test_assistant import pending
from test_chat_batch import cycle
from test_search_online import OnlineFake
from cloud_database import CloudDatabaseError


def result(send=False):
    value=cycle(count=0 if send else 1)
    value['navigation'].update(cycle_timeout_ms=90000, profile_read_budget_retries=0,
                               profile_ready_waits=0,greeting_frame_splits=1 if send else 0)
    return native.validate(value)

class Drain(unittest.TestCase):
    def test_real_authorization_taking_longer_than_old_two_seconds_finishes(self):
        done=threading.Event();complete=[]
        def commit():
            done.wait();time.sleep(2.1);complete.append(True)
        thread=threading.Thread(target=commit);thread.start()
        native.drain_threads([thread],done)
        self.assertEqual(complete,[True]);self.assertFalse(thread.is_alive())
    def test_one_deadline_not_per_thread_and_pending_stays_blocked(self):
        one=MagicMock();two=MagicMock();one.is_alive.return_value=False;two.is_alive.return_value=True
        clock=iter([0,3,29]);done=threading.Event()
        with self.assertRaisesRegex(StateError,'profile-authorization-pending'):
            native.drain_threads([one,two],done,clock=lambda:next(clock))
        one.join.assert_called_once_with(timeout=27);two.join.assert_called_once_with(timeout=1)
        self.assertTrue(done.is_set())
        from mumu_recovery import BLOCK_CODES
        self.assertIn('profile-authorization-pending',BLOCK_CODES)

class Monitor(unittest.TestCase):
    def test_original_database_failure_has_closed_phase_not_private_exception_in_state(self):
        script=MagicMock();script.exports_sync.cohortpending.return_value=pending()
        store=MagicMock();error=CloudDatabaseError('cloud-database-lock-timeout');error.operation='lock'
        store.reserve.side_effect=error;state={};failures=[]
        native.monitor(script,store,'Hi',lambda *a:True,threading.Event(),lambda:False,state,failures)
        self.assertIs(failures[0],error)
        self.assertEqual(error._dvk_preparation['stage'],'profile-reserve')
        self.assertEqual(error._dvk_preparation['database']['operation'],'lock')
        json.dumps(state);script.exports_sync.cohortack.assert_not_called()
        script.exports_sync.cancel.assert_called_once()
    def test_operation_end_is_not_user_decline(self):
        script=MagicMock();script.exports_sync.cohortpending.return_value=pending()
        store=MagicMock();done=threading.Event();state={}
        def approve(*args):done.set();return False
        native.monitor(script,store,'Hi',approve,done,lambda:False,state)
        self.assertNotIn('declined',state);store.reserve.assert_not_called()
        script.exports_sync.cohortack.assert_not_called()

class Inspector(unittest.TestCase):
    def inspect_error(self,value,error,*,finish=False,monitor=None):
        f=OnlineFake();create=f.create_script;store=MagicMock();store.visited_peers.return_value=[]
        store.record_visit.side_effect=None if finish else error
        if finish:store.finish.side_effect=error
        def created(*a,**kw):
            out=create(*a,**kw);f.exports_sync.root=lambda:value
            f.exports_sync.selectedpeer=lambda:'200';f.exports_sync.cohortpending=lambda:None
            return out
        f.create_script=created
        def normal_monitor(script,s,text,approve,done,cancel,state,failures):
            state['action_id']=1
        with patch.object(native,'monitor',side_effect=monitor or normal_monitor):
            with self.assertRaises(type(error)) as caught:
                native.inspect(37149,'PRIVATE_TOKEN',lambda:False,'Hi',store,MagicMock(),frida_api=f)
        return caught.exception,store
    def test_visit_failure_retains_valid_no_send_evidence(self):
        error,store=self.inspect_error(result(),StateError('PRIVATE'))
        self.assertEqual(error._dvk_failure['stage'],'profile-record-visit')
        self.assertTrue(error._dvk_profile_no_send_verified)
        self.assertFalse(error._dvk_profile_diagnostics['send_attempted'])
        self.assertNotIn('200',json.dumps(error._dvk_profile_diagnostics))
        store.reserve.assert_not_called();store.finish.assert_not_called()
    def test_finish_failure_after_handler_return_never_claims_no_send(self):
        error,store=self.inspect_error(result(True),StateError('PRIVATE'),finish=True)
        self.assertEqual(error._dvk_failure['stage'],'profile-finish-journal')
        self.assertFalse(error._dvk_profile_no_send_verified)
        self.assertTrue(error._dvk_profile_diagnostics['send_handler_returned'])
        store.finish.assert_called_once();store.reserve.assert_not_called()
    def test_finish_database_error_retains_closed_code_operation_and_send_uncertainty(self):
        failure=CloudDatabaseError('cloud-database-query-timeout');failure.operation='commit'
        error,store=self.inspect_error(result(True),failure,finish=True)
        self.assertEqual(error._dvk_preparation['stage'],'profile-finish-journal')
        self.assertEqual(error._dvk_preparation['database']['operation'],'commit')
        self.assertFalse(error._dvk_profile_no_send_verified);store.finish.assert_called_once()
    def test_unvalidated_result_has_no_no_send_proof(self):
        raw=result();raw['navigation']['send_attempted']='false'
        error,_=self.inspect_error(raw,ValueError('unused'))
        self.assertEqual(error._dvk_failure['stage'],'result-validation')
        self.assertFalse(hasattr(error,'_dvk_profile_no_send_verified'))
        self.assertFalse(hasattr(error,'_dvk_profile_diagnostics'))
    def test_original_monitor_exception_reaches_host_with_database_code(self):
        error=CloudDatabaseError('cloud-database-lock-timeout');error.operation='lock'
        def monitor(script,store,text,approve,done,cancel,state,failures):
            from run_preparation import record
            record(error,'profile-reserve');failures.append(error)
            state['authorization_checkpoint']='profile-reserve'
        # Avoid an unrelated visit failure, so the monitor's original object is raised.
        f=OnlineFake();create=f.create_script;store=MagicMock();store.visited_peers.return_value=[]
        def created(*a,**kw):
            out=create(*a,**kw);f.exports_sync.root=lambda:result()
            f.exports_sync.selectedpeer=lambda:None;return out
        f.create_script=created
        with patch.object(native,'monitor',side_effect=monitor),self.assertRaises(CloudDatabaseError) as caught:
            native.inspect(37149,'TOKEN',lambda:False,'Hi',store,MagicMock(),frida_api=f)
        self.assertIs(caught.exception,error)
        self.assertEqual(error._dvk_preparation['stage'],'profile-reserve')
        self.assertEqual(error._dvk_failure['stage'],'profile-authorization')
        self.assertTrue(error._dvk_profile_no_send_verified)

class Prechecks(unittest.TestCase):
    def test_readonly_checks_do_not_take_writer_lock_but_reserve_still_deduplicates(self):
        from mumu_store import SharedStore,connect,SharedPeerClaimed
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'db';s=SharedStore(path,device_port=5567);other=SharedStore(path,device_port=5569);sql=[]
            def traced(*a,**kw):
                db=connect(*a,**kw);db.set_trace_callback(sql.append);return db
            with patch('mumu_store.connect',side_effect=traced):
                self.assertFalse(s.peer_claimed(pending()));self.assertFalse(s.peer_terminal(pending()))
            self.assertIn('BEGIN',sql);self.assertFalse(any('IMMEDIATE' in q or 'CREATE' in q for q in sql))
            s.reserve(pending(),'Hi',approved=True)
            self.assertTrue(other.peer_claimed(pending()));self.assertFalse(other.peer_terminal(pending()))
            with self.assertRaises(SharedPeerClaimed):other.reserve(pending(),'Hi',approved=True)

from test_inbox_profiles import Base,Config
class ProfileReport(Base):
    def test_only_verified_no_send_avoids_unknown_and_preserves_closed_fields(self):
        import assistant_profiles as profiles
        profiles.Session(self.store).set('city','Псков')
        for no_send in (False,True):
            error=StateError('PRIVATE');error._dvk_profile_no_send_verified=no_send
            error._dvk_profile_diagnostics={'send_attempted':not no_send,'send_handler_returned':False}
            call=MagicMock(side_effect=error)
            out=profiles.walk(self.settings,self.stop,self.approve,lambda _:None,self.store,cycle=call,config=Config(),limit=1)
            self.assertIs(out['send_attempts_unknown'],not no_send)
            self.assertEqual(out.get('profile_cycle_no_send_verified',False),no_send)
            self.assertEqual(out['last_profile_diagnostics'],error._dvk_profile_diagnostics)
            call.assert_called_once();self.assertNotIn('PRIVATE',json.dumps(out))

class CityEvidence(unittest.TestCase):
    def test_claim_conflict_preserves_native_evidence_without_stealing_other_port(self):
        from mumu_store import SharedStore
        import mumu_cities as cities
        from test_search_city import ready_city
        with tempfile.TemporaryDirectory() as folder:
            store=SharedStore(Path(folder)/'db',device_port=5567);diag={}
            def capture(allowed,used):
                value=ready_city();n=value['navigation'];n.update(city_previous_name=None,city_round_reset=False)
                n['city_selected_name']=allowed[0]
                # Another DB action changed the reservation during the native operation.
                with store.connection() as db:
                    db.execute('UPDATE mumu_city_claims SET device=?',('5569',))
                return value
            with self.assertRaisesRegex(StateError,'city-claim-changed'):
                cities.change(store,['Pskov','OtherCity'],capture,diagnostics=diag)
            self.assertTrue(diag['last_city_navigation']['city_verified'])
            self.assertIn('root_probe',diag['last_city_navigation'])
            from assistant_error_notify import diagnostic_json
            safe=diagnostic_json(diag)
            self.assertIn(b'city_verified',safe);self.assertNotIn(b'Pskov',safe);self.assertNotIn(b'5569',safe)
            with store.connection() as db:
                self.assertTrue(all(row[0]=='5569' for row in db.execute('SELECT device FROM mumu_city_claims')))
    def test_database_completion_failure_keeps_native_evidence_and_pending_claim(self):
        from mumu_store import SharedStore
        import mumu_cities as cities
        with tempfile.TemporaryDirectory() as folder:
            store=SharedStore(Path(folder)/'db',device_port=5567);diag={}
            # A complete native result must survive a later database failure.
            from test_search_city import ready_city
            value=ready_city();n=value['navigation'];n.update(city_previous_name=None,city_round_reset=False)
            with patch.object(cities,'complete',side_effect=StateError('fixture database stop')) as complete:
                def capture(allowed,used):
                    n['city_selected_name']=allowed[0];return value
                with self.assertRaises(StateError):cities.change(store,['Pskov','OtherCity'],capture,diagnostics=diag)
            self.assertIn('root_probe',diag['last_city_navigation']);complete.assert_called_once()
            with store.connection() as db:
                self.assertTrue(any(row[0]=='pending' for row in db.execute('SELECT state FROM mumu_city_claims')))
