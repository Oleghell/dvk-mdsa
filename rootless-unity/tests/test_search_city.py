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
    n.update(city_scan_samples=2, city_visible_rows=1, city_total_rows=1,
             city_matches=1,city_checkpoint='complete')
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

    def test_no_ambiguous_offscreen_unstable_or_invalid_type_success(self):
        for key,bad in [('city_visible_rows',0),('city_total_rows',2),('city_scan_samples',1),
                        ('city_matches',2),('city_scan_samples',True),('city_verified',1),
                        ('city_checkpoint','private-code'),('city_visible_rows',9)]:
            value = ready_city()
            value['navigation'][key] = bad
            with self.assertRaises(ValueError):
                city.validate(value)

    def test_no_extra_private_values(self):
        value = ready_city()
        value['navigation']['geo_id'] = 'PRIVATE-CODE'
        with self.assertRaises(ValueError):
            city.validate(value)

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

    def test_uses_actual_records_and_complete_visible_results_only(self):
        source = city.build('Псков')
        for text in ('get_GeoID','get_RecordType','OnCellSelected','citySignature(f,entry,m)',
                     'city-query-changed','city-ambiguous','count!==total','cityFingerprint',
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
            self.assertIs(inspect.call_args.kwargs['validator'],city.validate)
            self.assertEqual(inspect.call_args.kwargs['timeout'],40)


@contextmanager
def gui(consent=True):
    import assistant_app as app
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
            self.assertEqual(value['messages_sent'],0)
            self.assertFalse(value['chat_content_read'])
            self.assertNotIn('geo_id',value)
            online.assert_not_called()
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
