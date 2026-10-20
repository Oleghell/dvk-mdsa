"""Synthetic APK definitions only; no installed app, ADB or user account."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

import search_catalog as search
from offline_metadata import Metadata31
from test_friends_catalog import metadata_fixture, bundle


def fixture():
    defs = [
        ('DV.Search.dll', 'DV.Search', 'SearchTabController', [('ShowSearchSettings', 0, False, 108)]),
        ('DV.Search.dll', 'DV.Search', 'SearchSettingsCardController', [
            ('get_Settings', 0, False, 102), ('OnOnlyOnlineChanged', 1, False, 108),
            ('OnLocationRequested', 0, False, 108), ('Apply', 0, False, 108)]),
        ('DV.dll', 'DV.Models', 'SearchOptions', [
            ('get_OnlyOnline', 0, False, 105), ('set_OnlyOnline', 1, False, 108)]),
        ('DV.Geo.dll', 'DV.Geo', 'City', [('get_Id', 0, False, 106), ('get_Name', 0, False, 107)]),
        ('DV.Geo.dll', 'DV.Geo', 'CitiesService', [('FindCities', 1, False, 103)]),
        ('mscorlib.dll', 'System', 'Boolean', []), ('mscorlib.dll', 'System', 'Int64', []),
        ('mscorlib.dll', 'System', 'String', []), ('mscorlib.dll', 'System', 'Void', []),
        ('DV.Messages.dll', 'DV.Messages', 'Chat', [('get_PrivateMessage', 0, False, 107)]),
        ('Other.dll', 'Private', 'SearchCookie', [('get_PrivateToken', 0, False, 107)])]
    fields = {0: [('m_Settings', 102)], 1: [('m_Location', 103)],
              2: [('m_OnlyOnline', 105), ('m_Location', 103)]}
    data = bytearray(metadata_fixture(defs, fields))
    methods = Metadata31(bytes(data)).methods
    h = struct.unpack_from('<64I', data)
    parameters = bytearray()
    cursor = 0
    for index, method in enumerate(methods):
        struct.pack_into('<i', data, h[12] + index * 36 + 16,
                         cursor if method['parameter_count'] else -1)
        for _ in range(method['parameter_count']):
            kind = 107 if method['name'] == 'FindCities' else 105
            parameters.extend(struct.pack('<IIi', 0, 0x08000001, kind))
            cursor += 1
    struct.pack_into('<II', data, 22 * 4, len(data), len(parameters))
    data.extend(parameters)
    return data


class SearchDefinitions(unittest.TestCase):
    def test_actual_definitions_and_parameter_types_not_guessed(self):
        out = search.collect(Metadata31(bytes(fixture())))
        self.assertTrue(all(r['status'] == 'found' for r in out['roots']))
        self.assertFalse(out['truncated'])
        controller = next(t for t in out['types'] if t['type'] == 'SearchSettingsCardController')
        method = next(m for m in controller['methods'] if m['method'] == 'OnOnlyOnlineChanged')
        self.assertEqual(method['parameters'][0]['target']['type'], 'Boolean')
        model = next(t for t in out['types'] if t['type'] == 'SearchOptions')
        self.assertIn('get_OnlyOnline', [m['method'] for m in model['methods']])
        self.assertIn('City', [t['type'] for t in out['types']])
        text = json.dumps(out)
        for token in ('PRIVATE-CHAT-TOKEN', 'PrivateMessage', 'PrivateToken', 'SearchCookie'):
            self.assertNotIn(token, text)

    def test_no_actions_no_data_no_gadget_config_opened(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            hashes = bundle(folder, bytes(fixture()))
            opened = []
            original = zipfile.ZipFile.open
            def open_entry(archive, name, *args, **kwargs):
                opened.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
                return original(archive, name, *args, **kwargs)
            with patch.object(zipfile.ZipFile, 'open', open_entry):
                out = search.inspect_bundle(folder, expected_hashes=hashes)
            self.assertEqual(out['review_status'], 'definitions-collected')
            self.assertTrue(opened and all(name.endswith('/global-metadata.dat') for name in opened))
            for flag in ('ui_actions_attempted', 'method_values_read', 'adb_used', 'emulator_contacted',
                         'chat_content_read', 'gadget_config_read', 'personal_data_exported',
                         'search_settings_applied', 'online_verified', 'city_verified'):
                self.assertIs(out[flag], False, flag)
            self.assertEqual(out['messages_sent'], 0)
            self.assertNotIn(str(folder), json.dumps(out))
            self.assertNotIn('PRIVATE-CHAT', json.dumps(out))

    def test_missing_ambiguous_and_truncated_are_not_ready(self):
        metadata = Metadata31(bytes(fixture()))
        metadata.types[1]['name'] = 'UnknownController'
        out = search.collect(metadata)
        self.assertEqual(out['roots'][1]['status'], 'missing')
        metadata = Metadata31(bytes(fixture()))
        metadata.types[0]['name'] = 'SearchSettingsCardController'
        out = search.collect(metadata)
        self.assertEqual(out['roots'][1]['status'], 'ambiguous')
        metadata = Metadata31(bytes(fixture()))
        with patch.object(search, 'MAX_TYPES', 1):
            self.assertTrue(search.collect(metadata)['truncated'])
        with patch.object(search, 'MAX_TOTAL_METHODS', 2), patch.object(search, 'MAX_TOTAL_FIELDS', 1):
            out = search.collect(metadata)
            self.assertLessEqual(out['exported_totals']['methods'], 2)
            self.assertLessEqual(out['exported_totals']['fields'], 1)
            self.assertTrue(out['truncated'])
        with patch.object(search, 'MAX_PARAMETERS', 0):
            out = search.collect(metadata)
            self.assertTrue(any(m['parameters_truncated'] for n in out['types'] for m in n['methods']))

    def test_cancel_during_collection_does_not_export_partial_result(self):
        with self.assertRaises(search.CatalogCancelled):
            search.collect(Metadata31(bytes(fixture())), lambda: True)
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            hashes = bundle(folder, bytes(fixture()))
            calls = 0
            def cancel():
                nonlocal calls
                calls += 1
                return calls > 20
            out = search.inspect_bundle(folder, cancel, hashes)
            self.assertEqual((out['status'], out['reason'], out['catalog']), ('catalog-stopped', 'cancelled', None))
            self.assertNotIn('PRIVATE', json.dumps(out))

    def test_bad_hash_and_corrupt_parameter_layout_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            hashes = bundle(folder, bytes(fixture()))
            out = search.inspect_bundle(folder, expected_hashes={**hashes, 'base.apk': '0' * 64})
            self.assertEqual(out['reason'], 'apk-hash-mismatch')
            self.assertIsNone(out['catalog'])
            data = fixture()
            struct.pack_into('<I', data, 22 * 4, 256)
            hashes = bundle(folder, bytes(data))
            out = search.inspect_bundle(folder, expected_hashes=hashes)
            self.assertEqual(out['reason'], 'metadata-unsupported-or-invalid')
            self.assertIsNone(out['catalog'])

    def test_atomic_safe_filename_and_no_private_path_or_text(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / 'PRIVATE_test_apks'
            source.mkdir()
            hashes = bundle(source, bytes(fixture()))
            target = folder / 'reports'
            with patch('friends_catalog.HASHES', hashes):
                out, path = search.write_report(source, destination=target)
            self.assertEqual(path.name, 'search-settings-definitions.json')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), out)
            self.assertFalse(path.with_suffix('.tmp').exists())
            self.assertNotIn('PRIVATE', path.read_text(encoding='utf-8'))
            self.assertNotIn(str(folder), path.read_text(encoding='utf-8'))
            with patch('friends_catalog.HASHES', hashes), patch.object(search, 'MAX_REPORT_BYTES', 2000):
                stopped, _ = search.write_report(source, destination=target)
            self.assertEqual(stopped['reason'], 'report-size-limit')
            self.assertIsNone(stopped['catalog'])

    def test_late_cancel_never_reports_completed_collection(self):
        ready = dict(status='catalog-ready', catalog={'fake': 'definitions'}, review_status='definitions-collected')
        with tempfile.TemporaryDirectory() as folder, patch.object(search, 'inspect_bundle', return_value=ready):
            out, path = search.write_report(folder, lambda: True, destination=folder)
            self.assertEqual(out['reason'], 'cancelled')
            self.assertIsNone(out['catalog'])
            self.assertNotIn('fake', path.read_text(encoding='utf-8'))

    def test_failed_write_does_not_replace_previous_report(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            path = folder / 'search-settings-definitions.json'
            path.write_text('previous', encoding='utf-8')
            with patch.object(search, 'inspect_bundle', return_value={'status': 'catalog-stopped'}), \
                 patch.object(Path, 'replace', side_effect=OSError('PRIVATE')):
                with self.assertRaises(OSError):
                    search.write_report(folder, destination=folder)
            self.assertEqual(path.read_text(encoding='utf-8'), 'previous')
            self.assertFalse(path.with_suffix('.tmp').exists())


class SearchButton(unittest.TestCase):
    def test_same_window_explicit_start_no_consent_to_read_chats_or_native_actions(self):
        import assistant_legacy as app
        tk, ttk = MagicMock(), MagicMock()
        tk.ttk = ttk
        tk.StringVar.return_value.get.return_value = 'C:/private/test-apks'
        tk.BooleanVar.return_value.get.return_value = False
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(sys.modules, {'tkinter': tk, 'tkinter.ttk': ttk,
                        'tkinter.filedialog': tk.filedialog, 'tkinter.messagebox': tk.messagebox}), \
             patch.object(app, 'data_directory', return_value=Path(folder)), \
             patch.object(app, 'prepare_search_report', return_value=({'status': 'catalog-ready'}, Path(folder) / 'search-settings-definitions.json')) as prepare, \
             patch.object(app, 'run') as native, patch.object(app.threading, 'Thread') as thread, \
             patch('os.startfile', create=True, side_effect=OSError('synthetic missing shell')):
            app.launch()
            prepare.assert_not_called()
            native.assert_not_called()
            thread.assert_not_called()
            commands = {c.kwargs.get('text'): c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Подготовить настройки поиска']()
            self.assertEqual(thread.call_args.kwargs['target'].__name__, 'search_worker')
            worker = thread.call_args.kwargs['target']
            worker('C:/private/test-apks')
            prepare.assert_called_once()
            native.assert_not_called()
            tk.messagebox.showinfo.assert_not_called()
            commands['Проверить одну анкету']()
            thread.return_value.start.assert_called_once()
            # Deliver the worker's result through the real GUI queue handler.
            poll = next(c.args[1] for c in tk.Tk.return_value.after.call_args_list
                        if len(c.args) == 2 and getattr(c.args[1], '__name__', '') == 'poll')
            poll()
            self.assertTrue(any('Эта подготовка не изменяет город и фильтры' in str(c)
                                for c in tk.StringVar.return_value.set.call_args_list))
            native.assert_not_called()
            commands['Открыть сведения']()
            tk.messagebox.showinfo.assert_called_once()


if __name__ == '__main__':
    unittest.main()
