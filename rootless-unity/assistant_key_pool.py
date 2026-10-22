"""Explicit local key list; never log credentials or switch the selected provider."""
from pathlib import Path
import hashlib,time
import groq_reply as g
from assistant_config import config_directory

RETRY_SUFFIXES={'key-invalid','key-unavailable','unauthorized','access-denied','rate-limit',
 'credits-required','model-unavailable','service-error','network-error','timeout',
 'request-rejected','invalid-response','unsafe-reply','repeat-greeting'}
_CACHE={}

def load(provider, path=None):
    path=config_directory()/'ai-keys.txt' if path is None else Path(path)
    if not path.exists():return []
    from assistant_ai import module
    try:
        if not 1<=path.stat().st_size<=32768:raise ValueError()
        result=[];section=None
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            if line in ('[groq]','[openrouter]'):section=line[1:-1];continue
            if section not in ('groq','openrouter'):raise ValueError()
            if section==provider:
                value=module(provider).key_value(line)
                if value not in result:result.append(value)
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
        self.failovers=0
    @property
    def calls(self):return sum(x.calls for x in self.items)
    def __call__(self,kind,snapshot):
        n=len(self.items);last=None
        for offset in range(n):
            if self.cancelled():raise g.GroqError(self.provider+'-cancelled')
            i=(self.state['cursor']+offset)%n
            if self.state['blocked'].get(i,0)>self.clock():continue
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
                cooldown=3600 if suffix in {'unauthorized','access-denied','key-invalid','key-unavailable'} else 60 if suffix in {'rate-limit','credits-required'} else 15
                self.state['blocked'][i]=self.clock()+cooldown
        raise g.GroqError(self.provider+'-key-pool-exhausted') from None
