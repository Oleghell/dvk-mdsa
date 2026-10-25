"""Use the real source builder, not just a mocked successful city response."""
from pathlib import Path
import tempfile,threading,unittest
from unittest.mock import MagicMock,patch
from assistant_config import Config,ConfigError
from assistant_settings import Settings
from assistant_store import StateError
from mumu_store import SharedStore
from test_assistant_rotation import exhausted
from test_search_city import ready_city
import search_city
import mumu_cities


class Contract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=SharedStore(Path(self.temp.name)/'db',device_port=5557)
        self.names=['OldCity','Pskov','OtherCity']
        with self.store.connection() as db:
            for name,device in [('OldCity','5557'),('OtherCity','5559')]:
                normalized=search_city.normalize_city(name)
                db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',(normalized,device,'active','legacy'))
                db.execute('INSERT INTO mumu_city_used VALUES(?)',(normalized,))
    def capture(self,exe,folder,allowed,used,stop):
        # This real builder raised ConfigError before any device access in 1.3.44.
        source=search_city.build_next(allowed,used)
        self.assertIn('cityCandidates',source)
        self.assertNotIn('OtherCity',allowed)
        self.assertTrue(set(map(search_city.normalize_city,used))<=set(map(search_city.normalize_city,allowed)))
        value=ready_city();value['navigation'].update(city_previous_name='OldCity',city_round_reset=False)
        return value
    def test_profile_city_change_with_other_ports_history(self):
        from assistant_profiles import change_city
        result=change_city(Settings(),threading.Event(),self.store,self.names,city_next=self.capture)
        self.assertEqual(result,'Pskov');self.assertTrue(mumu_cities.owns(self.store,'Pskov'))
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT device FROM mumu_city_claims WHERE city=?',('othercity',)).fetchone(),('5559',))
            self.assertIsNotNone(db.execute('SELECT city FROM mumu_city_used WHERE city=?',('othercity',)).fetchone())
    def test_exhaustion_city_change_uses_same_checked_contract(self):
        import assistant_rotation as rotation
        with patch.object(rotation,'load',return_value=Config(tuple(self.names),('Hi',))),patch.object(search_city,'_capture_next',side_effect=self.capture):
            result=rotation.after_exhaustion('ADB','APKS',exhausted(),self.store,lambda:False,lambda _:None)
        self.assertEqual(result['city_change']['status'],'changed')
        self.assertTrue(mumu_cities.owns(self.store,'Pskov'))
    def test_invalid_input_does_not_create_new_pending_claims(self):
        with patch.object(search_city,'rotation_inputs',side_effect=ConfigError('invalid contract')):
            with self.assertRaises(ConfigError):mumu_cities.reserve(self.store,self.names)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM mumu_city_claims WHERE state='pending'").fetchone()[0],0)
        self.assertTrue(mumu_cities.owns(self.store,'OldCity'))
    def test_strict_builder_still_rejects_foreign_history(self):
        with self.assertRaises(ConfigError):search_city.build_next(['Pskov'],['OtherCity'])
    def test_previous_unknown_reservations_are_not_automatically_erased(self):
        with self.store.connection() as db:
            db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',('pskov','5557','pending','old-unknown'))
        capture=MagicMock()
        with self.assertRaisesRegex(StateError,'city-reservation-unresolved'):
            mumu_cities.change(self.store,self.names,capture)
        capture.assert_not_called()
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT token FROM mumu_city_claims WHERE city=?',('pskov',)).fetchone(),('old-unknown',))
