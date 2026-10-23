"""No live API/account. HTTP, crypto and snapshots are synthetic."""
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import MagicMock

import groq_reply as g
import assistant_guided_chain as guided
from assistant_store import Store
from assistant_authorization import RunAuthorization
from test_guided_chain import WHO, GREETING, snapshot

KEY = 'gsk_' + 'x' * 32
QUESTION = 'Взаимно! Как настроение?)'
CONTACT = 'Понимаю. Удобнее общаться в Telegram или WhatsApp?'


def reply(text=QUESTION, **kw):
    return dict(decision='reply', text=text, **kw)


class Adapter(unittest.TestCase):
    def client(self, result=None, *, finish='stop'):
        value = dict(choices=[dict(finish_reason=finish, message=dict(content=json.dumps(result or reply())))])
        response = MagicMock()
        response.read.return_value = json.dumps(value).encode()
        client = MagicMock()
        client.open.return_value.__enter__.return_value = response
        return client

    def test_bounded_fixed_endpoint_no_ids_names_contacts_or_tools(self):
        client = self.client()
        value = snapshot(('Пиши @secret, https://private.test и +79991234567', False))
        responder = g.Responder(key_loader=lambda: KEY, opener=client)
        self.assertEqual(responder('question', value), reply())
        request = client.open.call_args.args[0]
        self.assertEqual(request.full_url, g.ENDPOINT)
        self.assertEqual(client.open.call_args.kwargs['timeout'], 12)
        body = json.loads(request.data)
        self.assertEqual(body['response_format'], dict(type='json_object'))
        self.assertEqual(body['model'], g.MODEL)
        self.assertNotIn('tools', body)
        context = json.loads(body['messages'][1]['content'])
        self.assertEqual(set(context), {'stage', 'history'})
        content = json.dumps(context)
        for private in ('secret', 'private.test', '79991234567', 'Александр', 'account', 'sender', '1001'):
            self.assertNotIn(private, content)
        self.assertEqual(responder.calls, 1)

    def test_owner_rules_reload_for_each_new_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'groq-rules.txt'
            client=self.client()
            responder=g.Responder(key_loader=lambda:KEY, opener=client, rules_loader=lambda:g.rules(path))
            for text in ('Пиши кратко.', 'Без эмодзи.'):
                path.write_text(text, encoding='utf-8-sig')
                responder('question', snapshot())
                body=json.loads(client.open.call_args.args[0].data)
                self.assertIn(text, body['messages'][0]['content'])
                self.assertNotIn(text, body['messages'][1]['content'])
            self.assertEqual(responder.calls, 2)

    def test_unavailable_invalid_or_oversized_rules_never_make_http_request(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'groq-rules.txt'; client=self.client()
            responder=g.Responder(key_loader=lambda:KEY, opener=client, rules_loader=lambda:g.rules(path))
            for raw in (None, b'', b'   ', b'\xff', b'x'*16385, ('я'*6001).encode(), b'abc\x00'):
                if raw is None: path.unlink(missing_ok=True)
                else: path.write_bytes(raw)
                with self.assertRaises(g.GroqError) as e: responder('question', snapshot())
                self.assertEqual(str(e.exception), 'groq-rules-unavailable')
            client.open.assert_not_called()
            self.assertEqual(responder.calls, 0)

    def test_context_includes_every_verified_message_without_fragment_truncation(self):
        v=snapshot(*[('x'*500, False) for _ in range(18)])
        history = g.public_context(v)
        self.assertEqual(len(history), 19)
        self.assertEqual([m['text'] for m in history], [m['text'] for m in v['messages']])
        with self.assertRaises(ValueError):
            g.public_context(snapshot(*[('x'*500, False) for _ in range(128)]))

    def test_auth_rate_limit_server_and_other_http_errors_are_fixed(self):
        for status, reason in ((401, 'groq-unauthorized'), (403, 'groq-unauthorized'),
                               (429, 'groq-rate-limit'), (503, 'groq-service-error'),
                               (400, 'groq-request-rejected'), (302, 'groq-request-rejected')):
            client = MagicMock()
            client.open.side_effect = urllib.error.HTTPError('https://PRIVATE', status, KEY, {}, io.BytesIO(KEY.encode()))
            with self.assertRaises(g.GroqError) as e:
                g.Responder(key_loader=lambda: KEY, opener=client)('question', snapshot())
            self.assertEqual(str(e.exception), reason)
            self.assertEqual(client.open.call_count, 1)

    def test_timeout_network_error_and_arbitrary_errors_are_sanitized(self):
        for error, code in ((TimeoutError(KEY), 'groq-timeout'),
                            (urllib.error.URLError(KEY), 'groq-network-error'),
                            (RuntimeError(KEY), 'groq-invalid-response')):
            client=MagicMock();client.open.side_effect=error
            with self.assertRaises(g.GroqError) as e:
                g.Responder(key_loader=lambda: KEY, opener=client)('contact', snapshot())
            self.assertEqual(str(e.exception), code)

    def test_truncated_and_malformed_responses_never_become_messages(self):
        for client in (self.client(finish='length'), self.client(dict(text='hello'))):
            with self.assertRaises(g.GroqError):g.Responder(key_loader=lambda: KEY, opener=client)('question', snapshot())
        for raw in (b'x'*32769, b'PRIVATE', b'{"choices":[],"choices":[]}'):
            client=self.client();client.open.return_value.__enter__.return_value.read.return_value=raw
            with self.assertRaises(g.GroqError):g.Responder(key_loader=lambda: KEY, opener=client)('question', snapshot())

    def test_reply_guards_keep_short_structure_and_no_links_or_contacts(self):
        self.assertEqual(g.decision(reply(CONTACT), 'contact'), reply(CONTACT))
        for kind, text in (('question', 'Как дела? Telegram?'), ('question', 'Привет'),
                            ('question', 'Как дела? @secret'), ('contact', 'Понятно'),
                            ('question', 'Как дела?\nPRIVATE'), ('question', 'Как дела? <tag>'),
                            ('contact', 'Telegram https://private.test'), ('contact', 'WhatsApp +7 999 123 45 67'), ('contact', 'WhatsApp '+ 'x'*241)):
            with self.assertRaises(g.GroqError):g.decision(reply(text), kind)
        for mode in ('decline','review'):
            self.assertEqual(g.decision(dict(decision=mode,text=''),'question')['decision'],mode)
            with self.assertRaises(g.GroqError):g.decision(dict(decision=mode,text='PRIVATE'),'question')

    def test_stop_before_and_during_http_never_yields_an_answer(self):
        stop=threading.Event();stop.set();client=self.client()
        responder=g.Responder(key_loader=lambda: KEY,opener=client,cancelled=stop.is_set)
        with self.assertRaises(g.GroqError):responder('question',snapshot())
        client.open.assert_not_called()
        stop.clear()
        response=client.open.return_value
        def opened(*a,**kw):stop.set();return response
        client.open.side_effect=opened
        with self.assertRaises(g.GroqError) as e:responder('question',snapshot())
        self.assertEqual(str(e.exception),'groq-cancelled')

    def test_key_roundtrip_is_encrypted_and_invalid_key_not_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'groq.dpapi'
            encode=lambda b:b'E'+b[::-1]
            decode=lambda b:b[1:][::-1]
            g.save_key(KEY,path,encoder=encode)
            self.assertNotIn(KEY.encode(),path.read_bytes())
            self.assertEqual(g.load_key(path,decoder=decode),KEY)
            self.assertFalse(path.with_suffix('.tmp').exists())
            for value in ('PRIVATE','gsk_x','gsk_'+('x'*250)):
                with self.assertRaises(g.GroqError):g.save_key(value,path,encoder=encode)
            with self.assertRaises(g.GroqError):g.load_key(path,decoder=lambda _:b'PRIVATE')


class Drafts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'assistant.sqlite3',Path(self.temp.name)/'old')
        self.stop=threading.Event();self.model=MagicMock(return_value=reply())
        self.chain=self.new_chain(self.model)
        self.chain.bind(snapshot(),(GREETING,),approved=True)

    def new_chain(self, responder):
        return guided.GuidedChain(self.store,responder=responder,choose=lambda:0,
               seal=lambda b:b'E'+b[::-1],unseal=lambda b:b[1:][::-1])

    def test_generated_reply_persists_encrypted_reloads_and_observes_without_resend(self):
        before=snapshot(('Взаимно',False))
        stage,action=self.chain.proposal(before)
        self.assertEqual(action['text'],QUESTION)
        self.assertEqual(stage,'pending-question')
        self.model.assert_called_once()
        context=self.model.call_args.args[1]
        self.assertEqual(context['_reply_ids'],['1002'])
        self.assertEqual({k:v for k,v in context.items() if k!='_reply_ids'},before)
        self.assertNotIn(QUESTION.encode(),self.store.path.read_bytes())
        model=MagicMock(side_effect=RuntimeError('must use saved draft'))
        other=self.new_chain(model)
        _,restored=other.proposal(before)
        self.assertEqual(restored,action);model.assert_not_called()
        other.reserve_confirmed(WHO,restored);other.finish(WHO,restored,True)
        stage,action=other.proposal(snapshot(('Взаимно',False),(QUESTION,True)))
        self.assertEqual(stage,'wait-mood');self.assertIsNone(action)
        model.assert_not_called()

    def test_api_failure_is_durable_and_cannot_fall_back_when_disabled(self):
        self.model.side_effect=g.GroqError('groq-rate-limit')
        before=snapshot(('Взаимно',False))
        with self.assertRaises(g.GroqError):self.chain.proposal(before)
        other=self.new_chain(None)
        with self.assertRaises(g.GroqError) as e:other.proposal(before)
        self.assertEqual(str(e.exception),'groq-configuration-required')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'awaiting-approval')

    def test_current_reply_is_bound_without_assuming_collection_order(self):
        before=snapshot(('Взаимно',False));before['messages'].reverse()
        self.chain.proposal(before)
        context=self.model.call_args.args[1]
        public=g.public_context(context)
        selected=[m for m in public if m['is_current_reply']]
        self.assertEqual([m['text'] for m in selected],['Взаимно'])
        self.assertNotIn('1002',json.dumps(public))

    def test_ready_ai_draft_also_requires_ai_enabled_to_resume(self):
        before=snapshot(('Взаимно',False));self.chain.proposal(before)
        with self.assertRaises(g.GroqError) as e:self.new_chain(None).proposal(before)
        self.assertEqual(str(e.exception),'groq-configuration-required')

    def test_crypto_failure_never_replaces_default_hash_or_allows_fallback(self):
        self.chain.seal=MagicMock(side_effect=RuntimeError('PRIVATE'))
        before=snapshot(('Взаимно',False))
        with self.assertRaises(g.GroqError):self.chain.proposal(before)
        with self.assertRaises(g.GroqError):self.new_chain(None).proposal(before)

    def test_corrupt_draft_is_blocked_and_not_regenerated(self):
        before=snapshot(('Взаимно',False));self.chain.proposal(before)
        with self.store.connection() as db:db.execute("UPDATE ai_drafts SET payload=?",(b'PRIVATE',))
        with self.assertRaises(g.GroqError):self.chain.proposal(before)
        self.assertEqual(self.model.call_count,1)

    def test_semantic_refusal_blocks_chat_without_outgoing(self):
        self.model.return_value=dict(decision='decline',text='')
        stage,action=self.chain.proposal(snapshot(('Нам не по пути',False)))
        self.assertEqual(stage,'declined');self.assertIsNone(action)
        stage,action=self.chain.proposal(snapshot(('Нам не по пути',False)))
        self.assertEqual(stage,'declined');self.assertIsNone(action)
        self.assertEqual(self.model.call_count,1)

    def test_network_is_outside_store_transaction(self):
        def compose(*a):
            # An independent BEGIN IMMEDIATE would fail if a transaction was held.
            with self.store.connection() as db:self.assertIsNotNone(db.execute('SELECT 1').fetchone())
            return reply()
        self.model.side_effect=compose
        self.chain.proposal(snapshot(('Взаимно',False)))

    def walk(self, values, sender=None):
        return guided.walk(self.chain,WHO,self.stop,RunAuthorization(self.stop, wait=lambda _: False),
           MagicMock(side_effect=__import__('test_guided_chain').stable_snapshots(copy.deepcopy(values))),sender or MagicMock(),approved=True,
           greetings=(GREETING,),pause=lambda _:False,until_waiting=True,max_polls=8)

    def test_history_changed_after_generation_cannot_send(self):
        before=snapshot(('Взаимно',False));changed=snapshot(('Изменено',False),('А ты кто?',False))
        sender=MagicMock()
        out=self.walk([before,changed],sender)
        sender.assert_not_called()
        self.assertEqual(out['reason'],'history-changed-during-approval')

    def test_api_error_never_sends_or_leaks_history(self):
        self.model.side_effect=g.GroqError('groq-timeout');sender=MagicMock()
        out=self.walk([snapshot(('PRIVATE_PEER',False))],sender)
        sender.assert_not_called()
        self.assertEqual(out['reason'],'ai-temporarily-unavailable');self.assertEqual(out['diagnostics']['failure_point'],'groq-timeout')
        self.assertNotIn('PRIVATE',json.dumps(out))

    def test_whole_brief_chain_uses_two_meaningful_replies_and_no_more(self):
        self.model.side_effect=[reply(),reply(CONTACT)]
        peer=('Взаимно',False);question=(QUESTION,True);mood=('Грустно сегодня',False);contact=(CONTACT,True)
        before=snapshot(peer)
        values=[before,before,snapshot(peer,question),snapshot(peer,question,mood),
                snapshot(peer,question,mood),snapshot(peer,question,mood,contact)]
        sent=[]
        def send(s,text):sent.append(text);return dict(attempted=True,handler_returned=True)
        # until_waiting yields after question; continue with new peer reply in a second pass.
        out=self.walk(values[:3],send)
        self.assertEqual(out['status'],'chain-waiting')
        out=self.walk(values[3:],send)
        self.assertEqual(out['status'],'chain-waiting')
        self.assertEqual(sent,[QUESTION,CONTACT]);self.assertEqual(self.model.call_count,2)
        self.assertEqual(out['stage'],'wait-contact')
        self.walk([values[-1]],send)
        self.assertEqual(len(sent),2)

if __name__=='__main__':unittest.main()
