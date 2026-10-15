import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import diagnose

IDS = ['1731099842042760', '1731097194660953', '1731097194660954', '1731097194660955']


def entry(phone_id, **updates):
    value = {'id': phone_id, 'supportAdb': True, 'enableAdb': True, 'envStatus': 4,
             'adbIp': 'private-host', 'adbPort': '5555', 'adbPassword': 'SECRET_PASSWORD',
             'command': None, 'remark': None}
    value.update(updates)
    return value


class FakeResponse(io.BytesIO):
    pass


class Tests(unittest.TestCase):
    def config(self, root, base='http://127.0.0.1:8001', ids=None):
        path = root / 'config.json'
        path.write_text(json.dumps({'api_base': base, 'phone_ids': IDS if ids is None else ids}), encoding='utf-8')
        return path

    def test_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = diagnose.load_config(self.config(Path(tmp)))
        self.assertEqual(c['phone_ids'], IDS)

    def test_reject_external_and_ambiguous_urls(self):
        urls = ['http://example.org:8001', 'https://127.0.0.1:8001', 'http://127.0.0.1',
                'http://user:pw@127.0.0.1:8001', 'http://127.0.0.1:8001/path',
                'http://127.0.0.1:8001?key=x', 'http://127.0.0.1:99999']
        with tempfile.TemporaryDirectory() as tmp:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(diagnose.DiagnosticError):
                    diagnose.load_config(self.config(Path(tmp), base=url))

    def test_invalid_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            for ids in [[], ['1', '1'], [123], ['abc'], ['１２３']]:
                with self.subTest(ids=ids), self.assertRaises(diagnose.DiagnosticError):
                    diagnose.load_config(self.config(Path(tmp), ids=ids))

    def test_correct_request_and_no_proxy(self):
        with patch('diagnose.build_opener') as builder:
            builder.return_value.open.return_value = FakeResponse(json.dumps({'code': 0, 'data': []}).encode())
            self.assertEqual(diagnose.fetch_adb_info({'api_base': 'http://127.0.0.1:8001', 'phone_ids': IDS}), [])
            request = builder.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1:8001/api/cloudphone/batchAdbInfo')
            self.assertEqual(json.loads(request.data), {'envIds': IDS})
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(builder.call_args.args[0].proxies, {})

    def test_ready_direct(self):
        phones = diagnose.safe_phone_report(IDS, [entry(x) for x in reversed(IDS)])
        self.assertEqual([x['phone_id'] for x in phones], IDS)
        self.assertTrue(all(x['ready'] for x in phones))
        text = json.dumps(phones)
        self.assertNotIn('SECRET_PASSWORD', text)
        self.assertNotIn('private-host', text)

    def test_tunnel(self):
        report = diagnose.safe_phone_report(['1'], [entry('1', adbIp=None, adbPort=None, command='SECRET_SSH')])[0]
        self.assertTrue(report['ready'])
        self.assertEqual(report['connection_mode'], 'ssh_tunnel')
        self.assertNotIn('SECRET_SSH', json.dumps(report))

    def test_partial_failure(self):
        data = [entry(IDS[0], enableAdb=False), entry(IDS[1], envStatus=2),
                entry(IDS[2], supportAdb=False)]
        phones = diagnose.safe_phone_report(IDS, data)
        self.assertFalse(any(x['ready'] for x in phones))
        self.assertIn('missing_result', phones[3]['issues'])

    def test_duplicate_and_remote_remark_not_echoed(self):
        report = diagnose.safe_phone_report(['1', '2'], [entry('1'), entry('1'), entry('2', remark='SECRET_DETAIL')])
        self.assertIn('duplicate_result', report[0]['issues'])
        self.assertFalse(report[1]['ready'])
        self.assertNotIn('SECRET_DETAIL', json.dumps(report))

    def test_business_error_never_echoes_remote_message(self):
        with patch('diagnose.build_opener') as builder:
            builder.return_value.open.return_value = FakeResponse(b'{"code":123,"msg":"SECRET_ERROR"}')
            with self.assertRaises(diagnose.DiagnosticError) as error:
                diagnose.fetch_adb_info({'api_base': 'http://127.0.0.1:8001', 'phone_ids': IDS})
            self.assertNotIn('SECRET_ERROR', str(error.exception))

    def test_http_auth(self):
        with patch('diagnose.build_opener') as builder:
            builder.return_value.open.side_effect = HTTPError('local', 401, 'SECRET_HTTP', {}, None)
            with self.assertRaises(diagnose.DiagnosticError) as error:
                diagnose.fetch_adb_info({'api_base': 'http://127.0.0.1:8001', 'phone_ids': IDS})
            self.assertNotIn('SECRET_HTTP', str(error.exception))

    def test_invalid_responses(self):
        for raw in [b'not-json', b'[]', b'{"code":false,"data":[]}', b'{"code":0,"data":{}}', b'{"code":0,"data":[1]}', b'x' * (diagnose.MAX_RESPONSE + 1)]:
            with self.subTest(raw_size=len(raw)), patch('diagnose.build_opener') as builder:
                builder.return_value.open.return_value = FakeResponse(raw)
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose.fetch_adb_info({'api_base': 'http://127.0.0.1:8001', 'phone_ids': IDS})

    def test_main_report_sanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.config(root)
            report = root / 'diagnostic.json'
            with patch('diagnose.fetch_adb_info', return_value=[entry(x) for x in IDS]), patch('diagnose.check_adb', return_value={'installed': False}), redirect_stdout(io.StringIO()) as console:
                code = diagnose.main(['--config', str(config), '--report', str(report)])
            self.assertEqual(code, 0)
            saved = report.read_text(encoding='utf-8')
            for secret in ['SECRET_PASSWORD', 'private-host', 'adbPassword']:
                self.assertNotIn(secret, saved + console.getvalue())
            self.assertFalse(json.loads(saved)['chat_automation_implemented'])

    def test_no_adb(self):
        with patch('diagnose.shutil.which', return_value=None):
            self.assertFalse(diagnose.check_adb()['installed'])

    def test_redirects_disabled(self):
        self.assertIsNone(diagnose.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://example.org'))


if __name__ == '__main__':
    unittest.main()
