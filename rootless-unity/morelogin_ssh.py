"""Loopback-only SSH forwarding, pinned host keys, owned sockets, no subprocess shell."""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import ipaddress
import select
import socket
import socketserver
import threading
from morelogin_common import CloudError, fingerprint

def key_fingerprint(key):
    return 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')

def domain_connection(address, timeout=15):
    """Resolve once, reject private/mixed DNS answers, connect to checked IP only."""
    host,port=address
    try:
        answers=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
        addresses=[]
        for family,kind,proto,_,target in answers:
            ip=ipaddress.ip_address(target[0])
            if not ip.is_global or ip.is_multicast or ip.is_reserved:raise ValueError()
            if str(ip) not in addresses:addresses.append(str(ip))
        if not addresses:raise ValueError()
        # No second lookup of the untrusted name: closes DNS-rebinding window.
        return socket.create_connection((addresses[0],port),timeout=timeout)
    except Exception:
        raise CloudError('ssh-unavailable') from None


@contextmanager
def handshake(plan, *, socket_factory=None, transport_factory=None):
    if transport_factory is None:
        import paramiko
        transport_factory = paramiko.Transport
    if socket_factory is None:
        try:
            ipaddress.IPv4Address(plan.host)
            socket_factory=socket.create_connection
        except ValueError:
            socket_factory=domain_connection
    sock = transport = None
    try:
        try:
            sock = socket_factory((plan.host, plan.ssh_port), timeout=15)
            if isinstance(sock,socket.socket):sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            transport = transport_factory(sock)
            transport.banner_timeout = 15
            transport.auth_timeout = 15
            transport.start_client(timeout=15)
        except CloudError:
            raise
        except Exception:
            raise CloudError('ssh-unavailable') from None
        # Do not turn installation, timeouts or engine errors into SSH errors.
        yield transport
    finally:
        for resource in (transport, sock):
            if resource is not None:
                try: resource.close()
                except Exception: pass

def probe(plan):
    """No password sent. This is an observation, NOT authentication of the host."""
    with handshake(plan) as transport:
        return key_fingerprint(transport.get_remote_server_key())

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True
    block_on_close = False

@contextmanager
def tunnel(plan, pinned, cancelled=lambda: False):
    pinned = fingerprint(pinned)
    with handshake(plan) as transport:
        actual = key_fingerprint(transport.get_remote_server_key())
        if not hmac.compare_digest(actual, pinned):
            raise CloudError('ssh-key-changed')
        if cancelled(): raise CloudError('cancelled')
        # No password is ever sent before the key pin has matched.
        try:
            transport.auth_password(plan.user, plan.password, fallback=False)
            if not transport.is_authenticated(): raise ValueError()
            transport.set_keepalive(20)
        except Exception:
            raise CloudError('ssh-unavailable') from None
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                channel = None
                try:
                    self.request.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                    channel = transport.open_channel('direct-tcpip', (plan.remote_host, plan.remote_port), self.client_address, timeout=15)
                    while not cancelled() and transport.is_active():
                        ready, _, _ = select.select([self.request, channel], [], [], .2)
                        for source in ready:
                            data = source.recv(32768)
                            if not data: return
                            (channel if source is self.request else self.request).sendall(data)
                except Exception:
                    pass  # Never export transport errors, passwords or server banners.
                finally:
                    if channel is not None: channel.close()
        server = Server(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield '127.0.0.1:' + str(server.server_address[1])
        finally:
            for close in (server.shutdown,server.server_close,transport.close):
                try: close()
                except Exception: pass
            thread.join(timeout=2)
