"""Context gates, explicit refusals and no persisted-send resets. No API calls."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import groq_reply as g
import assistant_guided_chain as guided
import assistant_contact_followup as follow
import assistant_ai_drafts as drafts
import mumu_ai
from assistant_store import Store
from test_guided_chain import snapshot,WHO,GREETING,QUESTIONS,CONTACT_TEXT
import test_groq_reply as adapter_tests
from test_groq_reply import reply
from assistant_chain import text_hash
from types import SimpleNamespace
import assistant_key_pool as pool


class Context(unittest.TestCase):
    def context(self,*rows):
        s=snapshot(*rows)
        s['_reply_ids']=[m['id'] for m in s['messages'] if m['sender']==WHO['peer']]
        return s

    def test_repeat_mood_blocked_on_every_stage_even_paraphrased(self):
        s=self.context(('Как настроение?',True),('Всё нормально',False))
        for kind,text in [('question','Как дела?'),('contact','Как настроение? Давай Telegram?'),
                          ('followup','Класс, отдыхай. Как настроение?)')]:
            with self.subTest(kind=kind),self.assertRaises(g.GroqError) as e:
                g.continuation(reply(text),kind,snapshot=s)
            self.assertEqual(e.exception.validation_reason,'repeat-question')

    def test_contextual_question_continuation_allowed_without_repeat(self):
        s=self.context(('Как настроение?',True),('Всё нормально',False),('Скоро на работу',False))
        text='Пусть рабочий день пройдёт спокойно.'
        self.assertEqual(g.continuation(reply(text),'question',snapshot=s),reply(text))
        with self.assertRaises(g.GroqError):g.continuation(reply(text),'question',snapshot=self.context(('Привет',False)))

    def test_peer_quote_is_not_a_previously_asked_self_question(self):
        s=self.context(('> Как настроение?\nЭто цитата',False))
        self.assertEqual(g.continuation(reply('Как настроение?'),'question',snapshot=s),reply('Как настроение?'))

    def test_reply_to_sleep_question_not_stale_location_answer(self):
        s=self.context(('Правда из другого города?',False),('Чего не спишь?',False))
        # Only this newest verified input is current, not the older city topic.
        s['_reply_ids']=[s['messages'][-1]['id']]
        with self.assertRaises(g.GroqError) as e:g.continuation(reply('В Питере жить 😁'),'followup',snapshot=s)
        self.assertEqual(e.exception.validation_reason,'context-mismatch')
        self.assertEqual(g.continuation(reply('Я ИИ-помощник и не сплю, могу поболтать.'),'followup',snapshot=s)['decision'],'reply')
        old=copy.deepcopy(s);old['_reply_ids']=[]
        self.assertEqual(g.continuation(reply('В Питере жить 😁'),'followup',snapshot=old)['decision'],'reply')

    def test_one_new_generation_repairs_repeat_not_sends(self):
        s=self.context(('Как настроение?',True),('Нормально',False))
        bad=adapter_tests.Adapter().client(reply('Как дела?')).open.return_value.__enter__.return_value
        good=adapter_tests.Adapter().client(reply('Пусть вечер пройдёт спокойно.')).open.return_value.__enter__.return_value
        client=MagicMock();client.open.return_value.__enter__.side_effect=[bad,good]
        a=g.Responder(key_loader=lambda:'gsk_'+'x'*32,opener=client,rules_loader=lambda:'Кратко.')
        self.assertEqual(a('question',s),reply('Пусть вечер пройдёт спокойно.'))
        self.assertEqual(a.calls,2)
        self.assertIn('Не задавай его снова',json.loads(client.open.call_args.args[0].data)['messages'][1]['content'])

    def test_greeting_fallback_cannot_repeat_existing_mood_question(self):
        self.assertIsNone(mumu_ai.safe_greeting_reply('question',self.context(('Как дела?',True),('Привет',False))))

    def test_context_survives_key_pool_and_provider_validation(self):
        s=self.context(('Как настроение?',True),('Хорошо',False))
        good=reply('Пусть вечер пройдёт спокойно.')
        class Fake:
            calls=0
            def __init__(self,**kwargs):pass
            def __call__(self,kind,snapshot):self.calls+=1;return good.copy()
        pool._CACHE.clear()
        p=pool.Responder('groq',g.MODEL,['test-key'],factory=Fake,clock=lambda:0)
        self.assertEqual(p('question',s),good)
        a=mumu_ai.Responder('groq',g.MODEL,collector=lambda provider:[])
        a.pools['groq']=p
        self.assertEqual(a('question',s),good)
        self.assertNotIn('openrouter',a.pools)

    def test_persisted_draft_is_checked_without_rehashing_or_regeneration(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        store=Store(Path(t.name)/'a.sqlite3',Path(t.name)/'old');drafts.initialize(store)
        chain=SimpleNamespace(store=store,unseal=lambda x:x)
        s=self.context(('Как настроение?',True),('Нормально',False))
        for text,valid in [('Пусть вечер пройдёт спокойно.',True),('Класс. Как дела?',False)]:
            data=json.dumps(reply(text),ensure_ascii=False).encode()
            with store.connection() as db:
                db.execute("INSERT OR REPLACE INTO ai_drafts VALUES('300','question',?,'ready')",(data,))
            if valid:self.assertEqual(drafts.restore(chain,'300','question',text_hash(text),snapshot=s),text)
            else:
                with self.assertRaises(g.GroqError):drafts.restore(chain,'300','question',text_hash(text),snapshot=s)
            with store.connection() as db:
                self.assertEqual(db.execute('SELECT payload,status FROM ai_drafts').fetchone(),(data,'ready'))


class Refusals(unittest.TestCase):
    def test_stay_here_and_no_apps_are_terminal_but_purpose_questions_are_not(self):
        for text in ['Может и тут','Пиши тут','Лучше здесь','Давай тут пообщаемся','Нет ни того ни другого','Ни того ни другого нет','У меня нет телеграма','Нет']:
            self.assertTrue(follow.refused([dict(text=text)],requested=True),text)
        for text in ['Для чего?','Чего не спишь?','Пиши тут свой номер','Не хочу тут общаться','Может в Telegram?','> Пиши тут\nДавай Telegram','Нет, давай ватсап']:
            self.assertFalse(follow.refused([dict(text=text)],requested=True),text)
        self.assertFalse(follow.refused([dict(text='Может и тут')],requested=False))

    def chain(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        store=Store(Path(t.name)/'a.sqlite3',Path(t.name)/'old')
        c=guided.GuidedChain(store,choose=lambda:0,seal=lambda x:x,unseal=lambda x:x)
        c.bind(snapshot(),(GREETING,),approved=True)
        h=[('Привет',False),(QUESTIONS[0],True),('Отлично',False),(CONTACT_TEXT,True)]
        for i in range(1,5):
            _,a=c.proposal(snapshot(*h[:i]))
            if a:c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
        return c,store,h

    def test_contact_refusal_never_calls_ai_never_reserves_new_send_and_stays_terminal(self):
        for refusal in ['Может и тут','Нет ни того ни другого']:
            c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI after refusal'))
            s=snapshot(*h,(refusal,False))
            stage,a=c.proposal(s);self.assertEqual((stage,a),('declined',None));c.responder.assert_not_called()
            self.assertEqual(c.proposal(snapshot(*h,(refusal,False),('Чего не спишь?',False))),('declined',None))
            with store.connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM chain_actions').fetchone()[0],2)

    def test_already_reserved_unknown_is_kept_when_refused(self):
        c,store,h=self.chain()
        # Simulate unknown contact handler outcome without changing its reservation.
        with store.connection() as db:db.execute("UPDATE chain_actions SET status='reserved-unknown' WHERE kind='contact'")
        self.assertEqual(c.proposal(snapshot(*h,('Может и тут',False))),('declined',None))
        with store.connection() as db:self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='contact'").fetchone()[0],'reserved-unknown')

    def test_old_already_answered_stay_here_stops_without_reopening_send(self):
        c,store,h=self.chain()
        h += [('Может и тут',False)]
        # Emulate 1.3.10 which already answered this preference.
        with patch('assistant_contact_followup.refused',return_value=False),patch('assistant_chain.contact_refused',return_value=False):
            _,a=c.proposal(snapshot(*h))
            self.assertEqual(a['kind'],'followup');c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
            h += [(a['text'],True)]
            c.proposal(snapshot(*h))
        c.responder=MagicMock(side_effect=AssertionError('No AI after known preference'))
        self.assertEqual(c.proposal(snapshot(*h,('Чего не спишь?',False))),('declined',None))
        c.responder.assert_not_called()
        with store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM chain_followup_archive").fetchone()[0],'outgoing-observed')
