"""Continuous supervision must skip, never replay unknown sends or Back."""
import copy, tempfile,threading,unittest
from pathlib import Path
from unittest.mock import MagicMock
from assistant_settings import Settings
from assistant_store import Store,StateError
from assistant_monitor import REPORT
from mumu_store import SharedStore
from mumu_recovery import Repair,recoverable,run
from test_guided_chain import snapshot,WHO,GREETING
from test_inbox_profiles import nav


def failure(code='native-transport-error'):
    return dict(status='stopped',reason='inbox-pass-stopped',last_pass=dict(status='inbox-stopped',host_failure=code))

class Policy(unittest.TestCase):
    def test_recover_only_current_failure_not_completed_historical_warning(self):
        self.assertTrue(recoverable(failure()))
        for status in ('cancelled','paused','completed'):
            self.assertFalse(recoverable(dict(failure(),status=status)))
        self.assertFalse(recoverable(dict(failure('internal-error'),initial_run=dict(status='completed',error='frame-budget'))))
        for code in ('identity-changed','journal-corrupt','message-not-approved','report-write-failed'):
            r=failure(code);r['last_pass']['error']='frame-budget';self.assertFalse(recoverable(r))
    def test_restart_only_after_repair_and_without_fresh_session_reset(self):
        stop=threading.Event();settings=Settings();calls=[]
        def monitor(*a,**kw):
            calls.append(kw)
            return failure() if len(calls)==1 else dict(status='cancelled',reason='cancelled')
        repair=MagicMock(side_effect=[False,True]);wait=MagicMock(return_value=False)
        out=run(settings,stop,None,monitor=monitor,repair=repair,wait=wait,write=lambda v:REPORT,fresh_session=True)
        self.assertEqual(out['status'],'cancelled');self.assertEqual(len(calls),2)
        self.assertTrue(calls[0]['fresh_session']);self.assertFalse(calls[1]['fresh_session'])
        self.assertFalse(calls[0]['terminal_notifications']);self.assertEqual(repair.call_count,2);wait.assert_called_once_with(2)
    def test_cancel_interrupts_recovery_without_engine_restart(self):
        stop=threading.Event();monitor=MagicMock(return_value=failure())
        def wait(seconds):stop.set();return True
        out=run(Settings(),stop,None,monitor=monitor,repair=lambda:False,wait=wait,write=lambda v:REPORT)
        self.assertEqual(out['status'],'cancelled');monitor.assert_called_once()
    def test_hard_failure_or_journal_error_is_not_hidden(self):
        for mode in ('hard','journal'):
            m=MagicMock(return_value=failure('journal-corrupt') if mode=='hard' else failure())
            repair=MagicMock(side_effect=StateError('PRIVATE'))
            out=run(Settings(),threading.Event(),None,monitor=m,repair=repair,write=lambda v:REPORT)
            self.assertEqual(out['status'],'stopped');m.assert_called_once()
            if mode=='hard':repair.assert_not_called()

class Skip(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=SharedStore(Path(self.tmp.name)/'x.db',Path(self.tmp.name)/'old',device_port=5561)
        pending=dict(attempt=1,**WHO,variant=0)
        self.reservation=self.store.reserve(pending,GREETING,approved=True)
        self.stop=threading.Event();self.reader=MagicMock(return_value=snapshot(('Норм',False)))
        self.nav=MagicMock(return_value=nav('returned',WHO))
        self.repair=Repair(Settings(),self.stop,self.store,reader=self.reader,navigator=self.nav)
    def test_durable_skip_and_review_precede_back_preserving_unknown(self):
        def back(*a,**kw):
            self.assertIn(WHO['peer'],self.store.visited_peers())
            with self.store.connection() as db:
                self.assertEqual(db.execute('SELECT stage FROM chain_dialogs').fetchone()[0],'manual-review')
                self.assertEqual(db.execute('SELECT status FROM manual_actions').fetchone()[0],'reserved-unknown')
            return nav('returned',WHO)
        self.nav.side_effect=back
        self.assertTrue(self.repair());self.nav.assert_called_once()
        self.assertEqual(self.nav.call_args.kwargs['expected'],WHO)
    def test_same_problem_is_not_backed_or_opened_twice(self):
        self.nav.side_effect=TimeoutError('PRIVATE')
        with self.assertRaises(TimeoutError):self.repair()
        self.assertFalse(self.repair());self.nav.assert_called_once()
        self.assertIn(WHO['peer'],self.store.visited_peers())
    def test_unreadable_chat_never_uses_startup_back(self):
        self.reader.side_effect=ValueError('PRIVATE');self.nav.side_effect=ValueError('PRIVATE')
        self.assertFalse(self.repair())
        self.assertEqual([c.kwargs['entry'] for c in self.nav.call_args_list],['dialogs','search'])
        self.assertTrue(all(c.args[0]=='list' for c in self.nav.call_args_list))
        self.assertNotIn('either',[c.kwargs['entry'] for c in self.nav.call_args_list])
    def test_different_binding_blocks_back(self):
        from assistant_inbox import InboxChain
        chain=InboxChain(self.store)
        chain.mark_review(WHO)
        newer=copy.deepcopy(snapshot());newer['identity']['chat']='301'
        self.reader.return_value=newer
        with self.assertRaises(StateError):self.repair()
        self.nav.assert_not_called()
    def test_boot_change_blocks_every_action(self):
        self.repair.recheck=MagicMock(side_effect=RuntimeError('PRIVATE'))
        with self.assertRaises(StateError):self.repair()
        self.reader.assert_not_called();self.nav.assert_not_called()

if __name__=='__main__':unittest.main()


class OfflineRecovery(unittest.TestCase):
    def test_temporarily_offline_device_keeps_recovery_without_navigation(self):
        p=Skip('test_boot_change_blocks_every_action');p.setUp();self.addCleanup(p.doCleanups)
        p.repair.recheck=MagicMock(side_effect=ConnectionError('PRIVATE'))
        with self.assertRaises(ConnectionError):p.repair()
        p.reader.assert_not_called();p.nav.assert_not_called()
    def test_cloud_caption_reports_recovery_instead_of_terminal_stop(self):
        import assistant_error_notify as alerts
        sender=MagicMock(return_value=True)
        status=alerts.notify_json(dict(status='recovering'),loader=lambda:('private','private'),sender=sender)
        self.assertEqual(status,'accepted');self.assertIn('восстанавливаю',sender.call_args.args[2])
