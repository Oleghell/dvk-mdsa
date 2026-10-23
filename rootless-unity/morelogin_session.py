"""Worker-scoped Gadget connection and forward; never cache screens or sessions.

Fresh process enumeration, attach, script, runtime/identity/boot guards remain
per operation. Only one operation may lease the exact loopback forward at once.
Connection loss stops; it never reconnects or repeats an action automatically.
"""
from contextlib import contextmanager
import os,time
from morelogin_common import CloudError

_installed=False

class Lease:
    def __init__(self,serial,original,metrics,cancelled):
        self.serial,self.original,self.metrics,self.cancelled=serial,original,metrics,cancelled
        self.adb=None;self.port=None;self.owner=None;self.device=None
        self.address=None;self.token=None;self.manager=None;self.remote_active=False;self.poisoned=False
    def measure(self,kind,fn):
        start=time.monotonic();failed=True
        try:value=fn();failed=False;return value
        finally:self.metrics.record(kind,time.monotonic()-start,failed)
    def check(self):
        from test_device import TestError
        if self.cancelled():raise TestError('Операция остановлена.')
        if self.poisoned:raise TestError('Предыдущее подключение не завершено. Автоповтора нет.')
    def run(self,adb,args,timeout=30):
        from test_device import TestError
        adb.validate(args)
        if args==['-s',self.serial,'forward','tcp:0','tcp:27042']:
            self.check()
            if self.owner is not None:raise TestError('Транспорт уже занят.')
            if self.adb is not None and (adb.executable!=self.adb.executable or adb.folder!=self.adb.folder):
                raise TestError('Конфигурация транспорта изменилась.')
            if self.port is None:
                value=self.measure('forward_open',lambda:self.original(adb,args,timeout=timeout))
                if not value.isdecimal() or not 1024<=int(value)<=65535:raise TestError('Некорректный forward.')
                self.port=int(value);self.adb=adb
                self.address='127.0.0.1:'+value
            self.owner=adb
            self.metrics.record('forward_lease',0,False)
            return str(self.port)
        if self.port is not None and args==['-s',self.serial,'forward','--remove','tcp:'+str(self.port)]:
            if self.owner is not adb or self.remote_active:raise TestError('Транспорт не освобождён.')
            self.owner=None
            return ''
        return self.original(adb,args,timeout=timeout)
    def add_remote_device(self,address,*,token):
        from test_device import TestError
        self.check()
        if self.owner is None or address!=self.address or self.remote_active:raise TestError('Неверная привязка Gadget.')
        if self.token is not None and token!=self.token:raise TestError('Ключ Gadget изменился.')
        if self.device is None:
            self.token=token
            self.device=self.measure('gadget_connect',lambda:self.manager.add_remote_device(address,token=token))
        if self.device.is_lost is not False:raise TestError('Соединение Gadget потеряно. Автоповтора нет.')
        self.remote_active=True
        return Device(self,self.device)
    def remove_remote_device(self,address):
        from test_device import TestError
        if address!=self.address or not self.remote_active:raise TestError('Неверная привязка Gadget.')
        self.remote_active=False
    def close(self):
        # Runs outside the operation's cancelled Frida guard, with a bounded guard.
        if self.manager is not None and self.token is not None:
            try:self.measure('gadget_cleanup',lambda:self.manager.remove_remote_device(self.address))
            except Exception:pass
        if self.port is not None:
            self.adb.forward_port=self.port
            self.measure('forward_close',lambda:self.original(self.adb,['-s',self.serial,'forward','--remove','tcp:'+str(self.port)],timeout=10))
        self.device=self.token=self.owner=None

class Device:
    def __init__(self,lease,device):self.lease,self.device=lease,device
    def enumerate_processes(self):return self.lease.measure('gadget_enumerate',self.device.enumerate_processes)
    def attach(self,pid):
        session=self.lease.measure('gadget_attach',lambda:self.device.attach(pid))
        return Session(self.lease,session)

class Session:
    def __init__(self,lease,session):self.lease,self.session=lease,session
    def create_script(self,*args,**kwargs):
        script=self.lease.measure('script_create',lambda:self.session.create_script(*args,**kwargs))
        return Script(self.lease,script)
    def detach(self):
        try:return self.lease.measure('gadget_detach',self.session.detach)
        except Exception:self.lease.poisoned=True;raise

class Script:
    def __init__(self,lease,script):self.lease,self.script=lease,script
    def load(self):return self.lease.measure('script_load',self.script.load)
    def unload(self):
        try:return self.lease.measure('script_unload',self.script.unload)
        except Exception:self.lease.poisoned=True;raise
    @property
    def exports_sync(self):return Rpc(self.lease,self.script.exports_sync)

class Rpc:
    def __init__(self,lease,exports):self.lease,self.exports=lease,exports
    def __getattr__(self,name):
        method=getattr(self.exports,name)
        def call(*args,**kwargs):return self.lease.measure('gadget_rpc',lambda:method(*args,**kwargs))
        return call

@contextmanager
def transport(serial,cancelled,metrics,*,frida_api=None):
    global _installed
    from test_device import TARGET
    from target_only import TargetOnlyAdb
    if os.environ.get('DVK_MORELOGIN')!='1' or serial!=TARGET or _installed:raise CloudError('configuration')
    if frida_api is None:import frida as frida_api
    import threading
    had_local='run' in TargetOnlyAdb.__dict__;original=TargetOnlyAdb.run
    get_manager=frida_api.get_device_manager
    lease=Lease(serial,original,metrics,cancelled)
    def manager():
        if lease.manager is None:lease.manager=get_manager()
        return lease
    TargetOnlyAdb.run=lambda adb,args,timeout=30:lease.run(adb,args,timeout)
    frida_api.get_device_manager=manager;_installed=True
    try:yield lease
    finally:
        try:
            guard=frida_api.Cancellable();timer=threading.Timer(5,guard.cancel);timer.daemon=True;timer.start()
            try:
                with guard:lease.close()
            finally:timer.cancel()
        finally:
            if had_local:TargetOnlyAdb.run=original
            else:delattr(TargetOnlyAdb,'run')
            frida_api.get_device_manager=get_manager;_installed=False
