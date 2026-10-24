"""Cooperative safe boundaries; resume is control flow, not a native error."""
class PortResumed(BaseException):
    """Unwind cached pass state only; never interrupts a native operation."""


def boundary(stopped, *, restart=True):
    check=getattr(stopped,'pause_checkpoint',None)
    if callable(check):
        resumed=check()
        if resumed and restart and getattr(stopped,'restart_on_resume',False):
            raise PortResumed()
