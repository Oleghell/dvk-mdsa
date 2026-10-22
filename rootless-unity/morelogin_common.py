"""MoreLogin-only paths and validation. No implicit MuMu fallback."""
import json
import os
from pathlib import Path
import re
import tempfile

MAX_PHONES = 200

class CloudError(RuntimeError):
    """Only fixed, non-secret reason codes may leave connection layers."""
    CODES = {'configuration', 'direct-adb-format', 'adb-auth-failed', 'api-transport', 'api-http', 'api-network', 'api-dns', 'api-tls', 'api-timeout', 'api-unavailable', 'api-denied', 'api-response',
             'phone-unavailable', 'phone-ambiguous', 'ssh-format', 'ssh-host-format', 'ssh-options-format', 'ssh-forward-format', 'ssh-key-untrusted',
             'ssh-key-changed', 'ssh-unavailable', 'adb-unavailable', 'device-busy',
             'device-not-ready', 'bundle-required', 'cancelled', 'worker-stopped'}
    def __init__(self, code, *, stage=None, http_status=None, service_code=None):
        self.code = code if code in self.CODES else 'worker-stopped'
        self.stage = stage if stage in ('auth', 'adb-info') else None
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        self.service_code = service_code if type(service_code) is int and 0 <= service_code <= 999999 else None
        super().__init__(self.code)


def phone_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,29}', value):
        raise CloudError('configuration')
    return value

def root_directory():
    value = os.environ.get('LOCALAPPDATA')
    if not value:
        raise CloudError('configuration')
    return Path(value) / 'DvkAssistantMoreLogin'

def phone_directory(value):
    return root_directory() / 'phones' / phone_id(value)

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def ids_from_text(text):
    values = [phone_id(line.strip()) for line in text.splitlines() if line.strip()]
    if not 1 <= len(values) <= MAX_PHONES or len(set(values)) != len(values):
        raise CloudError('configuration')
    return values

def fingerprint(value):
    if not isinstance(value, str) or not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', value):
        raise CloudError('configuration')
    return value
