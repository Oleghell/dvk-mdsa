"""Worker-local read-only ADB smart socket; no cache, sends, installs or retries.

The existing exact TargetOnlyAdb allowlist runs before routing. Only four fixed
read commands skip adb.exe startup. CLI connect/forward lifecycle is unchanged.
Shell v2 preserves stdout/stderr separation and requires an explicit zero exit.
"""
from contextlib import contextmanager
import math
import os
import socket
import struct
import threading
import time
from mumu_common import MumuError, port

_installed=False

class Timings:
    def __init__(self):
        self.lock=threading.Lock()
        self.values={k:dict(calls=0,failures=0,total_ms=0,max_ms=0) for k in ('socket_read','cli')}
    def record(self,kind,elapsed,failed):
        milliseconds=max(0,round(elapsed*1000))
        with self.lock:
            v=self.values[kind];v['calls']+=1;v['failures']+=int(failed)
            v['total_ms']+=milliseconds;v['max_ms']=max(v['max_ms'],milliseconds)
    def snapshot(self):
        with self.lock:return dict(schema=1,read_cache=False,automatic_retry=False,
            **{k:dict(v) for k,v in self.values.items()})

class ReadFailure(Exception):
    pass


def read(serial,command,cancelled,timeout=30,*,socket_factory=None):
    from test_device import PACKAGE,BOOT_ID
    if type(serial) is not str or serial != '127.0.0.1:'+str(port(serial.removeprefix('127.0.0.1:'))):
        raise ReadFailure('not-allowed')
    shells={('shell','cat',BOOT_ID):'cat '+BOOT_ID,
            ('shell','getprop','sys.boot_completed'):'getprop sys.boot_completed',
            ('shell','pm','list','packages',PACKAGE):'pm list packages '+PACKAGE}
    command=tuple(command)
    if command!=('get-state',) and command not in shells:raise ReadFailure('not-allowed')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=120:raise ReadFailure('timeout')
    deadline=time.monotonic()+timeout
    def check():
        if cancelled():raise ReadFailure('cancelled')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ReadFailure('timeout')
        return remaining
    check()
    try:
        with (socket_factory or socket.create_connection)(('127.0.0.1',5037),timeout=min(5,check())) as sock:
            sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            def exact(size):
                out=bytearray()
                while len(out)<size:
                    sock.settimeout(min(.25,check()))
                    try:block=sock.recv(size-len(out))
                    except socket.timeout:continue
                    if not block:raise ReadFailure('truncated')
                    out.extend(block)
                return bytes(out)
            def service(value):
                data=value.encode('ascii')
                if len(data)>1024:raise ReadFailure('not-allowed')
                sock.settimeout(min(5,check()))
                sock.sendall(('%04x'%len(data)).encode('ascii')+data)
                if exact(4)!=b'OKAY':raise ReadFailure('service-failed')
            if command==('get-state',):
                service('host-serial:'+serial+':get-state')
                header=exact(4)
                if any(c not in b'0123456789abcdefABCDEF' for c in header):raise ReadFailure('format')
                size=int(header,16)
                if not 0<size<=32:raise ReadFailure('format')
                result=exact(size).decode('ascii').strip();check();return result
            service('host:transport:'+serial)
            service('shell,v2,raw:'+shells[command])
            output=bytearray();total=0
            for _ in range(4096):
                header=exact(5);kind=header[0];size=struct.unpack('<I',header[1:])[0]
                if kind not in (1,2,3) or size>65536 or (kind==3 and size!=1):raise ReadFailure('format')
                total+=size
                if total>65536:raise ReadFailure('oversized')
                data=exact(size)
                if kind==3:
                    if data!=b'\0':raise ReadFailure('command-failed')
                    check();return output.decode('utf-8',errors='replace').strip()
                if kind==2 and data:raise ReadFailure('command-failed')
                if kind==1:output.extend(data)
            raise ReadFailure('format')
    except ReadFailure:raise
    except Exception:raise ReadFailure('transport-failed') from None


@contextmanager
def transport(serial,cancelled=lambda:False,*,socket_factory=None):
    """Install only in the selected MuMu worker; always restore on exit."""
    global _installed
    from test_device import TARGET,PACKAGE,BOOT_ID,TestError
    from target_only import TargetOnlyAdb
    if os.environ.get('DVK_MUMU_MULTI')!='1' or TARGET!=serial or _installed:
        raise MumuError('configuration')
    if type(serial) is not str or serial != '127.0.0.1:'+str(port(serial.removeprefix('127.0.0.1:'))):
        raise MumuError('configuration')
    had_local='run' in TargetOnlyAdb.__dict__;original=TargetOnlyAdb.run
    timings=Timings();_installed=True
    allowed={('get-state',),('shell','cat',BOOT_ID),('shell','getprop','sys.boot_completed'),
             ('shell','pm','list','packages',PACKAGE)}
    def run(adb,args,timeout=30):
        adb.validate(args)
        if cancelled():raise TestError('Операция остановлена.')
        fast=(args[:2]==['-s',serial] and tuple(args[2:]) in allowed)
        started=time.monotonic();failed=True
        try:
            if not fast:
                result=original(adb,args,timeout=timeout);failed=False;return result
            try:result=read(serial,args[2:],cancelled,timeout,socket_factory=socket_factory)
            except ReadFailure as error:
                outcome='timeout' if str(error)=='timeout' else 'oversized-output' if str(error)=='oversized' else 'completed'
                adb.observe_result(args,None,'',outcome)
                raise TestError('Не удалось выполнить проверку выбранного MuMu через ADB. Автоповтора нет.') from None
            adb.observe_result(args,0,result);failed=False;return result
        finally:timings.record('socket_read' if fast else 'cli',time.monotonic()-started,failed)
    TargetOnlyAdb.run=run
    try:yield timings
    finally:
        if had_local:TargetOnlyAdb.run=original
        else:delattr(TargetOnlyAdb,'run')
        _installed=False
