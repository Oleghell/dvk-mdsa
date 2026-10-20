"""Synthetic scheduler checks. No device, account, messages or network."""
import ast
from pathlib import Path
import unittest
from one_chat_monitor import ReadLoop

class Scheduler:
    def __init__(self):
        self.callbacks={}; self.index=0; self.delays=[]
    def later(self,ms,fn):
        self.index+=1; self.callbacks[self.index]=fn; self.delays.append(ms); return self.index
    def cancel(self,key):
        self.callbacks.pop(key,None)
    def tick(self):
        key=next(iter(self.callbacks)); self.callbacks.pop(key)()

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.scheduler=Scheduler(); self.reads=0
        def read():self.reads+=1;return True
        self.loop=ReadLoop(self.scheduler.later,self.scheduler.cancel,read)
    def test_idle_by_default_and_serial_reads_only_after_completion(self):
        self.assertFalse(self.loop.active);self.assertFalse(self.scheduler.callbacks)
        self.assertTrue(self.loop.start());self.assertEqual(self.reads,1)
        self.assertFalse(self.loop.start());self.assertFalse(self.scheduler.callbacks)
        self.loop.complete(True);self.assertEqual(self.scheduler.delays,[5000])
        self.scheduler.tick();self.assertEqual(self.reads,2);self.assertTrue(self.loop.in_flight)
        self.assertFalse(self.scheduler.callbacks)
    def test_stop_pending_and_stale_callback(self):
        self.loop.start();self.loop.complete(True)
        stale=next(iter(self.scheduler.callbacks.values()))
        self.loop.stop();self.assertFalse(self.scheduler.callbacks)
        self.loop.start();stale();self.assertEqual(self.reads,2)
    def test_stop_inflight_waits_for_completion_and_does_not_restart(self):
        self.loop.start();self.loop.stop()
        self.assertFalse(self.loop.start())
        self.loop.complete(True);self.assertFalse(self.scheduler.callbacks)
        self.assertTrue(self.loop.start());self.assertEqual(self.reads,2)
    def test_error_stops_without_retry(self):
        self.loop.start();self.loop.complete(False)
        self.assertFalse(self.loop.active);self.assertFalse(self.scheduler.callbacks)
    def test_duplicate_completion_does_not_schedule_twice(self):
        self.loop.start();self.loop.complete(True);self.loop.complete(True)
        self.assertEqual(len(self.scheduler.callbacks),1)
    def test_rejected_or_raising_read_stops(self):
        self.loop.read=lambda:False
        self.assertFalse(self.loop.start());self.assertFalse(self.loop.active)
        def fail():raise RuntimeError('synthetic')
        self.loop.read=fail
        with self.assertRaises(RuntimeError):self.loop.start()
        self.assertFalse(self.loop.active);self.assertFalse(self.loop.in_flight)
    def test_minimum_interval(self):
        for interval in (0,True,100,4999):
            with self.assertRaises(ValueError):ReadLoop(None,None,None,interval)
    def test_no_io_sender_navigation_or_contact_modules(self):
        p=Path(__file__).parents[1]/'one_chat_monitor.py'
        tree=ast.parse(p.read_text());self.assertFalse(any(isinstance(n,(ast.Import,ast.ImportFrom)) for n in ast.walk(tree)))
        source=(p.parent/'diagnose_one_chat.py').read_text()
        self.assertIn("monitor=ReadLoop(root.after,root.after_cancel,lambda:begin('read'))",source)
        self.assertIn("if busy or (monitor.active and kind!='read'):return False",source)
        self.assertIn('monitor.complete(success)',source)
        self.assertIn('monitor.stop()',source)

if __name__=='__main__':unittest.main()
