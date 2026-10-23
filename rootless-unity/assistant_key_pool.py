"""Explicit local key list; never log credentials or switch the selected provider."""
from pathlib import Path
import hashlib,time
import groq_reply as g
from assistant_config import config_directory

RETRY_SUFFIXES={'key-invalid','key-unavailable','unauthorized','access-denied','rate-limit',
 'credits-required','model-unavailable','service-error','network-error','timeout',
 'request-rejected','invalid-response','unsafe-reply','repeat-greeting','token-limit'}
_CACHE={}

def load(provider, path=None):
    path=config_directory()/'ai-keys.txt' if path is None else Path(path)
    if not path.exists():return []
    from assistant_ai import module
    try:
        if not 1<=path.stat().st_size<=32768:raise ValueError()
        result=[];section=None;invalid=False
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            if line in ('[groq]','[openrouter]'):section=line[1:-1];continue
            inferred='groq' if line.startswith('gsk_') else 'openrouter' if line.startswith('sk-or-v1-') else section
            if inferred not in ('groq','openrouter'):
                invalid=True;continue
            if inferred==provider:
                import re
                if provider=='openrouter' and re.fullmatch('[0-9a-fA-F]{64}',line):line='sk-or-v1-'+line
                try:value=module(provider).key_value(line)
                except g.GroqError:invalid=True;continue
                if value not in result:result.append(value)
        if invalid and not result:raise ValueError()
        if len(result)>16:raise ValueError()
        return result
    except Exception:
        raise g.GroqError(provider+'-key-pool-invalid') from None

class Responder:
    def __init__(self, provider, model, keys, cancelled=lambda:False, *, factory=None, clock=time.monotonic):
        from assistant_ai import module
        self.provider,self.model,self.cancelled,self.clock=provider,model,cancelled,clock
        factory=module(provider).Responder if factory is None else factory
        self.items=[factory(model=model,cancelled=cancelled,key_loader=lambda k=k:k) for k in keys]
        identity=hashlib.sha256((provider+'\0'+'\0'.join(keys)).encode()).hexdigest()
        self.state=_CACHE.setdefault(identity,dict(cursor=0,blocked={}))
        self.failovers=0;self.failures=[]
    @property
    def calls(self):return sum(x.calls for x in self.items)
    def __call__(self,kind,snapshot):
        n=len(self.items);last=None;self.failures=[]
        for offset in range(n):
            if self.cancelled():raise g.GroqError(self.provider+'-cancelled')
            i=(self.state['cursor']+offset)%n
            if self.state['blocked'].get(i,0)>self.clock():
                code=self.state.get('causes',{}).get(i,self.provider+'-key-pool-exhausted')
                self.failures.append(dict(provider=self.provider,key_index=i+1,code=code,cooldown=True))
                continue
            try:
                result=self.items[i](kind,snapshot)
                # Every regenerated answer must pass the same gate. Keys cannot
                # authorize an unsafe reply or retry a chat send.
                result=g.continuation(result,kind)
                self.state['cursor']=i
                return result
            except g.GroqError as error:
                suffix=str(error).removeprefix(self.provider+'-')
                if suffix not in RETRY_SUFFIXES:raise
                last=error;self.failovers+=1
                failure=dict(provider=self.provider,key_index=i+1,code=str(error),cooldown=False)
                if error.validation_reason in g.VALIDATION_REASONS:
                    failure['validation_reason']=error.validation_reason
                self.failures.append(failure)
                self.state.setdefault('causes',{})[i]=str(error)
                cooldown=3600 if suffix in {'unauthorized','access-denied','key-invalid','key-unavailable'} else 60 if suffix in {'rate-limit','credits-required'} else 15
                if suffix in {'rate-limit','service-error','credits-required'} and error.retry_after is not None:
                    cooldown=max(cooldown,error.retry_after)
                self.state['blocked'][i]=self.clock()+cooldown
        raise g.GroqError(self.provider+'-key-pool-exhausted') from None
