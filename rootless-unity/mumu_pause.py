"""One-port cooperative pause. Never suspend a native call or release journals."""
import queue
import threading

class PortControl:
    """GUI/controller state. A request is not confirmation of an actual pause."""
    def __init__(self):
        self.commands=queue.Queue();self.lock=threading.Lock()
        self.desired=False;self.actual=False;self.finished=False

    def request(self,paused):
        if type(paused) is not bool:raise ValueError('Invalid pause request')
        with self.lock:
            if self.finished or self.desired==paused:return False
            self.desired=paused;self.commands.put('pause' if paused else 'resume');return True

    def observe(self,state):
        if state not in ('pause-requested','resume-requested','paused','resumed'):
            raise ValueError('Invalid pause state')
        with self.lock:
            if state=='paused':self.actual=True
            elif state=='resumed':self.actual=False

    def finish(self):
        with self.lock:self.finished=True

    def state(self):
        with self.lock:
            if self.finished:return 'finished'
            if self.desired:return 'paused' if self.actual else 'pause-requested'
            return 'resume-requested' if self.actual else 'running'


class PauseGate:
    """Event-compatible cancellation plus explicit safe-boundary checkpoints."""
    def __init__(self,stopped,notify=lambda state:None):
        self.stopped=stopped;self.notify=notify;self.condition=threading.Condition()
        self.requested=False;self.paused=False;self.restart_on_resume=False

    def command(self,name):
        if name not in ('pause','resume'):raise ValueError('Invalid worker command')
        with self.condition:
            self.requested=name=='pause'
            self.notify('pause-requested' if self.requested else 'resume-requested' if self.paused else 'resumed')
            self.condition.notify_all()

    def pause_checkpoint(self):
        with self.condition:
            if not self.requested or self.is_set():return
            self.paused=True;self.notify('paused')
            try:
                while self.requested and not self.is_set():self.condition.wait(.1)
            finally:
                self.paused=False
            if not self.is_set():
                self.notify('resumed')
                return True

    def is_set(self):return self.stopped.is_set()
    def set(self):
        self.stopped.set()
        with self.condition:self.condition.notify_all()
    def clear(self):return self.stopped.clear()
    def wait(self,timeout=None):return self.stopped.wait(timeout)
