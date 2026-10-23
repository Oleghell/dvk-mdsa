"""Whole-chain synthetic integration tests. No real accounts or network."""
import copy
import itertools
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import assistant_guided_chain as guided
from assistant_store import Store
from assistant_settings import Settings
from conversation_engine import QUESTIONS, CONTACT_TEXT

WHO = dict(account='100', peer='200', chat='300')
GREETING = 'Привет 🙂'
PEER_NAME = 'Александр'
CONTACT = '@alex_test'


def snapshot(*extra):
    messages = [dict(id='1001', sender='100', text=GREETING)]
    for number, (text, own) in enumerate(extra, 1002):
        messages.append(dict(id=str(number), sender='100' if own else '200', text=text))
    return dict(identity=dict(WHO), messages=messages, peer_name=PEER_NAME)


def fresh_snapshot(message_id='9001', text=GREETING):
    return dict(identity=dict(WHO),
                messages=[dict(id=message_id, sender='100', text=text)])


def sequence(choice=0):
    hello = ('Привет!', False)
    question = (QUESTIONS[choice], True)
    mood = ('Отлично!', False)
    contact = (CONTACT_TEXT, True)
    return [snapshot(), snapshot(hello), snapshot(hello),
            snapshot(hello, question), snapshot(hello, question, mood),
            snapshot(hello, question, mood), snapshot(hello, question, mood, contact),
            snapshot(hello, question, mood, contact, (CONTACT, False))]


def stable_snapshots(values):
    values=list(values)
    return itertools.chain(values,itertools.repeat(copy.deepcopy(values[-1]))) if values and isinstance(values[-1],dict) else iter(values)

class WholeChain(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'assistant.sqlite3'
        self.store = Store(self.path, Path(self.temp.name) / 'old')
        self.stop = threading.Event()
        self.chain = guided.GuidedChain(self.store, choose=lambda: 0,
                                        seal=lambda value: value, unseal=lambda value: value)
        self.approve = MagicMock(return_value=True)
        self.notifier = MagicMock(return_value=True)
        self.sent = []

    def send(self, before, text):
        with self.store.connection() as db:
            kind = 'contact' if text == CONTACT_TEXT else 'question'
            self.assertEqual(db.execute('SELECT status FROM chain_actions WHERE chat=? AND kind=?',
                                        ('300', kind)).fetchone()[0], 'reserved-unknown')
        self.sent.append(text)
        return dict(attempted=True, handler_returned=True)

    def walk(self, history=None, **kwargs):
        defaults = dict(approved=True, greetings=(GREETING,), notifier=self.notifier,
                        pause=lambda _: False, max_polls=12)
        defaults.update(kwargs)
        return guided.walk(self.chain, WHO, self.stop, self.approve,
                           MagicMock(side_effect=stable_snapshots(sequence() if history is None else history)),
                           self.send, **defaults)

    def test_all_stages_in_one_run_both_question_variants(self):
        for choice in (0, 1):
            with self.subTest(choice=choice):
                path = Path(self.temp.name) / f'variant-{choice}.sqlite3'
                store = Store(path, Path(self.temp.name) / 'old')
                chain = guided.GuidedChain(store, choose=lambda: choice,
                                           seal=lambda value: value, unseal=lambda value: value)
                order = []
                def confirm(kind, text, cancelled):
                    order.append(('approved', kind))
                    return True
                def send(before, text):
                    kind = 'contact' if text == CONTACT_TEXT else 'question'
                    order.append(('submitted', kind))
                    with store.connection() as db:
                        self.assertEqual(db.execute('SELECT status FROM chain_actions WHERE kind=?',
                                                    (kind,)).fetchone()[0], 'reserved-unknown')
                    return dict(attempted=True, handler_returned=True)
                def notify(payload):
                    with store.connection() as db:
                        self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='contact'").fetchone()[0],
                                         'outgoing-observed')
                        self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone()[0],
                                         'attempted-unknown')
                    self.assertEqual(payload, dict(name=PEER_NAME, contacts=[CONTACT]))
                    order.append(('notified', 'contact'))
                    return True
                out = guided.walk(chain, WHO, self.stop, confirm,
                                  MagicMock(side_effect=sequence(choice)), send,
                                  approved=True, greetings=(GREETING,), notifier=notify,
                                  pause=lambda _: False, max_polls=12)
                self.assertEqual(out['status'], 'chain-completed')
                self.assertTrue(all(out['stages'].values()))
                self.assertEqual(out['confirmations'], 2)
                self.assertEqual(out['submission_calls'], 2)
                self.assertEqual(out['outgoing_observed'], 2)
                self.assertEqual(out['outgoing_observed_this_run'], 2)
                self.assertEqual(out['handler_returns'], 2)
                self.assertEqual(out['notifications']['accepted'], 1)
                self.assertEqual(order, [('approved', 'question'), ('submitted', 'question'),
                                         ('approved', 'contact'), ('submitted', 'contact'),
                                         ('notified', 'contact')])
                exported = json.dumps(out, ensure_ascii=False)
                for private in ('Привет', 'Отлично', '1001', '300', '"peer":', 'text_hash', 'salt'):
                    self.assertNotIn(private, exported)
                self.assertTrue(out['personal_data_exported'])
                self.assertFalse(out['delivery_confirmed'])
                with store.connection() as db:
                    self.assertEqual(db.execute("SELECT status FROM chain_contact_outbox").fetchone()[0],
                                     'accepted')
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM manual_actions').fetchone()[0], 0)

    def test_full_transport_reads_name_only_after_contact_arrives(self):
        histories = sequence()
        values = [dict(identity=WHO, messages=None)]
        values += [{key: value[key] for key in ('identity', 'messages')}
                   for value in histories]
        values.append(histories[-1])
        reader = MagicMock(side_effect=copy.deepcopy(values))
        sender = MagicMock(return_value=dict(attempted=True, handler_returned=True))
        with patch.object(guided, 'data_directory', return_value=Path(self.temp.name)), \
             patch('assistant_lock.operation_lock'), \
             patch.object(self.stop, 'wait', return_value=False), \
             patch.object(guided.GuidedChain, '__init__', autospec=True,
                          side_effect=lambda obj, store: self.initialize(obj, store)):
            out = guided.run(Settings(contacts_enabled=True), self.stop, self.approve,
                             approved=True, store=self.store, reader=reader, sender=sender,
                             notifier=self.notifier, greetings=(GREETING,))
        self.assertEqual(out['status'], 'chain-completed')
        self.assertIsNone(reader.call_args_list[0].args[3])
        self.assertTrue(all(call.args[3] == WHO and not call.kwargs
                            for call in reader.call_args_list[1:-1]))
        self.assertEqual(reader.call_args_list[-1].args[3], WHO)
        self.assertEqual(reader.call_args_list[-1].kwargs, {'read_name': True})
        self.assertEqual(sender.call_count, 2)
        self.notifier.assert_called_once_with(dict(name=PEER_NAME, contacts=[CONTACT]))
        self.assertEqual(out['report_name'], 'messages-chain-check.json')
        saved = json.loads((Path(self.temp.name) / out['report_name']).read_text())
        self.assertEqual(saved['status'], 'chain-completed')

    def contact_history_without_name(self):
        return [{key: copy.deepcopy(value[key]) for key in ('identity', 'messages')}
                for value in sequence()]

    def test_two_shared_contacts_same_batch_one_notification(self):
        values = sequence()
        values[-1]['messages'].append(dict(id='1007', sender='200', text='+79991234567'))
        out = self.walk(values)
        self.assertEqual(out['status'], 'chain-completed')
        self.notifier.assert_called_once_with(dict(name=PEER_NAME, contacts=[CONTACT, '+79991234567']))
        self.assertEqual(len(self.sent), 2)
        out = self.walk([values[-1]])
        self.assertEqual(out['reason'], 'contact-already-handled')
        self.assertEqual(self.notifier.call_count, 1)

    def test_second_contact_arrives_during_name_lookup(self):
        values = self.contact_history_without_name()
        named = copy.deepcopy(sequence()[-1])
        named['messages'].append(dict(id='1007', sender='200', text='+79991234567'))
        out = self.walk(values, contact_reader=MagicMock(return_value=named))
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(out['diagnostics']['name_source'], 'bound-chat')
        self.notifier.assert_called_once_with(dict(name=PEER_NAME, contacts=[CONTACT, '+79991234567']))

    def test_unavailable_name_rechecks_history_and_uses_honest_label(self):
        values = self.contact_history_without_name()
        values.append(copy.deepcopy(values[-1]))
        out = self.walk(values, contact_reader=MagicMock(side_effect=ValueError('PRIVATE_BODY_TOKEN')))
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(out['diagnostics']['name_source'], 'unavailable-label')
        self.notifier.assert_called_once_with(dict(name='не определено', contacts=[CONTACT]))
        self.assertNotIn('PRIVATE', json.dumps(out))
        self.assertNotIn(CONTACT, json.dumps(out))

    def test_name_failure_never_bypasses_changed_chat_on_plain_reread(self):
        values = self.contact_history_without_name()
        changed = copy.deepcopy(values[-1])
        changed['identity']['peer'] = '201'
        values.append(changed)
        out = self.walk(values, contact_reader=MagicMock(side_effect=RuntimeError('PRIVATE')))
        self.assertEqual(out['reason'], 'guided-binding-changed')
        self.assertFalse(out['telegram_used'])
        self.notifier.assert_not_called()

    def test_name_lookup_cannot_edit_or_truncate_previous_messages(self):
        values = self.contact_history_without_name()
        named = copy.deepcopy(sequence()[-1])
        named['messages'][0]['text'] = 'changed'
        out = self.walk(values, contact_reader=MagicMock(return_value=named))
        self.assertEqual(out['reason'], 'guided-contact-history-changed')
        self.assertEqual(out['diagnostics']['failure_point'], 'guided-contact-history-changed')
        self.notifier.assert_not_called()

    def test_encryption_failure_has_distinct_reason_no_name_fallback(self):
        self.chain.seal = MagicMock(side_effect=RuntimeError('PRIVATE_ENCRYPTION'))
        names = MagicMock()
        out = self.walk(contact_reader=names)
        self.assertEqual(out['reason'], 'contact-protection-failed')
        self.assertFalse(out['telegram_used'])
        self.notifier.assert_not_called()
        names.assert_not_called()
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_transient_loading_retries_only_read_then_sends_each_action_once(self):
        from one_chat_device import ReadStopped
        loading = ReadStopped('history-not-ready', dict(read_checkpoint='loaded-flag',
                              wait_reason='history-loading', private_text='PRIVATE'))
        out = self.walk([loading] + sequence())
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(out['diagnostics']['read_retries'], 1)
        self.assertEqual(len(self.sent), 2)
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_repeated_loading_stops_without_send_or_unbounded_retry(self):
        from one_chat_device import ReadStopped
        loading = ReadStopped('history-not-ready', dict(wait_reason='history-loading'))
        out = self.walk([loading, loading])
        self.assertEqual(out['reason'], 'bound-chat-read-failed')
        self.assertEqual(out['diagnostics']['read_retries'], 1)
        self.assertEqual(self.sent, [])

    def test_identity_failure_is_not_retried(self):
        from one_chat_device import ReadStopped
        reader = MagicMock(side_effect=ReadStopped('identity-not-bound'))
        out = guided.walk(self.chain, WHO, self.stop, self.approve, reader, self.send,
                          approved=True, greetings=(GREETING,), notifier=self.notifier)
        self.assertEqual(out['reason'], 'bound-chat-read-failed')
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(self.sent, [])

    def test_reader_failure_has_transport_category_without_private_error(self):
        from one_chat_device import ReadStopped
        reader = MagicMock(side_effect=ReadStopped('PRIVATE_ERROR'))
        out = guided.walk(self.chain, WHO, self.stop, self.approve, reader, self.send,
                          approved=True, greetings=(GREETING,), notifier=self.notifier)
        self.assertEqual(out['reason'], 'bound-chat-read-failed')
        self.assertNotIn('PRIVATE', json.dumps(out))
        self.notifier.assert_not_called()

    def test_resume_saved_wait_contact_after_name_error_without_resend(self):
        values = sequence()[:-1]
        self.walk(values + [values[-1]] * 12)
        private = self.contact_history_without_name()[-1]
        with self.assertRaisesRegex(guided.StateError, 'contact-name-required'):
            self.chain.proposal(private)
        self.chain = guided.GuidedChain(self.store, seal=lambda value: value, unseal=lambda value: value)
        out = self.walk([private, private], contact_reader=MagicMock(side_effect=ValueError('PRIVATE')))
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])
        self.notifier.assert_called_once_with(dict(name='не определено', contacts=[CONTACT]))

    @staticmethod
    def initialize(obj, store):
        ORIGINAL_INIT(obj, store, choose=lambda: 0,
                      seal=lambda value: value, unseal=lambda value: value)

    def test_no_approval_no_device_credentials_or_store(self):
        with patch('one_chat_device.capture') as read, patch('telegram_notify.load') as credentials, \
             patch.object(guided, 'Store') as store:
            out = guided.run(Settings(contacts_enabled=True), self.stop, self.approve)
        self.assertEqual(out['reason'], 'guided-consent-required')
        read.assert_not_called()
        credentials.assert_not_called()
        store.assert_not_called()

    def test_read_only_binding_does_not_authorize_chain(self):
        from assistant_read_binding import ReadBindings
        ReadBindings(self.path).bind(WHO, approved=True)
        reader, sender = MagicMock(), MagicMock()
        out = guided.walk(self.chain, WHO, self.stop, self.approve, reader, sender,
                          approved=False, greetings=(GREETING,))
        self.assertEqual(out['reason'], 'guided-consent-required')
        reader.assert_not_called()
        sender.assert_not_called()
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM guided_bindings').fetchone()[0], 0)

    def test_existing_incoming_at_first_start_is_not_assumed_after_greeting(self):
        out = self.walk([snapshot(('Привет', False))])
        self.assertEqual(out['reason'], 'start-before-peer-reply')
        self.assertFalse(self.sent)
        self.notifier.assert_not_called()

    def test_consent_and_greeting_baseline_are_atomic_and_survive_restart(self):
        self.chain.bind(snapshot(), (GREETING,), approved=True)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT greeting,stage FROM chain_dialogs').fetchone(),
                             ('1001', 'wait-reply'))
            self.assertEqual(db.execute('SELECT message FROM chain_seen').fetchone()[0], '1001')
        self.chain = guided.GuidedChain(self.store, choose=lambda: 0,
                                        seal=lambda value: value, unseal=lambda value: value)
        out = self.walk(sequence()[1:])
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])

    def test_explicit_reset_replaces_only_this_peers_stopped_chain(self):
        self.chain.bind(snapshot(), (GREETING,), approved=True)
        with self.store.connection() as db:
            db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,?)",
                       ('300', 'question', '1002', 'old-hash', 'unknown'))
            db.execute("INSERT INTO chain_contact_outbox VALUES(?,?,?,?)",
                       ('300', '1003', b'old-private-payload', 'unknown'))
            db.execute("INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)",
                       ('101', '201', '301', '7001', 'wait-reply', '11' * 32))
            db.execute("INSERT INTO chain_seen VALUES(?,?,?)",
                       ('301', '7001', 'other-fingerprint'))
        self.assertTrue(self.chain.reset(fresh_snapshot(), (GREETING,), approved=True))
        with self.store.connection() as db:
            self.assertEqual(db.execute(
                'SELECT greeting,stage FROM chain_dialogs WHERE chat=?',
                ('300',)).fetchone(), ('9001', 'wait-reply'))
            self.assertEqual(db.execute(
                'SELECT message FROM chain_seen WHERE chat=?',
                ('300',)).fetchall(), [('9001',)])
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM chain_actions WHERE chat=?',
                ('300',)).fetchone()[0], 0)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM chain_contact_outbox WHERE chat=?',
                ('300',)).fetchone()[0], 0)
            self.assertEqual(db.execute(
                'SELECT stage FROM chain_dialogs WHERE chat=?',
                ('301',)).fetchone()[0], 'wait-reply')
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM chain_seen WHERE chat=?',
                ('301',)).fetchone()[0], 1)

    def test_reset_requires_explicit_consent_and_exactly_one_fresh_greeting(self):
        with self.assertRaisesRegex(Exception, 'guided-reset-consent-required'):
            self.chain.reset(fresh_snapshot(), (GREETING,))
        with self.assertRaisesRegex(Exception, 'reset-needs-one-fresh-greeting'):
            self.chain.reset(snapshot(('Привет', False)), (GREETING,), approved=True)
        with self.assertRaisesRegex(Exception, 'reset-needs-one-fresh-greeting'):
            self.chain.reset(fresh_snapshot(text='Здарова'), (GREETING,), approved=True)
        with self.store.connection() as db:
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM guided_bindings').fetchone()[0], 0)

    def test_reset_entrypoint_reads_identity_then_one_bound_snapshot(self):
        reader = MagicMock(side_effect=[
            dict(identity=WHO, messages=None), fresh_snapshot()])
        with patch('assistant_lock.operation_lock'):
            out = guided.run_reset(
                Settings(), self.stop, approved=True, store=self.store,
                reader=reader, greetings=(GREETING,))
        self.assertEqual(out['status'], 'reset-completed')
        self.assertEqual(reader.call_count, 2)
        self.assertIsNone(reader.call_args_list[0].args[3])
        self.assertEqual(reader.call_args_list[1].args[3], WHO)
        with self.store.connection() as db:
            self.assertEqual(db.execute(
                'SELECT greeting,stage FROM chain_dialogs').fetchone(),
                ('9001', 'wait-reply'))

    def test_reset_without_approval_does_not_read_device_or_create_store(self):
        with patch('one_chat_device.capture') as reader, \
             patch.object(guided, 'Store') as store:
            out = guided.run_reset(Settings(), self.stop)
        self.assertEqual(out['reason'], 'guided-reset-consent-required')
        reader.assert_not_called()
        store.assert_not_called()

    def test_declined_confirmation_can_resume_but_no_unapproved_send(self):
        self.approve.return_value = False
        out = self.walk([snapshot(), snapshot(('Привет!', False))])
        self.assertEqual(out['reason'], 'message-not-approved')
        self.assertFalse(self.sent)
        self.approve.return_value = True
        # Resume the same reserved proposal; do not choose another variant.
        self.chain = guided.GuidedChain(self.store, choose=lambda: 1,
                                        seal=lambda value: value, unseal=lambda value: value)
        out = self.walk(sequence()[1:])
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])

    def test_history_changed_during_confirmation_no_send(self):
        values = sequence()
        values[2] = snapshot(('Привет', False), ('Ещё одно сообщение', False))
        out = self.walk(values)
        self.assertEqual(out['reason'], 'history-changed-during-approval')
        self.assertFalse(self.sent)
        self.notifier.assert_not_called()

    def test_changed_identity_during_confirmation_never_sends(self):
        values = sequence()
        values[2]['identity']['peer'] = '999'
        out = self.walk(values)
        self.assertEqual(out['status'], 'chain-stopped')
        self.assertFalse(self.sent)

    def test_stop_after_approval_and_after_durable_reservation(self):
        def stop_on_approval(*args):
            self.stop.set()
            return True
        self.approve.side_effect = stop_on_approval
        out = self.walk()
        self.assertEqual(out['status'], 'chain-cancelled')
        self.assertFalse(self.sent)
        self.stop.clear()
        self.approve.side_effect = None
        reserve = self.chain.reserve_confirmed
        def stop_on_reservation(*args):
            reserve(*args)
            self.stop.set()
        with patch.object(self.chain, 'reserve_confirmed', side_effect=stop_on_reservation):
            out = self.walk(sequence()[1:])
        self.assertEqual(out['status'], 'chain-cancelled')
        self.assertFalse(self.sent)
        self.stop.clear()
        out = self.walk([snapshot(('Привет!', False))])
        self.assertEqual(out['reason'], 'send-outcome-unknown')
        self.assertFalse(self.sent)

    def test_unknown_send_never_retried_or_notified_after_restart(self):
        def unknown(before, text):
            self.sent.append(text)
            raise TimeoutError('PRIVATE_TOKEN_AND_TEXT')
        with patch.object(self, 'send', side_effect=unknown):
            out = self.walk()
        self.assertEqual(out['reason'], 'send-outcome-unknown')
        self.chain = guided.GuidedChain(self.store,
                                        seal=lambda value: value, unseal=lambda value: value)
        out = self.walk([snapshot(('Привет!', False))])
        self.assertEqual(out['reason'], 'send-outcome-unknown')
        self.assertEqual(len(self.sent), 1)
        self.notifier.assert_not_called()
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_contact_handler_return_without_observed_message_does_not_notify(self):
        values = sequence()[:-2]
        values += [values[-1]] * 4
        out = self.walk(values)
        self.assertEqual(out['reason'], 'outgoing-not-observed')
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])
        self.notifier.assert_not_called()

    def test_observed_request_waits_for_contact_and_does_not_notify(self):
        values = sequence()[:-1]
        values += [values[-1]] * 20
        out = self.walk(values)
        self.assertEqual(out['reason'], 'wait-timeout')
        self.assertTrue(out['stages']['contact_request'])
        self.assertFalse(out['stages']['peer_contact'])
        self.notifier.assert_not_called()

    def test_plain_reply_or_refusal_after_request_never_notifies(self):
        for reply, expected in [('Потом напишу', 'wait-timeout'),
                                ('Не дам контакт', 'declined')]:
            with self.subTest(reply=reply):
                path = Path(self.temp.name) / ('after-request-' + expected + '.sqlite3')
                store = Store(path, Path(self.temp.name) / 'old')
                chain = guided.GuidedChain(store, choose=lambda: 0,
                                           seal=lambda value: value, unseal=lambda value: value)
                history = sequence()[:-1]
                history.append(snapshot(('Привет!', False), (QUESTIONS[0], True),
                                        ('Отлично!', False), (CONTACT_TEXT, True),
                                        (reply, False)))
                history += [history[-1]] * 12
                notice = MagicMock(return_value=True)
                out = guided.walk(chain, WHO, self.stop, self.approve,
                                  MagicMock(side_effect=history),
                                  lambda before, text: dict(attempted=True,
                                                            handler_returned=True),
                                  approved=True, greetings=(GREETING,), notifier=notice,
                                  pause=lambda _: False, max_polls=12)
                self.assertEqual(out['reason'], expected)
                self.assertFalse(out['stages']['peer_contact'])
                notice.assert_not_called()

    def test_telegram_failure_and_restart_never_retry_notification_or_messages(self):
        self.notifier.side_effect = TimeoutError('PRIVATE_BOT_TOKEN')
        out = self.walk()
        self.assertEqual(out['reason'], 'telegram-outcome-unknown')
        self.assertEqual(self.notifier.call_count, 1)
        self.chain = guided.GuidedChain(self.store,
                                        seal=lambda value: value, unseal=lambda value: value)
        out = self.walk([sequence()[-1]])
        self.assertEqual(out['reason'], 'telegram-outcome-unknown')
        self.assertEqual(self.notifier.call_count, 1)
        self.assertEqual(len(self.sent), 2)
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_successful_restart_never_resends_messages_or_notification(self):
        self.assertEqual(self.walk()['status'], 'chain-completed')
        self.chain = guided.GuidedChain(self.store,
                                        seal=lambda value: value, unseal=lambda value: value)
        out = self.walk([sequence()[-1]])
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.notifier.call_count, 1)

    def test_explicit_refusal_stops_whole_chain(self):
        for reply, expected in [('Не пиши мне', 'declined')]:
            with self.subTest(reply=reply):
                store = Store(Path(self.temp.name) / f'case-{expected}-{len(str(reply))}.sqlite3',
                              Path(self.temp.name) / 'old')
                chain = guided.GuidedChain(store, seal=lambda value: value,
                                           unseal=lambda value: value)
                send, notice = MagicMock(), MagicMock()
                out = guided.walk(chain, WHO, self.stop, self.approve,
                                  MagicMock(side_effect=[snapshot(), snapshot((reply, False))]), send,
                                  approved=True, greetings=(GREETING,), notifier=notice,
                                  pause=lambda _: False)
                self.assertEqual(out['reason'], expected)
                send.assert_not_called()
                notice.assert_not_called()

    def test_arbitrary_replies_complete_whole_chain_both_questions(self):
        for choice in (0, 1):
            for reply in ('Рабочее', 'Кто ты?', 'Мне плохо', '🙂', 'Нет настроения', None):
                with self.subTest(choice=choice, reply=reply):
                    store = Store(Path(self.temp.name) / f'any-{choice}-{len(str(reply))}-{str(reply)[:2]}.sqlite3',
                                  Path(self.temp.name) / 'old')
                    chain = guided.GuidedChain(store, choose=lambda: choice,
                                               seal=lambda value: value, unseal=lambda value: value)
                    values = sequence(choice)
                    for value in values:
                        for message in value['messages']:
                            if message['id'] == '1002':
                                message['text'] = 'Здарова'
                            elif message['id'] == '1004':
                                message['text'] = reply
                    notice = MagicMock(return_value=True)
                    sent = []
                    out = guided.walk(chain, WHO, self.stop, self.approve,
                                      MagicMock(side_effect=values),
                                      lambda before, text: (sent.append(text) or dict(attempted=True, handler_returned=True)),
                                      approved=True, greetings=(GREETING,), notifier=notice,
                                      pause=lambda _: False, max_polls=12)
                    self.assertEqual(out['status'], 'chain-completed')
                    self.assertEqual(sent, [QUESTIONS[choice], CONTACT_TEXT])
                    self.assertEqual(notice.call_count, 1)

    def test_multiple_incoming_messages_advance_only_one_stage(self):
        values = sequence()
        for index, value in enumerate(values):
            if index >= 1:
                value['messages'].append(dict(id='1998', sender='200', text='Как сам?'))
            if index >= 4:
                value['messages'].append(dict(id='1999', sender='200', text='Рабочее'))
        out = self.walk(values)
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])
        self.assertEqual(self.notifier.call_count, 1)

    def test_ordinary_reply_then_voluntary_contact_notifies_only_on_contact(self):
        values = sequence()[:-1]
        base = [('Привет!', False), (QUESTIONS[0], True),
                ('Отлично!', False), (CONTACT_TEXT, True)]
        ordinary = snapshot(*base, ('Сейчас найду', False))
        values += [ordinary, ordinary,
                   snapshot(*base, ('Сейчас найду', False), (CONTACT, False))]
        def notify(payload):
            self.assertEqual(payload, dict(name=PEER_NAME, contacts=[CONTACT]))
            return True
        self.notifier.side_effect = notify
        out = self.walk(values)
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(self.notifier.call_count, 1)
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])

    def test_unapproved_manually_added_outgoing_does_not_advance_chain(self):
        self.approve.return_value = False
        self.walk(sequence()[:2])
        out = self.walk([sequence()[3]])
        self.assertEqual(out['reason'], 'manual-review')
        self.assertFalse(self.sent)
        self.notifier.assert_not_called()

    def test_reordered_snapshot_is_not_a_new_message(self):
        values = sequence()
        values[2]['messages'].reverse()
        out = self.walk(values)
        self.assertEqual(out['status'], 'chain-completed')
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])

    def test_disabled_telegram_preflight_does_not_read_or_load_secrets(self):
        reader = MagicMock()
        with patch('assistant_lock.operation_lock'), patch('telegram_notify.load') as credentials, \
             patch.object(guided, 'data_directory', return_value=Path(self.temp.name)):
            out = guided.run(Settings(), self.stop, self.approve, approved=True, reader=reader)
        self.assertEqual(out['reason'], 'telegram-disabled')
        reader.assert_not_called()
        credentials.assert_not_called()


ORIGINAL_INIT = guided.GuidedChain.__init__

if __name__ == '__main__':
    unittest.main()