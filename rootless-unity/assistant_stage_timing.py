"""Local stage counters/durations only. No identity, bodies, keys or caches."""
from time import perf_counter

STAGES = frozenset({'read','bind','proposal','pacing','submit','notify','media','open','back','exit_photo'})
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
