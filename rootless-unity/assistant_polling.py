"""Only the idle host interval adapts. No extra device/threaded navigation."""
class Schedule:
    def __init__(self,clock):self.clock=clock;self.hot_until=0
    def record(self,result):
        if any(result.get(k,0)>0 for k in ('dialogs_processed','new_incoming_messages','submission_calls')):
            self.hot_until=self.clock()+30
    def delay(self,configured):return min(configured,2) if self.clock()<self.hot_until else configured
