"""Large histories are data, not compiled code; root/city failures stay closed."""
import json,tempfile,unittest,threading
from pathlib import Path
from unittest.mock import MagicMock,patch
import assistant_pass as native
import mumu_cities as cities
import search_city_state as state
from assistant_store import StateError
from mumu_store import SharedStore
from assistant_setup_retry import SetupRetry
from test_mumu1326_setup_retry import setup_error,Clock
from test_mumu1346_city_auto import proof
import test_mumu1346_city_auto as previous
import test_search_online as online_harness
import search_online


def root_not_ready(stage='window-not-ready'):
    value=proof();n=value['navigation']
    for k in ('cleanup_failed','search_verified','filters_verified','return_verified','open_attempted','open_completed','apply_attempted','apply_completed','ui_text_read'):n[k]=False
    n.update(state.DEFAULTS);n.update(stage='not-attempted',phase='search',error='none',frames=0,managed_calls=0,handles_acquired=0,handles_released=0,
        root_top_kind='not-checked',last_presented_kind='not-checked',controller_path=[],readiness_check='not-checked',view_parent_depth=0,
        readiness=dict.fromkeys(n['readiness']))
    value.update(stage=stage,step='window-get',managed_calls=0,observed_calls=0,main_thread_confirmed=False,object_classes_validated=False,
        runtime_available=False,window_available=False,runtime_handle_acquired=False,runtime_handle_released=False,window_handle_acquired=False,window_handle_released=False)
    return state.validate(value)

class Bootstrap(unittest.TestCase):
    def test_compiled_source_no_history_literals_or_arbitrary_eval(self):
        source=native.prepared_source('Hi')
        self.assertIn('new Set(assistantVisited)',source)
        self.assertIn('Object.freeze(assistantVisitedParts)',source)
        self.assertIn('assistantRootStarted=true;return probeBatchProfile()',source)
        self.assertNotIn('eval(',source)
        old=native.build('Hi',list(map(str,range(100000,110000))))
        self.assertLess(len(source),len(old)*.6)
    def test_host_upload_happens_before_root_and_never_authorizes_send(self):
        f=online_harness.OnlineFake();create=f.create_script;calls=[]
        def created(*a,**kw):
            value=create(*a,**kw)
            f.exports_sync.preparevisited=lambda values:calls.append(('history',values)) or True
            def root():
                calls.append(('root',None));raise RuntimeError('fixture stop before native')
            f.exports_sync.root=root;return value
        f.create_script=created;store=MagicMock();store.visited_peers.return_value=['200']
        with self.assertRaises(RuntimeError):native.inspect(37149,'TOKEN',lambda:False,'Hi',store,MagicMock(),frida_api=f)
        self.assertEqual(calls,[('history',['200']),('root',None)]);store.reserve.assert_not_called()
    def test_rejected_history_upload_never_calls_root_or_journal_authorization(self):
        f=online_harness.OnlineFake();create=f.create_script;root=MagicMock()
        def created(*a,**kw):
            value=create(*a,**kw);f.exports_sync.preparevisited=lambda values:False;f.exports_sync.root=root;return value
        f.create_script=created;store=MagicMock();store.visited_peers.return_value=[]
        with self.assertRaises(StateError) as e:native.inspect(37149,'TOKEN',lambda:False,'Hi',store,MagicMock(),frida_api=f)
        self.assertTrue(e.exception._dvk_profile_not_executed);root.assert_not_called();store.reserve.assert_not_called()
        self.assertEqual(e.exception._dvk_failure['stage'],'profile-history-upload')
    def test_persistent_compile_error_is_bounded_and_not_an_unknown_send(self):
        from types import SimpleNamespace
        clock=Clock();o=SetupRetry(SimpleNamespace(errors_enabled=False),threading.Event(),write=lambda _:None,clock=clock,wait=clock.wait)
        for n in range(1,6):self.assertFalse(o(setup_error(),n,min(30,2**min(n-1,5))))
        with self.assertRaisesRegex(StateError,'profile-script-unavailable') as e:o(setup_error(),6,30)
        self.assertTrue(e.exception._dvk_profile_not_executed)
        from mumu_recovery import recoverable
        self.assertFalse(recoverable(dict(status='stopped',reason='profile-script-unavailable',host_failure='native-transport-error')))

class Recovery(unittest.TestCase):
    def test_root_not_ready_is_valid_readonly_non_action_evidence(self):root_not_ready()
    def test_unattempted_root_wait_does_not_clear_claims_and_retries_fresh_read(self):
        with tempfile.TemporaryDirectory() as folder:
            s=SharedStore(Path(folder)/'db',device_port=5567)
            with s.connection() as db:db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',('pskov','5567','pending','original'))
            reads=[];diag={}
            def reader():
                reads.append(1)
                if len(reads)==1:return root_not_ready()
                with s.connection() as db:self.assertEqual(db.execute('SELECT token FROM mumu_city_claims').fetchone(),('original',))
                return proof('Pskov')
            self.assertEqual(cities.recover_pending(s,['Pskov'],reader,wait=lambda _:False,diagnostics=diag),'Pskov')
            self.assertEqual(len(reads),2);self.assertTrue(cities.owns(s,'Pskov'))
            self.assertIn('last_city_recovery',diag)
    def test_hard_root_failure_retains_closed_reason_without_city_or_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            s=SharedStore(Path(folder)/'db',device_port=5567)
            with s.connection() as db:db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',('pskov','5567','pending','original'))
            diag={}
            with self.assertRaisesRegex(StateError,'city-reservation-unresolved'):
                cities.recover_pending(s,['Pskov'],lambda:root_not_ready('signature-mismatch'),wait=lambda _:False,diagnostics=diag)
            from assistant_error_notify import diagnostic_json
            value=json.loads(diagnostic_json(diag))['diagnostic']['last_city_recovery']
            self.assertEqual(value['root_probe']['stage'],'signature-mismatch');self.assertNotIn('Pskov',json.dumps(value))


class CityTransport(unittest.TestCase):
    def test_actual_observer_marks_only_readonly_transport_stages(self):
        from startup_failure import record
        for stage in ('script-create','script-run','result-validation'):
            error=type('TransportError',(Exception,),{})('PRIVATE');record(error,stage)
            def capture(*a,inspector,**kw):return inspector(37149,'TOKEN',lambda:False,None)
            with patch('one_chat_device.capture',side_effect=capture),patch('search_online.inspect',side_effect=error):
                with self.assertRaises(Exception):state.capture('ADB','APKS')
            self.assertIs(error._dvk_city_readonly_transport,stage!='result-validation')
    def test_bare_transport_cannot_release_or_retry_reservations(self):
        from startup_failure import record
        with tempfile.TemporaryDirectory() as folder:
            s=SharedStore(Path(folder)/'db',device_port=5567)
            with s.connection() as db:db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',('pskov','5567','pending','original'))
            error=type('TransportError',(Exception,),{})('PRIVATE');record(error,'script-create')
            reader=MagicMock(side_effect=error)
            with self.assertRaises(Exception):cities.recover_pending(s,['Pskov'],reader,wait=lambda _:False)
            reader.assert_called_once()
            with s.connection() as db:self.assertEqual(db.execute('SELECT token FROM mumu_city_claims').fetchone(),('original',))
