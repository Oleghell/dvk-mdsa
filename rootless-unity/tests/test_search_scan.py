import unittest
import chat_batch as p
from test_chat_batch import cycle
class Scan(unittest.TestCase):
    def test_absolute_cycle_timer_not_reset_or_unbounded(self):
        self.assertEqual(p.CYCLE_TIMEOUT_MS,30000)
        self.assertIn("finish('callback-timeout');},30000);",p.FUNCTION)
        self.assertNotIn("finish('callback-timeout');},16000);",p.FUNCTION)
        self.assertIn('n.managed_calls>=6000',p.FUNCTION)
        self.assertIn('r.navigation.frames>=180',p.FUNCTION)
        self.assertIn("if(n.phase==='wait-chat'||n.phase==='wait-chat-back')state.nextActionAt=Date.now()+1000;",p.FUNCTION)
        for value in (True,0,16000,30001):
            r=cycle();r['navigation']['cycle_timeout_ms']=value
            with self.assertRaises(ValueError):p.validate(r)

    def test_hard_budget_and_action_retries_not_relaxed(self):
        s=p.FUNCTION
        for text in ('deadline=Date.now()+100','scanCellBusy','state.scanCell++','state.scan_yields'):
            if text!='state.scan_yields':self.assertIn(text,s)
        self.assertIn("n.phase==='search'&&!n.open_attempted&&state.targetUser.isNull()&&state.origin.isNull()&&n.scan_yields<8",s)
        self.assertIn("state.nextActionAt=Date.now()+1000;return;",s)
        self.assertNotIn('deadline=Date.now()+500',s)
    def test_counter_schema_closed(self):
        for key,value in [('scan_yields',9),('scan_yields',True),('scan_slices',181),('scan_slices',-1)]:
            r=cycle();r['navigation'][key]=value
            with self.assertRaises(ValueError):p.validate(r)
    def test_no_objects_or_pointers_in_scan_cursors(self):
        self.assertIn('scanCell:0,scanPassActive:false,scanRowCounted:false,scanCellCounted:false,scanRowPending:false,scanCellBusy:false',p.FUNCTION)
        self.assertIn('cellOrdinal++<state.scanCell',p.FUNCTION)
