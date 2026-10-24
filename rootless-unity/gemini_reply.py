"""Explicit Gemini Developer API adapter; no Vertex routing or hidden fallback.
Uses the same bounded, identity-masked context and continuation checks as Groq.
"""
import json
from pathlib import Path
import re
import urllib.request
import groq_reply as g
from assistant_store import credential_directory
from telegram_notify import protect

MODEL = 'gemini-3.1-flash-lite'
MODELS = (MODEL, 'gemini-2.5-flash')
ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/'


def key_value(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:AIza[A-Za-z0-9_-]{20,200}|AQ\.[A-Za-z0-9_-]{20,500})', value):
        raise g.GroqError('gemini-key-invalid')
    return value


def save_key(value, path=None, encoder=protect):
    value = key_value(value.strip())
    path = credential_directory() / 'gemini.dpapi' if path is None else Path(path)
    try:
        encrypted = encoder(value.encode())
        if not isinstance(encrypted, bytes) or not encrypted:
            raise ValueError()
    except Exception:
        raise g.GroqError('gemini-draft-protection-failed') from None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    try:
        temp.write_bytes(encrypted)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def load_key(path=None, decoder=lambda data: protect(data, decrypt=True)):
    try:
        path = credential_directory() / 'gemini.dpapi' if path is None else Path(path)
        if not 1 <= path.stat().st_size <= 8192:
            raise ValueError()
        return key_value(decoder(path.read_bytes()).decode())
    except Exception:
        raise g.GroqError('gemini-key-unavailable') from None


class Responder(g.Responder):
    endpoint = ENDPOINT
    timeout = 30

    def __init__(self, model=MODEL, cancelled=lambda: False, *, key_loader=load_key,
                 opener=None, rules_loader=g.rules):
        if not isinstance(model, str) or not re.fullmatch(r'gemini-[A-Za-z0-9.-]{1,100}', model):
            raise g.GroqError('gemini-model-unavailable')
        super().__init__(model, cancelled, key_loader=key_loader, opener=opener, rules_loader=rules_loader)

    def request(self, payload, key):
        key = key_value(key)
        systems = [m['content'] for m in payload['messages'] if m['role'] == 'system']
        users = [m for m in payload['messages'] if m['role'] == 'user']
        if len(users) != 1 or len(systems) not in (1, 2):
            raise g.GroqError('gemini-invalid-response')
        body = dict(systemInstruction=dict(parts=[dict(text='\n\n'.join(systems))]),
            contents=[dict(role='user', parts=[dict(text=users[0]['content'])])],
            generationConfig=dict(temperature=0.3, maxOutputTokens=1024,
                responseMimeType='application/json', thinkingConfig=dict(thinkingBudget=0),
                responseSchema=dict(type='OBJECT', properties=dict(
                    decision=dict(type='STRING', enum=['reply','decline','review']),
                    text=dict(type='STRING')), required=['decision','text'])))
        return urllib.request.Request(ENDPOINT + self.model + ':generateContent',
            data=json.dumps(body, ensure_ascii=False).encode(), method='POST', headers={
                'x-goog-api-key': key, 'Content-Type':'application/json', 'User-Agent':'DvkAssistant'})

    def decode_response(self, raw):
        value = g.strict_json(raw)
        if not isinstance(value, dict) or value.get('promptFeedback', {}).get('blockReason'):
            raise g.GroqError('gemini-invalid-response')
        candidates = value.get('candidates')
        if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
            raise g.GroqError('gemini-invalid-response')
        candidate = candidates[0]
        if candidate.get('finishReason') == 'MAX_TOKENS':
            raise g.GroqError('gemini-token-limit')
        if candidate.get('finishReason') != 'STOP':
            raise g.GroqError('gemini-invalid-response')
        content = candidate.get('content', {})
        parts = content.get('parts')
        if content.get('role') != 'model' or not isinstance(parts, list) or not 1 <= len(parts) <= 8:
            raise g.GroqError('gemini-invalid-response')
        texts = []
        for part in parts:
            if not isinstance(part, dict) or set(part) - {'text', 'thought', 'thoughtSignature'} or not isinstance(part.get('text'), str):
                raise g.GroqError('gemini-invalid-response')
            # Opaque Google transport metadata is discarded, not fed back, logged or used as text.
            if 'thoughtSignature' in part and (not isinstance(part['thoughtSignature'],str) or len(part['thoughtSignature']) > 16384):
                raise g.GroqError('gemini-invalid-response')
            if 'thought' in part and type(part['thought']) is not bool:
                raise g.GroqError('gemini-invalid-response')
            if not part.get('thought', False):
                texts.append(part['text'])
        if not texts:
            raise g.GroqError('gemini-invalid-response')
        return g.strict_json(''.join(texts))

    def http_error(self, status):
        return {400:'gemini-request-rejected',401:'gemini-unauthorized',403:'gemini-access-denied',
                404:'gemini-model-unavailable',429:'gemini-rate-limit'}.get(status,
                'gemini-service-error' if status >= 500 else 'gemini-request-rejected')

    def classify_error(self, error, code):
        # Only exact structured Google reasons, never message text or project IDs.
        if error.code in (400, 403):
            try:
                raw = error.read(4097)
                if len(raw) > 4096:
                    return code
                details = g.strict_json(raw).get('error', {}).get('details', [])
                reasons = {d.get('reason') for d in details if isinstance(d, dict) and
                           d.get('@type') == 'type.googleapis.com/google.rpc.ErrorInfo'}
                if 'API_KEY_INVALID' in reasons:
                    return 'gemini-unauthorized'
                if 'SERVICE_DISABLED' in reasons:
                    return 'gemini-service-disabled'
                if 'BILLING_DISABLED' in reasons:
                    return 'gemini-credits-required'
            except Exception:
                pass
        return code

    def __call__(self, kind, snapshot):
        try:
            return super().__call__(kind, snapshot)
        except g.GroqError as error:
            code = str(error)
            raise g.GroqError('gemini-' + code[5:] if code.startswith('groq-') else code,
                retry_after=error.retry_after, validation_reason=error.validation_reason) from None
