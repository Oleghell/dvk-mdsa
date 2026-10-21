"""The compact entry is honest about the missing live dialog navigator."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import assistant_settings as cfg
import assistant_cycle as cycle
import dialog_catalog
import one_chat_probe as reader
from assistant_store import StateError
from test_one_chat import WHO, rpc
from test_chat_catalog import fixture
from test_friends_catalog import bundle
from offline_metadata import Metadata31


class Settings(unittest.TestCase):
    def test_migrates_paths_and_keeps_token_out_of_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            (path/'settings.json').write_text(json.dumps(dict(adb='D:/adb.exe',test_apks='D:/apks')))
            settings=cfg.load(path)
            self.assertEqual(settings.adb,'D:/adb.exe')
            self.assertFalse(settings.contacts_enabled)
            cfg.save(cfg.Settings(settings.adb,settings.folder,True,120),path)
            self.assertTrue(cfg.load(path).contacts_enabled)
            self.assertEqual(set(json.loads((path/'settings.json').read_text())),{'adb','test_apks'})
            self.assertNotIn('token', (path/'workflow-settings.json').read_text())

    def test_default_interval_and_old_default_migrate_to_30(self):
        self.assertEqual(cfg.Settings().reply_interval, 30)
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'workflow-settings.json'
            p.write_text(json.dumps(dict(contacts_enabled=False, reply_interval=120)))
            self.assertEqual(cfg.load(temp).reply_interval, 30)
            cfg.save(cfg.Settings(reply_interval=120), temp)
            self.assertEqual(cfg.load(temp).reply_interval, 120)  # explicit new choice is preserved

    def test_bad_interval_and_broken_settings_fail_closed(self):
        for seconds in (True,0,29,3601,'120'):
            with self.assertRaises(StateError):cfg.Settings(reply_interval=seconds).check()
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'workflow-settings.json'
            p.write_text('PRIVATE_CORRUPT')
            with self.assertRaises(StateError) as error:cfg.load(temp)
            self.assertNotIn('PRIVATE',str(error.exception))


class CompactWindow(unittest.TestCase):
    def test_main_buttons_and_no_startup_activity(self):
        import sys
        import assistant_app as app
        tk,ttk=MagicMock(),MagicMock()
        tk.ttk=ttk
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog}), \
             patch.object(app,'load',return_value=cfg.Settings()), \
             patch.object(app,'monitor') as start, \
             patch.object(app.telegram_notify,'load') as credentials, \
             patch.object(app.telegram_notify,'send') as telegram, \
             patch.object(app.threading,'Thread') as thread:
            app.launch()
            labels=[c.kwargs.get('text') for c in ttk.Button.call_args_list]
            self.assertEqual(labels,['Старт','Только ответы','Стоп','Настройки'])
            start.assert_not_called();credentials.assert_not_called();telegram.assert_not_called();thread.assert_not_called()


    def test_start_is_single_flight_and_stop_requires_explicit_restart(self):
        import sys
        import assistant_app as app
        import assistant_monitor
        tk, ttk = MagicMock(), MagicMock()
        tk.ttk = ttk
        tk.messagebox.askyesno.return_value = True
        stopped_result = dict(assistant_monitor.report('full'), status='cancelled')
        with patch.dict(sys.modules, {'tkinter': tk, 'tkinter.ttk': ttk,
                                     'tkinter.filedialog': tk.filedialog}), \
             patch.object(app, 'load', return_value=cfg.Settings()), \
             patch.object(app, 'save'), \
             patch.object(app, 'monitor', return_value=stopped_result) as monitor, \
             patch.object(app.threading, 'Thread') as thread:
            app.launch()
            commands = {c.kwargs['text']: c.kwargs['command'] for c in ttk.Button.call_args_list}
            poll = tk.Tk.return_value.after.call_args.args[1]
            commands['Старт']()
            commands['Старт']()
            commands['Только ответы']()
            self.assertEqual(thread.call_count, 1)
            commands['Стоп']()
            call = thread.call_args
            call.kwargs['target'](*call.kwargs['args'])
            self.assertTrue(monitor.call_args.args[1].is_set())
            permission = monitor.call_args.args[2]
            self.assertTrue(permission.automatic_send)
            self.assertFalse(permission('greeting', 'Привет', lambda: False))
            tk.Toplevel.assert_not_called()
            poll()
            self.assertEqual(thread.call_count, 1)  # No auto-restart on completion.
            commands['Только ответы']()
            self.assertEqual(thread.call_count, 2)
            self.assertEqual(thread.call_args.kwargs['args'][1], 'inbox')


class NavigationReadiness(unittest.TestCase):
    def test_cancelled_preflight_reads_no_apk(self):
        stopped=threading.Event();stopped.set()
        with patch.object(cycle,'run_route') as collect:
            self.assertEqual(cycle.check_navigation(cfg.Settings(),stopped)['status'],'cancelled')
        collect.assert_not_called()

    def test_route_success_is_not_live_cycle_success(self):
        from test_dialog_navigation import ready_route
        with tempfile.TemporaryDirectory() as temp, patch.object(cycle,'operation_lock'), \
             patch.object(cycle,'data_directory',return_value=Path(temp)), \
             patch.object(cycle,'run_route',return_value=ready_route()):
            result=cycle.check_navigation(cfg.Settings(),threading.Event())
            report=json.loads((Path(temp)/result['report_name']).read_text())
        self.assertEqual(result['status'],'dialog-route-ready')
        self.assertFalse(result['live_cycle_available'])
        self.assertEqual(report['messages_sent'],0)
        self.assertFalse(report['telegram_used'])
        self.assertFalse(report['chat_content_read'])

    def test_collects_only_definitions_from_pinned_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir()
            hashes=bundle(folder,bytes(fixture()))
            report,path=dialog_catalog.write_report(folder,destination=temp,expected_hashes=hashes)
            self.assertEqual(report['status'],'catalog-ready')
            self.assertEqual(path.name,'messages-navigation-definitions.json')
            self.assertFalse(report['adb_used']);self.assertFalse(report['chat_content_read'])
            self.assertFalse(report['live_cycle_available'])
            self.assertNotIn('PRIVATE',path.read_text())
            self.assertNotIn(temp,path.read_text())
            self.assertIn('ChatsViewController',path.read_text())

    def test_incomplete_wrong_hash_or_cancel_are_not_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir()
            hashes=bundle(folder,bytes(fixture()));hashes['base.apk']='0'*64
            report,_=dialog_catalog.write_report(folder,destination=temp,expected_hashes=hashes)
            self.assertEqual(report['status'],'catalog-stopped')
            report,_=dialog_catalog.write_report(folder,lambda:True,destination=temp)
            self.assertEqual(report['reason'],'cancelled')


class BoundName(unittest.TestCase):
    def test_name_is_opt_in_bound_and_stable_before_export(self):
        with self.assertRaises(ValueError):reader.build(read_name=True)
        source=reader.build(WHO,read_name=True)
        self.assertLess(source.index('JSON.stringify(who)!==JSON.stringify(expectedIdentity)'),source.index('const display=call(s.peerName,user)'))
        self.assertIn('peer_name:peerName',source)
        self.assertIn('JSON.stringify(state.sample)!==JSON.stringify(sample)',source)
        self.assertNotIn('get_Name',reader.build(WHO))
        r=rpc();r['navigation']['private_result']['peer_name']='Анна'
        self.assertEqual(reader.private_snapshot(r,WHO,read_name=True)['peer_name'],'Анна')
        with self.assertRaises(ValueError):reader.private_snapshot(r,WHO)
        for name in ('',None,'x'*129,'name\nPRIVATE'):
            r['navigation']['private_result']['peer_name']=name
            with self.assertRaises(ValueError):reader.private_snapshot(r,WHO,read_name=True)




class RunAuthorization(unittest.TestCase):
    def test_known_actions_only_and_stop_revokes_permission(self):
        from assistant_authorization import RunAuthorization, flags
        stopped = threading.Event()
        permit = RunAuthorization(stopped)
        self.assertEqual(flags(permit), dict(per_message_confirmation=False, automatic_send=True))
        for kind in ('greeting', 'question', 'contact'):
            self.assertTrue(permit(kind, 'text', lambda: False))
        self.assertFalse(permit('arbitrary', 'text', lambda: False))
        self.assertFalse(permit('greeting', '', lambda: False))
        self.assertFalse(permit('greeting', 'text', lambda: True))
        stopped.set()
        self.assertFalse(permit('greeting', 'text', lambda: False))


if __name__=='__main__':unittest.main()


class GroqSettings(unittest.TestCase):
    def test_new_fields_roundtrip_without_key(self):
        with tempfile.TemporaryDirectory() as temp:
            value=cfg.Settings(groq_enabled=True,groq_model='llama-3.3-70b-versatile',errors_enabled=True)
            cfg.save(value,temp);self.assertEqual(cfg.load(temp),value)
            saved=Path(temp,'workflow-settings.json').read_text()
            self.assertNotIn('gsk_',saved);self.assertNotIn('api_key',saved)
            self.assertEqual(json.loads(saved)['settings_version'],4)
    def test_old_settings_migrate_with_ai_off_and_error_notifications_on(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp,'workflow-settings.json').write_text(json.dumps(dict(settings_version=2,contacts_enabled=True,reply_interval=30,profile_limit=5)))
            value=cfg.load(temp);self.assertFalse(value.groq_enabled);self.assertTrue(value.errors_enabled)
    def test_bad_model_or_toggle_rejected(self):
        for changes in (dict(groq_enabled=1),dict(errors_enabled='yes'),dict(groq_model='model\nPRIVATE'),dict(groq_model='https://PRIVATE:123')):
            with self.assertRaises(StateError):cfg.Settings(**changes).check()


class PackagedConfiguration(unittest.TestCase):
    def test_manifest_checks_all_external_configuration_and_current_features(self):
        import hashlib
        import build_manifest
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'DvkAssistant.exe').write_bytes(b'synthetic exe')
            (folder/'config').mkdir()
            names=('cities.json', 'greetings.json', 'groq-rules.txt')
            source=Path(__file__).resolve().parents[2]/'config'
            for name in names: (folder/'config'/name).write_bytes((source/name).read_bytes())
            build_manifest.main(folder)
            value=json.loads((folder/'build-manifest.json').read_text())
            self.assertEqual(value['config_sha256'], {name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in names})
            self.assertFalse(value['auto_start']); self.assertTrue(value['explicit_run_confirmation'])
            self.assertFalse(value['per_message_confirmation']); self.assertTrue(value['automatic_send'])
            self.assertTrue(value['features']['read_tracked_dialog_recovery'])
            self.assertEqual(value['features']['profile_interval_seconds'], 120)
            self.assertFalse(value['production_ready'])
            (folder/'config'/'groq-rules.txt').unlink()
            with self.assertRaises(FileNotFoundError): build_manifest.main(folder)
