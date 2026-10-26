"""MuMu-only generation failover. Never retries a send or loosens reply gates.
Selected provider first, then every other configured provider; DPAPI supplements the file.
Diagnostics contain closed error codes only, no key prefixes/body/exception text.
"""
import groq_reply as g
import openrouter_reply as o
import gemini_reply as google
import zai_reply as z
import assistant_key_pool as pool

PROVIDERS = ('groq', 'openrouter', 'gemini', 'zai')

def provider_order(selected):
    if selected not in PROVIDERS:
        from assistant_store import StateError
        raise StateError('Выбери поддерживаемый сервис ИИ.')
    return (selected,) + tuple(p for p in PROVIDERS if p != selected)

def strategy(selected):
    return '-then-'.join(provider_order(selected))

class Responder:
    def __init__(self,provider,model,cancelled=lambda:False,*,collector=None,factory=pool.Responder):
        self.cancelled=cancelled;self.collector=collector or self.collect;self.factory=factory
        self.providers = provider_order(provider)
        self.strategy = strategy(provider)
        self.models={'zai': model if provider == 'zai' else z.MODEL, 'gemini': model if provider == 'gemini' else google.MODEL, 'groq':model if provider=='groq' else g.MODEL,
                     'openrouter':model if provider=='openrouter' and model!='minimax/minimax-m3.1-flash:free' else o.MODEL}
        self.safe_greeting_fallbacks=0
        self.pools={};self.errors=[];self.failure_summary=[];self.failure_history=[]
    def note(self,code):
        if code in g.ERRORS and code not in self.errors:self.errors.append(code)
    def collect(self,provider):
        adapter={'groq':g,'openrouter':o,'gemini':google,'zai':z}[provider]
        try:keys=pool.load(provider)
        except g.GroqError as e:
            self.note(str(e));keys=[]
            self.failure_summary.append(dict(provider=provider,key_index=0,code=str(e),cooldown=False))
        try:
            key=adapter.load_key()
            if key not in keys:keys.append(key)
        except g.GroqError as e:
            if not keys:
                self.note(str(e))
                self.failure_summary.append(dict(provider=provider,key_index=0,code=str(e),cooldown=False))
        return keys
    @property
    def provider_calls(self):return {p:self.pools[p].calls if p in self.pools else 0 for p in ('groq','openrouter','gemini','zai')}
    @property
    def calls(self):return sum(self.provider_calls.values())
    def __call__(self,kind,snapshot):
        from assistant_runtime import phase
        # Restore pre-1.3.60 failover: every configured eligible key/provider
        # remains available. Per-request timeouts and provider cooldowns remain.
        with phase('ai'):return self.generate(kind,snapshot)
    def generate(self,kind,snapshot):
        self.errors=[];self.failure_summary=[]
        for provider in self.providers:
            if self.cancelled():raise g.GroqError('groq-cancelled')
            if provider not in self.pools:
                keys=self.collector(provider)
                if not keys:continue
                self.pools[provider]=self.factory(provider,self.models[provider],keys,self.cancelled)
            try:
                result=g.continuation(self.pools[provider](kind,snapshot),kind,snapshot=snapshot)
                self.capture_failures(provider)
                return result
            except g.GroqError as e:
                self.capture_failures(provider)
                code=str(e)
                if code.endswith('-cancelled') or code.removeprefix(provider+'-') not in pool.RETRY_SUFFIXES|{'key-pool-exhausted','key-pool-invalid'}:raise
                self.note(code)
        fallback=safe_greeting_reply(kind,snapshot)
        if fallback is not None:
            self.safe_greeting_fallbacks+=1
            return fallback
        raise g.GroqError(self.providers[0]+'-key-pool-exhausted') from None

    def capture_failures(self,provider):
        values=getattr(self.pools[provider],'failures',[])
        if type(values) is list:
            self.failure_summary.extend(values[:32]);self.failure_summary=self.failure_summary[-64:]
            self.failure_history.extend(values[:32]);self.failure_history=self.failure_history[-128:]

def safe_failures(responder):
    values=getattr(responder,'failure_summary',[])
    if type(values) is not list:return []
    result=[]
    for item in values[:64]:
        if (type(item) is dict and item.get('provider') in ('groq','openrouter','gemini','zai')
            and item.get('code') in g.ERRORS and type(item.get('key_index')) is int
            and 0<=item['key_index']<=17 and type(item.get('cooldown')) is bool):
            failure={k:item[k] for k in ('provider','key_index','code','cooldown')}
            if isinstance(item.get('validation_reason'),str) and item['validation_reason'] in g.VALIDATION_REASONS:
                failure['validation_reason']=item['validation_reason']
            retry = item.get('retry_in_seconds')
            if type(retry) is int and 1 <= retry <= 86400:
                failure['retry_in_seconds'] = retry
            result.append(failure)
    return result

def failure_explanation(values):
    safe=safe_failures(type('Failures',(),{'failure_summary':values})())
    codes={x['code'].split('-',1)[1] for x in safe}
    delayed = [x['retry_in_seconds'] for x in safe if type(x.get('retry_in_seconds')) is int]
    delay = (' Ближайший срок повторного использования ключа — через ' + str(min(delayed)) + ' с.') if delayed else ''
    if codes and codes <= {'organization-restricted','unauthorized','access-denied','key-invalid','key-unavailable'} and 'organization-restricted' in codes:
        return 'ИИ: Groq ограничил доступ организации; доступных ключей в пуле не осталось.' + delay
    if 'organization-restricted' in codes and codes <= {'organization-restricted','rate-limit','credits-required'}:
        return 'ИИ: часть ключей Groq ограничена на уровне организации, у остальных исчерпаны лимиты.' + delay + ' Переписка отложена без отправки.'
    if codes and 'model-unavailable' in codes and codes <= {'model-unavailable','organization-restricted','rate-limit','credits-required'}:
        return 'ИИ: выбранная модель недоступна доступным аккаунтам; часть ключей также может быть ограничена. Проверь модель и доступ к ней. Неверный ключ из этого не следует.'
    if 'service-disabled' in codes:
        return 'ИИ: Google API отключён для проекта ключа. Включи Gemini Developer API и проверь доступ проекта. Переписка отложена без отправки.'
    if codes == {'request-rejected'}:
        return 'ИИ: API отклонил запросы. Проверь модель и параметры; это не доказательство неверного ключа.' + delay
    if codes and codes <= {'rate-limit','credits-required','request-rejected'} and 'request-rejected' in codes:
        return 'ИИ: часть запросов отклонена API, у остальных ключей исчерпаны лимиты. Это не означает, что все ключи неверные.' + delay
    if codes and codes<={'rate-limit','credits-required'}:
        return 'ИИ: исчерпаны лимиты доступных ключей.' + delay + ' Проверю чат позже.'
    if codes and codes<={'unauthorized','access-denied','key-invalid','key-unavailable'}:
        return 'ИИ: доступные ключи отклонены. Проверь ключи и доступ к API.'
    if codes and codes<={'network-error','timeout','service-error'}:
        return 'ИИ: сервисы не ответили или недоступны. Проверю чат позже.'
    if codes and codes<={'invalid-response','unsafe-reply','repeat-greeting','token-limit'}:
        return 'ИИ: полученные ответы не прошли проверку. Проверю чат позже.'
    if codes and codes <= {'rate-limit','credits-required','invalid-response','unsafe-reply','repeat-greeting','token-limit'}:
        return 'ИИ: часть ответов не прошла проверку, у остальных ключей исчерпаны лимиты. Проверю чат позже.'
    return 'Доступные ключи ИИ не дали проверенного ответа. Проверю чат позже.'


def safe_greeting_reply(kind,snapshot):
    """Only a whole batch of simple greetings/emoji, after every provider failed.

    No fallback for questions, objections, moods, media, refusal or contacts.
    The same normal reply gate, durable draft and native send checks still apply.
    """
    import re,unicodedata
    if kind!='question' or not isinstance(snapshot,dict):return None
    ids=snapshot.get('_reply_ids',[])
    if not isinstance(ids,(list,tuple)) or not ids:return None
    try:
        history=g.public_context(snapshot)  # validate the full identity-bound context
        if any(m['speaker']=='self' and g.MOOD_QUESTION.search(m['text']) for m in history):return None
        peer=snapshot['identity']['peer']
        rows=[m for m in snapshot['messages'] if m['id'] in ids and m['sender']==peer]
        if {m['id'] for m in rows}!=set(ids):return None
        greeting=False
        pattern=r'(?:привет(?:ик)?|здравствуй(?:те)?|добрый\s+(?:день|вечер)|доброе\s+утро|доброго\s+(?:дня|вечера|утра)|хай|hello|hi)(?:\s+(?:красавец|красавица|милый|милая|сударь|сударыня))?'
        for m in rows:
            if not isinstance(m['text'],str) or '?' in m['text']:return None
            words=''.join(c if c.isalnum() or c.isspace() else ' ' for c in m['text']).strip().lower()
            words=' '.join(words.split())
            if words:
                if not re.fullmatch(pattern,words):return None
                greeting=True
            elif not m['text'].strip() or any(unicodedata.category(c)[0] not in 'PSZ' and not c.isspace() for c in m['text']):return None
        return g.continuation(dict(decision='reply',text='Как настроение?'),'question') if greeting else None
    except (KeyError,TypeError,ValueError,g.GroqError):return None
