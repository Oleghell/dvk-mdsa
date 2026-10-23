"""Direct MoreLogin ADB via a private loopback relay and code authentication.
Only the selected API endpoint is contacted. No shell commands from API, no
password on a process command line, no global disconnect/server reset/install.
The provider's direct ADB transport is not an encrypted SSH tunnel.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import select
import socket
import socketserver
import subprocess
import threading
import time
from morelogin_common import CloudError


def _serial(value):
    if not isinstance(value,str) or not re.fullmatch(r'127\.0\.0\.1:[0-9]{1,5}',value) or not 1024<=int(value.split(':')[1])<=65535:
        raise CloudError('configuration')
    return value


def _adb(executable,operation,serial):
    serial=_serial(serial)
    if operation not in ('connect','disconnect'):raise CloudError('configuration')
    path=Path(executable)
    if not path.is_absolute() or not path.is_file():raise CloudError('adb-unavailable')
    env=os.environ.copy()
    for key in ('ADB_SERVER_SOCKET','ANDROID_ADB_SERVER_PORT','ANDROID_SERIAL'):
        env.pop(key,None)
    env['ADB_SERVER_SOCKET']='tcp:localhost:5037'
    try:
        result=subprocess.run([str(path),operation,serial],stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,shell=False,env=env,
            timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode!=0:raise ValueError()
    except Exception:
        raise CloudError('adb-unavailable') from None


def _exact(sock,length):
    value=b''
    while len(value)<length:
        block=sock.recv(length-len(value))
        if not block:raise CloudError('adb-auth-failed')
        value+=block
    return value


def _service(sock,text):
    data=text.encode('ascii')
    if len(data)>1024:raise CloudError('configuration')
    sock.sendall(('%04x'%len(data)).encode('ascii')+data)
    if _exact(sock,4)!=b'OKAY':
        # Do not read/export the adb failure body (may contain the auth code).
        raise CloudError('adb-auth-failed')


def _shell(serial,operation,*,code=None,cancelled=lambda:False,socket_factory=socket.create_connection):
    serial=_serial(serial)
    if cancelled():raise CloudError('cancelled')
    if operation=='authenticate':
        if not isinstance(code,str) or not re.fullmatch(r'[0-9]{1,32}',code):raise CloudError('direct-adb-format')
        command=code
    elif operation=='boot-id':command='cat /proc/sys/kernel/random/boot_id'
    elif operation=='boot-completed':command='getprop sys.boot_completed'
    else:raise CloudError('configuration')
    try:
        # ADB smart-socket protocol, equivalent to adb -s SERIAL shell CODE.
        # Secret is sent only over the selected local socket, never argv/files.
        with socket_factory(('127.0.0.1',5037),timeout=10) as sock:
            sock.settimeout(10)
            _service(sock,'host:transport:'+serial)
            _service(sock,'shell:'+command)
            sock.settimeout(1)
            if operation=='authenticate':sock.sendall(b'exit\n')
            output=bytearray();deadline=time.monotonic()+15
            while True:
                if cancelled():raise CloudError('cancelled')
                if time.monotonic()>deadline:raise CloudError('adb-auth-failed')
                try:chunk=sock.recv(4096)
                except socket.timeout:continue
                if not chunk:break
                output.extend(chunk)
                if len(output)>65536:raise CloudError('adb-auth-failed')
            if operation=='authenticate':return None  # Never retain/export response.
            return output.decode('ascii',errors='strict').strip()
    except CloudError:raise
    except Exception:raise CloudError('adb-auth-failed') from None


def authenticate(serial,code,cancelled=lambda:False):
    _shell(serial,'authenticate',code=code,cancelled=cancelled)
    boot=_shell(serial,'boot-id',cancelled=cancelled)
    if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',boot):
        raise CloudError('adb-auth-failed')
    if _shell(serial,'boot-completed',cancelled=cancelled)!='1':raise CloudError('device-not-ready')
    return boot


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=False
    daemon_threads=True
    block_on_close=False


@contextmanager
def relay(plan,cancelled=lambda:False,*,socket_factory=socket.create_connection):
    active=set();lock=threading.Lock()
    closing=threading.Event()
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            remote=None
            try:
                if cancelled() or closing.is_set():return
                remote=socket_factory((plan.host,plan.adb_port),timeout=10)
                self.request.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                remote.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                with lock:active.update((self.request,remote))
                while not cancelled() and not closing.is_set():
                    ready,_,_=select.select([self.request,remote],[],[],.2)
                    for source in ready:
                        data=source.recv(32768)
                        if not data:return
                        (remote if source is self.request else self.request).sendall(data)
            except Exception:pass
            finally:
                with lock:
                    active.discard(self.request)
                    active.discard(remote)
                if remote is not None:remote.close()
    server=Server(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        if cancelled():raise CloudError('cancelled')
        yield '127.0.0.1:'+str(server.server_address[1])
    finally:
        closing.set()
        with lock:
            for sock in list(active):
                try:sock.shutdown(socket.SHUT_RDWR);sock.close()
                except OSError:pass
        server.shutdown();server.server_close();thread.join(timeout=2)


@contextmanager
def connection(plan,adb,cancelled=lambda:False):
    with relay(plan,cancelled) as serial:
        connected=False
        try:
            if cancelled():raise CloudError('cancelled')
            _adb(adb,'connect',serial);connected=True
            authenticate(serial,plan.password,cancelled)
            yield serial
        finally:
            if connected:
                try:_adb(adb,'disconnect',serial)
                except CloudError:pass


def check(plan,adb,cancelled=lambda:False):
    with connection(plan,adb,cancelled):return True
