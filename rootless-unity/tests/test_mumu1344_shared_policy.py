"""Cross-port policy, durable unknowns and pause regression tests. No device."""
import sqlite3
from contextlib import closing
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from mumu_store import SharedStore,SharedPeerClaimed
from assistant_store import Store,StateError
from assistant_profiles import Session,clear_history
from test_assistant import pending
from test_assistant_rotation import applied,exhausted
from test_search_city import ready_city
import mumu_cities as cities


def selected(name,previous=None):
    value=ready_city()
    value['navigation'].update(city_selected_name=name,city_previous_name=previous,city_round_reset=False)
    return value


class Shared(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'db';self.legacy=Path(self.temp.name)/'old'
        self.a=self.store(5557);self.b=self.store(5559)
        self.names=['Город'+chr(65+i) for i in range(20)]
    def store(self,port):return SharedStore(self.path,self.legacy,device_port=port)
    def active(self,store,options=None):
        token,allowed,_=cities.reserve(store,options or self.names)
        cities.complete(store,token,allowed,selected(allowed[0]))
        return allowed[0]
    def test_five_ports_simultaneous_reservations_never_overlap(self):
        stores=[self.store(p) for p in (5557,5559,5561,5563,5565)]
        barrier=threading.Barrier(5);results=[];errors=[]
        def reserve(s):
            try:
                barrier.wait();results.append(cities.reserve(s,self.names)[1])
            except BaseException as error:errors.append(error)
        threads=[threading.Thread(target=reserve,args=(s,)) for s in stores]
        for t in threads:t.start()
        for t in threads:t.join(10);self.assertFalse(t.is_alive())
        self.assertEqual(errors,[]);self.assertEqual(len(results),5)
        flat=[n for r in results for n in r];self.assertEqual(len(flat),len(set(flat)))
    def test_small_pool_leaves_one_per_port_and_never_reuses_occupied(self):
        names=self.names[:5];used=[]
        for port in (5557,5559,5561,5563,5565):
            token,allowed,_=cities.reserve(self.store(port),names)
            self.assertEqual(len(allowed),1);used+=allowed
        self.assertEqual(len(set(used)),5)
        with self.assertRaisesRegex(StateError,'city-pool-exhausted'):cities.reserve(self.store(5567),names)
    def test_verified_completion_releases_unused_not_other_ports(self):
        token,allowed,_=cities.reserve(self.a,self.names)
        other,other_allowed,_=cities.reserve(self.b,self.names)
        self.assertGreater(len(allowed),1)
        cities.complete(self.a,token,allowed,selected(allowed[0]))
        self.assertTrue(cities.owns(self.a,allowed[0]))
        with self.a.connection() as db:
            self.assertEqual(len(db.execute('SELECT city FROM mumu_city_claims WHERE device=?',('5557',)).fetchall()),1)
            self.assertEqual(len(db.execute('SELECT city FROM mumu_city_claims WHERE device=?',('5559',)).fetchall()),len(other_allowed))
        self.assertEqual(Session(self.a).get('city'),allowed[0])
    def test_unknown_transition_retains_reservations_and_does_not_retry(self):
        capture=MagicMock(side_effect=TimeoutError('native unknown'))
        with self.assertRaises(TimeoutError):cities.change(self.a,self.names,capture)
        restarted=self.store(5557)
        with self.assertRaisesRegex(StateError,'city-reservation-unresolved'):cities.change(restarted,self.names,capture)
        capture.assert_called_once()
        own=set(capture.call_args.args[0]);other=set(cities.reserve(self.b,self.names)[1])
        self.assertFalse(own & other)
    def test_malformed_or_unverified_outcome_cannot_release_claims(self):
        token,allowed,_=cities.reserve(self.a,self.names)
        with self.assertRaises(Exception):cities.complete(self.a,token,allowed,selected('NotAllowed'))
        self.assertFalse(cities.owns(self.a,allowed[0]))
        with self.assertRaisesRegex(StateError,'city-reservation-unresolved'):cities.reserve(self.a,self.names)
    def test_successful_rotation_keeps_old_until_verified_new_city(self):
        old=self.active(self.a)
        token,allowed,_=cities.reserve(self.a,self.names)
        self.assertIn(old,allowed)
        with self.a.connection() as db:
            self.assertEqual(db.execute('SELECT device FROM mumu_city_claims WHERE city=?',(cities.search_city.normalize_city(old),)).fetchone(),('5557',))
        new=next(n for n in allowed if n!=old)
        cities.complete(self.a,token,allowed,selected(new,old))
        self.assertTrue(cities.owns(self.a,new));self.assertFalse(cities.owns(self.a,old))
    def test_shuffle_and_shared_round_history(self):
        with patch.object(cities.secrets.SystemRandom,'shuffle',side_effect=lambda values:values.reverse()) as shuffle:
            first=self.active(self.a);second=self.active(self.b)
        self.assertGreaterEqual(shuffle.call_count,2);self.assertNotEqual(first,second)
        with self.b.connection() as db:
            used={r[0] for r in db.execute('SELECT city FROM mumu_city_used')}
        self.assertTrue({cities.search_city.normalize_city(first),cities.search_city.normalize_city(second)}<=used)
    def test_old_duplicate_sessions_are_not_both_owned(self):
        Session(self.a).set('city',self.names[0]);Session(self.b).set('city',self.names[0])
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('DROP TABLE mumu_city_claims');db.execute('DROP TABLE mumu_city_used')
        a=self.store(5557);b=self.store(5559)
        self.assertEqual(sum(cities.owns(s,self.names[0]) for s in (a,b)),1)
    def test_explicit_clear_only_own_city_not_other_city_or_greeting(self):
        first=self.active(self.a);second=self.active(self.b)
        self.a.reserve(pending(),'Hi',approved=True)
        clear_history(self.a)
        self.assertFalse(cities.owns(self.a,first));self.assertTrue(cities.owns(self.b,second))
        self.assertTrue(self.b.peer_claimed(pending(account='101')))
        self.assertFalse(self.b.peer_terminal(pending(account='101')))
    def test_clear_cannot_release_city_while_port_worker_holds_lock(self):
        from assistant_lock import operation_lock
        name=self.active(self.a)
        with operation_lock(self.path.parent/'devices'/'5557'/'worker.lock'):
            with self.assertRaises(StateError):clear_history(self.a)
        self.assertTrue(cities.owns(self.a,name))

    def test_old_unknowns_backfill_without_rewriting_journals(self):
        old=Store(self.path,self.legacy);action=old.reserve(pending(),'Hi',approved=True)
        with closing(sqlite3.connect(self.path)) as db,db:
            before=db.execute('SELECT * FROM manual_actions').fetchall()
            db.execute('DROP TABLE mumu_greeting_claims')
        b=self.store(5559)
        self.assertTrue(b.peer_claimed(pending()));self.assertFalse(b.peer_terminal(pending()))
        with closing(sqlite3.connect(self.path)) as db,db:self.assertEqual(db.execute('SELECT * FROM manual_actions').fetchall(),before)
    def test_cross_port_claim_does_not_deny_existing_dialogue(self):
        self.a.reserve(pending(),'Hi',approved=True)
        # Terminal guard is deliberately not the initial-greeting check.
        from mumu_peer_policy import ensure_communication_allowed
        from test_guided_chain import WHO
        ensure_communication_allowed(self.b,WHO)
        with self.b.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM mumu_peer_blocks').fetchone()[0],0)
        self.assertFalse(self.b.peer_terminal(pending()))
    def test_profile_and_exhaustion_paths_use_allocator(self):
        from assistant_profiles import change_city
        from assistant_settings import Settings
        import assistant_rotation
        native=MagicMock(side_effect=lambda exe,folder,allowed,used,stop:selected(allowed[0]))
        first=change_city(Settings(),threading.Event(),self.a,self.names,city_next=native)
        with patch.object(assistant_rotation,'load',return_value=MagicMock(cities=self.names)),patch.object(cities.search_city,'_capture_next',native):
            result=assistant_rotation.after_exhaustion('ADB','APKS',exhausted(),self.b,lambda:False,lambda _:None)
        self.assertEqual(result['city_change']['status'],'changed')
        self.assertNotEqual(result['city_change']['selected_city'],first)
        self.assertTrue(cities.owns(self.a,first))


class Resume(unittest.TestCase):
    def test_transient_readonly_recheck_retries_not_monitor_or_send(self):
        import mumu_recovery
        from mumu_pause import PauseGate
        from assistant_pause import PortResumed
        from assistant_settings import Settings
        gate=PauseGate(threading.Event())
        monitor=MagicMock(side_effect=[PortResumed(),dict(status='completed')])
        recheck=MagicMock(side_effect=[ConnectionError(),TimeoutError(),None]);wait=MagicMock(return_value=False)
        result=mumu_recovery.run(Settings(),gate,MagicMock(),monitor=monitor,repair=MagicMock(),recheck=recheck,wait=wait)
        self.assertEqual(result['status'],'completed');self.assertEqual(monitor.call_count,2)
        self.assertEqual(recheck.call_count,3);self.assertEqual([c.args[0] for c in wait.call_args_list],[1,2])
    def test_stop_during_resume_connection_wait_never_reenters_monitor(self):
        import mumu_recovery
        gate=threading.Event();check=MagicMock(side_effect=ConnectionError())
        self.assertFalse(mumu_recovery.resume_recheck(check,gate,MagicMock(),lambda delay:gate.set() or True))
        check.assert_called_once()
    def test_requested_pause_acknowledged_before_error_notification(self):
        import mumu_recovery
        from mumu_pause import PauseGate
        from assistant_settings import Settings
        paused=threading.Event();gate=PauseGate(threading.Event(),lambda s:paused.set() if s=='paused' else None)
        alert=MagicMock();out=[]
        def monitor(*args,**kwargs):gate.command('pause');return dict(status='stopped',reason='identity-changed')
        t=threading.Thread(target=lambda:out.append(mumu_recovery.run(Settings(errors_enabled=True),gate,MagicMock(),monitor=monitor,repair=MagicMock(),json_alert=alert)))
        t.start()
        try:
            self.assertTrue(paused.wait(3));alert.assert_not_called();self.assertTrue(t.is_alive())
            gate.command('resume');t.join(3);self.assertFalse(t.is_alive())
            self.assertEqual(out[0]['reason'],'identity-changed');alert.assert_called_once()
        finally:gate.set();t.join(3)

    def test_stop_while_paused_is_cancelled_not_error_alert(self):
        import mumu_recovery
        from mumu_pause import PauseGate
        from assistant_settings import Settings
        paused=threading.Event();gate=PauseGate(threading.Event(),lambda s:paused.set() if s=='paused' else None)
        alert=MagicMock();out=[]
        def monitor(*args,**kwargs):gate.command('pause');return dict(status='stopped',reason='read-stopped')
        t=threading.Thread(target=lambda:out.append(mumu_recovery.run(Settings(errors_enabled=True),gate,MagicMock(),monitor=monitor,repair=MagicMock(),json_alert=alert)))
        t.start()
        try:
            self.assertTrue(paused.wait(3));gate.set();t.join(3)
            self.assertFalse(t.is_alive());self.assertEqual(out[0]['status'],'cancelled')
            alert.assert_not_called()
        finally:gate.set();t.join(3)
