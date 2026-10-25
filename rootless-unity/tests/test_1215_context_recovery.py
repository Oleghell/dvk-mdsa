"""User-report regressions. No device, real contacts, API keys or external calls."""
import unittest
from unittest.mock import MagicMock, patch
import test_guided_chain as guide
import test_inbox_profiles as ih
import test_1210_context_loading as context
import test_1214_read_budget as budget_test
import assistant_guided_chain as guided
import assistant_inbox as inbox
import assistant_history_wait as wait
from assistant_chain import text_hash
from assistant_contact_followup import TEXT, eligible
from one_chat_device import ReadStopped, safe_read_failure
from one_chat_send import checked_reply,build
from groq_reply import decision,GroqError
from assistant_authorization import RunAuthorization

WHO=guide.WHO

def identity_budget(**changes):
    return budget_test.budget(read_checkpoint='identity',scalar_checkpoint='chat-id',frames=2,managed_calls=232,
                              message_slot=5,message_direction='own',**changes)

class IdentityBudget(guide.WholeChain):
    def test_exact_diagnostic_read_recovery(self):
        self.assertTrue(wait.verified_read_budget(safe_read_failure(identity_budget())))
        out=self.walk([identity_budget()]+guide.sequence())
        self.assertEqual(out['status'],'chain-completed');self.assertEqual(out['diagnostics']['read_retries'],1)
        self.assertEqual(out['submission_calls'],2)

    def test_exhausted_recheck_not_identity_success(self):
        out=self.walk([identity_budget()]*4)
        self.assertEqual(out['reason'],'history-read-budget-timeout');self.assertFalse(self.sent)

    def test_identity_mismatch_after_budget_still_stops(self):
        out=self.walk([identity_budget(),ReadStopped('identity-changed')])
        self.assertEqual(out['status'],'chain-stopped');self.assertFalse(self.sent)

    def test_nonpositive_or_missing_binding_is_not_recoverable(self):
        for changes in ({'scalar_state':'negative'},{'scalar_state':'zero'},
                        {'identity_checkpoint':'saved-binding'},{'identity_checkpoint':'distinct-accounts'},
                        {'metadata_checkpoint':'none'}):
            diag=identity_budget().diagnostic|changes
            self.assertFalse(wait.verified_read_budget(safe_read_failure(ReadStopped('frame-budget',diag))))

for name in dir(guide.WholeChain):
    if name.startswith('test_') and name not in IdentityBudget.__dict__:setattr(IdentityBudget,name,None)

class InboxIdentity(budget_test.InboxRecovery):
    def deferred(self):
        out=guided.report();out.update(status='chain-waiting',reason='history-read-budget-timeout')
        out['diagnostics'].update(history_budget_exhausted=True,last_read_failure=safe_read_failure(identity_budget()))
        return out

class Followup(context.Context):
    def send(self,before,text):
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='followup'").fetchone()[0],'reserved-unknown')
        self.sent.append(text);return dict(attempted=True,handler_returned=True)

    def test_maybe_gets_one_contextual_answer_not_contact_request(self):
        h=self.seed_contact();before=guide.snapshot(*h,('Наверное',False));after=guide.snapshot(*h,('Наверное',False),(TEXT,True))
        self.chain.responder=MagicMock(return_value=dict(decision='reply',text=TEXT))
        out=self.walk([before,before,after],until_waiting=True)
        self.assertEqual(out['reason'],'contact-followup-sent');self.assertEqual(self.sent,[TEXT]);self.notifier.assert_not_called()
        kind,snapshot=self.chain.responder.call_args.args
        self.assertEqual(kind,'followup');self.assertEqual(len(snapshot['messages']),len(before['messages']))
        self.assertEqual(snapshot['_reply_ids'],[before['messages'][-1]['id']])
        self.assertNotIn('номер',TEXT);self.assertNotIn('ник',TEXT)
        out=self.walk([after],until_waiting=True);self.assertEqual(out['submission_calls'],0)

    def test_technical_objection_uses_history_and_does_not_invent_vpn_advice(self):
        h=self.seed_contact();reply='Переходить необязательно, можем продолжить здесь.'
        before=guide.snapshot(*h,('Да не работают они без впн на айфоне, ты о чем!!!!! И вообще для чего?',False))
        self.chain.responder=MagicMock(return_value=dict(decision='reply',text=reply))
        stage,action=self.chain.proposal(before)
        self.assertEqual(stage,'pending-followup');self.assertEqual(action['text'],reply)
        self.assertEqual(self.chain.responder.call_args.args[0],'followup')

    def test_followup_is_durable_after_restart_and_never_replayed_if_unknown(self):
        h=self.seed_contact();before=guide.snapshot(*h,('Наверное',False));stage,action=self.chain.proposal(before)
        self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,False)
        self.chain=guided.GuidedChain(self.store,seal=lambda v:v,unseal=lambda v:v)
        out=self.walk([before]);self.assertEqual(out['reason'],'send-outcome-unknown');self.assertFalse(self.sent)

    def test_new_choice_after_followup_can_clarify_once(self):
        h=self.seed_contact();base=[('Наверное',False),(TEXT,True)]
        stage,action=self.chain.proposal(guide.snapshot(*h,*base[:1]));self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,True)
        self.chain.proposal(guide.snapshot(*h,*base))
        stage,action=self.chain.proposal(guide.snapshot(*h,*base,('Давай тг',False)))
        self.assertEqual(stage,'pending-clarify');self.assertEqual(action['kind'],'clarify')

    def test_choice_in_same_snapshot_as_returned_followup_is_not_consumed_silently(self):
        h=self.seed_contact();before=guide.snapshot(*h,('Наверное',False));stage,action=self.chain.proposal(before)
        self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,True)
        stage,action=self.chain.proposal(guide.snapshot(*h,('Наверное',False),(TEXT,True),('Давай тг',False)))
        self.assertEqual(stage,'pending-clarify');self.assertEqual(action['kind'],'clarify')
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='followup'").fetchone()[0],'outgoing-observed')

    def test_refusal_and_contact_have_priority(self):
        h=self.seed_contact();out=self.walk([guide.snapshot(*h,('Не пиши мне',False))],until_waiting=True)
        self.assertEqual(out['reason'],'declined');self.assertFalse(self.sent)

    def test_contact_after_unknown_followup_can_be_forwarded_without_resend(self):
        h=self.seed_contact();before=guide.snapshot(*h,('Наверное',False));stage,action=self.chain.proposal(before)
        self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,False)
        out=self.walk([guide.snapshot(*h,('Наверное',False),('@alex_test',False),('Давай тг',False))])
        self.assertEqual(out['status'],'chain-completed');self.assertFalse(self.sent)
        self.notifier.assert_called_once()
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='followup'").fetchone()[0],'unknown')

    def test_waiting_for_contact_does_not_trigger_extra_question(self):
        for text in ('Сейчас найду','Потом напишу','Подожди минутку'):
            self.assertFalse(eligible([dict(text=text)]))

    def test_native_adapter_and_35_word_pacing_allow_contextual_answer(self):
        self.assertEqual(checked_reply(TEXT),TEXT)
        sample=guide.snapshot(('Привет',False));sample.pop('peer_name')
        source=build(sample,text=TEXT)
        self.assertEqual(source.count('call(s.submit,current,args)'),1)
        delays=[];auth=RunAuthorization(self.stop,wait=lambda n:delays.append(n) or False)
        self.assertTrue(auth('followup',TEXT,lambda:False));self.assertAlmostEqual(sum(delays),len(TEXT.split())*60/35)

    def test_followup_rejects_repeat_greeting_secrets_contact_request(self):
        for text in ('Привет! Продолжим здесь.','Напиши свой номер','Дай пароль','arbitrary'):
            with self.assertRaises(GroqError):decision(dict(decision='reply',text=text),'followup')

for name in dir(context.Context):
    if name.startswith('test_') and name not in Followup.__dict__:setattr(Followup,name,None)

class JournalGreeting(ih.Base):
    def test_packet_normal_and_hello_uses_exact_journal_greeting(self):
        self.journal();chain=self.chain();before=ih.snap(ih.msg(1002,'нормально!а у тебя?😊'),ih.msg(1003,'приветик 😊'))
        chain.bind(before,(ih.GREETING,),approved=True);stage,action=chain.proposal(before)
        self.assertEqual(stage,'pending-question');self.assertEqual(action['kind'],'question')

    def test_prior_quarantine_not_reset_by_ordinary_incoming(self):
        self.journal();chain=self.chain();chain.mark_review(WHO)
        before=ih.snap(ih.msg(1002,'нормально!а у тебя?😊'),ih.msg(1003,'приветик 😊'))
        stage,action=chain.proposal(before);self.assertEqual(stage,'manual-review');self.assertIsNone(action)

    def test_missing_greeting_stays_blocked_with_exact_diagnostic(self):
        self.journal();chain=self.chain();before=ih.snap(ih.msg(1002,'приветик'))
        before['messages'][0]['text']='Другое приветствие'
        out=guided.walk(chain,WHO,self.stop,self.approve,MagicMock(return_value=before),lambda *args:None,approved=True,pause=lambda _:False)
        self.assertEqual(out['reason'],'greeting-not-verified');self.assertEqual(out['diagnostics']['greeting_anchor_failure'],'hash-mismatch')
