"""Synthetic automatic-chain tests. No real account, bodies or Telegram network."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from assistant_store import Store, StateError
from assistant_chain import Chain, step, run, QUESTIONS, CONTACT_TEXT
from assistant_pass import run_automatic
import one_chat_send as sender
import one_chat_send_device as transport

WHO = dict(account='100', peer='200', chat='300')
GREETING = 'Привет 🙂'


def msg(i, text, own=False):
    return dict(id=str(i), sender='100' if own else '200', text=text)


def snap(*messages):
    return dict(identity=dict(WHO), messages=[msg(1001, GREETING, True), *messages])


class AutomaticChain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'assistant.sqlite3'
        self.store = Store(self.path, Path(self.tmp.name) / 'old')
        action = self.store.reserve(dict(attempt=1, account='100', peer='200', chat='-1', variant=0), GREETING, approved=True)
        self.store.finish(action, dict(send_attempted=True, send_handler_returned=True))
        self.chain = Chain(self.store, choose=lambda: 0)
        self.sent = []

    def send(self, before, text):
        with self.store.connection() as db:
            # Durable reservation is visible through a separate connection.
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chain_actions WHERE status='reserved-unknown'").fetchone()[0], 1)
        self.sent.append(text)
        return dict(attempted=True, handler_returned=True)

    def test_complete_chain_observes_each_own_before_next_incoming(self):
        self.assertEqual(step(self.chain, snap(), self.send), 'wait-reply')
        reply = msg(1002, 'Привет!')
        self.assertEqual(step(self.chain, snap(reply), self.send), 'await-outgoing')
        question = msg(1003, QUESTIONS[0], True)
        self.assertEqual(step(self.chain, snap(reply, question), self.send), 'wait-mood')
        mood = msg(1004, 'Отлично!')
        self.assertEqual(step(self.chain, snap(reply, question, mood), self.send), 'await-outgoing')
        contact = msg(1005, CONTACT_TEXT, True)
        self.assertEqual(step(self.chain, snap(reply, question, mood, contact), self.send), 'wait-contact')
        last = msg(1006, '@privateperson')
        self.assertEqual(step(self.chain, snap(reply, question, mood, contact, last), self.send), 'done')
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])
        self.assertNotIn(b'privateperson', self.path.read_bytes())
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_notifications').fetchone()[0], 0)

    def test_no_incoming_no_action_and_collection_order_is_irrelevant(self):
        self.assertEqual(step(self.chain, snap(), self.send), 'wait-reply')
        self.assertEqual(step(self.chain, snap(), self.send), 'wait-reply')
        s = snap(msg(2, 'Привет'))
        s['messages'].reverse()
        self.assertEqual(step(self.chain, s, self.send), 'await-outgoing')
        self.assertEqual(self.sent, [QUESTIONS[0]])

    def test_restart_never_retries_pending_or_unknown_send(self):
        before = snap(msg(1002, 'Привет'))
        def lost(*args):
            raise TimeoutError('PRIVATE_TOKEN_OR_BODY')
        self.assertEqual(step(self.chain, before, lost), 'submission-unknown')
        other = Chain(Store(self.path, Path(self.tmp.name) / 'old'))
        self.assertEqual(step(other, before, self.send), 'pending-question')
        self.assertFalse(self.sent)
        self.assertNotIn(b'PRIVATE_TOKEN_OR_BODY', self.path.read_bytes())

    def test_no_false_delivery_when_handler_did_not_attempt(self):
        result = step(self.chain, snap(msg(1002, 'Привет')), lambda *a: dict(attempted=False, handler_returned=True))
        self.assertEqual(result, 'submission-unknown')

    def test_stop_before_read_and_after_reservation_never_sends(self):
        before = snap(msg(1002, 'Привет'))
        self.assertEqual(step(self.chain, before, self.send, lambda: True), 'cancelled')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_actions').fetchone()[0], 0)
        calls = iter((False, True))
        self.assertEqual(step(self.chain, before, self.send, lambda: next(calls)), 'cancelled')
        self.assertEqual(step(self.chain, before, self.send), 'pending-question')
        self.assertFalse(self.sent)

    def test_refusal_negative_question_media_and_multiple_stop(self):
        for incoming, expected in [([msg(1002, 'Не пиши мне')], 'declined'),
                                    ([msg(1002, 'плохо')], 'manual-review'),
                                    ([msg(1002, 'Кто ты?')], 'manual-review'),
                                    ([msg(1002, None)], 'manual-review'),
                                    ([msg(1002, 'Привет'), msg(1003, 'Как дела?')], 'manual-review')]:
            with self.subTest(incoming=incoming):
                with self.store.connection() as db:
                    for table in ('chain_dialogs','chain_seen','chain_actions','chain_notifications'):
                        db.execute('DELETE FROM ' + table)
                self.assertEqual(step(self.chain, snap(*incoming), self.send), expected)
        self.assertFalse(self.sent)

    def test_pending_new_incoming_or_simultaneous_deltas_never_advance(self):
        before = snap(msg(1002, 'Привет'))
        step(self.chain, before, self.send)
        self.assertEqual(step(self.chain, snap(msg(1002, 'Привет'), msg(1003, 'Отлично')), self.send), 'manual-review')
        self.assertEqual(len(self.sent), 1)

    def test_edited_or_missing_old_messages_stop(self):
        step(self.chain, snap(), self.send)
        edited = snap(msg(1002, 'Привет'))
        edited['messages'][0]['text'] = 'changed'
        self.assertEqual(step(self.chain, edited, self.send), 'manual-review')
        self.assertFalse(self.sent)

    def test_unrelated_chat_not_authorized_and_server_binding_fixed(self):
        for field in ('account', 'peer'):
            who = dict(WHO, **{field: '999'})
            with self.assertRaises(StateError):
                self.chain.authorized(who)
        step(self.chain, snap(), self.send)
        with self.assertRaises(StateError):
            self.chain.authorized(dict(WHO, chat='301'))

    def test_unverified_or_extra_greeting_cannot_enroll(self):
        for s in (dict(identity=WHO, messages=[msg(1001, 'OTHER', True)]),
                  snap(msg(1002, 'Own intervention', True))):
            with self.assertRaises(StateError):
                step(self.chain, s, self.send)
        self.assertFalse(self.sent)

    def test_notification_at_most_once_and_contains_no_private_content(self):
        step(self.chain, snap(msg(1002, 'Привет')), self.send)
        notifier = MagicMock(side_effect=TimeoutError('PRIVATE_TOKEN'))
        self.assertEqual(self.chain.notify(WHO, notifier), 'disabled')
        self.assertEqual(Chain(self.store).notify(WHO, notifier), 'disabled')
        notifier.assert_not_called()
        self.assertNotIn(b'PRIVATE_TOKEN', self.path.read_bytes())

    def test_no_network_when_notifications_disabled(self):
        step(self.chain, snap(msg(1002, 'Привет')), self.send)
        self.assertEqual(self.chain.notify(WHO, None), 'disabled')

    def test_poll_identity_check_precedes_bodies_and_unknown_never_read(self):
        identity_only = dict(identity=dict(WHO, peer='201'), messages=None)
        capture = MagicMock(return_value=identity_only)
        with patch('assistant_lock.operation_lock'):
            with self.assertRaises(StateError):
                run('adb', self.tmp.name, threading.Event(), store=self.store, capture=capture)
        capture.assert_called_once()
        self.assertEqual(len(capture.call_args.args), 3)

    def test_poll_stops_on_ambiguous_reply_without_sender(self):
        capture = MagicMock(side_effect=[dict(identity=WHO, messages=None), snap(msg(1002, 'Кто ты?'))])
        submit = MagicMock()
        with patch('assistant_lock.operation_lock'):
            result = run('adb', self.tmp.name, threading.Event(), store=self.store, capture=capture, submit=submit)
        self.assertEqual(result['state'], 'manual-review')
        submit.assert_not_called()
        self.assertEqual(capture.call_args.args[3], WHO)

    def test_corrupt_saved_stage_and_simultaneous_incoming_do_not_send(self):
        step(self.chain, snap(), self.send)
        with self.store.connection() as db:
            db.execute("UPDATE chain_dialogs SET stage='unknown'")
        with self.assertRaises(StateError):
            step(self.chain, snap(msg(1002,'Привет')), self.send)
        with self.store.connection() as db:
            db.execute("UPDATE chain_dialogs SET stage='wait-reply'")
        step(self.chain, snap(msg(1002,'Привет')), self.send)
        self.assertEqual(step(self.chain, snap(msg(1002,'Привет'),msg(1003,QUESTIONS[0],True),msg(1004,'Хорошо')),self.send),'manual-review')
        self.assertEqual(self.sent,[QUESTIONS[0]])

    def test_initial_stop_does_not_touch_device(self):
        stopped = threading.Event(); stopped.set()
        capture = MagicMock()
        with patch('assistant_lock.operation_lock'):
            self.assertEqual(run('adb', self.tmp.name, stopped, store=self.store, capture=capture)['state'], 'cancelled')
        capture.assert_not_called()


class AutomaticGreetingAndNativeReply(unittest.TestCase):
    def test_one_run_opt_in_required_and_cancelled_authority_false(self):
        for enabled in (False, None, 1, 'yes'):
            with patch('assistant_pass.run') as native:
                with self.assertRaises(StateError):
                    run_automatic('adb','folder',GREETING,enabled=enabled)
                native.assert_not_called()
        with patch('assistant_pass.run', return_value='done') as native:
            self.assertEqual(run_automatic('adb','folder',GREETING,enabled=True),'done')
            approve = native.call_args.args[3]
            self.assertTrue(approve({},GREETING,lambda:False))
            self.assertFalse(approve({},GREETING,lambda:True))

    def test_only_whitelisted_replies_keep_fresh_history_and_native_latch(self):
        before = snap(msg(1002,'Привет'))
        for text in (*QUESTIONS, CONTACT_TEXT):
            source = sender.build(before, text=text)
            self.assertIn(json.dumps(text),source)
            self.assertIn('canonical(messages)!==canonical(',source)
            self.assertIn("if(entry===s.submit){if(oneSubmissionAttempted)",source)
            self.assertLess(source.index('oneSubmissionAttempted=true'),source.index('const out=f.invoke(m,receiver,params,ex);'))
            self.assertEqual(source.count('call(s.submit,current,args)'),1)
        with self.assertRaises(ValueError):
            sender.build(before,text='arbitrary')
        with patch.object(transport,'capture') as capture:
            with self.assertRaises(ValueError):
                transport.submit('adb','folder',before,text='arbitrary')
            capture.assert_not_called()


class AutomaticWindow(unittest.TestCase):
    def test_opening_mode_or_declining_opt_in_does_not_touch_device_or_telegram(self):
        import sys
        import assistant_legacy as app
        tk, ttk = MagicMock(), MagicMock()
        tk.ttk = ttk
        tk.BooleanVar.return_value.get.return_value = False
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(sys.modules, {'tkinter': tk, 'tkinter.ttk': ttk,
                        'tkinter.filedialog': tk.filedialog, 'tkinter.messagebox': tk.messagebox}), \
             patch.object(app, 'data_directory', return_value=Path(directory)), \
             patch.object(app, 'run') as manual, \
             patch.object(app, 'run_automatic') as automatic, \
             patch.object(app, 'run_chain') as chain, \
             patch.object(app.telegram_notify, 'load') as credentials, \
             patch.object(app.telegram_notify, 'send') as telegram, \
             patch.object(app.threading, 'Thread') as thread:
            app.launch()
            commands = {c.kwargs.get('text'): c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Автоцепочка и Telegram']()
            commands = {c.kwargs.get('text'): c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Одно приветствие без подтверждения']()
            commands['Запустить автоцепочку открытого чата']()
            for forbidden in (manual, automatic, chain, credentials, telegram, thread):
                forbidden.assert_not_called()


if __name__ == '__main__':
    unittest.main()
