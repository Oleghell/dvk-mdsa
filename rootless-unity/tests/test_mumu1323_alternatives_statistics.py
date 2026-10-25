"""Alternatives, greeting aggregates and bounded model-source regressions."""
from datetime import datetime,timezone
from pathlib import Path
import tempfile,unittest
from unittest.mock import MagicMock,patch
import assistant_contact_clarify as clarify
import assistant_contact_intent as intent
import test_mumu1311_context as fixtures
from test_guided_chain import snapshot,WHO
from assistant_store import Store
import assistant_statistics as stats

class Alternatives(unittest.TestCase):
    def chain(self):
        c,store,h=fixtures.Refusals.chain(self)
        from assistant_contact_policy import enable
        enable(store)
        c.responder=MagicMock(side_effect=AssertionError('No API'))
        return c,store,h
    def test_offered_max_questions_and_typo_are_contact_related(self):
        for text in ('Макс?','А макса нет?','MAX ?','Мак?','А в макс можно?',
                     'У меня толька макс','А у тебя есть Макс?'):
            with self.subTest(text=text):
                c,store,h=self.chain()
                self.assertEqual(c.proposal(snapshot(*h,(text,False))),('pending-clarify',dict(kind='clarify',text=clarify.MAX_TEXT)))
                c.responder.assert_not_called()
    def test_only_available_app_is_requested_no_ai(self):
        cases=[(('Телеграмм у меня не работает','Ватсапп есть'),clarify.WHATSAPP_TEXT),
               (('Телега\nВатцап не работает',),clarify.TELEGRAM_TEXT),
               (('Нет телеграма','Вацап есть'),clarify.WHATSAPP_TEXT),
               (('Ватсап не работает. Тг есть',),clarify.TELEGRAM_TEXT)]
        for rows,text in cases:
            with self.subTest(rows=rows):
                c,store,h=self.chain();sample=snapshot(*h,*[(x,False) for x in rows])
                stage,a=c.proposal(sample);self.assertEqual((stage,a),('pending-clarify',dict(kind='clarify',text=text)))
                self.assertEqual(c.proposal(sample),(stage,a));c.responder.assert_not_called()
    def test_unavailable_max_question_is_not_an_asserted_refusal(self):
        self.assertTrue(intent.max_selected([dict(text='А макса нет?')]))
        for text in ('Макса нет','Не хочу в MAX','Макс не работает','Кто такой Макс?',
                     '> Макс?\nТы откуда?', 'У меня работает только Макс?'):
            self.assertFalse(intent.max_selected([dict(text=text)]),text)
    def test_unknown_clarification_not_replayed(self):
        c,store,h=self.chain();h.append(('Макс?',False));_,a=c.proposal(snapshot(*h))
        c.reserve_confirmed(WHO,a);c.finish(WHO,a,False)
        with store.connection() as db:before=db.execute('SELECT * FROM chain_actions').fetchall()
        _,again=c.proposal(snapshot(*h));self.assertIsNone(again)
        with store.connection() as db:self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())

class GreetingStatistics(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.path=Path(t.name)/'db';self.store=Store(self.path,Path(t.name)/'legacy')
    def test_returned_only_deduplicated_average_unknown_separate(self):
        now=datetime(2026,10,24,12,tzinfo=timezone.utc)
        with self.store.connection() as db:
            for peer,status in [('200','handler-returned-unconfirmed'),('201','handler-returned-unconfirmed'),('202','attempted-unknown'),('203','not-invoked')]:
                stats.greeting_reserved(db,'100',peer,datetime(2026,10,24,6,tzinfo=timezone.utc))
                stats.greeting_finished(db,'100',peer,status)
            stats.greeting_reserved(db,'100','200',now)
        text=stats.render('/today',self.path,now)
        self.assertIn('Новым собеседникам написано: 2',text)
        self.assertIn('Неизвестный исход первого приветствия: 1',text)
        self.assertIn('календарный час: 0.17',text)
        self.assertNotIn('200',text)
    def test_reserve_finish_hooks_and_shared_ports(self):
        from mumu_store import SharedStore
        for number,peer in ((5557,'210'),(5563,'211')):
            store=SharedStore(self.path,self.path.parent/'old',device_port=number)
            action=store.reserve(dict(attempt=1,account='100',peer=peer,chat='300',variant=0),'Привет',approved=True)
            store.finish(action,dict(send_attempted=True,send_handler_returned=True))
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM global_greeting_statistics WHERE status='handler-returned-unconfirmed'").fetchone()[0],2)
    def test_backfill_does_not_change_journal_or_duplicate_events(self):
        with self.store.connection() as db:
            db.execute("INSERT INTO manual_actions(account,peer,initial_chat,text_hash,confirmed,status,created_at) VALUES('100','200','300','hash',1,'handler-returned-unconfirmed','2026-10-24 06:00:00')")
            before=db.execute('SELECT * FROM manual_actions').fetchall()
            db.execute("DELETE FROM inbox_reply_policy WHERE key='greeting-statistics-v1'")
        self.store=Store(self.path,self.path.parent/'old');Store(self.path,self.path.parent/'old')
        with self.store.connection() as db:
            self.assertEqual(before,db.execute('SELECT * FROM manual_actions').fetchall())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM global_greeting_statistics').fetchone()[0],1)
        self.assertIn('написано: 1',stats.render('/today',self.path,datetime(2026,10,24,12,tzinfo=timezone.utc)))
    def test_exclusive_period_and_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.store.connection() as db:
                stats.greeting_reserved(db,'100','200');raise RuntimeError()
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM global_greeting_statistics').fetchone()[0],0)

class RecentModels(unittest.TestCase):
    def test_scan_is_bounded_and_checks_actual_reverse_index(self):
        import dialog_models as models
        source=models.build(recent_limit=50,reverse=True)
        self.assertIn('const scanEnd=Math.min(count,50)',source)
        self.assertIn('const modelIndex=scanEnd-1-state.scanIndex',source)
        self.assertIn('stableModels(current,manager,cm,count,modelIndex,chat)',source)
        self.assertIn('state.scanIndex<scanEnd',source)
        self.assertNotIn('state.scanIndex<count?',source)
        self.assertIn('state.scanIndex<count?',models.build())
    def test_invalid_window_and_cursor_are_rejected(self):
        import dialog_models as models
        for limit,reverse in ((0,True),(True,True),(129,True),(None,True),(50,1)):
            with self.assertRaises(ValueError):models.build(recent_limit=limit,reverse=reverse)
        with self.assertRaises(ValueError):models.build(recent_limit=50,reverse=True,offset=50)
        raw=dict(navigation=dict(private_model_scan=dict(next=50,count=130,skipped_headers=0)))
        with self.assertRaises(ValueError):models.validate(raw,recent_limit=50,reverse=True)
    def test_production_mumu_inbox_adapter_uses_recent_reverse_window(self):
        import threading
        import assistant_inbox as inbox
        from assistant_settings import Settings
        from mumu_store import SharedStore
        with tempfile.TemporaryDirectory() as directory:
            store=SharedStore(Path(directory)/'db',Path(directory)/'old',device_port=5557)
            result=dict(inbox.report(),status='inbox-empty',reason='no-chain-dialogs')
            with patch.object(inbox,'walk',return_value=result) as walk,patch('assistant_ai.responder',return_value=None):
                inbox.run(Settings(errors_enabled=False),threading.Event(),MagicMock(),store=store,
                    greetings=('Привет',),reader=MagicMock(),sender=MagicMock(),notifier=MagicMock(),exit_notifier=MagicMock())
            navigator=walk.call_args.kwargs['navigator']
            self.assertEqual(navigator.keywords['recent_limit'],50)
            self.assertIs(navigator.keywords['reverse'],True)
