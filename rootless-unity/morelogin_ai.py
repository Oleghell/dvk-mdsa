"""MoreLogin runtime only: Groq keys first, then free OpenRouter keys.

UI connection tests remain provider-specific. No chat sends or credential logs.
"""
from contextlib import contextmanager
import time
import groq_reply as g
import assistant_ai as ai
import assistant_key_pool as pool

_installed=False

class Responder:
    def __init__(self,provider,model,cancelled=lambda:False,*,metrics=None,models=None,totals=None):
        ai.module(provider)
        self.provider,self.model,self.cancelled,self.metrics=provider,model,cancelled,metrics
        self.items={}
        self.models=models or {}
        self.totals=totals

    @property
    def calls(self):return sum(x.calls for x in self.items.values())

    def client(self,provider):
        if provider in self.items:return self.items[provider]
        adapter=ai.module(provider)
        keys=pool.load(provider)
        try:
            saved=adapter.load_key()
        except g.GroqError as error:
            if str(error)!=provider+'-key-unavailable':raise
        else:
            if saved not in keys:keys.append(saved)
        model=self.models.get(provider,self.model if self.provider==provider else adapter.MODEL)
        # With no credentials, an empty pool reports exhausted without a network request.
        result=pool.Responder(provider,model,keys,self.cancelled)
        self.items[provider]=result
        return result

    def __call__(self,kind,snapshot):
        for provider in ('groq','openrouter'):
            if self.cancelled():raise g.GroqError('groq-cancelled')
            started=time.monotonic();failed=True
            before=self.items[provider].calls if provider in self.items else 0
            try:
                value=self.client(provider)(kind,snapshot)
                if self.cancelled():raise g.GroqError('groq-cancelled')
                result=g.continuation(value,kind);failed=False;return result
            except g.GroqError as error:
                suffix=str(error).split('-',1)[-1]
                if suffix not in pool.RETRY_SUFFIXES|{'key-pool-exhausted','key-pool-invalid'}:raise
            finally:
                if self.metrics:self.metrics.record('ai_'+provider,time.monotonic()-started,failed)
                if self.totals is not None and provider in self.items:
                    self.totals[provider]+=self.items[provider].calls-before
        raise g.GroqError('groq-key-pool-exhausted') from None

@contextmanager
def runtime(cancelled=lambda:False,*,metrics=None,models=None):
    global _installed
    import os
    from morelogin_common import CloudError
    if os.environ.get('DVK_MORELOGIN')!='1' or _installed:raise CloudError('configuration')
    import assistant_inbox
    original=ai.responder;original_inbox=assistant_inbox.run;_installed=True
    totals=dict(groq=0,openrouter=0)
    def responder(provider,model,cancelled=cancelled,*,entered_key=''):
        if entered_key.strip():return original(provider,model,cancelled,entered_key=entered_key)
        return Responder(provider,model,cancelled,metrics=metrics,models=models,totals=totals)
    def inbox(*args,**kwargs):
        before=dict(totals)
        result=original_inbox(*args,**kwargs)
        result['groq_requests']=totals['groq']-before['groq']
        result['openrouter_requests']=totals['openrouter']-before['openrouter']
        result['ai_requests']=result['groq_requests']+result['openrouter_requests']
        result['groq_context_export_enabled']=args[0].groq_enabled
        result['openrouter_context_export_enabled']=args[0].groq_enabled
        result['ai_provider_order']=['groq','openrouter']
        return result
    ai.responder=responder;assistant_inbox.run=inbox
    try:yield totals
    finally:
        ai.responder=original;assistant_inbox.run=original_inbox;_installed=False
