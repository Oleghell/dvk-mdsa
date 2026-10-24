"""No accounts/network: Gemini/Z.AI share all send gates and explicit routing."""
import io,json,os,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import MagicMock,patch
import assistant_ai as ai
import assistant_settings as cfg
import assistant_key_pool as pool
import assistant_error_notify as notify
import gemini_reply as gemini
import zai_reply as zai
import groq_reply as g
import mumu_ai
from test_guided_chain import snapshot

REPLY={'decision':'reply','text':'Всё спокойно. Как настроение?'}
GKEY='AQ.'+'A'*50
ZKEY='a'*32+'.'+'B'*16

def google(value=REPLY,reason='STOP',parts=None):
    return json.dumps({'candidates':[{'finishReason':reason,'content':{'role':'model',
        'parts':parts if parts is not None else [{'text':json.dumps(value,ensure_ascii=False)}]}}]}).encode()

def chat(value=REPLY,reason='stop'):
    return json.dumps({'choices':[{'finish_reason':reason,'message':{'content':json.dumps(value)}}]}).encode()

def client(*bodies):
    c=MagicMock();responses=[]
    for body in bodies:
        r=MagicMock();r.__enter__.return_value.read.return_value=body;responses.append(r)
    c.open.side_effect=responses
    return c

class ProviderSettings(unittest.TestCase):
    def test_explicit_settings_roundtrip_and_no_secret_in_settings(self):
        for provider,module in [('gemini',gemini),('zai',zai)]:
            s=cfg.Settings(ai_provider=provider,groq_enabled=True)
            self.assertEqual(s.ai_model,module.MODEL)
            with tempfile.TemporaryDirectory() as p:
                cfg.save(s,p);self.assertEqual(cfg.load(p),s)
                self.assertNotIn('AQ.',(Path(p)/'workflow-settings.json').read_text())
    def test_schema6_migrates_without_switching_existing_provider(self):
        with tempfile.TemporaryDirectory() as p:
            cfg.save(cfg.Settings(ai_provider='openrouter',groq_enabled=True),p)
            f=Path(p)/'workflow-settings.json';s=json.loads(f.read_text())
            s['settings_version']=6;s.pop('gemini_model');s.pop('zai_model');f.write_text(json.dumps(s))
            loaded=cfg.load(p)
            self.assertEqual(loaded.ai_provider,'openrouter');self.assertEqual(loaded.gemini_model,gemini.MODEL)
    def test_models_cannot_inject_endpoint_or_enable_paid_zai(self):
        for model in ('../gemini-x','https://malicious/gemini-x','gemini-x?key=secret','gemini-x/evil'):
            with self.subTest(model=model),self.assertRaises(g.GroqError):gemini.Responder(model)
        for model in ('glm-5.3','glm-4.5','auto','GLM-4.5-Flash'):
            with self.subTest(model=model),self.assertRaises(g.GroqError):zai.Responder(model)
        with self.assertRaises(Exception):cfg.Settings(zai_model='glm-5.3').check()
    def test_key_validation_accepts_google_formats_and_zai_only(self):
        self.assertEqual(gemini.key_value(GKEY),GKEY)
        self.assertEqual(gemini.key_value('AIza'+'x'*35),'AIza'+'x'*35)
        self.assertEqual(zai.key_value(ZKEY),ZKEY)
        for module in (gemini,zai):
            for value in ('synthetic','gsk_'+'a'*50,'Bearer '+GKEY,GKEY+'\n',None):
                with self.subTest(module=module.__name__,value=value),self.assertRaises(g.GroqError):module.key_value(value)
    def test_dpapi_storage_is_separate_and_never_plaintext_on_error(self):
        for module,key in ((gemini,GKEY),(zai,ZKEY)):
            with tempfile.TemporaryDirectory() as p:
                f=Path(p)/'key.dpapi'
                module.save_key(key,f,encoder=lambda b:b'ENCRYPTED')
                self.assertEqual(f.read_bytes(),b'ENCRYPTED');self.assertEqual(module.load_key(f,decoder=lambda b:key.encode()),key)
                with self.assertRaises(g.GroqError):module.save_key(key,f,encoder=lambda b:b'')
                self.assertEqual(f.read_bytes(),b'ENCRYPTED');self.assertFalse(f.with_suffix('.tmp').exists())
    def test_mixed_pool_sections_do_not_cross_providers(self):
        with tempfile.TemporaryDirectory() as p:
            f=Path(p)/'keys';f.write_text('[groq]\ngsk_'+'a'*30+'\n[gemini]\n'+GKEY+'\n'+GKEY+'\n[zai]\n'+ZKEY+'\n')
            self.assertEqual(pool.load('gemini',f),[GKEY]);self.assertEqual(pool.load('zai',f),[ZKEY])
            self.assertEqual(pool.load('groq',f),['gsk_'+'a'*30]);self.assertEqual(pool.load('openrouter',f),[])
    def test_more_than_sixteen_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as p:
            f=Path(p)/'keys';f.write_text('[gemini]\n'+'\n'.join('AQ.'+str(i).zfill(30) for i in range(17)))
            with self.assertRaisesRegex(g.GroqError,'gemini-key-pool-invalid'):pool.load('gemini',f)

class GeminiTransport(unittest.TestCase):
    def responder(self,c,**kw):
        return gemini.Responder(opener=c,key_loader=lambda:GKEY,rules_loader=lambda:'Правила',**kw)
    def test_success_headers_masked_context_and_no_openai_or_tools_payload(self):
        c=client(google());r=self.responder(c);s=snapshot();self.assertEqual(r('question',s),REPLY)
        req=c.open.call_args.args[0];body=json.loads(req.data)
        self.assertEqual(req.full_url,gemini.ENDPOINT+gemini.MODEL+':generateContent')
        self.assertNotIn(GKEY,req.full_url);self.assertNotIn(GKEY,req.data.decode())
        self.assertEqual(req.get_header('X-goog-api-key'),GKEY);self.assertIsNone(req.get_header('Authorization'))
        self.assertEqual(body['generationConfig']['responseMimeType'],'application/json')
        self.assertEqual(body['generationConfig']['thinkingConfig'],{'thinkingBudget':0})
        self.assertNotIn('tools',body);self.assertNotIn('messages',body)
        context=json.loads(body['contents'][0]['parts'][0]['text'])
        self.assertEqual(context['stage'],'question');self.assertNotIn('identity',context)
        self.assertEqual(context['history'],g.public_context(s));self.assertEqual(r.calls,1)
    def test_single_repair_retains_system_and_same_context(self):
        c=client(google({'decision':'reply','text':'Как настроение? Привет!'}),google())
        # Repeat greeting is not repairable: no second generation.
        r=self.responder(c)
        with self.assertRaisesRegex(g.GroqError,'gemini-repeat-greeting'):r('question',snapshot())
        self.assertEqual(c.open.call_count,1)
        c=client(google({'decision':'reply','text':'Вот и поговорили.'}),google())
        r=self.responder(c)
        self.assertEqual(r('question',snapshot()),REPLY);self.assertEqual(c.open.call_count,2)
        first,second=[json.loads(x.args[0].data) for x in c.open.call_args_list]
        self.assertEqual(first['contents'],second['contents'])
        self.assertIn('Предыдущий черновик',second['systemInstruction']['parts'][0]['text'])
    def test_google_signature_is_discarded_not_rendered_or_sent(self):
        c=client(google(parts=[{'text':json.dumps(REPLY),'thoughtSignature':'OPAQUE_SIGNATURE'}]));r=self.responder(c)
        self.assertEqual(r('question',snapshot()),REPLY)
        self.assertNotIn('OPAQUE_SIGNATURE',c.open.call_args.args[0].data.decode())
    def test_decline_and_review_are_not_repaired(self):
        for decision in ('decline','review'):
            c=client(google({'decision':decision,'text':''}));r=self.responder(c)
            self.assertEqual(r('question',snapshot())['decision'],decision);self.assertEqual(c.open.call_count,1)
    def test_blocked_tool_empty_truncated_and_malformed_responses_rejected(self):
        bad=[b'{}',b'not-json',google(reason='MAX_TOKENS'),google(reason='SAFETY'),
             google(parts=[{'functionCall':{'name':'send'}}]),google(parts=[{'text':'{}','thought':True}]),
             google(parts=[{'text':'{}','thought':'false'}]),b'X'*32769,
             json.dumps({'promptFeedback':{'blockReason':'SAFETY'}}).encode()]
        for body in bad:
            c=client(body)
            with self.subTest(body=body[:80]),self.assertRaises(g.GroqError) as e:self.responder(c)('question',snapshot())
            self.assertIn(str(e.exception),('gemini-invalid-response','gemini-token-limit'));self.assertEqual(c.open.call_count,1)
    def test_unsafe_reply_never_delivered_or_repaired(self):
        c=client(google({'decision':'reply','text':'Ссылка https://example.test'}))
        with self.assertRaisesRegex(g.GroqError,'gemini-unsafe-reply'):self.responder(c)('question',snapshot())
        self.assertEqual(c.open.call_count,1)
    def test_closed_http_codes_and_retry_after_without_error_body(self):
        for status,reason,code in [(400,'API_KEY_INVALID','unauthorized'),(403,'SERVICE_DISABLED','service-disabled'),
                                    (403,'BILLING_DISABLED','credits-required'),(429,None,'rate-limit'),(404,None,'model-unavailable')]:
            body=json.dumps({'error':{'message':'SECRET','details':[{'@type':'type.googleapis.com/google.rpc.ErrorInfo','reason':reason}]}}).encode()
            c=MagicMock();c.open.side_effect=urllib.error.HTTPError('https://SECRET',status,'SECRET',{'Retry-After':'2'},io.BytesIO(body))
            with self.subTest(status=status,reason=reason),self.assertRaises(g.GroqError) as e:self.responder(c)('question',snapshot())
            self.assertEqual(str(e.exception),'gemini-'+code);self.assertEqual(e.exception.retry_after,2)
            self.assertNotIn('SECRET',repr(e.exception));self.assertEqual(c.open.call_count,1)
    def test_cancellation_before_request_and_after_response(self):
        c=client(google());r=self.responder(c,cancelled=lambda:True)
        with self.assertRaisesRegex(g.GroqError,'gemini-cancelled'):r('question',snapshot())
        self.assertEqual(c.open.call_count,0)
        checks=iter([False,False,True]);r=self.responder(client(google()),cancelled=lambda:next(checks))
        with self.assertRaisesRegex(g.GroqError,'gemini-cancelled'):r('question',snapshot())

class ZaiTransport(unittest.TestCase):
    def test_flash_only_payload_and_shared_reply_gate(self):
        c=client(chat());r=zai.Responder(opener=c,key_loader=lambda:ZKEY,rules_loader=lambda:'Rules')
        self.assertEqual(r('question',snapshot()),REPLY)
        req=c.open.call_args.args[0];body=json.loads(req.data)
        self.assertEqual(req.full_url,zai.ENDPOINT);self.assertEqual(body['model'],zai.MODEL)
        self.assertEqual(body['thinking'],{'type':'disabled'});self.assertEqual(body['max_tokens'],1024)
        self.assertNotIn('max_completion_tokens',body);self.assertNotIn('provider',body)
        self.assertNotIn(ZKEY,req.data.decode());self.assertEqual(req.get_header('Authorization'),'Bearer '+ZKEY)
    def test_tools_and_truncated_responses_rejected(self):
        tool=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(REPLY),'tool_calls':[{}]}}]}).encode()
        for raw in (chat(reason='length'),tool):
            r=zai.Responder(opener=client(raw),key_loader=lambda:ZKEY,rules_loader=lambda:'Rules')
            with self.assertRaises(g.GroqError) as e:r('question',snapshot())
            self.assertIn(str(e.exception),('zai-token-limit','zai-invalid-response'))
    def test_quota_failure_is_closed(self):
        c=MagicMock();c.open.side_effect=urllib.error.HTTPError('https://SECRET',429,'SECRET',{'Retry-After':'3'},io.BytesIO(b'SECRET'))
        r=zai.Responder(opener=c,key_loader=lambda:ZKEY,rules_loader=lambda:'Rules')
        with self.assertRaisesRegex(g.GroqError,'zai-rate-limit') as e:r('question',snapshot())
        self.assertEqual(e.exception.retry_after,3);self.assertNotIn('SECRET',repr(e.exception))

class ExplicitRouting(unittest.TestCase):
    def setUp(self):pool._CACHE.clear()
    def test_selected_success_never_reads_other_keys(self):
        for provider,module in [('gemini',gemini),('zai',zai)]:
            trace=[]
            class Good:
                calls=1
                failures=[]
                def __call__(self,*a):return REPLY
            def factory(p,m,keys,cancelled):trace.append(p);return Good()
            def collect(p):self.assertEqual(p,provider);return ['synthetic']
            r=mumu_ai.Responder(provider,module.MODEL,collector=collect,factory=factory)
            self.assertEqual(r('question',snapshot()),REPLY);self.assertEqual(trace,[provider])
            self.assertEqual(r.strategy,mumu_ai.strategy(provider));self.assertEqual(r.provider_calls[provider],1)
    def test_selected_pool_failure_visits_remaining_services(self):
        for provider,module in [('gemini',gemini),('zai',zai)]:
            touched=[]
            class Bad:
                calls=1;failures=[]
                def __init__(self,p):self.provider=p
                def __call__(self,*a):raise g.GroqError(self.provider+'-key-pool-exhausted')
            r=mumu_ai.Responder(provider,module.MODEL,collector=lambda p:touched.append(p) or ['k'],factory=lambda p,*a:Bad(p))
            with self.assertRaisesRegex(g.GroqError,provider+'-key-pool-exhausted'):r('question',snapshot())
            self.assertEqual(touched,list(mumu_ai.provider_order(provider)))
    def test_live_key_test_uses_entered_provider_without_mumu_failover(self):
        for provider,module,key in [('gemini',gemini,GKEY),('zai',zai,ZKEY)]:
            with patch.dict(os.environ,{'DVK_MUMU_MULTI':'1'}):
                self.assertIsInstance(ai.responder(provider,module.MODEL,entered_key=key),module.Responder)
    def test_next_key_after_429_and_no_request_before_deadline(self):
        for provider,module in [('gemini',gemini),('zai',zai)]:
            touched=[];now=[0]
            class Adapter:
                def __init__(self,**kw):self.key=kw['key_loader']();self.calls=0
                def __call__(self,*a):
                    self.calls+=1;touched.append(self.key)
                    if self.key=='first':raise g.GroqError(provider+'-rate-limit',retry_after=2)
                    return REPLY
            r=pool.Responder(provider,module.MODEL,['first','second'],factory=Adapter,clock=lambda:now[0])
            self.assertEqual(r('question',snapshot()),REPLY);self.assertEqual(touched,['first','second'])
            r.state['cursor']=0;r('question',snapshot());self.assertEqual(touched,['first','second','second'])
            self.assertEqual(r.failures[0]['retry_in_seconds'],2)
            now[0]=2;r.state['cursor']=0;r('question',snapshot());self.assertEqual(touched[-2:],['first','second'])
    def test_json_diagnostics_admit_only_closed_codes_and_index(self):
        for provider in ('gemini','zai'):
            report={'status':'stopped','last_chat_diagnostics':{'ai_failures':[
                {'provider':provider,'key_index':2,'code':provider+'-rate-limit','cooldown':True,'retry_in_seconds':3,'raw':'SECRET'}]}}
            text=notify.diagnostic_json(report).decode();self.assertIn(provider+'-rate-limit',text);self.assertNotIn('SECRET',text)
    def test_saved_key_union_for_new_services_and_same_gate_on_pool_output(self):
        for provider,module,key in [('gemini',gemini,GKEY),('zai',zai,ZKEY)]:
            r=mumu_ai.Responder(provider,module.MODEL)
            with patch.object(pool,'load',return_value=[key]),patch.object(module,'load_key',return_value=key):
                self.assertEqual(r.collect(provider),[key])
