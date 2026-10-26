"""Numeric, task-local hot-path telemetry; never export SQL, text or identity."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
import threading

_context=ContextVar('assistant_runtime',default=None)
LABELS={'db_connect':'Подключение к базе','db_read':'Читаю журнал','db_write':'Сохраняю журнал',
        'db_lock':'Ожидаю доступ к общей базе','db_commit':'Подтверждаю запись в базу',
        'ai':'Ожидаю ответ ИИ','ai_http':'Ожидаю сервис ИИ'}

@contextmanager
def collect(diagnostics,progress):
    value=dict(diagnostics=diagnostics,progress=progress,active=None)
    token=_context.set(value);done=threading.Event()
    def watch():
        while not done.wait(1):
            active=value['active']
            if active:
                stage,started=active
                try:progress(LABELS.get(stage,stage)+f' • {int(perf_counter()-started)} с')
                except Exception:pass
    thread=threading.Thread(target=watch,daemon=True);thread.start()
    try:yield
    finally:
        done.set();thread.join(timeout=.2);_context.reset(token)

@contextmanager
def phase(stage):
    if stage not in LABELS:raise ValueError('Invalid runtime phase')
    value=_context.get()
    if value is None:
        yield;return
    started=perf_counter();previous=value['active'];value['active']=(stage,started)
    metrics=value['diagnostics'];metrics[stage+'_calls']=metrics.get(stage+'_calls',0)+1
    try:yield
    finally:
        metrics[stage+'_ms']=metrics.get(stage+'_ms',0)+max(0,round((perf_counter()-started)*1000))
        value['active']=previous
