import json,tempfile,unittest
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import patch
import telegram_notify as p
TOKEN='123456:'+('a'*35)
class Telegram(unittest.TestCase):
    def test_encrypted_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'token.dpapi'
            p.save(TOKEN,'98765',path,encoder=lambda b:bytes(x^42 for x in b))
            self.assertNotIn(TOKEN.encode(),path.read_bytes())
            self.assertEqual(p.load(path,decoder=lambda b:bytes(x^42 for x in b)),(TOKEN,'98765'))
    def test_protection_failure_never_writes_plaintext(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'token'
            with self.assertRaises(p.TelegramError):p.save(TOKEN,'98765',path,encoder=lambda b:(_ for _ in ()).throw(p.TelegramError('No DPAPI')))
            self.assertFalse(path.exists())
    def test_no_secret_in_exception(self):
        class Opener:
            def open(self,request,timeout):raise RuntimeError(request.full_url)
        with self.assertRaises(p.TelegramError) as e:p.send(TOKEN,'98765','Test',opener=Opener())
        self.assertNotIn(TOKEN,str(e.exception));self.assertNotIn(TOKEN,repr(e.exception))
    def test_payload_and_acknowledgement(self):
        requests=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):return b'{"ok":true,"result":{"message_id":1}}'
        class Opener:
            def open(self,r,timeout):requests.append(r);return Response()
        self.assertTrue(p.send(TOKEN,'98765','<b>Name</b>',opener=Opener()))
        self.assertEqual(len(requests),1);self.assertNotIn(b'parse_mode',requests[0].data)
    def test_contact_notification_has_required_text(self):
        requests=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):return b'{"ok":true,"result":{"message_id":1}}'
        class Opener:
            def open(self,r,timeout):requests.append(r);return Response()
        with patch.object(p.urllib.request,'build_opener',return_value=Opener()):
            self.assertTrue(p.send_contact(TOKEN,'98765',
                                           {'name':'Александр','contacts':['@alex_test']}))
        body=parse_qs(requests[0].data.decode())
        self.assertEqual(body['text'],['Новый контакт!\nИмя: Александр\nКонтакт: @alex_test'])
    def test_no_redirect(self):self.assertIsNone(p.NoRedirect().redirect_request(None,None,None,None,None,None))
    def test_invalid_credentials(self):
        for token,chat in [('bad','1'),(TOKEN,'0'),(TOKEN,'https://evil'),(TOKEN+'\n','1')]:
            with self.assertRaises(p.TelegramError):p.credentials(token,chat)

class WindowsDPAPI(unittest.TestCase):
    @unittest.skipUnless(__import__('os').name=='nt','Windows current-user DPAPI only')
    def test_real_current_user_encryption(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'settings.dpapi';p.save(TOKEN,'98765',path)
            self.assertNotIn(TOKEN.encode(),path.read_bytes());self.assertEqual(p.load(path),(TOKEN,'98765'))
