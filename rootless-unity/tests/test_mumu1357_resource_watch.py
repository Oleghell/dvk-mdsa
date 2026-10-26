"""Six completed passes + thirty returned greetings; no device/network."""
import json,tempfile,threading,unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock,patch
import assistant_resource_watch as resource
from assistant_settings import Settings
from test_assistant_monitor import inbox_result,list_result
import test_inbox_profiles as fixture


def empty(**kwargs):
    value=inbox_result();value.update(incoming_scan_complete=True,new_incoming_messages=0)
    value.update(kwargs);return value

def batch(n=30,**kwargs):
    value=dict(status='profiles-completed',handlers_returned=n,send_attempts_unknown=False)
    value.update(kwargs);return dict(status='completed',profiles=value)

class Resource(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'watch.json';self.watch=resource.Watch(self.path)
        self.alert=MagicMock(return_value='accepted')
    def scan(self,**kwargs):return self.watch.inbox(empty(**kwargs),alert=self.alert)
    def test_both_thresholds_and_one_alert_after_restart(self):
        self.watch.profiles(batch())
        for _ in range(5):self.assertEqual(self.scan(),'not-needed')
        self.alert.assert_not_called();self.assertEqual(self.scan(),'accepted')
        self.watch=resource.Watch(self.path)
        for _ in range(10):self.scan()
        self.assertEqual(self.alert.call_count,1)
    def test_six_scans_without_thirty_greetings_dont_alert(self):
        self.watch.profiles(batch(29))
        for _ in range(9):self.scan()
        self.alert.assert_not_called()
        self.watch.profiles(batch(1));self.alert.assert_not_called()
        self.assertEqual(self.scan(),'accepted')
    def test_incoming_resets_both_counts_even_when_no_answer_sent(self):
        self.watch.profiles(batch());self.scan(new_incoming_messages=1)
        self.assertEqual(self.watch.state['greetings'],0)
        self.assertEqual(self.watch.state['empty_passes'],0)
        for _ in range(6):self.scan()
        self.alert.assert_not_called()
    def test_actual_new_incoming_rearms_after_previous_warning(self):
        for _ in range(2):
            self.watch.profiles(batch())
            for i in range(6):self.scan()
            self.scan(new_incoming_messages=1)
        self.assertEqual(self.alert.call_count,2)
    def test_errors_deferred_incomplete_and_own_replies_are_not_empty(self):
        for bad in (dict(status='inbox-stopped'),dict(status='inbox-cancelled'),
                    dict(incoming_scan_complete=False),dict(history_deferred=1),
                    dict(history_cooldown_skipped=1),dict(isolated_dialogs=1),dict(review_pending=1),
                    dict(submission_calls=1),dict(handler_returns=1),dict(outgoing_observed=1),
                    dict(outcomes={'message-not-approved':1})):
            with self.subTest(bad=bad):
                self.watch.profiles(batch())
                for _ in range(5):self.scan()
                self.scan(**bad)
                self.assertEqual(self.watch.state['empty_passes'],0)
                self.assertEqual(self.watch.state['greetings'],0)
        self.alert.assert_not_called()
    def test_unknown_greeting_outcomes_and_failed_batches_do_not_qualify(self):
        for result in (batch(30,send_attempts_unknown=True),dict(batch(),status='stopped'),
                       batch(30,status='profiles-stopped')):
            self.watch.profiles(result)
            for _ in range(6):self.scan()
        self.alert.assert_not_called()
    def test_reservation_is_saved_before_network_unknown_never_retried(self):
        def alert():
            self.assertTrue(resource.Watch(self.path).state['notified'])
            raise RuntimeError('private error')
        self.watch.profiles(batch())
        for _ in range(5):self.scan()
        self.assertEqual(self.watch.inbox(empty(),alert=alert),'unknown')
        self.watch=resource.Watch(self.path);self.scan();self.alert.assert_not_called()
    def test_failed_save_prevents_send_corrupt_state_not_reset(self):
        self.watch.profiles(batch())
        for _ in range(5):self.scan()
        with patch.object(self.watch,'save',side_effect=OSError()):
            with self.assertRaises(OSError):self.scan()
        self.alert.assert_not_called()
        self.path.write_text('{}')
        with self.assertRaises(ValueError):resource.Watch(self.path)
    def test_disabled_alerts_and_separate_device_files(self):
        self.watch.profiles(batch())
        for _ in range(6):self.watch.inbox(empty(),enabled=False,alert=self.alert)
        self.alert.assert_not_called();self.assertFalse(self.watch.state['notified'])
        other=resource.Watch(self.path.parent/'other-device.json')
        for _ in range(6):other.inbox(empty(),alert=self.alert)
        self.alert.assert_not_called();self.scan();self.alert.assert_called_once()
    def test_telegram_payload_is_fixed_no_chat_content_or_retry(self):
        sender=MagicMock(return_value=True)
        self.assertEqual(resource.notify(loader=lambda:('token','chat'),sender=sender),'accepted')
        self.assertIn('Нужна проверка ресурса',sender.call_args.args[2])
        self.assertIn('Работа продолжается',sender.call_args.args[2])
        sender.side_effect=RuntimeError('SECRET')
        self.assertEqual(resource.notify(loader=lambda:('token','chat'),sender=sender),'unknown')
        self.assertEqual(sender.call_count,2)
    def test_monitor_counts_completed_passes_not_loop_iterations(self):
        import assistant_monitor as monitor
        stop=threading.Event();seen=[]
        initial=dict(batch(),report_name='last-run.json',inbox=empty())
        def incoming(*args,**kwargs):seen.append('inbox');return empty()
        def wait(delay):
            if len(seen)>=8:stop.set();return True
            return False
        with patch.object(resource,'notify',self.alert):
            # Pass an explicit alert because inbox() captures its default at definition time.
            original=self.watch.inbox
            self.watch.inbox=lambda value,**kw:original(value,alert=self.alert,**kw)
            out=monitor.run(Settings(),stop,MagicMock(),initial=lambda *a,**kw:initial,
                inbox=incoming,navigator=lambda op,*a,**kw:list_result() if op=='list' else dict(list_result(),state='search-ready'),
                lock=nullcontext,write=lambda _:'last-monitor.json',wait=wait,clock=lambda:0,
                resource_factory=lambda:self.watch)
        self.assertEqual(out['passes_completed'],8);self.alert.assert_called_once()
        self.assertEqual(out['resource_notification'],'accepted');self.assertEqual(out['status'],'cancelled')

class Incoming(fixture.Base):
    def test_new_incoming_is_counted_once_across_repeated_native_reads(self):
        self.journal();hello=fixture.msg(1002,'Привет');question=fixture.msg(1003,fixture.QUESTIONS[0],True)
        out=self.walk([fixture.nav('opened',fixture.WHO),fixture.nav('returned',fixture.WHO),fixture.nav('search-ready')],
            [fixture.snap(hello),fixture.snap(hello),fixture.snap(hello,question)])
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['new_incoming_messages'],1);self.assertTrue(out['incoming_scan_complete'])
    def test_empty_no_target_pass_has_explicit_complete_signal(self):
        out=self.walk([],[])
        self.assertEqual(out['new_incoming_messages'],0);self.assertTrue(out['incoming_scan_complete'])
