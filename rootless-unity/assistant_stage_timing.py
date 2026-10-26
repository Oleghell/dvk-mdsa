"""Local stage counters/durations only. No identity, bodies, keys or caches."""
from time import perf_counter
from contextlib import contextmanager
from contextvars import ContextVar

READ_PHASES = {
    'read_setup': 'Читаю историю • проверяю подключение MuMu.',
    'read_connect': 'Читаю историю • подключаюсь к приложению.',
    'read_script': 'Читаю историю • подготавливаю проверку.',
    'read_snapshot': 'Читаю историю • сверяю полную историю текущего чата.',
    'read_cleanup': 'Читаю историю • завершаю проверку подключения.',
}
_read_context = ContextVar('dvk_read_timing_context', default=None)

STAGES = frozenset({'read','bind','proposal','pacing','submit','notify','media','open','back','exit_photo'}) | frozenset(READ_PHASES)
FIELDS = frozenset(stage + suffix for stage in STAGES for suffix in ('_calls','_ms'))


def timed(diagnostics, stage, operation, *args, **kwargs):
    if stage not in STAGES:
        raise ValueError('Invalid timing stage')
    started = perf_counter()
    diagnostics[stage + '_calls'] = diagnostics.get(stage + '_calls', 0) + 1
    try:
        return operation(*args, **kwargs)
    finally:
        elapsed = max(0, round((perf_counter() - started) * 1000))
        diagnostics[stage + '_ms'] = diagnostics.get(stage + '_ms', 0) + elapsed


@contextmanager
def collect_read_timings(diagnostics, progress):
    """Task-local numeric telemetry only; never store snapshots/IDs/credentials."""
    token = _read_context.set((diagnostics, progress))
    try:
        yield
    finally:
        _read_context.reset(token)


@contextmanager
def read_phase(stage):
    if stage not in READ_PHASES:
        raise ValueError('Invalid read phase')
    context = _read_context.get()
    if context is None:
        yield
        return
    diagnostics, progress = context
    started = perf_counter()
    diagnostics[stage + '_calls'] = diagnostics.get(stage + '_calls', 0) + 1
    try:
        # Advisory UI telemetry must never prevent mandatory connection cleanup.
        try:
            progress(READ_PHASES[stage])
        except Exception:
            pass
        yield
    finally:
        elapsed = max(0, round((perf_counter() - started) * 1000))
        diagnostics[stage + '_ms'] = diagnostics.get(stage + '_ms', 0) + elapsed
