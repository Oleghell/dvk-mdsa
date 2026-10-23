"""1.3.6 exact loading checkpoint and pre-reservation AI repair; synthetic only."""
import io,json,unittest
from unittest.mock import MagicMock
import groq_reply as g
import openrouter_reply as router
import assistant_key_pool as pool
import mumu_ai
import assistant_history_wait as wait
from one_chat_device import safe_read_failure,ReadStopped
import test_guided_chain as guide
from test_1210_context_loading import loading,Clock,Loading,Context
from test_inbox_profiles import Base,WHO,OTHER,msg,snap,nav


def early_loading(**changes):
    return loading(read_checkpoint='last-message',wait_reason='history-not-loaded',
                   message_slot=-1,message_kind='not-read',message_direction='not-read',
                   frames=2,managed_calls=118,**changes)


def client_for(*texts):
    client=MagicMock()
    client.open.side_effect=[io.BytesIO(json.dumps(dict(choices=[dict(finish_reason='stop',
        message=dict(content=json.dumps(dict(decision='reply',text=t))))])).encode()) for t in texts]
    return client

class EarlyLoading(Loading):
    def test_exact_new_report_waits_then_recovers(self):
        clock=Clock()
        out=self.walk([early_loading(),early_loading()]+guide.sequence(),pause=clock.pause,read_clock=clock)
        self.assertEqual(out['status'],'chain-completed');self.assertEqual(out['submission_calls'],2)
        self.assertEqual(out['diagnostics']['read_retries'],2);self.assertEqual(clock.delays[:2],[1.,1.])
    def test_persistent_early_loading_never_sends_or_becomes_manual_review(self):
        clock=Clock();out=self.walk([early_loading()]*16,pause=clock.pause,read_clock=clock)
        self.assertEqual(out['reason'],'history-loading-timeout');self.assertEqual(clock.now,15)
        self.assertFalse(self.sent)
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_actions').fetchone()[0],0)
    def test_unknown_previous_send_survives_early_loading(self):
        self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
        _,action=self.chain.proposal(guide.snapshot(('Привет',False)))
        self.chain.reserve_confirmed(WHO,action);self.chain.finish(WHO,action,False)
        clock=Clock();out=self.walk([early_loading()]*16,pause=clock.pause,read_clock=clock)
        self.assertEqual(out['reason'],'history-loading-timeout')
        out=self.walk([guide.snapshot(('Привет',False))])
        self.assertEqual(out['reason'],'send-outcome-unknown');self.assertFalse(self.sent)
    def test_early_checkpoint_does_not_authorize_other_errors(self):
        d=early_loading().diagnostic
        self.assertTrue(wait.verified_loading(safe_read_failure(early_loading())))
        for key,value in [('identity_checkpoint','saved-binding'),('scalar_state','zero'),
                          ('scalar_checkpoint','peer-id'),('read_checkpoint','identity'),('metadata_checkpoint','base')]:
            self.assertFalse(wait.verified_loading(safe_read_failure(ReadStopped('history-not-ready',dict(d,**{key:value})))))
        for error in ('wrong-screen','identity-changed','frame-budget'):
            self.assertFalse(wait.verified_loading(safe_read_failure(ReadStopped(error,d))))

class InboxEarlyLoading(Base):
    def test_exact_loading_shape_defers_peer_and_processes_next(self):
        from conversation_engine import QUESTIONS
        self.journal();self.journal(OTHER)
        hello=msg(1002,'Привет',who=OTHER);answer=msg(1003,QUESTIONS[0],True,who=OTHER)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('opened',OTHER),nav('returned',OTHER),nav('search-ready')],
          [early_loading()]*16+[snap(hello,who=OTHER),snap(hello,who=OTHER),snap(hello,answer,who=OTHER)])
        self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['history_deferred'],1)
        self.assertEqual(self.sent,[QUESTIONS[0]])
    def test_wrong_return_does_not_enable_local_skip(self):
        self.journal();out=self.walk([nav('opened',WHO),nav('returned',OTHER)],[early_loading()]*16)
        self.assertEqual(out['status'],'inbox-stopped');self.assertEqual(out['history_deferred'],0);self.assertFalse(self.sent)

class DraftRepair(unittest.TestCase):
    def model(self,client,cls=g.Responder,**kw):
        return cls(key_loader=lambda:'gsk_'+'x'*32,opener=client,rules_loader=lambda:'Кратко.',**kw)
    def test_contextual_followup_repairs_stage_false_positive_before_send(self):
        client=client_for('Номер не нужен, можем общаться здесь.','Не нужно ничего доказывать. Можем спокойно общаться здесь 🙂')
        model=self.model(client);sample=guide.snapshot(('Мне нечего бояться)',False))
        sample['_reply_ids']=[sample['messages'][-1]['id']]
        result=model('followup',sample)
        self.assertEqual(result['text'],'Не нужно ничего доказывать. Можем спокойно общаться здесь 🙂')
        self.assertEqual(model.calls,2)
        first,second=[json.loads(c.args[0].data) for c in client.open.call_args_list]
        self.assertEqual(first['messages'][-1],second['messages'][-1])
        self.assertNotIn('Номер не нужен',json.dumps(second,ensure_ascii=False))
        self.assertEqual(len(second['messages']),3);self.assertNotIn('tools',second)
    def test_only_one_repair_and_fixed_reason_survives_provider_remap(self):
        for cls,prefix in ((g.Responder,'groq'),(router.Responder,'openrouter')):
            client=client_for('Напиши номер','Напиши номер')
            with self.assertRaises(g.GroqError) as error:self.model(client,cls)('followup',guide.snapshot())
            self.assertEqual(client.open.call_count,2);self.assertEqual(str(error.exception),prefix+'-unsafe-reply')
            self.assertEqual(error.exception.validation_reason,'followup-stage')
    def test_unsafe_format_and_http_errors_are_not_repaired(self):
        for text in ('Пиши @secret','Ссылка https://example.test','Как дела?\nскрыто','x'*241):
            client=client_for(text)
            with self.assertRaises(g.GroqError):self.model(client)('question',guide.snapshot())
            self.assertEqual(client.open.call_count,1)
    def test_sensitive_content_is_not_a_repairable_stage_mismatch(self):
        for kind,text in (('clarify','Какой номер и пароль?'),('followup','Пришли код'),('followup','Нужны деньги')):
            client=client_for(text)
            with self.assertRaises(g.GroqError) as error:self.model(client)(kind,guide.snapshot())
            self.assertEqual(error.exception.validation_reason,'sensitive-content')
            self.assertEqual(client.open.call_count,1)
    def test_rate_limit_does_not_repair_or_lose_retry_after(self):
        import urllib.error
        for cls,prefix in ((g.Responder,'groq'),(router.Responder,'openrouter')):
            client=MagicMock();client.open.side_effect=urllib.error.HTTPError(
                'https://example.invalid',429,'PRIVATE',{'Retry-After':'42'},io.BytesIO(b'PRIVATE'))
            with self.assertRaises(g.GroqError) as error:self.model(client,cls)('followup',guide.snapshot())
            self.assertEqual(str(error.exception),prefix+'-rate-limit')
            self.assertEqual(error.exception.retry_after,42);self.assertEqual(client.open.call_count,1)
    def test_decline_review_and_cancel_never_get_repaired(self):
        for decision in ('decline','review'):
            client=MagicMock();client.open.return_value=io.BytesIO(json.dumps(dict(choices=[dict(finish_reason='stop',
                message=dict(content=json.dumps(dict(decision=decision,text=''))))])).encode())
            self.assertEqual(self.model(client)('followup',guide.snapshot())['decision'],decision)
            self.assertEqual(client.open.call_count,1)
        client=client_for('Напиши номер');model=self.model(client,cancelled=lambda:client.open.call_count>0)
        with self.assertRaises(g.GroqError) as error:model('followup',guide.snapshot())
        self.assertEqual(str(error.exception),'groq-cancelled');self.assertEqual(client.open.call_count,1)
    def test_reason_diagnostics_never_include_raw_output_or_secrets(self):
        pool._CACHE.clear();client=client_for('Напиши номер','Напиши номер');model=self.model(client)
        p=pool.Responder('groq',g.MODEL,['PRIVATE'],factory=lambda **kw:model,clock=lambda:0)
        with self.assertRaises(g.GroqError):p('followup',guide.snapshot())
        report=mumu_ai.safe_failures(type('R',(),{'failure_summary':p.failures})())
        self.assertEqual(report[0]['validation_reason'],'followup-stage')
        self.assertNotIn('PRIVATE',json.dumps(report));self.assertNotIn('Напиши',json.dumps(report,ensure_ascii=False))
        p.failures[0]['validation_reason']='PRIVATE'
        self.assertNotIn('validation_reason',mumu_ai.safe_failures(type('R',(),{'failure_summary':p.failures})())[0])

class ContextualSend(Context):
    def send(self,before,text):
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE chat='300' AND kind='followup'").fetchone()[0],'reserved-unknown')
        self.sent.append(text);return dict(attempted=True,handler_returned=True)
    def test_screenshot_style_batch_repaired_draft_is_sent_once_and_observed(self):
        h=self.seed_contact();text='Не нужно ничего доказывать. Можем спокойно общаться здесь 🙂'
        h += [('Я сначала подумала это мессенджер какой-то новый🤣',False),('Мне нечего бояться)',False)]
        client=client_for('Номер не нужен, можем общаться здесь.',text)
        self.chain.responder=g.Responder(key_loader=lambda:'gsk_'+'x'*32,opener=client,rules_loader=lambda:'Кратко.')
        before=guide.snapshot(*h);after=guide.snapshot(*h,(text,True))
        out=self.walk([before,before,after],until_waiting=True)
        self.assertEqual(out['submission_calls'],1);self.assertGreaterEqual(out['outgoing_observed'],1)
        with self.store.connection() as db:self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='followup'").fetchone()[0],'outgoing-observed')
        self.assertEqual(self.sent,[text]);self.assertEqual(client.open.call_count,2)
        again=self.walk([after],until_waiting=True)
        self.assertEqual(again['submission_calls'],0);self.assertEqual(client.open.call_count,2)

# Inherit fixture setup/helpers, not old test cases a second time.
for cls,base in ((EarlyLoading,Loading),(ContextualSend,Context)):
    for name in dir(base):
        if name.startswith('test_') and name not in cls.__dict__:setattr(cls,name,None)
del cls,base
