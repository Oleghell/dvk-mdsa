"""One host-side deadline covers all retries of a read-only chat capture."""
from contextvars import ContextVar
from contextlib import contextmanager
from time import monotonic
_deadline=ContextVar('chat_read_deadline',default=None)
@contextmanager
def limit(seconds):
    old=_deadline.get();end=monotonic()+max(.01,seconds)
    token=_deadline.set(min(old,end) if old is not None else end)
    try:yield
    finally:_deadline.reset(token)
def remaining(default=25):
    end=_deadline.get()
    return default if end is None else max(.01,min(default,end-monotonic()))
