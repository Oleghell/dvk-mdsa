"""Opt-in serial read scheduling for one bound chat. No send or navigation."""

class ReadLoop:
    def __init__(self, later, cancel, read, interval_ms=5000):
        if type(interval_ms) is not int or interval_ms < 5000:
            raise ValueError('Read interval must be at least five seconds')
        self.later, self.cancel, self.read = later, cancel, read
        self.interval_ms = interval_ms
        self.active = False
        self.pending = None
        self.in_flight = False
        self.generation = 0

    def start(self):
        if self.active or self.in_flight:
            return False
        self.active = True
        self.generation += 1
        return self._read()

    def _read(self):
        if not self.active or self.in_flight:
            return False
        self.pending = None
        self.in_flight = True
        try:
            accepted = self.read()
        except Exception:
            self.in_flight = False
            self.stop()
            raise
        if not accepted:
            self.in_flight = False
            self.stop()
        return bool(accepted)

    def complete(self, success):
        if not self.in_flight:
            return
        self.in_flight = False
        if not success:
            self.stop()
        if not self.active:
            return
        generation = self.generation
        def tick():
            if self.active and self.generation == generation:
                self._read()
        self.pending = self.later(self.interval_ms, tick)

    def stop(self):
        self.active = False
        self.generation += 1
        if self.pending is not None:
            self.cancel(self.pending)
            self.pending = None
