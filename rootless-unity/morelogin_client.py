"""Read-only official Open API and strictly parsed SSH plans. Never execute command."""
from dataclasses import dataclass, field
import ipaddress
import json
import re
import shlex
import urllib.request
from morelogin_common import CloudError, phone_id, MAX_PHONES

BASE = 'https://api.morelogin.com'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class Client:
    def __init__(self, app_id, key, *, opener=None):
        if (not isinstance(app_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', app_id)
                or not isinstance(key, str) or not 8 <= len(key) <= 4096
                or any(ord(c) < 33 or ord(c) > 126 for c in key)):
            raise CloudError('configuration')
        self.app_id, self.key = app_id, key
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def post(self, path, body, token=None):
        if path not in ('/oauth2/token', '/cloudphone/batchAdbInfo'):
            raise CloudError('configuration')
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=headers, method='POST')
        try:
            with self.opener.open(request, timeout=25) as response:
                data = response.read(2 * 1024 * 1024 + 1)
                if len(data) > 2 * 1024 * 1024:
                    raise ValueError()
                value = json.loads(data)
            if not isinstance(value, dict) or type(value.get('code')) is not int:
                raise ValueError()
            if value['code'] != 0:
                raise CloudError('api-denied')
            return value['data']
        except CloudError:
            raise
        except Exception:
            raise CloudError('api-unavailable') from None

    def query(self, ids):
        if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_PHONES
                or len(set(ids)) != len(ids)):
            raise CloudError('configuration')
        ids = [phone_id(x) for x in ids]
        auth = self.post('/oauth2/token', dict(client_id=self.app_id, client_secret=self.key, grant_type='client_credentials'))
        if not isinstance(auth, dict):
            raise CloudError('api-response')
        token = auth.get('access_token')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_.~-]{16,16384}', token):
            raise CloudError('api-response')
        entries = self.post('/cloudphone/batchAdbInfo', {'envIds': ids}, token)
        if not isinstance(entries, list) or len(entries) > MAX_PHONES:
            raise CloudError('api-response')
        result = {}
        for entry in entries:
            if not isinstance(entry, dict) or entry.get('id') not in ids or entry['id'] in result:
                raise CloudError('phone-ambiguous')
            result[entry['id']] = entry
        # Missing/failed phones do NOT cancel successful peers. They fail individually.
        return {x: result.get(x) for x in ids}

def port(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch('[0-9]{1,5}', value) or not 1 <= int(value) <= 65535:
        raise CloudError('ssh-format')
    return int(value)

@dataclass(frozen=True)
class Plan:
    host: str
    ssh_port: int
    user: str
    remote_host: str
    remote_port: int
    password: str = field(repr=False)

def plan(entry, expected):
    """Only SSH -L to the documented ADB proxy, no shell/options from service."""
    phone_id(expected)
    if not isinstance(entry, dict) or entry.get('id') != expected:
        raise CloudError('phone-ambiguous')
    if (entry.get('supportAdb') not in (True, 1) or entry.get('enableAdb') not in (True, 1)
            or type(entry.get('envStatus')) is not int or entry['envStatus'] != 4
            or entry.get('remark')):
        raise CloudError('phone-unavailable')
    password = entry.get('adbPassword')
    if not isinstance(password, str) or not 1 <= len(password) <= 4096 or '\x00' in password:
        raise CloudError('ssh-format')
    command = entry.get('command')
    if not isinstance(command, str) or not 1 <= len(command) <= 2048:
        raise CloudError('ssh-format')  # A14/15 SSH only, direct is intentionally not guessed.
    try:
        args = shlex.split(command, posix=True)
        if not args or args.pop(0) != 'ssh':
            raise ValueError()
        host = user = forwarding = number = None
        flags = set()
        while args:
            arg = args.pop(0)
            if arg in ('-N', '-f', '-Nf', '-fN'):
                if arg in flags: raise ValueError()
                flags.add(arg)
            elif arg.startswith('-o'):
                option = arg[2:] or args.pop(0)
                if option != 'HostKeyAlgorithms=+ssh-rsa': raise ValueError()
            elif arg in ('-p', '-L'):
                val = args.pop(0)
                if arg == '-p':
                    if number is not None: raise ValueError()
                    number = port(val)
                else:
                    if forwarding is not None: raise ValueError()
                    forwarding = val
            elif not arg.startswith('-') and arg.count('@') == 1 and host is None:
                user, host = arg.split('@')
                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', user) or user.startswith('-'): raise ValueError()
                host = str(ipaddress.IPv4Address(host))
            else:
                raise ValueError()
        if None in (host, user, forwarding, number) or not flags: raise ValueError()
        bits = forwarding.split(':')
        if len(bits) == 4:
            if bits.pop(0) not in ('127.0.0.1', 'localhost'): raise ValueError()
        if len(bits) != 3 or bits[1] not in ('adb-proxy', '127.0.0.1', 'localhost'): raise ValueError()
        port(bits[0])  # Never bind the supplied local port: allocate our own loopback port.
        return Plan(host, number, user, bits[1], port(bits[2]), password)
    except Exception:
        raise CloudError('ssh-format') from None
