"""Synthetic privacy/contact policy and DPAPI-outbox tests; no network."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from shared_contact import self_shared, payload
from assistant_chain import Chain, step
from assistant_store import Store, StateError
import telegram_notify
from test_assistant_chain import WHO, GREETING, msg, snap


def seal(data):
    return bytes(b ^ 77 for b in data)


class ContactPolicy(unittest.TestCase):
    def test_explicit_ownership_or_direct_contact_response(self):
        for text, requested, expected in (
            ('мой тг @myhandle', False, ['@myhandle']),
            ('Вот мой номер +7 (999) 123-45-67', False, ['+79991234567']),
            ('@myhandle', True, ['@myhandle']),
            ('https://t.me/myhandle', True, ['@myhandle']),
            ('тг: @myhandle', True, ['@myhandle']),
            ('+7 (999) 123-45-67', True, ['+79991234567']),
            ('Привет', True, []), ('да', True, []), ('нет', True, []),
            ('@myhandle', False, []), ('это не мой @myhandle', True, []),
            ('номер моей подруги +79991234567', True, []),
            ('мой друг @otherguy', True, []), ('мой бывший @otherguy', True, []),
            ('мой номер заказа 89991234567', True, []), ('твой номер +79991234567?', True, []),
            ('например @myhandle', True, []), ('> мой тг @myhandle', True, []),
            ('не пиши мне, мой тг @myhandle', True, []),
            ('мой тг @myhandle, не пересылай никому', True, []),
            ('"мой тг @myhandle"', True, []),
            ('@myhandle 1234567890123456', True, []),
        ):
            with self.subTest(text=text):
                self.assertEqual(self_shared(text, requested=requested), expected)

    def test_name_and_payload_are_bounded_plain_text(self):
        self.assertEqual(payload(' Анна ', ['@myhandle']), dict(name='Анна', contacts=['@myhandle']))
        for name, items in [('', ['@myhandle']), ('x\nPRIVATE', ['@myhandle']), ('x'*129, ['@myhandle']), ('Анна', ['not a contact'])]:
            with self.assertRaises(ValueError):
                payload(name, items)

    def test_telegram_formats_only_name_and_contact_no_history(self):
        data = dict(name='Анна', contacts=['@myhandle'])
        with patch.object(telegram_notify, 'send', return_value=True) as send:
            self.assertTrue(telegram_notify.send_contact('token', '123', data))
        text = send.call_args.args[2]
        self.assertIn('Анна', text)
        self.assertIn('@myhandle', text)
        self.assertNotIn('identity', text)
        with patch.object(telegram_notify, 'send') as send:
            with self.assertRaises(telegram_notify.TelegramError):
                telegram_notify.send_contact('token','123',dict(data,history='PRIVATE'))
            send.assert_not_called()


class ContactOutbox(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'assistant.sqlite3'
        self.store = Store(self.path, Path(self.temp.name) / 'old')
        a = self.store.reserve(dict(attempt=1, account='100', peer='200', chat='-1', variant=0),GREETING,approved=True)
        self.store.finish(a,dict(send_attempted=True,send_handler_returned=True))
        self.chain = Chain(self.store,contact_notifications=True,seal=seal,unseal=seal)

    def shared(self, text='мой тг @privatecontact'):
        return dict(snap(msg(1002,text)),peer_name='ИмяДляТеста')

    def test_one_explicit_contact_sealed_then_once_after_restart(self):
        sender = MagicMock()
        self.assertEqual(step(self.chain,self.shared(),sender),'done')
        sender.assert_not_called()
        for text in ('privatecontact','ИмяДляТеста'):
            self.assertNotIn(text.encode(),self.path.read_bytes())
        notifier = MagicMock(return_value=True)
        def send(data):
            with self.store.connection() as db:
                self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone()[0],'attempted-unknown')
            return True
        notifier.side_effect=send
        self.assertEqual(self.chain.notify(WHO,notifier),'accepted')
        self.assertEqual(self.chain.notify(WHO,notifier),'nothing-pending')
        after = Chain(Store(self.path,Path(self.temp.name)/'old'),contact_notifications=True,seal=seal,unseal=seal)
        self.assertEqual(step(after,self.shared(),sender),'done')
        self.assertEqual(after.notify(WHO,notifier),'nothing-pending')
        notifier.assert_called_once_with(dict(name='ИмяДляТеста',contacts=['@privatecontact']))

    def test_unknown_network_result_never_retries(self):
        step(self.chain,self.shared(),MagicMock())
        notifier=MagicMock(side_effect=TimeoutError('PRIVATE_TOKEN'))
        self.assertEqual(self.chain.notify(WHO,notifier),'unknown')
        self.assertEqual(self.chain.notify(WHO,notifier),'nothing-pending')
        notifier.assert_called_once()
        self.assertNotIn(b'PRIVATE_TOKEN',self.path.read_bytes())

    def test_normal_reply_and_former_generic_queue_never_notify(self):
        step(self.chain,snap(msg(1002,'Привет')),MagicMock())
        with self.store.connection() as db:
            db.execute("INSERT INTO chain_notifications VALUES('300','1002','pending')")
        notifier=MagicMock()
        self.assertEqual(self.chain.notify(WHO,notifier),'nothing-pending')
        notifier.assert_not_called()

    def test_missing_name_or_encryption_failure_prevents_forwarding(self):
        for kind in ('name','encryption'):
            with self.subTest(kind=kind):
                s=self.shared()
                if kind=='name':
                    s.pop('peer_name')
                else:
                    self.chain.seal=MagicMock(side_effect=RuntimeError('PRIVATE'))
                with self.assertRaises(StateError):
                    step(self.chain,s,MagicMock())
                with self.store.connection() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_contact_outbox').fetchone()[0],0)

    def test_disabled_contact_notifications_store_no_payload(self):
        chain=Chain(self.store,contact_notifications=False)
        self.assertEqual(step(chain,self.shared(),MagicMock()),'done')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_contact_outbox').fetchone()[0],0)
        n=MagicMock()
        self.assertEqual(chain.notify(WHO,n),'disabled')
        n.assert_not_called()

    def test_stop_before_network_consumes_reservation_but_does_not_send(self):
        step(self.chain,self.shared(),MagicMock())
        calls=iter((False,True))
        n=MagicMock()
        self.assertEqual(self.chain.notify(WHO,n,lambda:next(calls)),'cancelled')
        n.assert_not_called()
        self.assertEqual(self.chain.notify(WHO,n),'nothing-pending')

    def test_changed_name_or_invalid_decryption_blocks_outbox(self):
        step(self.chain,self.shared(),MagicMock())
        self.chain.unseal=MagicMock(side_effect=ValueError('PRIVATE'))
        n=MagicMock()
        self.assertEqual(self.chain.notify(WHO,n),'blocked')
        n.assert_not_called()


if __name__=='__main__':
    unittest.main()
