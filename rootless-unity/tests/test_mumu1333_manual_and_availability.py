"""Available-app regression and explicit deny-only bot commands; no live services."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import assistant_contact_intent as intent
import assistant_contact_clarify as clarify
import telegram_statistics as bot
from mumu_peer_policy import manual_block, ensure_communication_allowed, PeerCommunicationBlocked
from mumu_store import SharedStore
from mumu_profile_id import lookup, display
import test_mumu1323_alternatives_statistics as alternatives
from test_guided_chain import WHO, snapshot


class Availability(unittest.TestCase):
    chain = alternatives.Alternatives.chain

    def test_live_available_whatsapp_is_choice_not_refusal(self):
        for phrase in ('ТГ у меня не работает, ватсап пока живой',
                       'Телеграм не работает. Ватсап пока работает',
                       'Тг нет, ватсап еще живой'):
            with self.subTest(phrase=phrase):
                c, store, h = self.chain()
                stage, action = c.proposal(snapshot(*h, (phrase, False)))
                self.assertEqual((stage, action), ('pending-clarify', dict(kind='clarify', text=clarify.WHATSAPP_TEXT)))
                self.assertEqual(c.proposal(snapshot(*h, (phrase, False))), (stage, action))
                c.responder.assert_not_called()
                c.reserve_confirmed(WHO, action)
                c.finish(WHO, action, True)
                h.extend([(phrase, False), (action['text'], True)])
                self.assertEqual(c.proposal(snapshot(*h)), ('wait-contact', None))
                self.assertEqual(c.proposal(snapshot(*h, ('9012345678', False))), ('done', None))

    def test_real_refusal_and_unavailability_still_win(self):
        for rows in (('Ватсап пока живой', 'Не пиши мне'),
                     ('Ватсап пока живой', 'Номер не дам'),
                     ('ТГ не работает', 'Ватсап пока не работает')):
            c, store, h = self.chain()
            self.assertEqual(c.proposal(snapshot(*h, *[(x, False) for x in rows])), ('declined', None))
            c.responder.assert_not_called()
        for text in ('Ватсап пока живой?', '> Ватсап пока живой', 'Ватсап пока не живой'):
            self.assertIsNone(intent.available_alternative([dict(text=text)]))

    def test_old_declined_or_unknown_is_not_reopened(self):
        c, store, h = self.chain()
        h.append(('Не пиши мне', False))
        self.assertEqual(c.proposal(snapshot(*h)), ('declined', None))
        self.assertEqual(c.proposal(snapshot(*h, ('Ватсап пока живой', False))), ('declined', None))
        c, store, h = self.chain()
        h.append(('Ватсап пока живой', False))
        _, action = c.proposal(snapshot(*h))
        c.reserve_confirmed(WHO, action)
        c.finish(WHO, action, False)
        with store.connection() as db:
            before = db.execute('SELECT * FROM chain_actions').fetchall()
        self.assertIsNone(c.proposal(snapshot(*h))[1])
        with store.connection() as db:
            self.assertEqual(before, db.execute('SELECT * FROM chain_actions').fetchall())

    def test_number_after_max_already_supported_without_country_guess(self):
        c, store, h = self.chain()
        h.append(('Телеграмма нет, только ватсап и Макс', False))
        _, action = c.proposal(snapshot(*h))
        self.assertEqual(action, dict(kind='clarify', text=clarify.MAX_TEXT))
        c.reserve_confirmed(WHO, action); c.finish(WHO, action, True)
        h.append((action['text'], True))
        self.assertEqual(c.proposal(snapshot(*h, ('9012345678', False))), ('done', None))


    def test_read_budget_notice_keeps_closed_details_and_never_retries(self):
        from assistant_exit_notify import notify_exit
        c, store, h = self.chain()
        sender=MagicMock(return_value=True)
        result=dict(reason='history-read-budget-timeout',diagnostics=dict(last_read_failure=dict(
            error='frame-budget',read_checkpoint='identity',identity_checkpoint='initial-ids',
            scalar_checkpoint='peer-id',private_text='PRIVATE_TOKEN_BODY')))
        notice=notify_exit(c,WHO,result,sender=sender)
        self.assertEqual(notice['notification'],'accepted')
        text=sender.call_args.args[0]
        self.assertIn('frame-budget, identity, initial-ids, peer-id',text)
        self.assertIn('сама по себе не подтверждает',text)
        self.assertNotIn('PRIVATE',text)
        self.assertEqual(notify_exit(c,WHO,result,sender=sender)['notification'],'already-attempted')
        sender.assert_called_once()



def update(text='/num 200', **message_changes):
    message = dict(chat=dict(id=123, type='private'), text=text)
    message['from'] = dict(id=123, is_bot=False)
    message.update(message_changes)
    return dict(update_id=1, message=message)


class BotCommands(unittest.TestCase):
    def test_configured_private_sender_only_and_no_forwarded_commands(self):
        self.assertEqual(bot.command(update(), '123'), '/num 200')
        self.assertEqual(bot.command(update('/num@my_bot 200'), '123'), '/num 200')
        for value in (update(chat=dict(id=124,type='private')),
                      update(chat=dict(id=-123,type='group')),
                      update(**{'from':dict(id=124,is_bot=False)}),
                      update(**{'from':dict(id=123,is_bot=True)}),
                      update(forward_origin={}), update(sender_chat={}), update(**{'from':{}})):
            self.assertIsNone(bot.command(value, str(value['message']['chat']['id']) if value['message']['chat']['id'] < 0 else '123'))

    def test_bad_id_usage_never_writes(self):
        for text in ('/num', '/num 0', '/num -1', '/num 01', '/num 2 3',
                     '/num 9223372036854775808', '/num @someone', '/num 2;DROP TABLE x'):
            blocker = MagicMock()
            answer = bot.manual_reply(text, blocker=blocker)
            self.assertIn('Использование', answer)
            blocker.assert_not_called()

    def test_update_committed_before_mutation_and_no_telegram_retry(self):
        calls=[]
        def commit(offset):calls.append(('commit', offset))
        def block(peer):calls.append(('block',peer));return True
        sender=MagicMock(side_effect=TimeoutError('PRIVATE'))
        offset=bot.cycle('TOKEN','123',0,commit,fetcher=lambda *a:[update()],sender=sender,blocker=block)
        self.assertEqual(calls,[('commit',2),('block','200')])
        sender.assert_called_once()
        bot.cycle('TOKEN','123',offset,commit,fetcher=lambda *a:[update()],sender=sender,blocker=block)
        self.assertEqual(calls,[('commit',2),('block','200')])
        sender.assert_called_once()
        blocker=MagicMock()
        with self.assertRaises(OSError):
            bot.cycle('TOKEN','123',0,MagicMock(side_effect=OSError()),fetcher=lambda *a:[update()],blocker=blocker)
        blocker.assert_not_called()

    def test_database_failure_is_not_acknowledged_or_exposed(self):
        blocker=MagicMock(side_effect=RuntimeError('PRIVATE_PATH_TOKEN'))
        reply=bot.manual_reply('/num 200',blocker=blocker)
        self.assertIn('не подтверждён',reply)
        self.assertNotIn('PRIVATE',reply)


class ManualRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'shared.db';self.old=Path(self.tmp.name)/'old'
        self.a=SharedStore(self.path,self.old,device_port=5557)

    def test_persistent_deny_for_all_ports_and_readonly_lookup(self):
        self.assertTrue(manual_block(WHO['peer'],self.path))
        self.assertFalse(manual_block(WHO['peer'],self.path))
        for port in (5557,5559,5561,5563,5565,16790):
            store=SharedStore(self.path,self.old,device_port=port)
            with self.assertRaises(PeerCommunicationBlocked):
                ensure_communication_allowed(store,dict(WHO,account='999',chat='9999'))
            self.assertIn(WHO['peer'],store.visited_peers())
        self.assertEqual(lookup(self.path,WHO['peer']),('blocked','manual-block'))
        self.assertIn('/num',display(dict(peer=WHO['peer'],samples=2,read_only=True,block_status='blocked',block_reason='manual-block')))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT peer,reason,device,account,chat FROM mumu_peer_blocks').fetchall(),[(WHO['peer'],'manual-block','telegram','','')])

    def test_existing_reason_and_unknown_send_journal_remain_unchanged(self):
        self.a.reserve(dict(attempt=1,account='100',peer=WHO['peer'],chat='300',variant=0),'Synthetic',approved=True)
        with self.a.connection() as db:
            before=db.execute('SELECT * FROM manual_actions').fetchall()
        self.assertTrue(manual_block(WHO['peer'],self.path))
        with self.a.connection() as db:
            self.assertEqual(before,db.execute('SELECT * FROM manual_actions').fetchall())
            self.a.record_peer_outcome(db,dict(WHO,peer='201'),'contact-received')
        self.assertFalse(manual_block('201',self.path))
        self.assertEqual(lookup(self.path,'201'),('blocked','contact-received'))

    def test_missing_registry_and_wrong_platform_never_create_or_modify_db(self):
        missing=Path(self.tmp.name)/'missing.db'
        with self.assertRaises(ValueError):manual_block('200',missing)
        self.assertFalse(missing.exists())
        blank=Path(self.tmp.name)/'blank.db'
        with closing(sqlite3.connect(blank)):pass
        before=blank.read_bytes()
        with self.assertRaises(sqlite3.Error):manual_block('200',blank)
        self.assertEqual(before,blank.read_bytes())
        with patch.dict('os.environ',DVK_MORELOGIN='1'):
            with self.assertRaises(ValueError):manual_block('200',self.path)
