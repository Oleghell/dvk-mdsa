"""Provider failures and key scheduling; synthetic requests only, no credentials."""
import io
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import groq_reply as g
import openrouter_reply as router
import assistant_key_pool as pool
import mumu_ai as ai
from test_guided_chain import snapshot

REPLY=dict(decision='reply',text='Всё спокойно. Как настроение?')

class OrganizationError(unittest.TestCase):
    def client(self,status,body):
        c=MagicMock();c.open.side_effect=urllib.error.HTTPError('https://SECRET',status,'SECRET',{},io.BytesIO(body));return c
    def test_only_exact_structured_code_classified(self):
        for status in (400,403):
            c=self.client(status,b'{"error":{"code":"organization_restricted","message":"SECRET"}}')
            with self.assertRaises(g.GroqError) as e:
                g.Responder(key_loader=lambda:'synthetic',rules_loader=lambda:'',opener=c)('question',snapshot())
            self.assertEqual(str(e.exception),'groq-organization-restricted');self.assertNotIn('SECRET',repr(e.exception));c.open.assert_called_once()
    def test_bad_large_or_free_text_errors_not_trusted(self):
        for body in (b'organization_restricted',b'{"message":"organization_restricted"}',
            b'{"error":{"code":"organization_restricted"},"extra":"'+b'x'*4096+b'"}',
            b'{"error":{"code":"organization_restricted_SECRET"}}',b'[]'):
            c=self.client(400,body)
            with self.assertRaises(g.GroqError) as e:
                g.Responder(key_loader=lambda:'synthetic',rules_loader=lambda:'',opener=c)('question',snapshot())
            self.assertEqual(str(e.exception),'groq-request-rejected');self.assertNotIn('SECRET',str(e.exception))
    def test_openrouter_and_429_not_misclassified(self):
        body=b'{"error":{"code":"organization_restricted"}}'
        for cls,status,want in ((g.Responder,429,'groq-rate-limit'),(router.Responder,400,'openrouter-request-rejected')):
            c=self.client(status,body)
            with self.assertRaises(g.GroqError) as e:
                cls(key_loader=lambda:'synthetic',rules_loader=lambda:'',opener=c)('question',snapshot())
            self.assertEqual(str(e.exception),want)

class Rotation(unittest.TestCase):
    def setUp(self):pool._CACHE.clear();self.now=0;self.trace=[];self.errors={}
    def make(self,keys=None):
        parent=self
        class Adapter:
            def __init__(self,**kwargs):self.key=kwargs['key_loader']();self.calls=0
            def __call__(self,*args):
                self.calls+=1;parent.trace.append(self.key)
                if self.key in parent.errors:raise parent.errors[self.key]
                return REPLY.copy()
        with patch.dict('os.environ',{'DVK_MUMU_MULTI':'0'}):
            return pool.Responder('groq',g.MODEL,keys or ['first','second','third'],factory=Adapter,clock=lambda:self.now)
    def test_success_rotates_instead_of_hammering_first_good_key(self):
        r=self.make()
        for _ in range(5):self.assertEqual(r('question',snapshot()),REPLY)
        self.assertEqual(self.trace,['first','second','third','first','second'])
    def test_six_restricted_nine_healthy_are_selected_not_hardcoded_indices(self):
        keys=[str(i) for i in range(15)]
        self.errors={k:g.GroqError('groq-organization-restricted') for k in keys[:6]}
        r=self.make(keys)
        for _ in range(10):r('question',snapshot())
        self.assertEqual(self.trace[:15],keys)
        self.assertEqual(self.trace[15:],['6'])
        self.assertEqual([self.trace.count(k) for k in keys[:6]],[1]*6)
        self.assertEqual(r.failures[0]['code'],'groq-organization-restricted')
        self.assertTrue(r.failures[0]['cooldown'])
    def test_rate_limit_next_key_and_do_not_retry_before_retry_after(self):
        self.errors={'first':g.GroqError('groq-rate-limit',retry_after=120)}
        r=self.make(['first','second']);r('question',snapshot());self.now=119;r('question',snapshot())
        self.assertEqual(self.trace,['first','second','second'])
        self.assertEqual(r.failures[0]['retry_in_seconds'],1)
        del self.errors['first'];self.now=120;r('question',snapshot())
        self.assertEqual(self.trace[-1],'first')
    def test_short_server_retry_after_does_not_add_artificial_minute(self):
        self.errors={'first':g.GroqError('groq-rate-limit',retry_after=2)}
        r=self.make(['first','second']);r('question',snapshot());self.now=1;r('question',snapshot())
        self.assertEqual(self.trace.count('first'),1)
        self.now=2;del self.errors['first'];r('question',snapshot())
        self.assertEqual(self.trace[-1],'first')

    def test_restricted_key_rechecked_after_long_cooldown_not_forever_deleted(self):
        self.errors={'first':g.GroqError('groq-organization-restricted')}
        r=self.make(['first','second']);r('question',snapshot());self.now=3599;r('question',snapshot())
        self.assertEqual(self.trace,['first','second','second']);del self.errors['first'];self.now=3600;r('question',snapshot())
        self.assertEqual(self.trace[-1],'first')
    def test_all_unavailable_return_no_draft_and_next_call_no_http(self):
        self.errors={k:g.GroqError('groq-rate-limit') for k in ['first','second','third']}
        r=self.make()
        for _ in range(2):
            with self.assertRaisesRegex(g.GroqError,'^groq-key-pool-exhausted$'):r('question',snapshot())
        self.assertEqual(self.trace,['first','second','third'])
        self.assertTrue(all(x['cooldown'] and x['retry_in_seconds']==60 for x in r.failures))
    def test_instance_recreation_does_not_reset_cooldown(self):
        self.errors={'first':g.GroqError('groq-organization-restricted')}
        r=self.make(['first','second']);r('question',snapshot());self.make(['first','second'])('question',snapshot())
        self.assertEqual(self.trace.count('first'),1)
    def test_bad_generation_still_requires_same_validation_on_next_key(self):
        self.errors={'first':g.GroqError('groq-unsafe-reply',validation_reason='repeat-question')}
        r=self.make();self.assertEqual(r('question',snapshot()),REPLY)
        self.assertEqual(self.trace,['first','second']);self.assertEqual(r.failures[0]['validation_reason'],'repeat-question')
    def test_port_seed_is_bounded_and_not_applied_outside_mumu(self):
        for port in ('5557','5559','5561','5563','5565','SECRET','-1','999999','٥٥٥٧'):
            pool._CACHE.clear()
            with patch.dict('os.environ',{'DVK_MUMU_MULTI':'1','DVK_MUMU_PORT':port}):
                r=pool.Responder('groq',g.MODEL,['a','b','c'],factory=lambda **kwargs:MagicMock(calls=0))
            self.assertIn(r.state['cursor'],range(3))
    def test_cancelled_never_tries_another_key(self):
        r=self.make();r.cancelled=lambda:True
        with self.assertRaisesRegex(g.GroqError,'cancelled'):r('question',snapshot())
        self.assertFalse(self.trace)

class Diagnostics(unittest.TestCase):
    def failures(self,*codes):return [dict(provider='groq',key_index=i+1,code='groq-'+c,cooldown=True,retry_in_seconds=60) for i,c in enumerate(codes)]
    def test_mixed_restriction_and_limits_explained_not_bad_keys(self):
        v=ai.failure_explanation(self.failures('organization-restricted','rate-limit'))
        self.assertIn('организации',v);self.assertIn('лимиты',v);self.assertIn('60 с',v)
        self.assertNotIn('не дали проверенного ответа',v)
    def test_attached_report_old_codes_get_specific_explanation(self):
        v=ai.failure_explanation(self.failures('request-rejected','rate-limit'))
        self.assertIn('отклонена API',v);self.assertIn('не означает',v)
    def test_countdown_is_sanitized_optional_and_secret_dropped(self):
        f=self.failures('organization-restricted');f[0]['key']='SECRET'
        self.assertNotIn('SECRET',json.dumps(ai.safe_failures(type('R',(),dict(failure_summary=f))())))
        for bad in (True,-1,86401,'SECRET'):
            f[0]['retry_in_seconds']=bad
            self.assertNotIn('retry_in_seconds',ai.safe_failures(type('R',(),dict(failure_summary=f))())[0])

    def test_json_preserves_only_closed_key_failure_diagnostics(self):
        from assistant_error_notify import diagnostic_json
        failures=self.failures('organization-restricted','rate-limit')
        failures[0]['secret']='SECRET';failures[0]['raw_error']='SECRET'
        b=diagnostic_json(dict(status='stopped',last_pass=dict(last_chat_diagnostics=dict(ai_failures=failures))))
        values=json.loads(b)['diagnostic']['last_pass']['last_chat_diagnostics']['ai_failures']
        self.assertEqual(values[0]['code'],'groq-organization-restricted')
        self.assertEqual(values[1]['retry_in_seconds'],60);self.assertNotIn(b'SECRET',b)
