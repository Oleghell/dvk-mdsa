"""Per-port pause: actual worker pipe protocol, synthetic work, no Android."""
from dataclasses import asdict
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock,patch
from assistant_pause import boundary
from assistant_settings import Settings
from assistant_store import Store
from mumu_pause import PortControl,PauseGate
from mumu_controller import run_many,run_one


class Gate(unittest.TestCase):
    def test_request_waits_for_safe_boundary_not_the_current_operation(self):
        events=[];paused=threading.Event()
        def notify(state):
            events.append(state)
            if state=='paused':paused.set()
        gate=PauseGate(threading.Event(),notify);gate.command('pause')
        self.assertFalse(gate.is_set());self.assertNotIn('paused',events)
        finished=threading.Event();thread=threading.Thread(target=lambda:(boundary(gate),finished.set()))
        thread.start()
        try:
            self.assertTrue(paused.wait(2));self.assertFalse(finished.is_set())
            gate.command('resume');self.assertTrue(finished.wait(2));self.assertFalse(gate.is_set())
            self.assertEqual(events,['pause-requested','paused','resume-requested','resumed'])
        finally:gate.set();thread.join(3)

    def test_stop_wakes_a_paused_worker_without_resuming_or_clearing_journals(self):
        paused=threading.Event();states=[]
        gate=PauseGate(threading.Event(),lambda state:(states.append(state),paused.set() if state=='paused' else None))
        gate.command('pause');thread=threading.Thread(target=gate.pause_checkpoint);thread.start()
        try:
            self.assertTrue(paused.wait(2));gate.set();thread.join(2)
            self.assertFalse(thread.is_alive());self.assertNotIn('resumed',states)
        finally:gate.set();thread.join(2)
        self.assertTrue(gate.is_set())

    def test_plain_events_remain_noop_and_rapid_commands_do_not_fake_ack(self):
        event=threading.Event();boundary(event);self.assertFalse(event.is_set())
        control=PortControl();self.assertTrue(control.request(True));self.assertFalse(control.request(True))
        self.assertEqual(control.state(),'pause-requested');control.request(False)
        control.observe('paused');self.assertEqual(control.state(),'resume-requested')
        control.observe('resumed');self.assertEqual(control.state(),'running')
        control.finish();self.assertFalse(control.request(True));self.assertEqual(control.state(),'finished')
        with self.assertRaises(ValueError):control.observe('unexpected')
        with self.assertRaises(ValueError):control.request(1)

    def test_profile_boundary_is_after_completed_cycle_and_before_next(self):
        import assistant_profiles as profiles
        from test_inbox_profiles import Config,cycle_result
        paused=threading.Event();gate=PauseGate(threading.Event(),lambda s:paused.set() if s=='paused' else None)
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'db',Path(directory)/'legacy');profiles.Session(store).set('city','Псков')
            def cycle(*a,**kw):
                if native.call_count==1:gate.command('pause')
                return cycle_result(send_attempted=True,send_handler_returned=True)
            native=MagicMock(side_effect=cycle);result=[]
            thread=threading.Thread(target=lambda:result.append(profiles.walk(Settings(),gate,MagicMock(),lambda _:None,store,cycle=native,config=Config(),limit=2)))
            thread.start()
            try:
                self.assertTrue(paused.wait(2));self.assertEqual(native.call_count,1)
                gate.command('resume');thread.join(3);self.assertFalse(thread.is_alive())
                self.assertEqual(native.call_count,2);self.assertEqual(result[0]['status'],'profiles-completed')
            finally:gate.set();thread.join(3)


SCRIPT=r'''
import sys,time
import mumu_worker,assistant_monitor
assistant_monitor.summary=lambda value:'fixture-finished'
def fake(spec,stopped,progress):
    progress('fixture-current-task')
    time.sleep(.6)
    from assistant_pause import boundary
    boundary(stopped)
    if not stopped.is_set():progress('fixture-next-task')
    return {'status':'cancelled' if stopped.is_set() else 'completed'}
mumu_worker.run=fake
sys.argv=['mumu_worker.py','--mumu-worker']
raise SystemExit(mumu_worker.main())
'''

class WorkerPipes(unittest.TestCase):
    def test_one_port_pauses_other_finishes_and_resume_reuses_same_process(self):
        self.run_control(False)

    def test_global_stop_unblocks_paused_port(self):
        self.run_control(True)

    def run_control(self,stop_all):
        controls={5557:PortControl(),5559:PortControl()};stopped=threading.Event()
        paused=threading.Event();sibling_done=threading.Event();children=[];guard=threading.Lock();events=[]
        def popen(command,**options):
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]))
            options['stderr']=subprocess.PIPE
            child=subprocess.Popen([sys.executable,'-u','-c',SCRIPT],env=env,**options)
            with guard:children.append(child)
            return child
        def worker(*args,**kwargs):return run_one(*args,popen=popen,**kwargs)
        def progress(n,text):
            events.append((n,text))
            if n==5557 and text=='fixture-current-task':controls[n].request(True)
            if n==5557 and text=='На паузе':paused.set()
            if n==5559 and text=='fixture-finished':sibling_done.set()
        result=[];thread=threading.Thread(target=lambda:result.append(run_many([5557,5559],Settings(),'full',False,stopped,progress,worker=worker,controls=controls,spacing=0)))
        thread.start()
        try:
            self.assertTrue(paused.wait(12),events);self.assertTrue(sibling_done.wait(12),events)
            self.assertTrue(thread.is_alive());self.assertEqual(controls[5557].state(),'paused')
            self.assertNotIn((5557,'fixture-next-task'),events)
            if stop_all:stopped.set()
            else:controls[5557].request(False)
            thread.join(12);self.assertFalse(thread.is_alive(),events)
            self.assertEqual(len(children),2,'Pause/resume must not restart any process')
            self.assertEqual(set(result[0]),{5557,5559})
            if stop_all:self.assertNotIn((5557,'fixture-next-task'),events)
            else:self.assertEqual(events.count((5557,'fixture-next-task')),1)
            self.assertTrue(all(c.state()=='finished' for c in controls.values()))
            self.assertTrue(all(c.returncode==0 for c in children),[(c.returncode,c.stderr.read().decode(errors='replace')) for c in children])
        finally:
            stopped.set();controls[5557].request(False);thread.join(3)
            for child in children:
                if child.poll() is None:child.kill();child.wait(3)
                if child.stderr is not None:child.stderr.close()


class GuiPause(unittest.TestCase):
    def test_selected_port_buttons_do_not_pause_the_other_port(self):
        import assistant_app as app
        tk,ttk=MagicMock(),MagicMock();tk.ttk=ttk
        tk.Text.return_value.get.return_value='5557\n5563'
        ttk.Treeview.return_value.selection.return_value=('5557',)
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog}), \
             patch.object(app,'load',return_value=Settings()),patch.object(app,'save'), \
             patch.object(app,'save_ports'),patch.object(app,'run_many',return_value={}) as many, \
             patch.object(app.threading,'Thread') as thread, \
             patch('telegram_statistics.start',return_value=threading.Event()):
            app.launch()
            commands={c.kwargs['text']:c.kwargs['command'] for c in ttk.Button.call_args_list}
            commands['Старт']();commands['Пауза порта']()
            call=thread.call_args;call.kwargs['target'](*call.kwargs['args'])
            controls=many.call_args.kwargs['controls']
            self.assertEqual(controls[5557].state(),'pause-requested')
            self.assertEqual(controls[5563].state(),'running')
            commands['Продолжить порт']()
            self.assertEqual(controls[5557].state(),'running')
            self.assertEqual(controls[5563].state(),'running')
            self.assertEqual(thread.call_count,1,'Continue must not launch a worker')
