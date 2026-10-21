"""Run-scoped permission created only after the explicit Start confirmation."""
class RunAuthorization:
    automatic_send = True
    def __init__(self, stopped):
        self.stopped = stopped
    def __call__(self, kind, text, cancelled):
        return (kind in {'greeting', 'question', 'contact'} and isinstance(text, str)
                and bool(text.strip()) and not self.stopped.is_set() and not cancelled())


def flags(approve):
    automatic = getattr(approve, 'automatic_send', False) is True
    return dict(per_message_confirmation=not automatic, automatic_send=automatic)
