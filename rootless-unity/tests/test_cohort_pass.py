import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import cohort_pass as p

class Cohort(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'local.sqlite3';self.store=p.Store(self.path);self.store.create()
    def value(self,n=1,**kw):return dict(attempt=n,account='9999',peer=str(n),chat=str(1000+n),variant=0,**kw)
    def test_reservation_is_durable_and_idempotent(self):
        v=self.value();self.store.reserve(v);p.Store(self.path).reserve(v)
        self.assertEqual(p.Store(self.path).summary()['reserved'],1)
        self.assertNotIn('9999',json.dumps(self.store.summary()))
        self.store.finish({'items':[{'number':1,'send_handler_returned':True}]})
        self.assertEqual(self.store.summary()['handlers_returned'],1)
        self.assertFalse(self.store.summary()['delivery_confirmed'])
        with self.assertRaises(p.CohortError):p.Store(self.path).create()
        with self.assertRaises(p.CohortError):self.store.reserve(self.value(2))
    def test_ten_only_unique_peers_and_account(self):
        self.store.reserve(self.value())
        for changes in ({'account':'8888'},{'peer':'1'},{'variant':1,'attempt':1}):
            v=self.value(2);v.update(changes)
            with self.assertRaises(Exception):self.store.reserve(v)
        for i in range(2,11):self.store.reserve(self.value(i))
        with self.assertRaises(p.CohortError):self.store.reserve(self.value(11))
        self.assertEqual(self.store.summary()['reserved'],10)
    def test_invalid_ids_and_unknown_fields(self):
        for field,value in [('chat','-0'),('chat','9223372036854775808'),('account','0'),('peer','9999'),('attempt',True),('variant',True),('extra','PRIVATE')]:
            v=self.value();v[field]=value
            with self.assertRaises(Exception):self.store.reserve(v)
        for chat in ('0','-1','-9223372036854775808'):
            v=self.value();v['chat']=chat;p.Store.check(v)
        self.assertEqual(self.store.summary()['reserved'],0)
    def test_failed_commit_never_acknowledged(self):
        script=MagicMock();script.exports_sync.cohortpending.return_value=self.value()
        failed=threading.Event();stop=MagicMock();stop.wait.return_value=False
        store=MagicMock();store.reserve.side_effect=OSError('PRIVATE')
        p.monitor(script,store,stop,lambda:False,failed)
        self.assertTrue(failed.is_set());script.exports_sync.cohortack.assert_not_called();script.exports_sync.cancel.assert_called_once()
    def test_ack_after_commit_not_before(self):
        stop=threading.Event();failed=threading.Event();script=MagicMock()
        script.exports_sync.cohortpending.return_value=self.value()
        def ack(value):
            self.assertEqual(p.Store(self.path).summary()['reserved'],1)
            stop.set();return True
        script.exports_sync.cohortack.side_effect=ack
        p.monitor(script,self.store,stop,lambda:False,failed)
        self.assertFalse(failed.is_set());script.exports_sync.cohortack.assert_called_once()
    def test_source_and_old_lock_unchanged(self):
        s=p.build();self.assertLess(s.index('const reservation={'),s.index('batchSent.add(batchCandidateKey)'))
        self.assertIn('cohortApproved!==reservationKey',s);self.assertIn('Date.now()+1000',s)
        lock=self.path.parent/'.dvk-ten-profile-pass.lock';lock.write_text('old')
        with patch('diagnose_device.diagnose',return_value=('result','path')) as diagnose:
            newpath=self.path.parent/'new.sqlite3';p.start(None,self.path.parent,path=newpath)
            self.assertIs(diagnose.call_args.kwargs['automatic_probe'],True)
        self.assertEqual(lock.read_text(),'old')
    def test_unknown_outcome_is_held_not_retried(self):
        self.store.reserve(self.value());self.store.finish({'items':[{'number':1,'send_handler_returned':False}]})
        self.assertEqual(self.store.summary()['reserved'],1);self.assertEqual(self.store.summary()['handlers_returned'],0)
        with self.assertRaises(p.CohortError):p.Store(self.path).create()
    def test_submission_without_matching_reservation_is_rejected(self):
        for variant in (0,1):
            if variant==1:self.store.reserve(self.value())
            with self.assertRaises(p.CohortError):
                self.store.finish({'items':[dict(number=1,send_attempted=True,
                                                greeting_variant=variant,send_handler_returned=True)]})
    def test_gui_cohort_is_explicit_and_busy_guarded(self):
        import sys,navigate_profile_device as gui
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk
        tk.Tk.return_value.winfo_height.return_value=300;ttk.Frame.return_value.winfo_reqheight.return_value=260
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}),patch.object(gui.threading,'Thread') as thread:
            gui.launch_gui();thread.assert_not_called()
            commands={c.kwargs.get('text'):c.kwargs.get('command') for c in ttk.Button.call_args_list}
            self.assertNotIn('Автопроход · до 10 анкет',commands)
            commands['Новая десятка · сохранить привязки']()
            self.assertIs(thread.call_args.kwargs['args'][8],True)
            commands['Новая десятка · сохранить привязки']();thread.return_value.start.assert_called_once()
        ttk.Checkbutton.assert_not_called()
    def test_conflicting_modes_are_closed(self):
        import diagnose_device as d
        for flags in ({},{'automatic_probe':True,'replies_probe':True},{'automatic_probe':True,'batch_probe':True}):
            with self.assertRaises(d.TestError):
                d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=MagicMock(),
                                 cohort_store=self.store,**flags)
