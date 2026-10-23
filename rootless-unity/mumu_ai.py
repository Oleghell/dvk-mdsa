"""MuMu-only generation failover. Never retries a send or loosens reply gates.
All configured Groq keys precede OpenRouter; saved DPAPI keys supplement the file.
Diagnostics contain closed error codes only, no key prefixes/body/exception text.
"""
import groq_reply as g
import openrouter_reply as o
import assistant_key_pool as pool

class Responder:
    def __init__(self,provider,model,cancelled=lambda:False,*,collector=None,factory=pool.Responder):
        self.cancelled=cancelled;self.collector=collector or self.collect;self.factory=factory
        self.models={'groq':model if provider=='groq' else g.MODEL,
                     'openrouter':model if provider=='openrouter' and model!='minimax/minimax-m3.1-flash:free' else o.MODEL}
        self.pools={};self.errors=[]
    def note(self,code):
        if code in g.ERRORS and code not in self.errors:self.errors.append(code)
    def collect(self,provider):
        adapter=g if provider=='groq' else o
        try:keys=pool.load(provider)
        except g.GroqError as e:self.note(str(e));keys=[]
        try:
            key=adapter.load_key()
            if key not in keys:keys.append(key)
        except g.GroqError as e:
            if not keys:self.note(str(e))
        return keys
    @property
    def provider_calls(self):return {p:self.pools[p].calls if p in self.pools else 0 for p in ('groq','openrouter')}
    @property
    def calls(self):return sum(self.provider_calls.values())
    def __call__(self,kind,snapshot):
        self.errors=[]
        for provider in ('groq','openrouter'):
            if self.cancelled():raise g.GroqError('groq-cancelled')
            if provider not in self.pools:
                keys=self.collector(provider)
                if not keys:continue
                self.pools[provider]=self.factory(provider,self.models[provider],keys,self.cancelled)
            try:return g.continuation(self.pools[provider](kind,snapshot),kind)
            except g.GroqError as e:
                code=str(e)
                if code.endswith('-cancelled') or code.removeprefix(provider+'-') not in pool.RETRY_SUFFIXES|{'key-pool-exhausted','key-pool-invalid'}:raise
                self.note(code)
        raise g.GroqError('groq-key-pool-exhausted') from None
