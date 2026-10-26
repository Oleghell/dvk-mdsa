"""A MuMu generation deadline, never a send retry or a new key/quota permit.

Only HTTP is isolated. Late bytes are discarded; background code cannot parse a
reply, write a journal or send a message. At most two unfinished HTTP calls may
exist in this process, even with a server that never finishes its response.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from time import monotonic
import threading
import io
import urllib.error

_current=ContextVar('ai_generation_budget',default=None)
_slots=threading.BoundedSemaphore(2)
class Budget:
    def __init__(self,seconds=12,attempts=3,clock=monotonic):
        self.clock=clock;self.deadline=clock()+seconds;self.remaining_attempts=attempts
    def exhausted(self):return self.clock()>=self.deadline or self.remaining_attempts<=0
    def claim(self):
        if self.exhausted():raise TimeoutError()
        self.remaining_attempts-=1
        return max(.01,min(6,self.deadline-self.clock()))

@contextmanager
def generation(seconds=12,attempts=3):
    token=_current.set(Budget(seconds,attempts))
    try:yield
    finally:_current.reset(token)

def exhausted():
    value=_current.get();return value is not None and value.exhausted()

def request(client,request,timeout,cancelled):
    value=_current.get()
    def call(limit):
        with client.open(request,timeout=limit) as response:return response.read(32769)
    if value is None:return call(timeout)
    limit=min(timeout,value.claim());deadline=min(value.deadline,value.clock()+limit)
    if not _slots.acquire(blocking=False):raise TimeoutError()
    done=threading.Event();abandoned=threading.Event();result=[]
    def worker():
        try:
            raw=call(limit)
            if not abandoned.is_set():result.append((True,raw))
        except Exception as error:
            if isinstance(error,urllib.error.HTTPError):
                # Error bodies can also trickle forever. Read them under the
                # SAME deadline; provider classification only sees memory.
                try:body=error.read(4097)
                except Exception:body=b''
                finally:error.close()
                error=urllib.error.HTTPError(error.url,error.code,error.msg,error.headers,io.BytesIO(body))
            if not abandoned.is_set():result.append((False,error))
        finally:done.set();_slots.release()
    try:threading.Thread(target=worker,daemon=True).start()
    except Exception:
        _slots.release();raise
    try:
        while True:
            if cancelled():
                from groq_reply import GroqError
                raise GroqError('groq-cancelled')
            remaining=deadline-value.clock()
            if remaining<=0:raise TimeoutError()
            if done.wait(min(.05,remaining)):
                if value.clock()>deadline:raise TimeoutError()
                ok,data=result[0]
                if not ok:raise data
                return data
    finally:abandoned.set()
