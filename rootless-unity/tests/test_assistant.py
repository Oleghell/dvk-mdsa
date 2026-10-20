import copy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import assistant_config as config
import assistant_pass as manual
from assistant_store import Store, StateError
from assistant_lock import operation_lock
from test_chat_batch import cycle


def pending(**changes):
    result = dict(attempt=1, account='100', peer='200', chat='-1', variant=0)
    result.update(changes)
    return result


class Configuration(unittest.TestCase):
    def test_spec_lists_and_unicode(self):
        c = config.load()
        self.assertEqual((len(c.cities), len(c.greetings)), (30, 30))
        self.assertIn('Петропавловск-Камчатский', c.cities)
        self.assertIn(c.greeting(), c.greetings)

    def test_editable_and_invalid_configs_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'cities.json').write_text('{"cities":["Нальчик"]}', encoding='utf-8')
            file = folder / 'greetings.json'
            for value in ([], [''], [' A'], ['A\nB'], ['X', 'X'], [5], ['a' * 257]):
                file.write_text(json.dumps({'greetings': value}), encoding='utf-8')
                with self.assertRaises(config.ConfigError):
                    config.load(folder)
            file.write_text('{"greetings":["Привет 🌷"]}', encoding='utf-8-sig')
            self.assertEqual(config.load(folder).greetings, ('Привет 🌷',))
            file.write_text('{"greetings":["A"],"greetings":["B"]}', encoding='utf-8')
            with self.assertRaises(config.ConfigError):
                config.load(folder)
            file.unlink()
            with self.assertRaises(config.ConfigError):
                config.load(folder)


class DurableAuthorization(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.legacy = self.folder / 'old'
        self.legacy.mkdir()
        self.path = self.folder / 'assistant.sqlite3'
        self.store = Store(self.path, self.legacy)

    def test_only_explicit_approval_and_no_bodies(self):
        for approval in (False, None, 1, 'yes'):
            with self.assertRaises(StateError):
                self.store.reserve(pending(), 'PRIVATE_HELLO', approved=approval)
        action = self.store.reserve(pending(), 'PRIVATE_HELLO', approved=True)
        self.assertEqual(action, 1)
        self.assertNotIn(b'PRIVATE_HELLO', self.path.read_bytes())
        self.assertNotIn('200', json.dumps(self.store.summary()))
        for chat in ('-1', '42'):
            with self.assertRaises(StateError):
                Store(self.path, self.legacy).reserve(pending(chat=chat), 'Hello', approved=True)

    def test_unknown_not_invoked_and_returned_all_block_retries(self):
        for number, (attempted, returned) in enumerate(((False, False), (True, False), (True, True)), 1):
            p = pending(peer=str(300 + number))
            action = self.store.reserve(p, 'Hi', approved=True)
            status = self.store.finish(action, dict(send_attempted=attempted, send_handler_returned=returned))
            self.assertIn(status, self.store.summary()['statuses'])
            with self.assertRaises(StateError):
                Store(self.path, self.legacy).reserve(p, 'Hi', approved=True)
        self.assertFalse(self.store.summary()['delivery_confirmed'])
        with self.assertRaises(StateError):
            self.store.finish(999, dict(send_attempted=True, send_handler_returned=True))

    def test_legacy_cohort_is_respected(self):
        with closing(sqlite3.connect(self.legacy / 'new-ten.sqlite3')) as db:
            db.isolation_level = None
            db.execute('CREATE TABLE bindings(account TEXT,peer TEXT)')
            db.execute("INSERT INTO bindings VALUES('100','200')")
        with self.assertRaises(StateError):
            self.store.reserve(pending(), 'Hi', approved=True)
        self.assertEqual(self.store.summary()['reserved'], 0)

    def test_legacy_one_chat_is_respected_and_never_modified(self):
        path = self.legacy / 'one-chat-check.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            db.isolation_level = None
            db.execute('CREATE TABLE test_manual_send(status TEXT)')
            db.execute("INSERT INTO test_manual_send VALUES('reserved-unknown')")
            db.execute('CREATE TABLE test_meta(key TEXT,value TEXT)')
            db.execute('INSERT INTO test_meta VALUES(?,?)', ('identity', json.dumps(dict(account='100', peer='200', chat='300'))))
        before = path.read_bytes()
        with self.assertRaises(StateError):
            self.store.reserve(pending(), 'Hi', approved=True)
        self.assertEqual(before, path.read_bytes())

    def test_corrupt_existing_legacy_fails_closed(self):
        (self.legacy / 'new-ten.sqlite3').write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.reserve(pending(), 'Hi', approved=True)
        self.assertEqual(self.store.summary()['reserved'], 0)

    def test_device_lock_and_release_on_error(self):
        path = self.folder / 'operation.lock'
        with operation_lock(path):
            with self.assertRaises(StateError):
                with operation_lock(path):
                    self.fail('Second lock acquired')
        with self.assertRaises(RuntimeError):
            with operation_lock(path):
                raise RuntimeError()
        with operation_lock(path):
            pass


class ManualGate(unittest.TestCase):
    def test_no_ack_on_rejection_cancellation_or_failed_commit(self):
        for approved, cancelled, fail in ((False, False, False), (True, True, False), (True, False, True)):
            script, store, approve = MagicMock(), MagicMock(), MagicMock(return_value=approved)
            script.exports_sync.cohortpending.return_value = pending()
            done = MagicMock()
            done.wait.return_value = False
            done.is_set.return_value = False
            state = {}
            if fail:
                store.reserve.side_effect = OSError('PRIVATE')
            manual.monitor(script, store, 'Hi', approve, done, lambda: cancelled, state)
            script.exports_sync.cohortack.assert_not_called()
            if not approved or cancelled:
                store.reserve.assert_not_called()
            self.assertNotIn('PRIVATE', json.dumps(state))

    def test_commit_before_ack_exactly_once(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'assistant.sqlite3', Path(folder) / 'old')
            script = MagicMock()
            script.exports_sync.cohortpending.return_value = pending()
            def ack(value):
                self.assertEqual(store.summary()['reserved'], 1)
                self.assertEqual(value, pending())
                return True
            script.exports_sync.cohortack.side_effect = ack
            done = threading.Event()
            state = {}
            manual.monitor(script, store, 'Hi', lambda *args: True, done, lambda: False, state)
            script.exports_sync.cohortack.assert_called_once()
            self.assertEqual(state, {'action_id': 1})

    def test_stale_reply_after_operation_end_cannot_authorize(self):
        script, store = MagicMock(), MagicMock()
        script.exports_sync.cohortpending.return_value = pending()
        done = threading.Event()
        def approve(*args):
            done.set()
            return True
        manual.monitor(script, store, 'Hi', approve, done, lambda: False, {})
        store.reserve.assert_not_called()
        script.exports_sync.cohortack.assert_not_called()

    def test_new_text_is_json_data_and_native_single_cycle(self):
        text = 'Привет "🌷" \\ ${not_code}'
        source = manual.build(text)
        self.assertIn('batchAttempts>=1', source)
        self.assertNotIn('batchAttempts>=10', source)
        self.assertIn('"cycle_timeout_ms":90000', source)
        self.assertIn("finish('callback-timeout');},90000);", source)
        self.assertIn('const batchGreetings=' + json.dumps([text] * 10), source)
        self.assertLess(source.index('cohortApproved!==reservationKey'), source.index('batchSent.add(batchCandidateKey)'))
        self.assertLess(source.index('batchSent.add(batchCandidateKey)'), source.index('call(s.send,current,args)'))
        for phrase in ('Memory.scan', 'input tap', 'get_PhoneNumber', 'set_Text'):
            self.assertNotIn(phrase, source)

    def test_validator_preserves_safety_and_only_changes_timeout_copy(self):
        value = cycle()
        value['navigation']['cycle_timeout_ms'] = 90000
        before = copy.deepcopy(value)
        self.assertIs(manual.validate(value), value)
        self.assertEqual(value, before)
        for field, bad in (('cycle_timeout_ms', 30000), ('history_fully_loaded', False),
                           ('chat_identity_verified', False), ('friends_count', 50), ('messages_sent', 1)):
            broken = copy.deepcopy(value)
            broken['navigation'][field] = bad
            with self.assertRaises(ValueError, msg=field):
                manual.validate(broken)

    def test_transport_uses_existing_target_only_capture_not_legacy_diagnose(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('one_chat_device.capture', return_value='ok') as capture, \
                 patch('assistant_lock.operation_lock') as lock:
                self.assertEqual(manual.run('adb', folder, 'Hi', lambda *args: False, store=MagicMock()), 'ok')
                lock.assert_called_once()
                self.assertEqual(capture.call_args.args[:2], ('adb', Path(folder).resolve()))
            (Path(folder) / '.dvk-ten-profile-pass.lock').write_text('reserved')
            with patch('one_chat_device.capture') as capture:
                with self.assertRaises(StateError):
                    manual.run('adb', folder, 'Hi', lambda *args: True)
                capture.assert_not_called()


class MainWindow(unittest.TestCase):
    def test_opening_window_and_declining_consent_never_start_transport(self):
        import sys
        import assistant_legacy as app
        tk, ttk = MagicMock(), MagicMock()
        tk.ttk = ttk
        tk.BooleanVar.return_value.get.return_value = False
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(sys.modules, {'tkinter': tk, 'tkinter.ttk': ttk,
                        'tkinter.filedialog': tk.filedialog, 'tkinter.messagebox': tk.messagebox}), \
             patch.object(app, 'data_directory', return_value=Path(folder)), \
             patch.object(app, 'run') as transport, patch.object(app.threading, 'Thread') as thread:
            app.launch()
            transport.assert_not_called()
            thread.assert_not_called()
            commands = {c.kwargs.get('text'): c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Проверить одну анкету']()
            thread.assert_not_called()
            transport.assert_not_called()
            commands['Стоп']()
            transport.assert_not_called()

    def test_working_paths_are_prefilled_and_saved_choices_override_defaults(self):
        import sys
        import assistant_legacy as app
        self.assertEqual(app.DEFAULT_ADB, 'C:/Users/XXX/Desktop/platform-tools/adb.exe')
        self.assertEqual(app.DEFAULT_TEST_APKS, 'C:/Users/XXX/Desktop/spam-dvk-main/test-apks')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            for saved in (None, {'adb': 'D:/tools/adb.exe', 'test_apks': 'D:/private/test-apks'},
                          {'adb': '', 'test_apks': ''}):
                if saved is not None:
                    path.write_text(json.dumps(saved), encoding='utf-8')
                tk, ttk = MagicMock(), MagicMock()
                tk.ttk = ttk
                with patch.dict(sys.modules, {'tkinter': tk, 'tkinter.ttk': ttk,
                                'tkinter.filedialog': tk.filedialog, 'tkinter.messagebox': tk.messagebox}), \
                     patch.object(app, 'data_directory', return_value=Path(folder)), \
                     patch.object(app, 'run') as transport, patch.object(app.threading, 'Thread') as thread:
                    app.launch()
                    tk.StringVar.assert_any_call(value=app.DEFAULT_ADB)
                    tk.StringVar.assert_any_call(value=app.DEFAULT_TEST_APKS)
                    if saved and saved['adb']:
                        tk.StringVar.return_value.set.assert_any_call('D:/tools/adb.exe')
                        tk.StringVar.return_value.set.assert_any_call('D:/private/test-apks')
                    else:
                        self.assertNotIn(unittest.mock.call(''), tk.StringVar.return_value.set.call_args_list)
                    transport.assert_not_called()
                    thread.assert_not_called()

    def test_packaged_config_is_external_next_to_exe(self):
        import sys
        with tempfile.TemporaryDirectory() as folder, patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(Path(folder) / 'DvkAssistant.exe')):
            self.assertEqual(config.config_directory(), Path(folder).resolve() / 'config')


class ProfileJournal(unittest.TestCase):
    def test_seen_profiles_survive_restart_without_bodies(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'assistant.sqlite3'
            store = Store(path, Path(folder) / 'old')
            self.assertEqual(store.visited_peers(), [])
            n = cycle(97)['navigation']
            store.record_visit('9', n)
            self.assertEqual(Store(path).visited_peers(), ['9'])
            source = manual.build('Hi', ['9'])
            self.assertIn('batchSeen=new Set(["9"])', source)
            with self.assertRaises(Exception):
                manual.build('Hi', ['9;evil()'])
            n['profile_verified'] = False
            store.record_visit('10', n)
            self.assertEqual(store.visited_peers(), ['9'])

    def test_reservations_are_excluded_even_if_result_was_lost(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'assistant.sqlite3', Path(folder) / 'old')
            store.reserve(pending(), 'Hi', approved=True)
            self.assertEqual(store.visited_peers(), ['200'])


class TargetTransport(unittest.TestCase):
    def test_new_run_uses_only_existing_restricted_target_and_cleans_forward(self):
        from test_target_only import TargetOnly
        from test_device import TARGET, WORKING
        fixture = TargetOnly('test_preflight_works_without_working_instance')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with fixture.patched(), patch('one_chat_device.TargetOnlyAdb', return_value=fixture.adb), \
             patch('one_chat_device.bundle_token', return_value='a' * 64), \
             patch('assistant_lock.operation_lock'), patch.object(manual, 'inspect', return_value='result') as inspector:
            result = manual.run('adb', fixture.folder, 'Hi', lambda *args: False, store=MagicMock())
            self.assertEqual(result, 'result')
            self.assertFalse(any(WORKING in args for args in fixture.calls))
            self.assertIn(['-s', TARGET, 'forward', '--remove', 'tcp:37149'], fixture.calls)
            inspector.assert_called_once()


if __name__ == '__main__':
    unittest.main()
