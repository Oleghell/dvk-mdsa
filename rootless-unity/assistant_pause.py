"""Cooperative task boundary; ordinary cancellation events are unchanged."""
def boundary(stopped):
    check=getattr(stopped,'pause_checkpoint',None)
    if callable(check):check()
