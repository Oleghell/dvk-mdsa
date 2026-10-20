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

    def test_bad_interval_and_broken_settings_fail_closed(self):
        for seconds in (True,0,29,3601,'120'):
            with self.assertRaises(StateError):cfg.Settings(reply_interval=seconds).check()
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'workflow-settings.json'
            p.write_text('PRIVATE_CORRUPT')
            with self.assertRaises(StateError) as error:cfg.load(temp)
            self.assertNotIn('PRIVATE',str(error.exception))


class CompactWindow(unittest.TestCase):
    def test_only_three_main_buttons_and_no_startup_activity(self):
        import sys
        import assistant_app as app
        tk,ttk=MagicMock(),MagicMock()
        tk.ttk=ttk
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog}), \
             patch.object(app,'load',return_value=cfg.Settings()), \
             patch.object(app,'start_cycle') as start, \
             patch.object(app.telegram_notify,'load') as credentials, \
             patch.object(app.telegram_notify,'send') as telegram, \
             patch.object(app.threading,'Thread') as thread:
            app.launch()
            labels=[c.kwargs.get('text') for c in ttk.Button.call_args_list]
            self.assertEqual(labels,['Старт','Стоп','Настройки'])
            start.assert_not_called();credentials.assert_not_called();telegram.assert_not_called();thread.assert_not_called()


class NavigationReadiness(unittest.TestCase):
    def test_cancelled_preflight_reads_no_apk(self):
        stopped=threading.Event();stopped.set()
        with patch.object(cycle,'write_report') as collect:
            self.assertEqual(cycle.start(cfg.Settings(),stopped)['status'],'cancelled')
        collect.assert_not_called()

    def test_catalogue_success_is_not_live_navigation_success(self):
        with patch.object(cycle,'operation_lock'), \
             patch.object(cycle,'write_report',return_value=(dict(status='catalog-ready'),Path('messages-navigation-definitions.json'))):
            result=cycle.start(cfg.Settings(),threading.Event())
        self.assertEqual(result['status'],'navigation-required')
        self.assertFalse(result['live_cycle_available'])

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


if __name__=='__main__':unittest.main()
