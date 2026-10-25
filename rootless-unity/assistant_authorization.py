"""Permission from an explicit Start click; cancellable configurable word/minute pacing."""

from math import ceil

WORDS_PER_MINUTE = 35
MIN_WORDS_PER_MINUTE = 1
MAX_WORDS_PER_MINUTE = 300

def check_words_per_minute(value):
    if type(value) is not int or not MIN_WORDS_PER_MINUTE <= value <= MAX_WORDS_PER_MINUTE:
        raise ValueError("Скорость печати: целое число от 1 до 300 слов/мин.")
    return value


class RunAuthorization:
    automatic_send = True
    def __init__(self, stopped, *, wait=None, immediate_greeting=False, progress=None, words_per_minute=WORDS_PER_MINUTE):
        if type(immediate_greeting) is not bool:raise ValueError("Invalid greeting pacing")
        self.words_per_minute = check_words_per_minute(words_per_minute)
        self.progress = progress
        self.immediate_greeting = immediate_greeting
        self.stopped = stopped
        self.wait = stopped.wait if wait is None else wait
    def __call__(self, kind, text, cancelled):
        if (kind not in {'greeting', 'question', 'contact', 'clarify', 'followup'} or not isinstance(text, str)
                or not text.strip() or self.stopped.is_set() or cancelled()):
            return False
        if kind == 'greeting' and self.immediate_greeting:
            if self.progress is not None:self.progress('Первое приветствие • без задержки печати.')
            return not self.stopped.is_set() and not cancelled()
        # Host-side delay, not a claimed native typing indicator. Never reserve a
        # send before waiting. The caller must then re-read identity/history.
        remaining = len(text.split()) * 60 / self.words_per_minute
        reported = None
        while remaining > 1e-9:
            seconds = ceil(remaining - 1e-9)
            if self.progress is not None and seconds != reported:
                self.progress(f'Печатаю ответ • осталось около {seconds} с')
                reported = seconds
            step = min(0.25, remaining)
            if self.wait(step) or self.stopped.is_set() or cancelled():
                return False
            remaining -= step
        return not self.stopped.is_set() and not cancelled()


def flags(approve):
    automatic = getattr(approve, 'automatic_send', False) is True
    return dict(per_message_confirmation=not automatic, automatic_send=automatic)
