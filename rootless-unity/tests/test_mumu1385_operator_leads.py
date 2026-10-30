"""v1.3.85: the operator KEEPS leading; the chain must keep working.

Reports (user): «если я сам начинал диалог и вел его то ты не игноришь а тоже
с ним работаешь если там все по структуре» — v1.3.84 adoption binds an
operator-started dialog once, but the NEXT manually typed outgoing still hit
the terminal unjournalled-outgoing review, so the freshly adopted (or any
tracked) dialog was lost again exactly as before. Also: «Собеседник: «Я в
Максе сижу» … Пропущено: Цепочка закрыта без нового ответа … лимит
уточнений» — after the one clarification a recognized messenger choice still
closed the chain; it must re-ask the app-specific number question instead.
Synthetic only: no device, no network, no live services.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

import assistant_chain
from assistant_chain import text_hash
from assistant_contact_intent import max_selected
from assistant_store import Store
from test_inbox_profiles import Base, WHO, nav, msg, snap
from conversation_engine import QUESTIONS, CONTACT_TEXT

NUMBER = '+79991234567'


class MaxWordOrder(unittest.TestCase):
    def test_presence_verb_after_the_app_name_is_a_choice(self):
        for phrase in ('Я в Максе сижу', 'В Максе сижу', 'я в максе общаюсь',
                       'В Максе переписываюсь', 'Максе сижу постоянно'):
            with self.subTest(phrase=phrase):
                self.assertTrue(max_selected([dict(text=phrase)]), phrase)

    def test_negated_presence_after_the_app_name_is_not_a_choice(self):
        for phrase in ('Я в Максе не сижу', 'в максе не общаюсь', 'не сижу в максе'):
            with self.subTest(phrase=phrase):
                self.assertFalse(max_selected([dict(text=phrase)]), phrase)

    def test_question_and_person_clauses_stay_unrecognized(self):
        for phrase in ('Я в Максе сижу?', 'Меня зовут Макс, сижу тут', 'друг с Максом сижу'):
            with self.subTest(phrase=phrase):
                self.assertFalse(max_selected([dict(text=phrase)]), phrase)


class OperatorLeads(Base):
    def test_operator_outgoing_continues_chain_and_answers_incoming(self):
        """v1.3.85: a manually typed outgoing no longer stops the chain.

        While HIS text is the newest arrival the bot stays quiet (the peer was
        already answered by the human); the peer's NEXT message is answered by
        the bot exactly as in a program-led dialog.
        """
        self.journal();chain=self.chain();chain.consume(snap())
        incoming=msg(1002,'Входящее');manual=msg(1003,'Ручной ответ',True)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                      [snap(incoming,manual)],chain=chain)
        self.assertEqual(out['review_causes'],{})
        self.assertEqual(out['submission_calls'],0)
        self.assertFalse(self.sent)
        # v1.3.97: the clean waiting stage, not 'incoming-answer-pending' - the
        # owed projection sees the operator's own word AFTER her arrival, so
        # no false answer-pending defer/notice fires on the human's answer.
        self.assertEqual(out['outcomes'],{'chain-waiting:wait-reply':1})
        with chain.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs').fetchone(),('wait-reply',))
            self.assertEqual({r[0] for r in db.execute('SELECT message FROM chain_seen')},{'1001','1002','1003'})
            self.assertEqual(db.execute('SELECT reason FROM chain_review_reasons').fetchall(),[])
        # The peer writes again AFTER the operator's manual answer: the bot answers.
        import assistant_history_wait as history_wait
        history_wait.clear(chain.store, WHO)
        fresh=msg(1004,'Новое сообщение');question=msg(1005,QUESTIONS[0],True)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                      [snap(incoming,manual,fresh),snap(incoming,manual,fresh),snap(incoming,manual,fresh,question)],chain=chain)
        self.assertEqual(out['submission_calls'],1)
        self.assertEqual(self.sent,[QUESTIONS[0]])
        # The operator-answered arrival keeps its receipt pending (the program
        # never claims the human's answer), but v1.3.97's owed projection sees
        # our side's later words (his manual answer, the bot's confirmed
        # question) shadowing both arrivals: the visit ends in the CLEAN
        # waiting stage - the chat stays a scan target exactly as before,
        # without the inert answer-pending cooldown on top.
        self.assertEqual(out['outcomes'],{'chain-waiting:wait-mood':1})

    def test_number_beside_operator_request_is_saved_and_forwarded(self):
        self.journal(WHO)
        chain = self.chain()
        chain.consume(snap())  # greeting anchored: wait-reply, greeting seen
        with chain.store.connection() as db:
            db.execute("UPDATE chain_dialogs SET stage='wait-contact'")
        # The operator asked for the number himself; the peer answers it.
        sample = snap(msg(1002, 'Как настроение?'), msg(1003, NUMBER))
        notice = MagicMock(return_value=True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [sample, dict(sample, peer_name='Мария')], chain=chain, notifier=notice)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['contacts_detected'], 1)
        notice.assert_called_once_with(dict(name='Мария', contacts=[NUMBER]))
        self.assertFalse(self.sent)

    def test_pending_send_verifies_one_match_beside_operator_text(self):
        self.journal();chain=self.chain();chain.consume(snap())
        # Greeting answered; the bot's question was reserved and returned.
        stage,action=chain.proposal(snap(msg(1002,'Привет')))
        self.assertEqual(action['kind'],'question')
        chain.reserve_confirmed(WHO,action);chain.finish(WHO,action,True)
        hello=msg(1002,'Привет');question=msg(1003,QUESTIONS[0],True)
        # The operator typed BESIDE the program's question: both appear together.
        stage,action=chain.proposal(snap(hello,question,msg(1004,'Ручное уточнение',True)))
        self.assertEqual((stage,action),('wait-mood',None))
        with chain.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='question'").fetchone(),
                             ('outgoing-observed',))
            self.assertEqual({r[0] for r in db.execute('SELECT message FROM chain_seen')},{'1001','1002','1003','1004'})


class RecycledClarify(unittest.TestCase):
    def test_unknown_reservation_is_never_recycled_but_observed_one_reasks(self):
        from test_mumu1311_context import Refusals
        from assistant_contact_clarify import WHATSAPP_TEXT, TELEGRAM_TEXT
        c, store, h = Refusals.chain(self)
        with store.connection() as db:
            db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,'handler-returned-unconfirmed')",
                       (WHO['chat'], 'clarify', '1005', text_hash(WHATSAPP_TEXT)))
            # An unobserved/unknown reservation is never touched, whatever text.
            self.assertFalse(assistant_chain.recycled_clarify(db, WHO['chat'], '1006', WHATSAPP_TEXT))
            self.assertFalse(assistant_chain.recycled_clarify(db, WHO['chat'], '1006', TELEGRAM_TEXT))
            self.assertEqual(db.execute("SELECT trigger FROM chain_actions WHERE kind='clarify'").fetchone(),
                             ('1005',))
            db.execute("UPDATE chain_actions SET status='outgoing-observed' WHERE kind='clarify'")
            self.assertTrue(assistant_chain.recycled_clarify(db, WHO['chat'], '1007', TELEGRAM_TEXT))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chain_followup_archive").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT trigger,status FROM chain_actions WHERE kind='clarify'").fetchone(),
                             ('1007', 'reserved-unknown'))

    def test_post_clarify_choice_no_longer_closes_the_chain(self):
        from assistant_contact_policy import enable, should_close
        from assistant_contact_clarify import chosen
        from test_mumu1311_context import Refusals
        c, store, h = Refusals.chain(self)
        enable(store)
        with store.connection() as db:
            db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,'outgoing-observed')",
                       (WHO['chat'], 'clarify', '1005', text_hash('старое уточнение')))
            # v1.3.85: a recognized choice after the one clarification keeps the
            # chain open for the app-specific re-ask; off-topic still closes.
            self.assertFalse(should_close(db, dict(identity=dict(WHO)), 'wait-contact',
                                          [dict(text='Я в Максе сижу')],
                                          requested=True, max_choice=True))
            self.assertTrue(should_close(db, dict(identity=dict(WHO)), 'wait-contact',
                                         [dict(text='Какая погода в городе?')],
                                         requested=True))
            self.assertTrue(chosen([dict(text='Я в Максе сижу')]))


class GreetingDedup(unittest.TestCase):
    def test_greeting_never_targets_a_bound_peer(self):
        from mumu_store import SharedStore
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'db'; old = Path(temp) / 'old'
            store = SharedStore(path, old, device_port=5557)
            store.reserve(dict(attempt=1, account='100', peer='210', chat='-1', variant=0),
                          'Привет', approved=True)
            with store.connection() as db:
                db.execute('''CREATE TABLE IF NOT EXISTS guided_bindings(
                    account TEXT, peer TEXT, chat TEXT UNIQUE, greeting_hash TEXT,
                    PRIMARY KEY(account,peer))''')
                db.execute('''CREATE TABLE IF NOT EXISTS operator_bindings(
                    account TEXT, peer TEXT, chat TEXT UNIQUE, anchor_hash TEXT,
                    PRIMARY KEY(account,peer))''')
                db.execute("INSERT INTO guided_bindings VALUES('100','211','311','hash')")
                db.execute("INSERT INTO operator_bindings VALUES('100','212','312','hash')")
                self.assertTrue(store.blocked(db, '210'))
                self.assertTrue(store.blocked(db, '211'))
                self.assertTrue(store.blocked(db, '212'))
                self.assertFalse(store.blocked(db, '213'))
            for peer in ('210', '211', '212'):
                self.assertIn(peer, store.visited_peers())


if __name__ == '__main__':
    unittest.main()
