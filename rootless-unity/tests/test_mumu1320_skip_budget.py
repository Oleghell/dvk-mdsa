"""Local skip and bounded post-contact attempts; no device or external API."""
import copy
import unittest
from unittest.mock import MagicMock
import assistant_pass
import assistant_contact_followup as follow
import assistant_contact_budget as budget
import assistant_guided_chain as guided
import test_mumu1311_context as fixtures
from test_guided_chain import snapshot,WHO
from test_mumu1311_autorecovery import skipped
import test_mumu1311_autorecovery as recovery
from test_inbox_profiles import cycle_result


def disabled():
    v=skipped();v['navigation'].update(profile_read_skip_reason='input-disabled',
        profile_input_enabled=False,profile_ready_waits=0,wait_reason='none')
    return v


class InputSkip(unittest.TestCase):
    go=recovery.ContinueProfiles.go
    def test_native_validation_requires_disabled_model_and_verified_return(self):
        self.assertIs(assistant_pass.validate(disabled()).__class__,dict)
        for key,value in [('profile_input_enabled',None),('profile_input_enabled',True),('profile_input_enabled',0),
                          ('chat_identity_verified',False),('send_attempted',True),('chat_back_completed',False),('return_verified',False)]:
            v=disabled();v['navigation'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):assistant_pass.validate(v)
    def test_many_deleted_profiles_are_skips_not_port_recovery(self):
        notify=MagicMock()
        values=[disabled() for _ in range(5)]+[cycle_result(send_attempted=True,send_handler_returned=True)]
        out,calls=self.go(values,notifier=notify)
        self.assertEqual((out['status'],calls),('profiles-completed',6))
        self.assertEqual(out['skipped_input_disabled'],5)
        self.assertEqual(out['consecutive_read_recoveries'],0)
        self.assertFalse(out['recovery_events']);notify.assert_not_called()
    def test_wrong_or_unknown_return_never_becomes_skip(self):
        for change in ({'chat_back_completed':False},{'return_verified':False},{'cleanup_failed':True}):
            v=disabled();v['navigation'].update(change)
            out,calls=self.go([v],notifier=MagicMock())
            self.assertEqual(calls,1);self.assertEqual(out['status'],'profiles-stopped')


class ContactBudget(unittest.TestCase):
    chain=fixtures.Refusals.chain
    def answer(self,c,h,text):
        h.append((text,False))
        stage,a=c.proposal(snapshot(*h));self.assertIsNotNone(a)
        c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
        h.append((a['text'],True));c.proposal(snapshot(*h))
        return a
    def two(self):
        c,store,h=self.chain()
        self.answer(c,h,'Давай ватсап')
        self.answer(c,h,'Чего не спишь?')
        return c,store,h
    def test_no_third_reply_after_restart_preserves_journal(self):
        c,store,h=self.two()
        with store.connection() as db:before=db.execute('SELECT * FROM chain_actions').fetchall()
        c=guided.GuidedChain(store,choose=lambda:0,seal=lambda x:x,unseal=lambda x:x)
        c.responder=MagicMock(side_effect=AssertionError('No API'))
        self.assertEqual(c.proposal(snapshot(*h,('Чем занимаешься?',False))),('declined',None))
        self.assertEqual(c.proposal(snapshot(*h,('Чем занимаешься?',False),('Ок',False))),('declined',None))
        with store.connection() as db:self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())
        c.responder.assert_not_called()
    def test_current_contact_wins_over_reached_budget(self):
        c,store,h=self.two();c.responder=MagicMock(side_effect=AssertionError('No API'))
        self.assertEqual(c.proposal(snapshot(*h,('Мой ватсап +79991234567',False))),('done',None))
        c.responder.assert_not_called()
    def test_unknown_second_send_is_never_replayed_or_cleared(self):
        c,store,h=self.chain();self.answer(c,h,'Давай ватсап');h.append(('Чего не спишь?',False))
        _,a=c.proposal(snapshot(*h));c.reserve_confirmed(WHO,a);c.finish(WHO,a,False)
        with store.connection() as db:before=db.execute('SELECT * FROM chain_actions').fetchall()
        self.assertEqual(c.proposal(snapshot(*h)),('submission-unknown',None))
        with store.connection() as db:self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())
    def test_two_contextual_followups_recycle_once_then_stop(self):
        c,store,h=self.chain()
        c.responder=MagicMock(side_effect=[dict(decision='reply',text='Пусть вечер пройдёт спокойно.'),
                                         dict(decision='reply',text='Хорошего отдыха.')])
        self.answer(c,h,'Чего не спишь?')
        self.answer(c,h,'Отдыхаю')
        self.assertEqual(c.responder.call_count,2)
        with store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chain_followup_archive").fetchone()[0],1)
        self.assertEqual(c.proposal(snapshot(*h,('Чем занимаешься?',False))),('declined',None))
        self.assertEqual(c.responder.call_count,2)
    def test_awaiting_approval_draft_does_not_consume_second_slot(self):
        c,store,h=self.chain();self.answer(c,h,'Давай ватсап')
        h.append(('Чего не спишь?',False));stage,action=c.proposal(snapshot(*h))
        with store.connection() as db:self.assertFalse(budget.exhausted(db,WHO['chat']))
        self.assertEqual(c.proposal(snapshot(*h)),(stage,action))
    def test_archived_followups_count_without_resetting_reservations(self):
        c,store,h=self.chain();c.responder=MagicMock()
        with store.connection() as db:
            db.execute("CREATE TABLE chain_followup_archive(chat TEXT,trigger TEXT,text_hash TEXT,status TEXT,inputs TEXT,PRIMARY KEY(chat,trigger))")
            db.execute("INSERT INTO chain_followup_archive VALUES('300','old-1','hash-1','outgoing-observed','[]')")
            db.execute("INSERT INTO chain_followup_archive VALUES('300','old-2','hash-2','outgoing-observed','[]')")
            self.assertTrue(budget.exhausted(db,WHO['chat']))
        self.assertEqual(c.proposal(snapshot(*h,('Что делаешь?',False))),('declined',None))
        c.responder.assert_not_called()
    def test_truncated_history_is_not_a_terminal_success(self):
        c,store,h=self.two()
        self.assertEqual(c.proposal(snapshot(*h[:-1])),('manual-review',None))
    def test_both_unavailable_is_immediate_skip_from_actual_example(self):
        c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No API'))
        text='И то и то работает не очень... Даже с впн...'
        self.assertEqual(c.proposal(snapshot(*h,(text,False))),('declined',None))
        self.assertFalse(follow.refused([dict(text=text)],requested=False))
        for negative in ('И то и то работает не очень?', 'И то и то работает, давай тг', 'Оба работают'):
            self.assertFalse(follow.refused([dict(text=negative)],requested=True))
        c.responder.assert_not_called()


class NumberChoice(unittest.TestCase):
    chain=fixtures.Refusals.chain
    def test_indifferent_reply_uses_fixed_number_question_without_ai(self):
        from assistant_contact_clarify import NUMBER_TEXT
        for text in ('Да без разницы','Без разницы','Мне всё равно','Как тебе удобнее'):
            c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No API'))
            sample=snapshot(*h,(text,False))
            stage,action=c.proposal(sample)
            self.assertEqual((stage,action),('pending-clarify',dict(kind='clarify',text=NUMBER_TEXT)))
            self.assertEqual(c.proposal(sample),(stage,action))
            c.reserve_confirmed(WHO,action);c.finish(WHO,action,True)
            self.assertEqual(c.proposal(snapshot(*h,(text,False),(NUMBER_TEXT,True))),('wait-contact',None))
            self.assertEqual(c.proposal(snapshot(*h,(text,False),(NUMBER_TEXT,True),('Мой ватсап +79991234567',False))),('done',None))
            c.responder.assert_not_called()
    def test_quotes_questions_and_actual_contacts_do_not_trigger_number_question(self):
        from assistant_contact_clarify import indifferent,chosen
        for text in ('Без разницы?', '> Да без разницы', 'Не без разницы','Без разницы, останемся тут'):
            self.assertFalse(indifferent([dict(text=text)]))
        c,store,h=self.chain()
        self.assertEqual(c.proposal(snapshot(*h,('Без разницы, мой ватсап +79991234567',False))),('done',None))
    def test_old_generic_followup_can_be_corrected_once_without_resend(self):
        from unittest.mock import patch
        from assistant_contact_clarify import NUMBER_TEXT
        c,store,h=self.chain();h.append(('Да без разницы',False))
        with patch('assistant_chain.indifferent_selected',return_value=False),patch('assistant_contact_clarify.indifferent',return_value=False):
            _,a=c.proposal(snapshot(*h));c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
            h.append((a['text'],True));c.proposal(snapshot(*h))
        c.responder=MagicMock(side_effect=AssertionError('No API'))
        stage,a=c.proposal(snapshot(*h,('Давай',False)))
        self.assertEqual((stage,a),('pending-clarify',dict(kind='clarify',text=NUMBER_TEXT)))
        c.responder.assert_not_called()
