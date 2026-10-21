"""Explicitly selected free OpenRouter models. No paid fallback or raw error logging."""
from pathlib import Path
import re
import groq_reply as g
from assistant_store import data_directory
from telegram_notify import protect

MODEL = 'minimax/minimax-m3.1-flash:free'
MODELS = (MODEL, 'dots-studio/dots-3-note-preview:free')
ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'


def key_value(value):
    if not isinstance(value, str) or not re.fullmatch(r'sk-or-v1-[A-Za-z0-9_-]{20,200}', value):
        raise g.GroqError('openrouter-key-invalid')
    return value


def save_key(value, path=None, encoder=protect):
    value = key_value(value.strip())
    path = data_directory() / 'openrouter.dpapi' if path is None else Path(path)
    try:
        encrypted = encoder(value.encode())
        if not isinstance(encrypted, bytes) or not encrypted:
            raise ValueError()
    except Exception:
        raise g.GroqError('openrouter-draft-protection-failed') from None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    try:
        temp.write_bytes(encrypted)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def load_key(path=None, decoder=lambda data: protect(data, decrypt=True)):
    try:
        path = data_directory() / 'openrouter.dpapi' if path is None else Path(path)
        if not 1 <= path.stat().st_size <= 8192:
            raise ValueError()
        return key_value(decoder(path.read_bytes()).decode())
    except Exception:
        raise g.GroqError('openrouter-key-unavailable') from None


class Responder(g.Responder):
    endpoint = ENDPOINT
    timeout = 30

    def __init__(self, model=MODEL, cancelled=lambda: False, *, key_loader=load_key,
                 opener=None, rules_loader=g.rules):
        if not isinstance(model, str) or len(model) > 150 or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:free', model):
            raise g.GroqError('openrouter-paid-model-blocked')
        super().__init__(model, cancelled, key_loader=key_loader, opener=opener, rules_loader=rules_loader)

    def payload(self, kind, snapshot):
        body = super().payload(kind, snapshot)
        body.pop('max_completion_tokens')
        body.update(max_tokens=2048, reasoning=dict(effort='low', exclude=True),
                    provider=dict(data_collection='deny', require_parameters=True,
                                  max_price=dict(prompt=0, completion=0)))
        # No "models" fallback array, auto-router, plugins or tools.
        return body

    def http_error(self, status):
        return {401: 'openrouter-unauthorized', 402: 'openrouter-credits-required',
                403: 'openrouter-access-denied', 404: 'openrouter-model-unavailable',
                429: 'openrouter-rate-limit'}.get(status,
                'openrouter-service-error' if status >= 500 else 'openrouter-request-rejected')

    def __call__(self, kind, snapshot):
        try:
            return super().__call__(kind, snapshot)
        except g.GroqError as error:
            code = str(error)
            raise g.GroqError('openrouter-' + code[5:] if code.startswith('groq-') else code) from None
