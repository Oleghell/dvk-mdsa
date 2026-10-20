"""Synthetic online schema/transport/GUI tests. No Android or user account."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import search_online as online
from test_uikit_navigation import ready_navigation, NavFake


def ready_online():
    out = ready_navigation()
    n = out['navigation']
    n['apply_attempted'] = n.pop('cancel_attempted')
    n['apply_completed'] = n.pop('cancel_completed')
    n.update(online.DEFAULTS)
    n.update(online_before=False, online_set_attempted=True, online_set_completed=True,
             form_refreshed=True, online_verified=True, location_preserved=True,
             settings_checkpoint='complete')
    return out


class OnlineSchema(unittest.TestCase):
    def test_complete_evidence(self):
        value = ready_online()
        self.assertIs(online.validate(value), value)
        self.assertNotIn('cancel_attempted', value['navigation'])

    def test_success_requires_post_apply_evidence(self):
        for key in ('online_verified', 'location_preserved', 'form_refreshed'):
            value = ready_online()
            value['navigation'][key] = False
            with self.assertRaises(ValueError):
                online.validate(value)
        value = ready_online()
        value['navigation']['online_before'] = None
        with self.assertRaises(ValueError):
            online.validate(value)

    def test_typed_flags_and_exact_report_no_private_properties(self):
        for key, bad in [('online_before', 1), ('online_verified', 'true'),
                         ('settings_checkpoint', 'private-city'), ('form_refreshed', 1)]:
            value = ready_online()
            value['navigation'][key] = bad
            with self.assertRaises(ValueError):
                online.validate(value)
        value = ready_online()
        value['navigation']['city_name'] = 'PRIVATE'
        with self.assertRaises(ValueError):
            online.validate(value)

    def test_no_missing_or_out_of_order_evidence(self):
        for key in online.DEFAULTS:
            value = ready_online()
            del value['navigation'][key]
            with self.assertRaises(ValueError):
                online.validate(value)
        value = ready_online()
        value['navigation']['online_set_attempted'] = False
        with self.assertRaises(ValueError):
            online.validate(value)

    def test_no_refresh_after_uncompleted_setter(self):
        value = ready_online()
        value['navigation']['online_set_completed'] = False
        with self.assertRaises(ValueError):
            online.validate(value)

    def test_already_enabled_does_not_require_setter(self):
        value = ready_online()
        value['navigation'].update(online_before=True, online_set_attempted=False, online_set_completed=False)
        online.validate(value)

    def test_fixed_actions_no_message_or_city_selection(self):
        s = online.FUNCTION
        for required in ('OnApplyButton', 'set_OnlineOnly', 'ApplySearchFilter', 'm_PeopleFilterViewController',
                         'm_SearchCM', 'onlineSignature(f,entry,m)', 'checkView(people)',
                         "['card','origin','onlineCM']", 'get_GeoCode', 'get_RegionCode'):
            self.assertIn(required, s)
        for prohibited in ('call(s.cancel,', 'OnOnlineSwitch', 'set_GeoCode', 'set_RegionCode',
                           'UseCurrentLocation', 'OnSendText', 'OnMessageButton', 'set_Text',
                           'OnResetButton', 'OnContactButton', 'rpc.exports', '5555', 'input tap', 'setInterval'):
            self.assertNotIn(prohibited, s)


class OnlineFake(NavFake):
    def create_script(self, source, name):
        super().create_script(source, name)
        self.exports_sync.root = ready_online
        return self


class OnlineTransport(unittest.TestCase):
    def test_exact_source_and_cleanup(self):
        f = OnlineFake()
        value = online.inspect(37149, 'a' * 64, lambda: False, frida_api=f)
        self.assertTrue(value['navigation']['online_verified'])
        self.assertIn(online.FUNCTION, f.script_source)
        self.assertNotIn('selectedpeer', f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)

    def test_invalid_evidence_cleans_and_never_retries(self):
        f = OnlineFake()
        create = f.create_script
        root = MagicMock(return_value={'private': 'bad report'})
        def invalid(*a, **kw):
            result = create(*a, **kw)
            f.exports_sync.root = root
            return result
        f.create_script = invalid
        with self.assertRaises((ValueError, KeyError)):
            online.inspect(37149, 'a' * 64, lambda: False, frida_api=f)
        root.assert_called_once()
        self.assertTrue(f.script_unloaded and f.detached and f.removed)

    def test_run_uses_shared_lock_and_target_only_capture(self):
        with patch('assistant_lock.operation_lock') as lock, patch('one_chat_device.capture') as capture:
            online.run('ADB', 'APK', lambda: False)
            lock.return_value.__enter__.assert_called_once()
            self.assertIs(capture.call_args.kwargs['inspector'], online.inspect)
            self.assertEqual(capture.call_args.args[:2], ('ADB', 'APK'))


@contextmanager
def gui(consent=True):
    import assistant_app as app
    tk, ttk = MagicMock(), MagicMock()
    tk.ttk = ttk
    tk.StringVar.return_value.get.return_value = 'C:/private/test-apks'
    tk.BooleanVar.return_value.get.return_value = consent
    with tempfile.TemporaryDirectory() as folder, \
         patch.dict(sys.modules, {'tkinter': tk, 'tkinter.ttk': ttk,
                    'tkinter.filedialog': tk.filedialog, 'tkinter.messagebox': tk.messagebox}), \
         patch.object(app, 'data_directory', return_value=Path(folder)), \
         patch.object(app, 'enable_online', return_value=ready_online()) as native, \
         patch.object(app, 'run') as profiles, patch.object(app.threading, 'Thread') as thread:
        app.launch()
        commands = {c.kwargs.get('text'): c.kwargs.get('command') for c in ttk.Button.call_args_list}
        poll = next(c.args[1] for c in tk.Tk.return_value.after.call_args_list
                    if len(c.args) == 2 and getattr(c.args[1], '__name__', '') == 'poll')
        yield tk, commands, poll, thread, native, profiles, Path(folder)


class OnlineButton(unittest.TestCase):
    def test_no_autostart_and_requires_consent(self):
        with gui(consent=False) as (tk, commands, poll, thread, native, profiles, folder):
            native.assert_not_called()
            thread.assert_not_called()
            commands['Включить только онлайн']()
            thread.assert_not_called()
            native.assert_not_called()
            profiles.assert_not_called()
            tk.messagebox.showinfo.assert_called_once()

    def test_explicit_start_busy_guard_and_private_free_report(self):
        with gui() as (tk, commands, poll, thread, native, profiles, folder):
            commands['Включить только онлайн']()
            self.assertEqual(thread.call_args.kwargs['target'].__name__, 'online_worker')
            commands['Проверить одну анкету']()
            commands['Подготовить настройки поиска']()
            commands['Включить только онлайн']()
            thread.return_value.start.assert_called_once()
            thread.call_args.kwargs['target']('ADB', 'APKS')
            native.assert_called_once()
            profiles.assert_not_called()
            poll()
            report = json.loads((folder / 'last-search-settings.json').read_text(encoding='utf-8'))
            self.assertTrue(report['online_verified'] and report['location_preserved'])
            self.assertFalse(report['city_selected'] or report['chat_content_read'])
            self.assertEqual(report['messages_sent'], 0)
            self.assertNotIn('C:/private', json.dumps(report))

    def test_native_error_never_exports_exception_or_reports_success(self):
        with gui() as (tk, commands, poll, thread, native, profiles, folder):
            native.side_effect = RuntimeError('SECRET-PRIVATE-CITY')
            commands['Включить только онлайн']()
            thread.call_args.kwargs['target']('ADB', 'APKS')
            poll()
            text = str(tk.StringVar.return_value.set.call_args_list)
            self.assertNotIn('SECRET-PRIVATE-CITY', text)
            self.assertIn('изменения могли успеть примениться', text)
            self.assertFalse((folder / 'last-search-settings.json').exists())
            profiles.assert_not_called()


if __name__ == '__main__':
    unittest.main()
