"""1.2.2: supplied failure shape and repeated-salutation regressions, synthetic only."""
from contextlib import nullcontext
import json
import unittest
from unittest.mock import MagicMock

import assistant_inbox as inbox
import assistant_run
import groq_reply as g
import openrouter_reply as o
from assistant_chain import text_hash
from one_chat_device import ReadStopped
from test_inbox_profiles import Base, WHO, OTHER, GREETING, nav, msg, snap
import test_groq_reply as groq_tests
from test_groq_reply import reply
from test_guided_chain import snapshot


def local_failure(**changes):
    data = dict(stage='navigation-stopped', metadata_checkpoint='ready',
                read_checkpoint='last-message', wait_reason='none', frames=1,
                managed_calls=64, message_kind='text', message_direction='own',
                scalar_checkpoint='message-chat-id', identity_checkpoint='recheck',
                scalar_state='negative', message_slot=0, private_text='PRIVATE')
    data.update(changes)
    return ReadStopped('local-own-message-unanchored', data)


class LocalReadIsolation(Base):
    def test_screenshot_reply_is_continued_without_new_greeting_or_duplicate_send(self):
        self.journal()
        model = MagicMock(return_value=reply('Привет! Как настроение?'))
        chain = inbox.InboxChain(self.store, responder=model,
                                 seal=lambda v:v, unseal=lambda v:v)
        hello = msg(1002, 'Привет')
        before = snap(hello)
        after = snap(hello, msg(1003, 'Как настроение?', True))
        route = lambda: [nav('opened', WHO), nav('returned', WHO), nav('search-ready')]
        out = self.walk(route(), [before, before, after], chain=chain)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(self.sent, ['Как настроение?'])
        self.assertEqual(model.call_count, 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT text_hash,status FROM chain_actions').fetchone(),
                             (text_hash('Как настроение?'), 'outgoing-observed'))
        again = self.walk(route(), [after], chain=self.chain())
        self.assertEqual(again['submission_calls'], 0)
        self.assertEqual(self.sent, ['Как настроение?'])

    def test_reported_failure_skips_only_that_chat_then_processes_next(self):
        self.journal(); self.journal(OTHER)
        hello = msg(1002, 'Привет', who=OTHER)
        q = msg(1003, 'Как дела?)', True, who=OTHER)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('opened', OTHER),
                         nav('returned', OTHER), nav('search-ready')],
                        [local_failure(), snap(hello, who=OTHER), snap(hello, who=OTHER),
                         snap(hello, q, who=OTHER)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual((out['dialogs_processed'], out['isolated_dialogs']), (2, 1))
        self.assertEqual(out['isolated_reasons'], {'local-own-message-unanchored': 1})
        self.assertEqual(self.sent, ['Как дела?)'])
        self.assertEqual(self.reader.call_count, 4)  # bad chat is not retried
        self.assertEqual(out['outcomes']['isolated:local-own-message-unanchored'], 1)
        self.assertNotIn('PRIVATE', json.dumps(out))
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs WHERE peer=?',
                                        (WHO['peer'],)).fetchone()[0], 'manual-review')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_actions WHERE chat=?',
                                        (WHO['chat'],)).fetchone()[0], 0)
        # Reopen the store through a fresh chain; the failed chat stays excluded.
        active = sum(inbox.inbox_targets(self.chain()), [])
        self.assertNotIn(WHO['peer'], [v['peer'] for v in active])

    def test_initial_pass_continues_to_profiles_after_isolating_unreadable_chat(self):
        self.journal()
        profiles = MagicMock(return_value=dict(status='profiles-completed'))
        def run_inbox(*args):
            return self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                             [local_failure()])
        out = assistant_run.start(self.settings, self.stop, self.approve,
            inbox=run_inbox, profiles=profiles, lock=nullcontext, write=lambda _: 'last-run.json')
        self.assertEqual(out['status'], 'completed')
        self.assertEqual(out['inbox']['isolated_dialogs'], 1)
        profiles.assert_called_once()

    def test_failed_or_changed_back_still_stops_and_retains_block(self):
        for who, result in ((WHO, nav('returned', OTHER)), (OTHER, RuntimeError('PRIVATE'))):
            with self.subTest(peer=who['peer']):
                self.journal(who)
                out = self.walk([nav('opened', who), result], [local_failure()])
                self.assertEqual(out['status'], 'inbox-stopped')
                self.assertEqual(out['isolated_dialogs'], 0)  # no verified return
                self.assertEqual(self.nav.call_count, 2)
                self.assertFalse(self.sent)
                self.assertEqual(inbox.inbox_targets(self.chain()), ([], []))

    def test_other_read_and_identity_errors_remain_global(self):
        self.journal()
        for error in (ReadStopped('unsupported-runtime'), ReadStopped('identity-not-bound'),
                      ReadStopped('nonpositive-message-id'), ReadStopped('snapshot-too-large'),
                      local_failure(identity_checkpoint='saved-binding'),
                      local_failure(scalar_state='positive'),
                      ReadStopped('local-own-message-unanchored')):
            with self.subTest(error=str(error)):
                out = self.walk([nav('opened', WHO)], [error])
                self.assertEqual(out['status'], 'inbox-stopped')
                self.assertEqual(out['isolated_dialogs'], 0)
                self.assertEqual(self.nav.call_count, 1)
        self.assertFalse(self.sent)

    def test_cancelled_read_does_not_back_or_open_next_chat(self):
        self.journal()
        def reader(*args):
            self.stop.set()
            raise local_failure()
        self.nav = MagicMock(side_effect=[nav('opened', WHO)])
        out = inbox.walk(self.settings, self.stop, self.approve, lambda _: None,
            self.chain(), navigator=self.nav, reader=reader, sender=self.sender,
            greetings=(GREETING,), pause=lambda _: False)
        self.assertEqual(out['status'], 'inbox-cancelled')
        self.assertEqual(self.nav.call_count, 1)
        self.assertFalse(self.sent)

    def test_failure_after_send_keeps_unknown_journal_and_never_resends(self):
        self.journal(); hello = msg(1002, 'Привет')
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), local_failure()])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['isolated_dialogs'], 1)
        self.assertEqual(self.sent, ['Как дела?)'])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],
                             'handler-returned-unconfirmed')
        self.assertEqual(self.walk([], [])['status'], 'inbox-empty')
        self.assertEqual(len(self.sent), 1)

    def test_old_ready_greeting_draft_is_blocked_not_rewritten_or_sent(self):
        self.journal(); hello = msg(1002, 'Привет'); before = snap(hello)
        chain = inbox.InboxChain(self.store, responder=lambda *_: reply('Как настроение?'),
                                 seal=lambda v:v, unseal=lambda v:v)
        chain.bind(before, (GREETING,), approved=True)
        chain.proposal(before)
        old = 'Привет! Как настроение?'
        payload = json.dumps(reply(old), ensure_ascii=False).encode()
        with self.store.connection() as db:
            db.execute('UPDATE ai_drafts SET payload=?', (payload,))
            db.execute('UPDATE chain_actions SET text_hash=?', (text_hash(old),))
        sender = MagicMock()
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [before], chain=chain, sender=sender)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['isolated_reasons'], {'groq-repeat-greeting': 1})
        sender.assert_not_called()
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT payload FROM ai_drafts').fetchone()[0], payload)
            self.assertEqual(db.execute('SELECT text_hash,status FROM chain_actions').fetchone(),
                             (text_hash(old), 'awaiting-approval'))


class Continuation(unittest.TestCase):
    def test_both_providers_remove_only_new_leading_greeting_once(self):
        for adapter, key in ((g, 'gsk_'+'x'*32), (o, 'sk-or-v1-'+'x'*32)):
            for text, expected, kind in (
                    ('Привет! Как настроение?', 'Как настроение?', 'question'),
                    ('Привет 🙂 Как дела?', 'Как дела?', 'question'),
                    ('Приветствую Вас 👋 Как настроение?', 'Как настроение?', 'question'),
                    ('Здравствуйте, милая 🌼 Как дела?', 'Как дела?', 'question'),
                    ('Рад знакомству 🤝 Как дела?', 'Как дела?', 'question'),
                    ('Привет! Удобно общаться в Telegram?', 'Удобно общаться в Telegram?', 'contact')):
                client = groq_tests.Adapter().client(reply(text))
                responder = adapter.Responder(key_loader=lambda:key, opener=client)
                self.assertEqual(responder(kind, snapshot(('Привет',False))), reply(expected))
                self.assertEqual(client.open.call_count, 1)
                body=json.loads(client.open.call_args.args[0].data)
                self.assertIn('НИКОГДА не здоровайся повторно', body['messages'][0]['content'])

    def test_native_gate_rejects_repeat_but_keeps_quoted_word_and_stage(self):
        from one_chat_send import checked_reply
        for text in ('Привет! Как дела?', 'Здравствуй 🙂 Как настроение?',
                     'Hello! Как дела?', 'Понимаю. Привет! Как дела?'):
            with self.assertRaises(ValueError): checked_reply(text)
        self.assertEqual(checked_reply('Ты написал «Привет». Как дела?'),
                         'Ты написал «Привет». Как дела?')
        for text in ('Привет!', 'Привет! @private Как дела?', 'Привет! Как дела?\n'):
            with self.assertRaises(g.GroqError): g.continuation(reply(text), 'question')

    def test_entire_snapshot_is_sent_not_just_first_twelve_or_first_300_chars(self):
        entries = [('фрагмент'+str(i)+' '+('я'*400), i%2==0) for i in range(18)]
        value = snapshot(*entries)
        value['messages'].reverse()  # never sort IDs or invent chronological order
        current = [m for m in value['messages'] if m['sender']==value['identity']['peer']][-1]
        value['_reply_ids']=[current['id']]
        for adapter, key in ((g,'gsk_'+'x'*32),(o,'sk-or-v1-'+'x'*32)):
            client=groq_tests.Adapter().client()
            adapter.Responder(key_loader=lambda:key,opener=client)('question',value)
            body=json.loads(client.open.call_args.args[0].data)
            public=json.loads(body['messages'][1]['content'])['history']
            self.assertEqual([m['text'] for m in public], [m['text'] for m in value['messages']])
            self.assertEqual(len(public),19)
            self.assertEqual([m['text'] for m in public if m['is_current_reply']], [current['text']])
            self.assertNotIn('sender',json.dumps(public))

    def test_full_context_still_masks_contacts_anywhere_in_long_messages(self):
        value=snapshot(('я'*350+' @private https://private.example +79991234567',False))
        public=g.public_context(value)
        self.assertTrue(public[1]['text'].startswith('я'*350))
        encoded=json.dumps(public)
        for secret in ('@private','private.example','79991234567'):
            self.assertNotIn(secret,encoded)

    def test_oversized_or_invalid_context_never_makes_http_request(self):
        cases=[snapshot(*[('x',False) for _ in range(20)]), snapshot(('x'*2049,False)),
               snapshot(*[('x'*2048,False) for _ in range(9)])]
        wrong=snapshot(('Привет',False));wrong['_reply_ids']=['1001'];cases.append(wrong)
        for value in cases:
            client=groq_tests.Adapter().client()
            with self.assertRaises((g.GroqError,ValueError)):
                g.Responder(key_loader=lambda:'gsk_'+'x'*32,opener=client)('question',value)
            client.open.assert_not_called()


if __name__=='__main__': unittest.main()
