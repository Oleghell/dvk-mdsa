"""One bounded MuMu network worker. Device/photo work NEVER runs here.

The encrypted contact outbox is the durable queue, not this in-memory hint list.
Unstarted pending rows survive shutdown; attempted/unknown rows are never replayed.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from collections import deque
import threading
_current=ContextVar('contact_notification_queue',default=None)

def current():return _current.get()

class Dispatcher:
    def __init__(self,stopped):
        self.stopped=stopped;self.condition=threading.Condition();self.jobs=deque();self.keys=set();self.results=deque();self.closed=False
        self.thread=threading.Thread(target=self.work,daemon=True);self.thread.start()
    def enqueue(self,chain,who,notifier,cancelled):
        key=(str(chain.store.path),getattr(chain.store,'prefix',''),who['account'],who['peer'],who['chat'])
        with self.condition:
            if self.closed or self.stopped.is_set() or cancelled():return 'cancelled'
            if key in self.keys:return 'queued'
            if len(self.jobs)>=64:return 'queued' # durable pending row, no new attempt
            self.keys.add(key);self.jobs.append((key,'contact',chain,dict(who),notifier,cancelled));self.condition.notify()
        return 'queued'
    def exit_hint(self,chain,who,signature,sender,photo_sender,cancelled):
        key=('exit',str(chain.store.path),getattr(chain.store,'prefix',''),who['chat'],signature)
        with self.condition:
            if self.closed or self.stopped.is_set() or cancelled():return
            if key in self.keys or len(self.jobs)>=64:return
            self.keys.add(key);self.jobs.append((key,signature,chain,dict(who),(sender,photo_sender),cancelled));self.condition.notify()

    def work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.jobs or self.closed,timeout=.25)
                if self.closed or self.stopped.is_set():return
                if not self.jobs:continue
                key,kind,chain,who,notifier,cancelled=self.jobs.popleft()
            try:
                if kind=='contact':status=chain._notify(who,notifier,lambda:self.stopped.is_set() or cancelled())
                else:
                    from assistant_exit_queue import deliver
                    status=deliver(chain,who,kind,notifier,lambda:self.stopped.is_set() or cancelled())
            except Exception:status='unknown' # an attempted DB row is never reset
            finally:
                # Do not occupy a Supabase session while an auxiliary worker
                # sleeps or exits; each MuMu port has its own worker process.
                from cloud_database import close_idle_connections
                close_idle_connections()
            with self.condition:
                self.keys.discard(key)
                if kind=='contact' and status in ('accepted','unknown','blocked'):self.results.append(status)
    def drain(self):
        with self.condition:
            values=list(self.results);self.results.clear()
        return values
    def close(self):
        with self.condition:self.closed=True;self.jobs.clear();self.condition.notify_all()
        self.thread.join(timeout=1)

@contextmanager
def running(stopped):
    dispatcher=Dispatcher(stopped);token=_current.set(dispatcher)
    try:yield dispatcher
    finally:dispatcher.close();_current.reset(token)
