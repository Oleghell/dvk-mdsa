"""Automatic pending-city recovery. No Android, network, messages or DB reset."""
import copy,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from assistant_store import StateError
from assistant_settings import Settings
from assistant_profiles import change_city,Session
from mumu_store import SharedStore
from test_search_online import ready_online
import search_online,search_city_state as state,mumu_cities as cities


def proof(city='OldCity',online=True,distance=False):
    value=ready_online();n=value['navigation'];n.update(search_online.DEFAULTS)
    for key in ('open_attempted','open_completed','filters_verified','apply_attempted','apply_completed','return_verified'):
        n[key]=False
    n.update(state.DEFAULTS)
    n.update(observed_city=city,online_only=online,by_distance=distance,state_samples=2,state_verified=True)
    return value


def waiting():
    value=proof();n=value['navigation']
    n.update(stage='navigation-stopped',phase='search',error='wrong-screen',search_verified=False,**state.DEFAULTS)
    return value


class Evidence(unittest.TestCase):
    def test_two_ready_readonly_samples_are_valid(self):state.validate(proof())
    def test_mutation_flags_identity_thread_and_unverified_city_rejected(self):
        for fields in [dict(open_attempted=True),dict(apply_attempted=True),dict(state_samples=1),dict(online_only=1),dict(state_verified=False),dict(observed_city=''),dict(online_set_attempted=0),dict(frames=1)]:
            value=proof();value['navigation'].update(fields)
            with self.subTest(fields=fields),self.assertRaises((ValueError,StateError)):state.validate(value)
        value=proof();value['main_thread_confirmed']=False
        with self.assertRaises(ValueError):state.validate(value)
    def test_source_has_no_action_calls_and_invocation_write_guard(self):
        source=state.build()
        for call in ('call(s.open,','call(s.apply,','call(s.onlineSet,','call(s.cancel,','call(s.refreshForm,','OnSendText','input tap'):
            self.assertNotIn(call,source)
        self.assertIn('[s.open,s.cancel,s.onlineSet,s.refreshForm,s.apply].includes(entry)',source)
        self.assertIn('state.currentNext=Date.now()+300',source)
        self.assertIn("n.state_samples=2",source)


class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=SharedStore(Path(self.tmp.name)/'db',device_port=5557)
        self.names=['OldCity','Pskov','OtherCity']
        with self.store.connection() as db:
            for city,device,kind in [('oldcity','5557','active'),('pskov','5557','pending'),('othercity','5559','active')]:
                db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',(city,device,kind,'legacy'))
    def recover(self,reader=None,**kw):
        return cities.recover_pending(self.store,self.names,reader or (lambda:proof()),wait=lambda _:False,**kw)
    def claims(self):
        with self.store.connection() as db:return db.execute('SELECT city,device,state,token FROM mumu_city_claims ORDER BY city').fetchall()
    def test_old_bug_pending_restored_without_ui_action(self):
        self.assertEqual(self.recover(),'OldCity')
        rows=self.claims();self.assertEqual([(c,d,s) for c,d,s,t in rows],[('oldcity','5557','active'),('othercity','5559','active')])
        self.assertEqual(Session(self.store).get('city'),'OldCity')
    def test_applied_pending_city_promoted_instead_of_repeating_apply(self):
        self.assertEqual(self.recover(lambda:proof('Pskov')),'Pskov')
        self.assertTrue(cities.owns(self.store,'Pskov'))
        self.assertNotIn('oldcity',[row[0] for row in self.claims()])
    def test_another_ports_city_never_stolen_and_new_rotation_required(self):
        self.assertIsNone(self.recover(lambda:proof('OtherCity')))
        self.assertEqual(self.claims(),[('othercity','5559','active','legacy')])
        self.assertIsNone(Session(self.store).get('city'))
    def test_nearby_or_offline_filter_requires_normal_verified_change(self):
        self.assertIsNone(self.recover(lambda:proof(online=False,distance=True)))
        self.assertTrue(cities.owns(self.store,'OldCity'))
    def test_unknown_current_city_can_be_reserved_but_not_resumed_outside_config(self):
        self.assertIsNone(self.recover(lambda:proof('ExternalCity')))
        self.assertTrue(cities.owns(self.store,'ExternalCity'))
    def test_unreadable_screen_preserves_claims_until_fresh_verified_read(self):
        before=self.claims();calls=[]
        def reader():
            calls.append(True)
            if len(calls)==1:return waiting()
            self.assertEqual(self.claims(),before)
            return proof()
        self.assertEqual(self.recover(reader),'OldCity');self.assertEqual(len(calls),2)
    def test_cancel_wait_does_not_clear_pending_or_other_port(self):
        before=self.claims();stop=threading.Event()
        with self.assertRaisesRegex(StateError,'cancelled'):
            cities.recover_pending(self.store,self.names,waiting,cancelled=stop.is_set,wait=lambda _:stop.set() or True)
        self.assertEqual(self.claims(),before)
    def test_invalid_evidence_is_hard_failure_not_retry_or_reset(self):
        before=self.claims();reader=MagicMock(return_value=proof());reader.return_value['navigation']['open_attempted']=True
        with self.assertRaises(ValueError):self.recover(reader)
        reader.assert_called_once();self.assertEqual(self.claims(),before)
    def test_changed_claim_during_read_is_not_overwritten(self):
        calls=[]
        def reader():
            calls.append(True)
            if len(calls)==1:
                with self.store.connection() as db:db.execute("UPDATE mumu_city_claims SET token=? WHERE city=?",('new-unknown','pskov'))
            else:
                self.assertIn(('pskov','5557','pending','new-unknown'),self.claims())
            return proof()
        self.assertEqual(self.recover(reader),'OldCity')
        self.assertEqual(len(calls),2,'A stale observation must be discarded and read again')
    def test_no_pending_means_no_native_read(self):
        self.recover();reader=MagicMock(side_effect=AssertionError('No native read needed'))
        self.assertIsNone(self.recover(reader));reader.assert_not_called()
    def test_profile_integration_resumes_without_new_picker_or_history_clear(self):
        picker=MagicMock(side_effect=AssertionError('Must not repeat city change'));diagnostics={}
        result=change_city(Settings(),threading.Event(),self.store,self.names,city_next=picker,
            city_state_reader=lambda:proof(),diagnostics=diagnostics)
        self.assertEqual(result,'OldCity');picker.assert_not_called()
        self.assertEqual(diagnostics['city_reservations_recovered'],1)
        self.assertTrue(diagnostics['last_city_resumed'])
    def test_exhaustion_path_resumes_automatically_too(self):
        import assistant_rotation
        from test_assistant_rotation import exhausted
        with patch.object(assistant_rotation,'load',return_value=MagicMock(cities=self.names)),patch.object(state,'capture',return_value=proof()),patch('search_city._capture_next') as picker:
            result=assistant_rotation.after_exhaustion('ADB','APKS',exhausted(),self.store,lambda:False,lambda _:None)
        self.assertEqual(result['city_change']['status'],'recovered');picker.assert_not_called()
    def test_send_and_contact_registries_are_untouched(self):
        from test_assistant import pending
        self.store.reserve(pending(),'Hi',approved=True)
        with self.store.connection() as db:
            self.store.record_peer_outcome(db,dict(account='100',peer='201',chat='300'),'contact-refused')
            before={t:db.execute('SELECT * FROM '+t).fetchall() for t in ('manual_actions','mumu_greeting_claims','mumu_peer_blocks')}
        self.recover()
        with self.store.connection() as db:
            for table,rows in before.items():self.assertEqual(db.execute('SELECT * FROM '+table).fetchall(),rows)
