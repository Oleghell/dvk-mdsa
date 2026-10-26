"""Explicit local key list; never log credentials; cross-provider ordering is owned by mumu_ai."""
from pathlib import Path
import hashlib,time
import groq_reply as g
from assistant_config import config_directory

RETRY_SUFFIXES={'organization-restricted','key-invalid','key-unavailable','unauthorized','access-denied','rate-limit',
 'credits-required','service-disabled','model-unavailable','service-error','network-error','timeout',
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
            if line in ('[groq]','[openrouter]','[gemini]','[zai]'):section=line[1:-1];continue
            import re
            inferred='groq' if line.startswith('gsk_') else 'openrouter' if line.startswith('sk-or-v1-') else 'gemini' if line.startswith(('AIza','AQ.')) else 'zai' if re.fullmatch(r'[a-fA-F0-9]{32}\.[A-Za-z0-9_-]{16,200}',line) else section
            if inferred not in ('groq','openrouter','gemini','zai'):
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
        identity=hashlib.sha256((provider+'\0'+model+'\0'+'\0'.join(keys)).encode()).hexdigest()
        # Different MuMu ports start at different places; successful generation
        # then rotates to the next key. This spreads load, not organization quota.
        import os
        seed = 0
        if os.environ.get('DVK_MUMU_MULTI') == '1' and keys:
            port = os.environ.get('DVK_MUMU_PORT', '')
            if port.isascii() and port.isdigit() and 1024 <= int(port) <= 65535:
                seed = int(hashlib.sha256((provider+'\0'+port).encode()).hexdigest()[:8],16) % len(keys)
        self.state=_CACHE.setdefault(identity,dict(cursor=seed,blocked={}))
        self.failovers=0;self.failures=[]
    @property
    def calls(self):return sum(x.calls for x in self.items)
    def __call__(self,kind,snapshot):
        import math
        n=len(self.items);self.failures=[]
        start=self.state['cursor']
        for offset in range(n):
            from assistant_ai_budget import exhausted
            if exhausted():raise g.GroqError(self.provider+'-timeout')
            if self.cancelled():raise g.GroqError(self.provider+'-cancelled')
            i=(start+offset)%n
            if self.state['blocked'].get(i,0)>self.clock():
                code=self.state.get('causes',{}).get(i,self.provider+'-key-pool-exhausted')
                self.failures.append(dict(provider=self.provider,key_index=i+1,code=code,cooldown=True,
                    retry_in_seconds=max(1,min(86400,math.ceil(self.state['blocked'][i]-self.clock())))))
                continue
            try:
                result=self.items[i](kind,snapshot)
                # Every regenerated answer must pass the same gate. Keys cannot
                # authorize an unsafe reply or retry a chat send.
                result=g.continuation(result,kind,snapshot=snapshot)
                self.state['cursor']=(i+1)%n
                return result
            except g.GroqError as error:
                suffix=str(error).removeprefix(self.provider+'-')
                if suffix not in RETRY_SUFFIXES:raise
                self.failovers+=1
                failure=dict(provider=self.provider,key_index=i+1,code=str(error),cooldown=False)
                if error.validation_reason in g.VALIDATION_REASONS:
                    failure['validation_reason']=error.validation_reason
                self.failures.append(failure)
                self.state.setdefault('causes',{})[i]=str(error)
                cooldown=3600 if suffix in {'organization-restricted','unauthorized','access-denied','key-invalid','key-unavailable','service-disabled'} else 60 if suffix in {'rate-limit','credits-required'} else 15
                if suffix in {'rate-limit','service-error','credits-required'} and error.retry_after is not None:
                    # A server deadline is authoritative: no premature retry and
                    # no artificial extra minute when it explicitly says 2s.
                    cooldown=error.retry_after if suffix in {'rate-limit','credits-required'} else max(cooldown,error.retry_after)
                cooldown=math.ceil(cooldown)
                self.state['blocked'][i]=self.clock()+cooldown
                failure['retry_in_seconds']=cooldown
        raise g.GroqError(self.provider+'-key-pool-exhausted') from None
