"""Explicit Z.AI model adapter; same strict context and reply gates, no paid fallback."""
from pathlib import Path
import re
import groq_reply as g
from assistant_store import data_directory, credential_directory
from telegram_notify import protect

MODEL = 'glm-4.5-flash'
MODELS = (MODEL,)
ENDPOINT = 'https://api.z.ai/api/paas/v4/chat/completions'


def key_value(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{32}\.[A-Za-z0-9_-]{16,200}', value):
        raise g.GroqError('zai-key-invalid')
    return value


def save_key(value, path=None, encoder=protect):
    value = key_value(value.strip())
    path = credential_directory() / 'zai.dpapi' if path is None else Path(path)
    try:
        encrypted = encoder(value.encode())
        if not isinstance(encrypted, bytes) or not encrypted:
            raise ValueError()
    except Exception:
        raise g.GroqError('zai-draft-protection-failed') from None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    try:
        temp.write_bytes(encrypted)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def load_key(path=None, decoder=lambda data: protect(data, decrypt=True)):
    try:
        path = credential_directory() / 'zai.dpapi' if path is None else Path(path)
        if not 1 <= path.stat().st_size <= 8192:
            raise ValueError()
        return key_value(decoder(path.read_bytes()).decode())
    except Exception:
        raise g.GroqError('zai-key-unavailable') from None


class Responder(g.Responder):
    endpoint = ENDPOINT
    timeout = 30

    def __init__(self, model=MODEL, cancelled=lambda: False, *, key_loader=load_key,
                 opener=None, rules_loader=g.rules):
        if model not in MODELS:
            raise g.GroqError('zai-paid-model-blocked')
        super().__init__(model, cancelled, key_loader=key_loader, opener=opener, rules_loader=rules_loader)

    def payload(self, kind, snapshot):
        body = super().payload(kind, snapshot)
        body['max_tokens'] = body.pop('max_completion_tokens')
        body['thinking'] = dict(type='disabled')
        # Only the explicitly supported Flash model; no paid model routing.
        return body

    def http_error(self, status):
        return {401: 'zai-unauthorized', 402: 'zai-credits-required',
                403: 'zai-access-denied', 404: 'zai-model-unavailable',
                429: 'zai-rate-limit'}.get(status,
                'zai-service-error' if status >= 500 else 'zai-request-rejected')

    def __call__(self, kind, snapshot):
        try:
            return super().__call__(kind, snapshot)
        except g.GroqError as error:
            code = str(error)
            raise g.GroqError('zai-' + code[5:] if code.startswith('groq-') else code,
                              retry_after=error.retry_after, validation_reason=error.validation_reason) from None
