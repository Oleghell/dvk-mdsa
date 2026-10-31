"""Reports 246/247, synthetic phone data: no live accounts, sends or API calls."""
import copy
import unittest
from unittest.mock import MagicMock
import assistant_contact_clarify as clarify
from assistant_chain import text_hash
from assistant_store import Store
from pathlib import Path
import tempfile
from assistant_exit_notify import REASONS
from assistant_history_wait import verified_read_budget
from one_chat_device import ReadStopped
from shared_contact import self_shared, payload
import test_mumu1323_alternatives_statistics as fixtures
import test_guided_chain as g
import assistant_guided_chain as guided


def budget(**changes):
    value=dict(error='frame-budget',stage='navigation-stopped',metadata_checkpoint='ready',
        read_checkpoint='last-message',wait_reason='none',frames=2,managed_calls=152,
        message_slot=4,scalar_state='negative',scalar_checkpoint='message-chat-id',
        identity_checkpoint='recheck',message_direction='own',message_kind='text')
    value.update(changes)
    return value


def stopped_budget():
    d=budget();return ReadStopped(d.pop('error'),d)


class Contacts(unittest.TestCase):
    chain=fixtures.Alternatives.chain
    def test_exact_whatsapp_examples_choose_one_clarification_without_ai(self):
        for text in ('Ватс ап','Ну работает вроде ватцап'):
            c,store,h=self.chain()
            expected=('pending-clarify',dict(kind='clarify',text=clarify.WHATSAPP_TEXT))
            self.assertEqual(c.proposal(g.snapshot(*h,(text,False))),expected)
            c.responder.assert_not_called()

    def test_old_bare_no_is_not_a_new_contact_refusal(self):
        for text in ('Ватс ап','Ну работает вроде ватцап','123 456 78 90'):
            t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
            store=Store(Path(t.name)/'db',Path(t.name)/'old')
            c=guided.GuidedChain(store,choose=lambda:0,seal=lambda b:b,unseal=lambda b:b)
            c.bind(g.snapshot(),(g.GREETING,),approved=True)
            from assistant_contact_policy import enable
            enable(store)
            h=[('Привет',False),(g.QUESTIONS[0],True),('Нет',False),(g.CONTACT_TEXT,True)]
            for i in range(1,5):
                _,action=c.proposal(g.snapshot(*h[:i]))
                if action:c.reserve_confirmed(g.WHO,action);c.finish(g.WHO,action,True)
            c.responder=MagicMock(side_effect=AssertionError('No API'))
            result=c.proposal(g.snapshot(*h,(text,False)))
            self.assertEqual(result[0], 'done' if text[0].isdigit() else 'pending-clarify')
            c.responder.assert_not_called()

    def test_formatted_countryless_phone_requires_verified_contact_context(self):
        for text in ('123 456 78 90','123-456-78-90','(123) 456 78 90','1234567890'):
            self.assertEqual(self_shared(text,requested=True),['1234567890'])
            self.assertEqual(self_shared(text),[])
            self.assertEqual(payload('Тест',['1234567890'])['contacts'],['1234567890'])
        for text in ('Код 123 456 78 90','Номер подруги 123 456 78 90',
                     '> 123 456 78 90','Не передавай 123 456 78 90','123 456 78 90?'):
            self.assertEqual(self_shared(text,requested=True),[])

    def test_exact_phone_saved_once_without_requesting_it_again(self):
        c,store,h=self.chain();sample=g.snapshot(*h,('123 456 78 90',False))
        self.assertEqual(c.proposal(sample),('done',None))
        self.assertEqual(c.proposal(sample),('done',None))
        with store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_contact_outbox').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chain_actions WHERE kind='clarify'").fetchone()[0],0)
        c.responder.assert_not_called()

    def test_real_current_refusal_and_unknown_reservations_remain_terminal(self):
        for refusal in ('Нет','Не пиши','Номер не дам','Давай тут пообщаемся'):
            c,store,h=self.chain()
            self.assertEqual(c.proposal(g.snapshot(*h,(refusal,False))),('declined',None))
            with store.connection() as db:before=db.execute('SELECT * FROM chain_actions').fetchall()
            self.assertEqual(c.proposal(g.snapshot(*h,(refusal,False),('Ватс ап',False))),('declined',None))
            with store.connection() as db:self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())

    def test_durable_contact_stage_no_is_still_a_refusal(self):
        c,store,h=self.chain();sample=g.snapshot(*h,('Нет',False))
        # Exact contextual input previously used by a legacy followup.
        with store.connection() as db:
            db.execute("INSERT INTO chain_actions VALUES(?, 'followup', ?, ?, 'outgoing-observed')",
                (g.WHO['chat'],sample['messages'][-1]['id'],text_hash('legacy response')))
        self.assertEqual(c.proposal(sample),('declined',None))

    def test_declined_notice_does_not_claim_every_policy_closure_is_a_refusal(self):
        self.assertNotIn('Собеседник отказался',REASONS['declined'])
        from assistant_exit_notify import notify_exit
        for text in ('Ватс ап','Ну работает вроде ватцап','123 456 78 90','Не пиши мне'):
            c,store,h=self.chain();sender=MagicMock(return_value=True)
            notify_exit(c,g.WHO,dict(reason='declined',_exit_messages=[text]),sender=sender)
            message=sender.call_args.args[0]
            self.assertEqual('Собеседник отказался' in message,text=='Не пиши мне')


class ReadRecovery(unittest.TestCase):
    setUp=g.WholeChain.setUp
    send=g.WholeChain.send
    def test_exact247_shape_is_read_budget_not_success_or_identity_proof(self):
        self.assertTrue(verified_read_budget(budget()))
        for changes in (dict(error='identity-changed'),dict(error='message-invalid'),
                dict(error='nonpositive-message-chat-id'),dict(message_direction='not-own'),
                dict(scalar_checkpoint='chat-id'),dict(scalar_state='zero'),
                dict(identity_checkpoint='saved-binding'),dict(read_checkpoint='identity'),
                dict(message_slot=True),dict(message_slot=-1),dict(message_kind='not-read')):
            self.assertFalse(verified_read_budget(budget(**changes)),changes)

    def walk(self,values):
        self.reader=MagicMock(side_effect=values)
        return guided.walk(self.chain,g.WHO,self.stop,self.approve,self.reader,self.send,
            approved=True,greetings=(g.GREETING,),notifier=self.notifier,pause=lambda _:False,max_polls=12)

    def test_post_send_interruption_retries_only_read_and_never_resends(self):
        seq=g.sequence();out=self.walk(seq[:3]+[stopped_budget()]+seq[3:])
        self.assertEqual(out['status'],'chain-completed')
        self.assertEqual(out['diagnostics']['read_retries'],1)
        self.assertEqual(len(self.sent),2)  # one question, one contact proposal
        self.assertTrue(all(call.args==(g.WHO,) for call in self.reader.call_args_list))

    def test_persistent_post_send_budget_defers_without_replaying_unknown_send(self):
        seq=g.sequence();out=self.walk(seq[:3]+[stopped_budget() for _ in range(4)])
        self.assertEqual(out['reason'],'history-read-budget-timeout')
        self.assertEqual(len(self.sent),1)
        with self.store.connection() as db:before=db.execute('SELECT * FROM chain_actions').fetchall()
        again=self.walk([seq[1] for _ in range(8)])
        self.assertEqual(len(self.sent),1)
        with self.store.connection() as db:self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())


class ProfileSkipValidation(unittest.TestCase):
    def raw(self,latched=False):
        from test_chat_batch import cycle
        from assistant_pass import CYCLE_TIMEOUT_MS
        raw=cycle();n=raw['navigation']
        n.update(cycle_timeout_ms=CYCLE_TIMEOUT_MS,profile_read_budget_retries=0,
            greeting_frame_splits=1,profile_ready_waits=0,submit_frame_retries=0,shared_peer_skipped=latched,
            stage='navigation-stopped',error='cancelled',phase='submit-greeting',
            send_attempted=False,send_handler_returned=False,greeting_variant=None,messages_sent=0,
            chat_back_attempted=False,chat_back_completed=False,chat_return_verified=False,
            chat_return_route='not-checked',close_attempted=False,close_completed=False,return_verified=False)
        return raw

    def test_stop_before_skip_observation_preserves_failure_without_success_or_replay(self):
        from unittest.mock import patch
        from assistant_pass import validate
        for latched in (False,True):
            raw=self.raw(latched);before=copy.deepcopy(raw)
            with patch.dict('os.environ',DVK_MUMU_MULTI='1'):
                self.assertIs(validate(raw,shared_peer_skipped=True),raw)
            self.assertEqual(raw,before)
            self.assertEqual(raw['navigation']['stage'],'navigation-stopped')

    def test_unconfirmed_skip_never_normalizes_a_success_or_send(self):
        from unittest.mock import patch
        from assistant_pass import validate
        for changes in (dict(stage='navigation-ready'),dict(send_attempted=True),
                        dict(send_handler_returned=True),dict(send_attempted='false')):
            raw=self.raw();raw['navigation'].update(changes)
            with patch.dict('os.environ',DVK_MUMU_MULTI='1'),self.assertRaises(ValueError):
                validate(raw,shared_peer_skipped=True)
        with self.assertRaises(ValueError):validate(self.raw(True),shared_peer_skipped=False)
