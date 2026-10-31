"""One bounded MuMu network worker. Device/photo work NEVER runs here.

The encrypted contact outbox is the durable queue, not this in-memory hint list.
Unstarted pending rows survive shutdown; attempted/unknown rows are never replayd.

v1.3.106 («на каком-то этапе скрипт молча работает и отчеты в телеграм бота
перестает присылать будто где-то копиться в буфере»): the delivery thread could
die SILENTLY while `closed` stayed False - one BaseException inside a job (a
pause-gate control-flow signal, a teardown-time error) unwound the whole work()
loop, after which enqueue()/exit_hint() kept appending jobs into a queue nobody
drained: exit notices piled up as 'queued' rows, contact hints returned
'queued', the script kept processing dialogs and Telegram stayed silent for
hours - exactly the reported «буфер». The loop now survives every job
(BaseException included, each caught per job), a dead thread is restarted by
the next enqueue under a restart lock (bounded, counted), and the queue depth
plus delivered/failed/restart counters ride backlog() into the pass report and
the monitor summary («в очереди TG N»), so a slow or stuck Telegram becomes a
VISIBLE number instead of silence. The durable row semantics never change:
'attempted-unknown' stays never-replayed, 'queued' rows still re-hint at every
pass through resume(), the 64-job in-memory cap stays.
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
        self.restart_lock=threading.Lock()
        # v1.3.106: the queue's own observable health, surfaced through
        # backlog() into the pass report and the Telegram summary line.
        self.stats=dict(delivered=0,failed=0,depth=0,deepest=0,restarts=0)
        self.thread=threading.Thread(target=self.work,daemon=True);self.thread.start()
    def ensure_running(self):
        """A dead worker is restarted before a new job is accepted.

        The restart is bounded (one live thread at a time under the restart
        lock) and counted, so a repeatedly dying delivery shows up in the
        report instead of silently swallowing notifications.
        """
        if self.closed or self.stopped.is_set():return False
        if self.thread.is_alive():return True
        with self.restart_lock:
            if self.closed or self.stopped.is_set():return False
            if self.thread.is_alive():return True
            self.stats['restarts']+=1
            self.thread=threading.Thread(target=self.work,daemon=True);self.thread.start()
            return True
    def enqueue(self,chain,who,notifier,cancelled):
        key=(str(chain.store.path),getattr(chain.store,'prefix',''),who['account'],who['peer'],who['chat'])
        with self.condition:
            if self.closed or self.stopped.is_set() or cancelled():return 'cancelled'
            if key in self.keys:return 'queued'
            if len(self.jobs)>=64:return 'queued' # durable pending row, no new attempt
            if not self.ensure_running():return 'cancelled'
            self.keys.add(key);self.jobs.append((key,'contact',chain,dict(who),notifier,cancelled));self.condition.notify()
            self.stats['depth']=len(self.jobs);self.stats['deepest']=max(self.stats['deepest'],self.stats['depth'])
        return 'queued'
    def exit_hint(self,chain,who,signature,sender,photo_sender,cancelled):
        key=('exit',str(chain.store.path),getattr(chain.store,'prefix',''),who['chat'],signature)
        with self.condition:
            if self.closed or self.stopped.is_set() or cancelled():return
            if key in self.keys or len(self.jobs)>=64:return
            if not self.ensure_running():return
            self.keys.add(key);self.jobs.append((key,signature,chain,dict(who),(sender,photo_sender),cancelled));self.condition.notify()
            self.stats['depth']=len(self.jobs);self.stats['deepest']=max(self.stats['deepest'],self.stats['depth'])

    def work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.jobs or self.closed,timeout=.25)
                if self.closed or self.stopped.is_set():return
                if not self.jobs:
                    self.stats['depth']=0
                    continue
                job=self.jobs.popleft()
                self.stats['depth']=len(self.jobs)
            key,kind,chain,who,notifier,cancelled=job
            status='unknown'
            try:
                try:
                    if kind=='contact':status=chain._notify(who,notifier,lambda:self.stopped.is_set() or cancelled())
                    else:
                        from assistant_exit_queue import deliver
                        status=deliver(chain,who,kind,notifier,lambda:self.stopped.is_set() or cancelled())
                except Exception:status='unknown' # an attempted DB row is never reset
                finally:
                    # Do not occupy a Supabase session while an auxiliary worker
                    # sleeps or exits; each MuMu port has its own worker process.
                    try:
                        from cloud_database import close_idle_connections
                        close_idle_connections()
                    except Exception:
                        pass
            except BaseException:
                # v1.3.106: control-flow signals (pause gates, teardown) and any
                # other BaseException used to unwind the whole loop and leave a
                # live-looking queue that nobody drained. The durable row keeps
                # its own reservation semantics; the loop always continues.
                status='unknown'
            try:
                with self.condition:
                    # 'blocked'/'nothing-pending'/'cancelled'/'disabled' are
                    # decided outcomes, not delivery failures; only an unknown
                    # telegram/database result counts against the queue.
                    if status=='accepted':self.stats['delivered']+=1
                    elif status=='unknown':self.stats['failed']+=1
                    self.keys.discard(key)
                    if kind=='contact' and status in ('accepted','unknown','blocked'):self.results.append(status)
            except Exception:
                pass
    def drain(self):
        with self.condition:
            values=list(self.results);self.results.clear()
        return values
    def backlog(self):
        """v1.3.106: the queue's observable health for the pass report."""
        with self.condition:
            return dict(self.stats,queued=len(self.jobs),dead=(self.thread.is_alive() is False and self.closed is False))
    def close(self):
        with self.condition:self.closed=True;self.jobs.clear();self.condition.notify_all()
        self.thread.join(timeout=1)

@contextmanager
def running(stopped):
    dispatcher=Dispatcher(stopped);token=_current.set(dispatcher)
    try:yield dispatcher
    finally:dispatcher.close();_current.reset(token)
