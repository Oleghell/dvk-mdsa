from contextlib import contextmanager
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import assistant_rotation as rotation
import search_city
from assistant_config import Config, ConfigError
from assistant_store import Store
from test_search_city import ready_city


def exhausted(**updates):
    result = dict(limit=5,status='preview-exhausted',reason='visible-exhausted',
                  attempts=1,visited=0,checked=0,eligible=0,skipped=0,unknown=0,
                  profile_may_remain_open=False,chats_opened=0,messages_sent=0)
    result.update(updates)
    return result


def applied(previous='OldCity', reset=False):
    value = ready_city()
    value['navigation'].update(city_previous_name=previous,city_round_reset=reset)
    return value


class CityRotation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/'assistant.sqlite3',Path(self.temp.name)/'old')
        self.cities = ['OldCity','Pskov','ThirdCity']

    def execute(self, result=None, cancelled=lambda:False, progress=lambda text:None, value=None):
        with patch.object(rotation,'load',return_value=Config(tuple(self.cities),('Hi',))), \
             patch.object(rotation.secrets.SystemRandom,'shuffle'), \
             patch.object(search_city,'_capture_next',return_value=value or applied()) as city:
            out = rotation.after_exhaustion('ADB','APKS',result or exhausted(),self.store,cancelled,progress)
            return out,city

    def test_exhausted_zero_or_partial_changes_city_exactly_once(self):
        for count in (0,4):
            out,city=self.execute(exhausted(checked=count))
            city.assert_called_once()
            self.assertEqual(out['city_change']['status'],'changed')
            self.assertEqual(out['city_change']['selected_city'],'Pskov')
            self.assertEqual((out['chats_opened'],out['messages_sent']),(0,0))

    def test_completed_stopped_cancelled_and_unsafe_outcomes_never_rotate(self):
        for updates in ({'status':'preview-completed','reason':'limit-reached'},
                        {'status':'preview-stopped'},{'status':'preview-cancelled'},
                        {'reason':'probe-failed'},{'profile_may_remain_open':True},
                        {'messages_sent':1},{'chats_opened':1}):
            out,city=self.execute(exhausted(**updates))
            city.assert_not_called()
            self.assertNotIn('city_change',out)

    def test_stop_before_city_or_during_progress_does_not_change_settings(self):
        out,city=self.execute(cancelled=lambda:True)
        city.assert_not_called()
        self.assertEqual(out['city_change']['status'],'cancelled')
        stopped=[]
        out,city=self.execute(cancelled=lambda:bool(stopped),progress=lambda text:stopped.append(True))
        city.assert_not_called()

    def test_history_survives_restart_and_reset_never_touches_send_reservations(self):
        pending=dict(attempt=1,account='100',peer='200',chat='-1',variant=0)
        self.store.reserve(pending,'Hi',approved=True)
        before=self.store.summary()
        history=rotation.History(self.store)
        history.record(self.cities,applied())
        restarted=rotation.History(Store(self.store.path,self.store.legacy))
        self.assertEqual(set(restarted.used(self.cities)),{'OldCity','Pskov'})
        value=applied(previous='ThirdCity',reset=True)
        restarted.record(self.cities,value)
        self.assertEqual(set(restarted.used(self.cities)),{'ThirdCity','Pskov'})
        self.assertEqual(self.store.summary(),before)

    def test_failure_or_invalid_result_does_not_clear_history_or_retry(self):
        rotation.History(self.store).record(self.cities,applied())
        before=rotation.History(self.store).used(self.cities)
        for value in ({'navigation':{}},applied(previous='Pskov')):
            out,city=self.execute(value=value)
            city.assert_called_once()
            self.assertEqual(out['city_change']['status'],'unknown')
            self.assertEqual(rotation.History(self.store).used(self.cities),before)

    def test_corrupt_config_prevents_any_city_action(self):
        with patch.object(rotation,'load',side_effect=ConfigError('PRIVATE')), \
             patch.object(search_city,'_capture_next') as city:
            out=rotation.after_exhaustion('ADB','APKS',exhausted(),self.store,lambda:False,lambda text:None)
            city.assert_not_called()
            self.assertEqual(out['city_change']['status'],'unknown')
            self.assertNotIn('PRIVATE',str(out))

    def test_stop_between_preview_and_rotation_keeps_city_unchanged(self):
        stopped=[]
        def capture(*args,**kwargs):
            stopped.append(True)
            return exhausted()
        with patch('assistant_lock.operation_lock'),patch('one_chat_device.capture',side_effect=capture), \
             patch.object(search_city,'_capture_next') as city:
            out=rotation.run('ADB',self.temp.name,cancelled=lambda:bool(stopped),store=self.store)
            city.assert_not_called()
            self.assertEqual(out['status'],'preview-cancelled')

    def test_one_shared_lock_covers_preview_and_city(self):
        events=[]
        @contextmanager
        def lock():
            events.append('locked')
            yield
            events.append('unlocked')
        def city(*args):
            self.assertEqual(events,['locked','preview'])
            events.append('city')
            return applied()
        with patch('assistant_lock.operation_lock',lock), \
             patch('one_chat_device.capture',side_effect=lambda *a,**kw:events.append('preview') or exhausted()), \
             patch.object(search_city,'_capture_next',side_effect=city), \
             patch.object(rotation,'load',return_value=Config(tuple(self.cities),('Hi',))):
            out=rotation.run('ADB',self.temp.name,store=self.store)
        self.assertEqual(events,['locked','preview','city','unlocked'])
        self.assertEqual(out['city_change']['status'],'changed')


class NativeCityPolicy(unittest.TestCase):
    def test_fresh_current_name_is_read_before_any_settings_action(self):
        source=search_city.build_next(['OldCity','Pskov'],['OldCity'])
        self.assertIn('cityNorm(name)!==cityNorm(previousCityName)',source)
        self.assertIn('!cityUsed.has(cityNorm(name))',source)
        self.assertIn("if(found.match.id===state.rotationCityID)fail('identity-changed');",source)
        self.assertIn("fail('city-no-alternative')",source)
        self.assertLess(source.index('const previousCityName='),source.index('call(s.open,current)'))
        for text in ('OnMessageButton','OnSendText','input tap','5555'):
            self.assertNotIn(text,source)

    def test_config_and_rotation_evidence_are_strict(self):
        for cities in ([],['Орёл','Орел'],['Pskov\n'],[' X'],[False]):
            with self.assertRaises(ConfigError):
                search_city.build_next(cities)
        for changes in ({'city_round_reset':1},{'city_previous_name':'Other'},
                        {'city_previous_name':'Pskov'},{'city_selected_name':'Pskovsk'}):
            value=applied()
            value['navigation'].update(changes)
            with self.assertRaises((ValueError,ConfigError)):
                search_city.validate_next(value,['OldCity','Pskov'])
        self.assertIsNotNone(search_city.validate_next(applied(),['OldCity','Pskov']))

    def test_city_capture_reuses_target_only_transport_without_nested_lock(self):
        with patch('one_chat_device.capture') as capture,patch('assistant_lock.operation_lock') as lock:
            search_city._capture_next('ADB','APKS',['OldCity','Pskov'],[],lambda:False)
            capture.assert_called_once()
            lock.assert_not_called()