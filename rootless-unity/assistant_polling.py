"""Only the idle host interval adapts. No extra device/threaded navigation."""
from random import uniform

# Reports aPYyN7weMm (v1.3.78, «равномерно всё шло и не глючило»): a fleet of
# MuMu workers sharing one database pooler and one AI backend poll their
# inboxes on the SAME fixed interval, so after a shared slowdown their passes
# finish together and the next poll lands as one synchronized wave against
# exactly those shared resources. The COLD (idle) wait is therefore jittered
# upward by a bounded factor; the HOT drain interval stays exact so active
# conversations keep their fast rechecks. Non-adaptive callers (single-port
# and test flows) keep the plain configured interval.
IDLE_JITTER_RANGE = (1.0, 1.6)

def idle_jitter(seconds):
    return seconds * uniform(*IDLE_JITTER_RANGE)

class Schedule:
    def __init__(self,clock,jitter=idle_jitter):
        self.clock=clock;self.hot_until=0;self.jitter=jitter
    def record(self,result):
        if any(result.get(k,0)>0 for k in ('dialogs_processed','new_incoming_messages','submission_calls')):
            self.hot_until=self.clock()+30
    def delay(self,configured):
        if self.clock()<self.hot_until:return min(configured,2)
        return self.jitter(configured)
