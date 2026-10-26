"""Configurable reply pacing: migration, settings UI and cancellable delays."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

import assistant_authorization as auth
import assistant_settings as cfg
from assistant_store import StateError
import test_mumu1314_key_ui as ui


class Settings(unittest.TestCase):
    def test_default_and_roundtrip_boundaries(self):
        self.assertEqual(cfg.Settings().typing_words_per_minute, 35)
        for speed in (1, 35, 70, 300):
            with self.subTest(speed=speed), tempfile.TemporaryDirectory() as folder:
                value = cfg.Settings(typing_words_per_minute=speed)
                cfg.save(value, folder)
                self.assertEqual(cfg.load(folder), value)
                saved = json.loads(Path(folder, 'workflow-settings.json').read_text())
                self.assertEqual(saved['settings_version'], 9)
                self.assertEqual(saved['typing_words_per_minute'], speed)

    def test_old_schemas_default_to_35_without_losing_provider(self):
        for schema in range(1, 8):
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as folder:
                value = dict(settings_version=schema, contacts_enabled=False, reply_interval=5)
                if schema >= 4:
                    value.update(ai_provider='openrouter', openrouter_model='fixture/model:free')
                Path(folder, 'workflow-settings.json').write_text(json.dumps(value))
                loaded = cfg.load(folder)
                self.assertEqual(loaded.typing_words_per_minute, 35)
                self.assertEqual(loaded.ai_provider, 'openrouter' if schema >= 4 else 'groq')

    def test_invalid_values_are_rejected_before_save_and_in_worker(self):
        for speed in (0, -1, 301, True, False, 35.5, '70', None):
            with self.subTest(speed=speed):
                with self.assertRaises(StateError):
                    cfg.Settings(typing_words_per_minute=speed).check()
                with self.assertRaises(ValueError):
                    auth.RunAuthorization(threading.Event(), words_per_minute=speed)
                with tempfile.TemporaryDirectory() as folder:
                    with self.assertRaises(StateError):
                        cfg.save(cfg.Settings(typing_words_per_minute=speed), folder)
                    self.assertFalse(Path(folder, 'workflow-settings.json').exists())

    def test_schema8_requires_valid_explicit_speed(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg.save(cfg.Settings(), folder)
            file = Path(folder, 'workflow-settings.json')
            value = json.loads(file.read_text())
            for speed in (None, True, 0, 301, '70'):
                value['typing_words_per_minute'] = speed
                file.write_text(json.dumps(value))
                with self.assertRaises(StateError):
                    cfg.load(folder)
            value.pop('typing_words_per_minute')
            file.write_text(json.dumps(value))
            with self.assertRaises(StateError):
                cfg.load(folder)


class Pacing(unittest.TestCase):
    def test_selected_speed_changes_actual_wait_for_all_reply_kinds(self):
        for speed in (1, 35, 70, 300):
            for kind in ('question', 'contact', 'clarify', 'followup'):
                with self.subTest(speed=speed, kind=kind):
                    waits = []
                    permit = auth.RunAuthorization(threading.Event(), words_per_minute=speed,
                        wait=lambda seconds: waits.append(seconds) or False, immediate_greeting=True)
                    self.assertTrue(permit(kind, ' '.join(['слово'] * 35), lambda: False))
                    self.assertAlmostEqual(sum(waits), 35 * 60 / speed, places=6)
                    waits.clear()
                    self.assertTrue(permit('greeting', 'Привет', lambda: False))
                    self.assertEqual(waits, [])

    def test_slow_typing_is_still_cancellable_in_quarter_second_steps(self):
        wait = MagicMock(return_value=True)
        permit = auth.RunAuthorization(threading.Event(), words_per_minute=1, wait=wait)
        self.assertFalse(permit('question', 'Тест отмены', lambda: False))
        wait.assert_called_once_with(0.25)


class SpeedUI(unittest.TestCase):
    setUp = ui.KeyTab.setUp
    command = ui.KeyTab.command

    def speed(self):
        tabs = {c.kwargs['text']: c.args[0] for c in self.ttk.Notebook.return_value.add.call_args_list}
        entries = [c.kwargs['textvariable'] for c in self.ttk.Entry.call_args_list
                   if c.args[0] is tabs['Поиск и ответы']]
        return entries[-1]

    def test_field_saves_and_reopens_and_updates_main_caption(self):
        self.assertEqual(self.speed().get(), '35')
        for call in self.ttk.Checkbutton.call_args_list:
            if call.kwargs.get('text', '').startswith('Telegram:'):
                call.kwargs['variable'].set(False)
        for call in self.ttk.Checkbutton.call_args_list:
            if call.kwargs.get('text','').startswith('Имитировать задержку'):call.kwargs['variable'].set(True)
        self.speed().set('70')
        self.command('Сохранить')()
        self.assertEqual(self.save.call_args.args[0].typing_words_per_minute, 70)
        labels = [c.kwargs['textvariable'] for c in self.ttk.Label.call_args_list if 'textvariable' in c.kwargs]
        self.assertTrue(any('70 слов/мин' in str(v.get()) for v in labels))
        close = next(c.args[1] for c in self.tk.Toplevel.return_value.protocol.call_args_list
                     if c.args[0] == 'WM_DELETE_WINDOW')
        close()
        self.command('Настройки')()
        self.assertEqual(self.speed().get(), '70')
        self.thread.assert_not_called()

    def test_invalid_ui_speed_never_saves(self):
        for speed in ('0', '301', '', 'abc', '1.5'):
            self.speed().set(speed)
            self.command('Сохранить')()
            self.save.assert_not_called()
