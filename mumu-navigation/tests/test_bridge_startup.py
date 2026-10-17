"""One local consent prepares the complete bridge, never starts messaging."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
import bridge_startup as startup
from mumu_bridge import BridgeError


class DiscoverAdbTests(unittest.TestCase):
    def test_bundled_adb_is_found_without_running_any_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            adb=Path(tmp)/'adb.exe';adb.touch()
            with patch('subprocess.run') as run:
                self.assertEqual(startup.discover_adb(tmp,environ={},which=lambda _:None),str(adb.resolve()))
                run.assert_not_called()
    def test_path_adb_and_known_mumu_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);adb=root/'Programs'/'Netease'/'MuMuPlayer-12.0'/'shell'/'adb.exe'
            adb.parent.mkdir(parents=True);adb.touch()
            self.assertEqual(startup.discover_adb(root/'empty',environ={'ProgramFiles':str(root/'Programs')},which=lambda _:None),str(adb.resolve()))
            self.assertEqual(startup.discover_adb(root/'empty',environ={},which=lambda n:str(adb) if n=='adb.exe' else None),str(adb.resolve()))
    def test_missing_adb_returns_none_not_a_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(startup.discover_adb(tmp,environ={'USERPROFILE':tmp},which=lambda _:None))
    def test_user_desktop_platform_tools_are_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            adb=Path(tmp)/'Desktop'/'platform-tools'/'adb.exe';adb.parent.mkdir(parents=True);adb.touch()
            self.assertEqual(startup.discover_adb(Path(tmp)/'empty',environ={'USERPROFILE':tmp},which=lambda _:None),str(adb.resolve()))


class PrepareDeviceTests(unittest.TestCase):
    def setUp(self):
        self.facade=Mock();self.reader=self.facade.inner;self.reader.control_enabled=False
        self.cancelled=threading.Event();self.progress=Mock();self.events=[]
        self.patches=[patch('bridge_startup.content_pixel_sha256'),patch('bridge_startup.install_helper_with_local_consent'),patch('universal_control.enable_locally'),patch('universal_control.stop_locally'),patch('universal_control.UniversalControl')]
        self.image,self.install,self.enable,self.stop,self.control=[p.start() for p in self.patches]
        self.facade.connect.side_effect=lambda:self.events.append('connect')
        self.reader.screen.side_effect=lambda:self.events.append('screen') or b'png'
        self.install.side_effect=lambda reader,base,confirm:self.events.append('install') or self.assertIs(confirm(),True)
        def enable(*args):self.events.append('enable');self.reader.control_enabled=True
        self.enable.side_effect=enable
        self.control.return_value.inspect.side_effect=lambda:self.events.append('inspect') or {'focused':False}
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
    def run_prepare(self,consent=True):
        return startup.prepare_device(self.facade,Path('.'),self.cancelled,self.progress,consent=consent)
    def test_single_consent_prepares_everything_before_public_server(self):
        self.run_prepare()
        self.assertEqual(self.events,['connect','screen','install','enable','inspect'])
        self.stop.assert_not_called();self.assertTrue(self.reader.control_enabled)
        self.facade.ledger.start.assert_not_called();self.facade.execute_control.assert_not_called()
    def test_exact_boolean_local_consent_required(self):
        for value in (False,None,1,'yes'):
            with self.assertRaises(BridgeError):self.run_prepare(value)
        self.facade.connect.assert_not_called();self.install.assert_not_called();self.enable.assert_not_called()
    def test_cancel_before_start_has_no_device_action(self):
        self.cancelled.set()
        with self.assertRaises(BridgeError):self.run_prepare()
        self.facade.connect.assert_not_called()
    def test_wrong_app_or_screen_never_installs_or_switches_keyboard(self):
        self.image.side_effect=BridgeError('wrong screen')
        with self.assertRaises(BridgeError):self.run_prepare()
        self.install.assert_not_called();self.enable.assert_not_called();self.stop.assert_not_called()
    def test_install_failure_does_not_enable_or_retry(self):
        self.install.side_effect=BridgeError('install refused')
        with self.assertRaises(BridgeError):self.run_prepare()
        self.assertEqual(self.install.call_count,1);self.enable.assert_not_called()
    def test_cancel_after_install_does_not_switch_keyboard(self):
        self.install.side_effect=lambda *a:self.cancelled.set()
        with self.assertRaises(BridgeError):self.run_prepare()
        self.enable.assert_not_called()
    def test_cancel_after_enable_restores_keyboard(self):
        def enable(*args):self.reader.control_enabled=True;self.cancelled.set()
        self.enable.side_effect=enable
        with self.assertRaises(BridgeError):self.run_prepare()
        self.stop.assert_called_once_with(self.reader,self.facade.ledger)
        self.control.assert_not_called()
    def test_inspection_failure_restores_keyboard_without_retry(self):
        self.control.return_value.inspect.side_effect=BridgeError('inspect refused')
        with self.assertRaises(BridgeError):self.run_prepare()
        self.assertEqual(self.control.return_value.inspect.call_count,1)
        self.stop.assert_called_once_with(self.reader,self.facade.ledger)
    def test_failed_restore_tells_user_to_restore_keyboard_manually(self):
        self.control.return_value.inspect.side_effect=BridgeError('inspect refused')
        self.stop.side_effect=BridgeError('private raw output')
        with self.assertRaises(BridgeError) as caught:self.run_prepare()
        self.assertIn('настройки Android',str(caught.exception));self.assertNotIn('private',str(caught.exception))
    def test_consent_names_scope_and_narrow_replacement(self):
        self.assertLessEqual(len(startup.STARTUP_CONSENT),760)
        for text in ('Cloudflare','Скриншоты, OCR, CV','платные','журналы','Остановить доступ','Клавиатура не меняется'):
            self.assertIn(text,startup.STARTUP_CONSENT)


if __name__=='__main__':unittest.main()
