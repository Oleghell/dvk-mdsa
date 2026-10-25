"""1.2.10 synthetic regressions. No device, accounts or external requests."""
import copy
import unittest
from unittest.mock import MagicMock, patch
import test_guided_chain as guide
import test_inbox_profiles as ih
import assistant_guided_chain as guided
import assistant_inbox as inbox
import assistant_history_wait as wait
import assistant_exit_notify as exits
import assistant_contact_clarify as clarify
from assistant_chain import text_hash
from one_chat_device import ReadStopped
from conversation_engine import QUESTIONS, CONTACT_TEXT
import groq_reply as groq
import one_chat_send

WHO=guide.WHO

def loading(**changes):
    value=dict(stage='navigation-stopped',metadata_checkpoint='ready',read_checkpoint='recheck',
        identity_checkpoint='recheck',scalar_checkpoint='chat-id',scalar_state='positive',
        wait_reason='history-loading',frames=2,managed_calls=270,message_slot=0,message_kind='text',message_direction='not-own')
    value.update(changes)
    return ReadStopped('history-not-ready',value)

class Clock:
    def __init__(self):self.now=0.;self.delays=[]
    def __call__(self):return self.now
    def pause(self,seconds):self.delays.append(seconds);self.now+=seconds;return False

class Context(guide.WholeChain):
    # Reuse fixture helpers, not inherited tests.
    def send(self,before,text):
        kind='followup' if text==__import__('assistant_contact_followup').TEXT else 'clarify' if text in (clarify.TEXT,clarify.WHATSAPP_TEXT,clarify.TELEGRAM_TEXT) else 'contact' if text==CONTACT_TEXT else 'question'
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions WHERE chat=? AND kind=?',('300',kind)).fetchone()[0],'reserved-unknown')
        self.sent.append(text);return dict(attempted=True,handler_returned=True)

    def history(self):
        return [('Приветик',False),(QUESTIONS[0],True),('нормально!а у тебя?😊',False),(CONTACT_TEXT,True)]

    def seed_contact(self):
        h=self.history();self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
        for sample in [guide.snapshot(*h[:1]),guide.snapshot(*h[:2]),guide.snapshot(*h[:3]),guide.snapshot(*h)]:
            stage,action=self.chain.proposal(sample)
            if action:self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,True)
        self.assertEqual(stage,'wait-contact');return h

    def test_choice_generates_one_optional_clarification_and_contact(self):
        h=self.seed_contact();h += [('Хотя тг лучше',False),('Давай ватсап',False)]
        before=guide.snapshot(*h);sent=guide.snapshot(*h,(clarify.TEXT,True))
        contact=guide.snapshot(*h,(clarify.TEXT,True),('+79991234567',False))
        out=self.walk([before,before,sent,contact])
        self.assertEqual(out['status'],'chain-completed');self.assertEqual(self.sent,[clarify.TEXT])
        self.notifier.assert_called_once_with(dict(name=guide.PEER_NAME,contacts=['+79991234567']))
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='clarify'").fetchone()[0],'outgoing-observed')
        out=self.walk([contact]);self.assertEqual(out['submission_calls'],0)

    def test_no_second_clarification_on_new_choice_or_restart(self):
        h=self.seed_contact();h += [('Давай ватсап',False)]
        first=guide.snapshot(*h);seen=guide.snapshot(*h,(clarify.WHATSAPP_TEXT,True))
        out=self.walk([first,first,seen],until_waiting=True)
        self.assertEqual(self.sent,[clarify.WHATSAPP_TEXT]);self.assertEqual(out['reason'],'contact-clarification-sent')
        self.chain=guided.GuidedChain(self.store,choose=lambda:0,seal=lambda v:v,unseal=lambda v:v)
        new=guide.snapshot(*h,(clarify.WHATSAPP_TEXT,True),('Тг лучше',False))
        follow=__import__('assistant_contact_followup').TEXT
        observed=guide.snapshot(*h,(clarify.WHATSAPP_TEXT,True),('Тг лучше',False),(follow,True))
        out=self.walk([new,new,observed],until_waiting=True)
        self.assertEqual(out['submission_calls'],1);self.assertEqual(self.sent,[clarify.WHATSAPP_TEXT,follow])
        self.assertEqual(self.sent.count(clarify.WHATSAPP_TEXT),1)

    def test_refusal_and_unavailable_messenger_do_not_request_again(self):
        for text in ('Не хочу общаться','Тг не работает, давай потом','Не пиши мне, лучше тг'):
            with self.subTest(text=text):self.assertFalse(clarify.chosen([dict(text=text)]))

    def test_contact_bypasses_clarification(self):
        h=self.seed_contact();out=self.walk([guide.snapshot(*h,('+79991234567',False))])
        self.assertEqual(out['status'],'chain-completed');self.assertFalse(self.sent)

    def test_unknown_clarification_is_not_replayed(self):
        h=self.seed_contact();sample=guide.snapshot(*h,('Давай ватсап',False))
        stage,action=self.chain.proposal(sample);self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,False)
        out=self.walk([sample]);self.assertEqual(out['reason'],'send-outcome-unknown');self.assertFalse(self.sent)

    def test_exact_returned_question_plus_two_incoming_advances_one_step(self):
        self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
        h=[('Привет',False)];stage,action=self.chain.proposal(guide.snapshot(*h))
        self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,True)
        h += [(QUESTIONS[0],True),('нормально!а у тебя?😊',False),('приветик 😊',False)]
        stage,action=self.chain.proposal(guide.snapshot(*h))
        self.assertEqual(stage,'pending-contact');self.assertEqual(action['kind'],'contact')
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='question'").fetchone()[0],'outgoing-observed')
        self.assertNotIn('Привет',action['text'])

    def test_incoming_before_own_visibility_remains_unconsumed(self):
        self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
        a=guide.snapshot(('Привет',False));stage,action=self.chain.proposal(a)
        self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,True)
        pending=guide.snapshot(('Привет',False),('нормально, а у тебя?',False))
        stage,action=self.chain.proposal(pending);self.assertEqual(stage,'pending-question');self.assertIsNone(action)
        with self.store.connection() as db:self.assertIsNone(db.execute("SELECT 1 FROM chain_seen WHERE message='1003'").fetchone())
        pending['messages'].append(dict(id='1004',sender='100',text=QUESTIONS[0]))
        stage,action=self.chain.proposal(pending);self.assertEqual(stage,'pending-contact')

    def test_choice_arrives_with_exact_returned_contact(self):
        h=self.seed_contact()
        # Roll back only the synthetic observation, preserving the reserved returned action.
        with self.store.connection() as db:
            db.execute("DELETE FROM chain_seen WHERE message='1005'")
            db.execute("UPDATE chain_dialogs SET stage='pending-contact'")
            db.execute("UPDATE chain_actions SET status='handler-returned-unconfirmed' WHERE kind='contact'")
        stage,action=self.chain.proposal(guide.snapshot(*h,('Давай ватсап',False)))
        self.assertEqual(stage,'pending-clarify');self.assertEqual(action['text'],clarify.WHATSAPP_TEXT)

    def test_unreturned_or_mismatched_own_still_requires_review(self):
        self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
        stage,action=self.chain.proposal(guide.snapshot(('Привет',False)))
        self.chain.reserve_confirmed(WHO,action)
        stage,action=self.chain.proposal(guide.snapshot(('Привет',False),(QUESTIONS[0],True),('нормально',False)))
        self.assertEqual(stage,'manual-review');self.assertIsNone(action)

    def test_ai_context_contains_entire_packet_and_old_greeting(self):
        self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
        reply='Понял, спасибо. Как настроение?'
        responder=MagicMock(return_value=dict(decision='reply',text=reply));self.chain.responder=responder
        stage,action=self.chain.proposal(guide.snapshot(('нормально!а у тебя?😊',False),('приветик 😊',False)))
        context=responder.call_args.args[1];public=groq.public_context(context)
        self.assertEqual([x['text'] for x in public if x['is_current_reply']],['нормально!а у тебя?😊','приветик 😊'])
        self.assertEqual(public[0]['text'],guide.GREETING);self.assertEqual(action['text'],reply)
        self.assertEqual(stage,'pending-question');self.assertFalse(groq.GREETING.search(reply))

    def test_ai_clarification_is_durable_and_adapter_accepted(self):
        h=self.seed_contact();self.chain.responder=MagicMock(return_value=dict(decision='reply',text='Хорошо, по какому номеру тебя найти в WhatsApp?'))
        sample=guide.snapshot(*h,('Давай ватсап',False));stage,action=self.chain.proposal(sample)
        self.assertEqual(stage,'pending-clarify');self.assertEqual(one_chat_send.checked_reply(action['text']),action['text'])
        self.chain.responder.reset_mock();stage,restored=self.chain.proposal(sample)
        self.assertEqual(restored,action);self.chain.responder.assert_not_called()

# Inherit fixture setup/helpers only; inherited integration tests are discovered
# separately in their original module, not duplicated here.
for name in dir(guide.WholeChain):
    if name.startswith('test_') and name not in Context.__dict__:setattr(Context,name,None)

class Loading(guide.WholeChain):
    def test_loading_recovers_before_send(self):
        clock=Clock();values=[loading(),loading()]+guide.sequence()
        out=self.walk(values,pause=clock.pause,read_clock=clock)
        self.assertEqual(out['status'],'chain-completed');self.assertEqual(out['diagnostics']['read_retries'],2)
        self.assertEqual(out['submission_calls'],2)

    def test_persistent_loading_is_waiting_not_manual_review(self):
        clock=Clock();reader=MagicMock(side_effect=lambda who:(_ for _ in ()).throw(loading()))
        out=guided.walk(self.chain,WHO,self.stop,self.approve,reader,self.send,approved=True,greetings=(guide.GREETING,),pause=clock.pause,read_clock=clock)
        self.assertEqual(out['reason'],'history-loading-timeout');self.assertEqual(out['status'],'chain-waiting')
        self.assertLessEqual(reader.call_count,16);self.assertEqual(clock.now,15);self.assertFalse(self.sent)
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_dialogs').fetchone()[0],0)

    def test_incomplete_identity_evidence_cannot_be_local_loading(self):
        self.assertFalse(wait.verified_loading(dict(error='history-not-ready',wait_reason='history-loading')))
        for key,value in [('identity_checkpoint','failed'),('scalar_state','zero'),('metadata_checkpoint','none')]:
            error=loading(**{key:value});from one_chat_device import safe_read_failure
            self.assertFalse(wait.verified_loading(safe_read_failure(error)))

    def test_wrong_bound_chat_after_loading_stops(self):
        clock=Clock();bad=guide.snapshot();bad['identity']['peer']='999'
        out=self.walk([loading(),bad],pause=clock.pause,read_clock=clock)
        self.assertNotEqual(out['reason'],'history-loading-timeout');self.assertFalse(self.sent)

    def test_cancel_loading_never_sends(self):
        def pause(seconds):self.stop.set();return True
        out=self.walk([loading()],pause=pause)
        self.assertEqual(out['status'],'chain-cancelled');self.assertFalse(self.sent)

    def test_loading_after_reservation_preserves_unknown_send(self):
        self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
        stage,action=self.chain.proposal(guide.snapshot(('Привет',False)))
        self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,False)
        clock=Clock();out=self.walk([loading()]*16,pause=clock.pause,read_clock=clock)
        self.assertEqual(out['reason'],'history-loading-timeout')
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'unknown')
        out=self.walk([guide.snapshot(('Привет',False))]);self.assertEqual(out['reason'],'send-outcome-unknown');self.assertFalse(self.sent)

for name in dir(guide.WholeChain):
    if name.startswith('test_') and name not in Loading.__dict__:setattr(Loading,name,None)

class InboxLoading(ih.Base):
    def deferred(self):
        from one_chat_device import safe_read_failure
        out=guided.report();out.update(status='chain-waiting',reason='history-loading-timeout')
        out['diagnostics'].update(history_wait_exhausted=True,last_read_failure=safe_read_failure(loading()))
        return out

    def test_verified_back_defers_only_peer_then_processes_other(self):
        self.journal();self.journal(ih.OTHER);chain=self.chain()
        normal=guided.report();normal.update(status='chain-waiting',reason='wait-reply')
        with patch.object(inbox,'walk_chat',side_effect=[self.deferred(),normal]):
            out=self.walk([ih.nav('opened',WHO),ih.nav('returned',WHO),ih.nav('opened',ih.OTHER),ih.nav('returned',ih.OTHER),ih.nav('search-ready')],[],chain=chain,clock=lambda:100.)
        self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['history_deferred'],1)
        self.assertEqual(out['dialogs_processed'],2);self.assertEqual(out['isolated_dialogs'],0)
        a,u,n=wait.eligible(self.store,[WHO,ih.OTHER],[],clock=lambda:159.)
        self.assertEqual(a,[ih.OTHER]);self.assertEqual(n,1)
        self.assertEqual(wait.eligible(self.store,[WHO],[],clock=lambda:160.)[0],[WHO])
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_review_reasons').fetchone()[0],0)

    def test_failed_back_does_not_set_cooldown(self):
        self.journal();chain=self.chain()
        with patch.object(inbox,'walk_chat',return_value=self.deferred()):
            out=self.walk([ih.nav('opened',WHO),ValueError('wrong return')],[],chain=chain,clock=lambda:100.)
        self.assertEqual(out['status'],'inbox-stopped')
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM inbox_history_deferrals').fetchone()[0],0)

    def test_cooldown_persists_matches_peer_not_unknown_initial_chat(self):
        self.journal();wait.initialize(self.store);wait.defer(self.store,WHO,clock=lambda:100.)
        out=self.walk([],[],chain=self.chain(),clock=lambda:101.)
        self.assertEqual(out['status'],'inbox-empty');self.assertEqual(out['history_cooldown_skipped'],1)
        self.nav.assert_not_called()
        other_account=dict(WHO,account='999')
        self.assertEqual(wait.eligible(self.store,[other_account],[],clock=lambda:101.)[0],[other_account])

    def test_review_notification_explains_exact_cause(self):
        self.journal();chain=self.chain();chain.consume(ih.snap())
        sender=MagicMock(return_value=True)
        exits.notify_exit(chain,WHO,dict(reason='manual-review',diagnostics=dict(review_cause='incoming-during-pending'),_exit_messages=['нормально!а у тебя?😊','приветик 😊']),sender=sender)
        text=sender.call_args.args[0];self.assertIn('предыдущая отправка',text);self.assertIn('нормально',text)
        self.assertNotIn('Не удалось безопасно',text);self.assertNotIn('300',text)

class ExtraContext(Context):
    def test_unsent_clarification_refreshes_then_accepts_arriving_contact(self):
        h=self.seed_contact();before=guide.snapshot(*h,('Давай ватсап',False))
        stage,action=self.chain.proposal(before)
        fresh=guide.snapshot(*h,('Давай ватсап',False),('+79991234567',False))
        self.assertTrue(self.chain.refresh_unsubmitted(before,fresh,action))
        stage,action=self.chain.proposal(fresh)
        self.assertEqual(stage,'done');self.assertIsNone(action)
        with self.store.connection() as db:self.assertIsNone(db.execute("SELECT 1 FROM chain_actions WHERE kind='clarify'").fetchone())

    def test_reserved_clarification_is_never_refreshed(self):
        h=self.seed_contact();before=guide.snapshot(*h,('Давай ватсап',False))
        stage,action=self.chain.proposal(before);self.chain.reserve_confirmed(WHO,action)
        self.assertFalse(self.chain.refresh_unsubmitted(before,guide.snapshot(*h,('Давай ватсап',False),('тг лучше',False)),action))

    def test_manual_review_not_automatically_cleared(self):
        self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True);self.chain.mark_review(WHO)
        stage,action=self.chain.proposal(guide.snapshot(('нормально!а у тебя?😊',False),('приветик 😊',False)))
        self.assertEqual(stage,'manual-review');self.assertIsNone(action)

    def test_model_review_persists_specific_cause_without_body(self):
        self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
        self.chain.responder=MagicMock(return_value=dict(decision='review',text=''))
        stage,action=self.chain.proposal(guide.snapshot(('Текст для решения ИИ',False)))
        self.assertEqual(stage,'manual-review');self.assertEqual(self.chain.review_reason(WHO),'ai-context-review')
        self.assertIsNone(action)

for name in dir(Context):
    if name.startswith('test_') and name not in ExtraContext.__dict__:setattr(ExtraContext,name,None)

class Gates(unittest.TestCase):
    def test_packaged_instructions_match_release_and_main_readme(self):
        from pathlib import Path
        from mumu_version import VERSION
        root=Path(__file__).resolve().parents[2]
        guide=(root/'rootless-unity/ASSISTANT.md').read_text(encoding='utf-8')
        self.assertEqual(guide,(root/'README.md').read_text(encoding='utf-8'))
        self.assertTrue(guide.startswith('# DvkAssistant '+VERSION+' '))

    def test_clarification_rejects_sensitive_requests_and_second_greeting(self):
        for text in ['Привет! Напиши номер','Напиши номер карты','Дай пароль и номер','Как настроение?','Номер +79991234567']:
            with self.subTest(text=text):
                with self.assertRaises(groq.GroqError):groq.decision(dict(decision='reply',text=text),'clarify')
    def test_native_adapter_allows_new_fallback(self):
        self.assertEqual(one_chat_send.checked_reply(clarify.TEXT),clarify.TEXT)
