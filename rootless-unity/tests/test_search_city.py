"""No APK/account data: fixed city schema, safe source, mock GUI and transport."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from assistant_config import Config, ConfigError
import search_city as city
from test_search_online import ready_online, OnlineFake


def ready_city():
    value = ready_online()
    n = value['navigation']
    n.update(city.DEFAULTS)
    n.update({k:True for k,v in city.DEFAULTS.items() if type(v) is bool})
    n.update(city_queries_started=1,city_query_text_returns=1,city_query_returns=1,city_scan_samples=2, city_visible_rows=1, city_total_rows=1,
             city_matches=1,city_selected_name='Pskov',city_checkpoint='complete',city_prepare='ready')
    # A city operation has a separate bounded wait budget; online-only still
    # retains its original 180-frame validation budget.
    n['ui_text_read'] = True
    n['frames'] = 600
    value['managed_calls'] = 1800
    value['observed_calls'] = 600
    return value


class CitySchema(unittest.TestCase):
    def test_complete_post_apply_evidence(self):
        value = ready_city()
        self.assertIs(city.validate(value), value)

    def test_online_only_keeps_original_budget(self):
        import search_online
        value = ready_online()
        value['navigation']['frames'] = 600
        with self.assertRaises(ValueError):
            search_online.validate(value)

    def test_success_requires_each_city_step(self):
        for k,v in city.DEFAULTS.items():
            if type(v) is bool:
                value = ready_city()
                value['navigation'][k] = False
                with self.assertRaises(ValueError):
                    city.validate(value)

    def test_invalid_city_evidence_is_rejected(self):
        for key,bad in [('city_visible_rows',0),('city_total_rows',0),('city_scan_samples',1),
                        ('city_matches',0),('city_scan_samples',True),('city_verified',1),
                        ('city_checkpoint','private-code'),('city_visible_rows',13)]:
            value = ready_city()
            value['navigation'][key] = bad
            with self.assertRaises(ValueError):
                city.validate(value)

    def test_no_extra_private_values(self):
        value = ready_city()
        value['navigation']['geo_id'] = 'PRIVATE-CODE'
        with self.assertRaises(ValueError):
            city.validate(value)

    def test_first_result_evidence_allows_virtualized_list(self):
        for visible,total,matches in ((2,1,1),(1,1,2),(2,2,0)):
            value = ready_city()
            value['navigation'].update(city_visible_rows=visible, city_total_rows=total, city_matches=matches)
            with self.assertRaises(ValueError):
                city.validate(value)
        value = ready_city()
        for visible,total in ((1,2),(12,30),(2,2)):
            value['navigation'].update(city_visible_rows=visible, city_total_rows=total, city_matches=1)
            self.assertIs(city.validate(value), value)

    def test_verified_name_must_be_real_and_match_request_not_prefix(self):
        for name in (None, '', True, 'Pskov\n', ' Pskov', 'A'*81, '\ud800'):
            value = ready_city()
            value['navigation']['city_selected_name'] = name
            with self.assertRaises(ConfigError):
                city.validate(value, expected_city='Pskov')
        for requested,name in (('Pskov','Pskovsk'),('Pskov','NotPskov'),
                               ('Армавир','Армавирский'),('Армавир','Армавир-2')):
            value = ready_city()
            value['navigation']['city_selected_name'] = name
            with self.assertRaises(ValueError):
                city.validate(value, expected_city=requested)
        value = ready_city()
        value['navigation']['city_selected_name'] = 'ОрЁл'
        self.assertIs(city.validate(value, expected_city='орел'), value)

    def test_configured_random_city(self):
        config = Config(('Pskov','City2'),('Greeting',))
        with patch('assistant_config.secrets.choice',return_value='City2') as choose:
            self.assertEqual(config.city(), 'City2')
            choose.assert_called_once_with(config.cities)

    def test_query_is_json_data_never_code(self):
        text = 'X";danger(); //'
        source = city.build(text)
        self.assertIn('const cityWanted='+json.dumps(text)+';', source)
        for bad in (None,True,'',' Pskov','Pskov\n','\ud800','A'*81):
            with self.assertRaises(ConfigError):
                city.build(bad)

    def test_uses_verified_first_result_without_requiring_all_rows(self):
        source = city.build('Псков')
        for text in ('get_GeoID','get_RecordType','OnCellSelected','citySignature(f,entry,m)',
                     'city-query-changed','cityExact','cityFingerprint',
                     'city_scan_samples=2',
                     'field_static_get_value','class_enum_basetype','get_SectionsCount','GetSectionItemsCount'):
            self.assertIn(text, source)
        for bad in ('set_GeoCode','set_GeoID','ApplyGeoRecord','ConfigureSample','OnGeoLocationPressed',
                    'UseCurrentLocation','set_Scope','OnSendText','OnMessageButton','5555',
                    'rpc.exports','il2cpp_object_new','input tap'):
            self.assertNotIn(bad, source)
        self.assertIn("if(n.phase==='scan-city'&&Date.now()<state.cityNext)return;", source)
        self.assertIn('r.navigation.frames>=900', source)
        self.assertIn('},30000);', source)
        self.assertNotIn('.startsWith(', source)
        self.assertIn("if(count>200||count>total)fail('city-results-incomplete');", source)
        self.assertIn("const scan=1;", source)
        self.assertIn("fingerprint:JSON.stringify({records,count,total})", source)
        self.assertIn("if(found.match===null){", source)
        self.assertIn("fail('city-not-found');",source)
        self.assertIn("state.cityRemaining.shift()",source)


class CityPrepare(unittest.TestCase):
    def test_unsupported_step_is_fixed_label_and_success_needs_ready(self):
        value = ready_city()
        value['navigation']['city_prepare'] = 'private-code'
        with self.assertRaises(ValueError):
            city.validate(value)
        value = ready_city()
        value['navigation']['city_prepare'] = 'method:cityItem'
        with self.assertRaises(ValueError):
            city.validate(value)
        self.assertIn('method:cityItem', city.PREPARE_STEPS)
        self.assertIn('field:cityTableField', city.PREPARE_STEPS)

class CityTransport(unittest.TestCase):
    def test_source_and_validator_inject_only_through_internal_run(self):
        f = OnlineFake()
        create = f.create_script
        def script(*a, **kw):
            value = create(*a, **kw)
            f.exports_sync.root = ready_city
            return value
        f.create_script = script
        import search_online
        source = city.build('Pskov')
        value = search_online.inspect(37149,'a'*64,lambda:False,frida_api=f,
                                       source_function=source,validator=city.validate,timeout=40)
        self.assertTrue(value['navigation']['city_verified'])
        self.assertIn(source, f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)

    def test_target_only_transport_and_shared_lock(self):
        with patch('assistant_lock.operation_lock') as lock, patch('one_chat_device.capture') as capture, \
             patch.object(city.online,'inspect') as inspect:
            city.run('ADB','APKS','Pskov')
            lock.return_value.__enter__.assert_called_once()
            inspector = capture.call_args.kwargs['inspector']
            inspector(37149,'a'*64,lambda:False,None)
            validator = inspect.call_args.kwargs['validator']
            self.assertEqual(validator(ready_city())['navigation']['city_selected_name'], 'Pskov')
            wrong = ready_city()
            wrong['navigation']['city_selected_name'] = 'Pskovsk'
            with self.assertRaises(ValueError):
                validator(wrong)
            self.assertEqual(inspect.call_args.kwargs['timeout'],40)


@contextmanager
def gui(consent=True):
    import assistant_legacy as app
    tk,ttk = MagicMock(),MagicMock()
    tk.ttk = ttk
    tk.StringVar.return_value.get.return_value='C:/private/test-apks'
    tk.BooleanVar.return_value.get.return_value=consent
    with tempfile.TemporaryDirectory() as directory, \
         patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,
                    'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}), \
         patch.object(app,'data_directory',return_value=Path(directory)), \
         patch.object(app,'load',return_value=Config(('Pskov',),('Greeting',))) as load, \
         patch.object(app,'select_city',return_value=ready_city()) as native, \
         patch.object(app,'enable_online') as online,patch.object(app,'run') as profile, \
         patch.object(app.threading,'Thread') as thread:
        app.launch()
        commands={c.kwargs.get('text'):c.kwargs.get('command') for c in ttk.Button.call_args_list}
        poll=next(c.args[1] for c in tk.Tk.return_value.after.call_args_list
                  if len(c.args)==2 and getattr(c.args[1],'__name__','')=='poll')
        yield tk,commands,poll,thread,native,online,profile,load,Path(directory)


class CityButton(unittest.TestCase):
    def test_no_autostart_or_action_without_consent(self):
        with gui(False) as (tk,buttons,poll,thread,native,online,profile,load,folder):
            thread.assert_not_called()
            buttons['Выбрать город и онлайн']()
            native.assert_not_called()
            thread.assert_not_called()
            online.assert_not_called()
            profile.assert_not_called()
            tk.messagebox.showinfo.assert_called_once()

    def test_random_city_action_blocks_all_other_operations_and_reports_no_id(self):
        with gui() as (tk,buttons,poll,thread,native,online,profile,load,folder):
            buttons['Выбрать город и онлайн']()
            self.assertEqual(thread.call_args.kwargs['target'].__name__,'city_worker')
            self.assertEqual(thread.call_args.kwargs['args'][-1],'Pskov')
            for label in ('Проверить одну анкету','Включить только онлайн','Подготовить настройки поиска','Выбрать город и онлайн'):
                buttons[label]()
            thread.return_value.start.assert_called_once()
            thread.call_args.kwargs['target']('ADB','APKS','Pskov')
            poll()
            value=json.loads((folder/'last-city-settings.json').read_text(encoding='utf-8'))
            self.assertTrue(value['city_verified'] and value['online_verified'])
            self.assertEqual(value['requested_city'],'Pskov')
            self.assertEqual(value['city_selected_name'],'Pskov')
            self.assertEqual(value['messages_sent'],0)
            self.assertFalse(value['chat_content_read'])
            self.assertNotIn('geo_id',value)
            online.assert_not_called()
            profile.assert_not_called()

    def test_success_displays_actual_name_not_config_spelling(self):
        with gui() as (tk,buttons,poll,thread,native,online,profile,load,folder):
            result = ready_city()
            result['navigation']['city_selected_name'] = 'PSKOV'
            native.return_value = result
            buttons['Выбрать город и онлайн']()
            thread.call_args.kwargs['target']('ADB','APKS','Pskov')
            poll()
            messages = [c.args[0] for c in tk.StringVar.return_value.set.call_args_list if c.args]
            self.assertTrue(any('Город выбран и проверен: PSKOV.' in text for text in messages))
            report = json.loads((folder/'last-city-settings.json').read_text(encoding='utf-8'))
            self.assertEqual(report['requested_city'], 'Pskov')
            self.assertEqual(report['city_selected_name'], 'PSKOV')
            profile.assert_not_called()

    def test_config_error_prevents_thread(self):
        with gui() as (tk,buttons,poll,thread,native,online,profile,load,folder):
            load.side_effect=ConfigError('Broken city list')
            buttons['Выбрать город и онлайн']()
            thread.assert_not_called()
            native.assert_not_called()

    def test_exception_is_private_and_no_success_file_is_written(self):
        with gui() as (tk,buttons,poll,thread,native,online,profile,load,folder):
            native.side_effect=RuntimeError('SECRET-LOCATION-TOKEN')
            buttons['Выбрать город и онлайн']()
            thread.call_args.kwargs['target']('ADB','APKS','Pskov')
            poll()
            text=str(tk.StringVar.return_value.set.call_args_list)
            self.assertNotIn('SECRET-LOCATION-TOKEN',text)
            self.assertIn('часть изменений могла выполниться',text)
            self.assertFalse((folder/'last-city-settings.json').exists())
            profile.assert_not_called()


if __name__=='__main__':
    unittest.main()
