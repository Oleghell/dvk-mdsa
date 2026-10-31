"""Synthetic safe skip/continue and cloud diagnostic contracts; no live services."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
import assistant_pass
import assistant_profiles as profiles
import assistant_error_notify as alerts
import telegram_notify as telegram
from assistant_store import Store
from test_chat_batch import cycle
from test_inbox_profiles import cycle_result, Config


def skipped():
    value=cycle(count=1);n=value['navigation']
    n.update(cycle_timeout_ms=90000, profile_ready_waits=4, greeting_frame_splits=0,
        profile_read_budget_retries=0,submit_frame_retries=0,profile_read_skipped=True,profile_read_skip_reason='chat-not-actual',
        history_status='not-ready',wait_reason='chat-not-actual',message_count=None,samples=0,
        read_checkpoint='model',model_actual=False)
    return value


class NativeSkipContracts(unittest.TestCase):
    def test_unready_not_forged_into_empty_and_source_still_checks_exact_chat(self):
        value=skipped();old=copy.deepcopy(value)
        self.assertIs(assistant_pass.validate(value),value);self.assertEqual(value,old)
        s=assistant_pass.build('Привет')
        self.assertIn("n.profile_read_skipped=true",s)
        part=s[s.index("if(n.phase==='close-chat'){"):s.index("if(n.phase==='wait-chat-back'){")]
        for guard in ("k!=='chat'",'target(state.chatController)','target(state.targetUser)','target(state.chatModelPin)'):
            self.assertIn(guard,part)
        self.assertEqual(part.count('call(s.chatBack,current)'),1)
        # Avoid a recurrence of accidentally embedding Python concatenation in JS.
        self.assertNotIn('+ SKIP_GUARD +',s);self.assertNotIn('+ SKIP +',s)

    def test_no_success_on_send_reservation_phase_wrong_history_or_unverified_return(self):
        for key,bad in [('send_attempted',True),('send_handler_returned',True),('greeting_frame_splits',1),
            ('profile_read_skipped',False),('profile_read_skip_reason','PRIVATE'),('profile_ready_waits',3),
            ('wait_reason','none'),('chat_identity_verified',False),('chat_return_verified',False),
            ('chat_back_completed',False),('return_verified',False),('message_count',0),('samples',2),
            ('history_status','empty'),('phase','prepare-greeting')]:
            v=skipped();v['navigation'][key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):assistant_pass.validate(v)

    def test_unknown_back_does_not_become_successful_recovery(self):
        v=skipped();n=v['navigation'];n.update(stage='navigation-stopped',error='frame-budget',
            phase='close-chat',chat_back_completed=False,chat_return_verified=False,chat_return_route='not-checked',
            return_verified=False,close_attempted=False,close_completed=False)
        assistant_pass.validate(v)
        self.assertEqual(n['stage'],'navigation-stopped')

    def test_skipped_profile_survives_restart_without_new_send_reservation(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'s.sqlite3',Path(folder)/'legacy')
            store.record_visit('200',skipped()['navigation'])
            self.assertIn('200',Store(store.path,store.legacy).visited_peers())
            self.assertEqual(store.summary()['reserved'],0)


class ContinueProfiles(unittest.TestCase):
    def go(self, values, *, approve=None, errors=True, notifier=None):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'s.sqlite3',Path(folder)/'legacy')
            profiles.Session(store).set('city','Псков')
            calls=[]
            def next_cycle(*args,**kwargs):
                calls.append(1)
                if approve:args[3]({},'Привет',lambda:False)
                return values[len(calls)-1]
            result=profiles.walk(SimpleNamespace(adb='fake',folder=folder,errors_enabled=errors),
                threading.Event(),MagicMock(return_value=True),lambda _:None,store,cycle=next_cycle,
                config=Config(),limit=1,recovery_notifier=notifier)
            return result,len(calls)

    def test_continue_next_profile_and_notify_once_after_verified_return(self):
        notified=[]
        def notify(event):
            self.assertTrue(event['return_verified']);self.assertFalse(event['send_attempted'])
            notified.append(copy.deepcopy(event));return 'accepted'
        out,calls=self.go([skipped(),cycle_result(send_attempted=True,send_handler_returned=True)],notifier=notify)
        self.assertEqual((out['status'],calls),('profiles-completed',2))
        self.assertEqual((out['skipped_unready_chat'],out['skipped_existing_chat'],out['qualified_profiles']),(1,0,1))
        self.assertEqual(out['recovery_events'][0]['notification'],'accepted');self.assertEqual(len(notified),1)
        self.assertEqual(out['last_profile_diagnostics']['send_attempted'],True)

    def test_uncertain_send_or_wrong_return_never_continue(self):
        for change in ({'send_attempted':True},{'return_verified':False},{'chat_identity_verified':False},
            {'chat_back_completed':False},{'cleanup_failed':True},{'stage':'navigation-stopped','error':'identity-changed'}):
            v=skipped();v['navigation'].update(change);notify=MagicMock()
            with self.subTest(change=change):
                out,calls=self.go([v],notifier=notify)
                self.assertEqual(calls,1);self.assertEqual(out['status'],'profiles-stopped');notify.assert_not_called()

    def test_offered_authorization_never_local_recovery(self):
        notify=MagicMock();out,calls=self.go([skipped()],approve=True,notifier=notify)
        self.assertEqual((calls,out['reason']),(1,'return-not-verified'));notify.assert_not_called()

    def test_repeated_broken_profiles_bounded_not_infinite_restart(self):
        notify=MagicMock(return_value='accepted')
        out,calls=self.go([skipped() for _ in range(10)],notifier=notify)
        self.assertEqual(calls,profiles.MAX_READ_RECOVERIES);self.assertEqual(out['reason'],'profile-recovery-limit')
        self.assertEqual(notify.call_count,profiles.MAX_READ_RECOVERIES)
        self.assertFalse(out['recovery_events'][-1]['continue_work'])
        self.assertTrue(all(e['return_verified'] for e in out['recovery_events']))

    def test_successful_read_resets_consecutive_error_limit(self):
        values=[]
        for _ in range(4):
            values.extend([skipped(),cycle_result()])
        values.append(cycle_result(send_attempted=True,send_handler_returned=True))
        out,calls=self.go(values,errors=False)
        self.assertEqual((out['status'],calls),('profiles-completed',9))
        self.assertEqual(out['skipped_unready_chat'],4)
        self.assertEqual(out['consecutive_read_recoveries'],0)

    def test_disabled_alert_and_unknown_telegram_not_retried(self):
        for enabled,result in [(False,'accepted'),(True,'unknown'),(True,RuntimeError('PRIVATE'))]:
            notify=MagicMock(side_effect=result if isinstance(result,Exception) else None,return_value=result)
            out,calls=self.go([skipped(),cycle_result(send_attempted=True,send_handler_returned=True)],errors=enabled,notifier=notify)
            self.assertEqual(calls,2);self.assertEqual(out['status'],'profiles-completed')
            self.assertEqual(notify.call_count,int(enabled));self.assertNotIn('PRIVATE',json.dumps(out))


class JsonDiagnostic(unittest.TestCase):
    def test_only_closed_diagnostic_fields_leave_machine(self):
        r=dict(status='stopped',reason='profile-pass-stopped',token='SECRET',account='100',city='PRIVATE',
            last_profile_run=dict(status='stopped',profiles=dict(status='profiles-stopped',
                last_profile_diagnostics=dict(skipped()['navigation'],private_text='PRIVATE',exception='SECRET'))),
            last_pass=dict(status='SECRET',reason='SECRET'),message='PRIVATE')
        b=alerts.diagnostic_json(r);self.assertNotIn(b'SECRET',b);self.assertNotIn(b'PRIVATE',b)
        x=json.loads(b)['diagnostic']['last_profile_run']['profiles']['last_profile_diagnostics']
        self.assertEqual(x['profile_read_skip_reason'],'chat-not-actual');self.assertFalse(x['send_attempted'])
        self.assertNotIn('account',json.dumps(json.loads(b)))

    def test_json_notify_one_attempt_and_unknown_no_retry(self):
        for result in (True,False,RuntimeError('SECRET')):
            sender=MagicMock(side_effect=result if isinstance(result,Exception) else None,return_value=result)
            outcome=alerts.notify_json(dict(status='stopped',reason='history-not-ready'),
                loader=lambda:('token','chat'),sender=sender)
            self.assertEqual(outcome,'accepted' if result is True else 'unknown');sender.assert_called_once()
            json.loads(sender.call_args.args[3])

    def test_recovery_json_requires_verified_return_and_no_send(self):
        for bad in ({'return_verified':False},{'send_attempted':True},{'status':'working'}):
            sender=MagicMock();event=dict(status='recovered',return_verified=True,send_attempted=False);event.update(bad)
            self.assertEqual(alerts.notify_json(event,recovered=True,loader=lambda:('t','c'),sender=sender),'not-needed')
            sender.assert_not_called()

    def test_transport_fixed_json_name_port_prefix_ack_and_no_redirect(self):
        requests=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return b'{"ok":true,"result":{"message_id":1}}'
        class Opener:
            def open(self,request,timeout):requests.append(request);return Response()
        token='123456:'+('a'*35)
        with patch.object(telegram,'cloud_label',side_effect=lambda text:'MuMu ADB 5563 (1)\n'+text):
            self.assertTrue(telegram.send_json_document(token,'98765','Отчёт',b'{"reason":"history-not-ready"}',opener=Opener()))
        self.assertEqual(len(requests),1);r=requests[0]
        self.assertTrue(r.full_url.endswith('/sendDocument'));self.assertIn(b'filename="last-monitor.json"',r.data)
        self.assertIn(b'Content-Type: application/json',r.data);self.assertIn(b'MuMu ADB 5563 (1)',r.data)
        self.assertNotIn(token.encode(),r.data)
        for bad in (b'invalid',b'[]',b'x'*262145):
            with self.assertRaises(telegram.TelegramError):telegram.send_json_document(token,'98765','report',bad,opener=Opener())
        self.assertEqual(len(requests),1)

    def test_transport_exception_does_not_expose_secret_or_retry(self):
        class Opener:
            calls=0
            def open(self,request,timeout):self.calls+=1;raise OSError(request.full_url)
        client=Opener();token='123456:'+('a'*35)
        with self.assertRaises(telegram.TelegramError) as error:
            telegram.send_json_document(token,'98765','report',b'{}',opener=client)
        self.assertEqual(client.calls,1);self.assertNotIn(token,str(error.exception))


class MonitorJson(unittest.TestCase):
    def test_terminal_monitor_requests_one_text_and_one_json_then_saves_status(self):
        from assistant_monitor import run
        from assistant_settings import Settings
        from contextlib import nullcontext
        stop=threading.Event();text=MagicMock(return_value='accepted');attachment=MagicMock(return_value='unknown')
        writes=[]
        def write(value):writes.append(copy.deepcopy(value));return 'last-monitor.json'
        out=run(Settings(errors_enabled=True),stop,MagicMock(),navigator=MagicMock(side_effect=OSError('PRIVATE')),
            lock=nullcontext,write=write,alert=text,json_alert=attachment)
        self.assertEqual(out['status'],'stopped');text.assert_called_once();attachment.assert_called_once()
        self.assertEqual(out['error_json_notification'],'unknown')
        self.assertEqual(writes[-1]['error_json_notification'],'unknown');self.assertNotIn('PRIVATE',json.dumps(out))

    def test_recovery_complete_monitor_does_not_treat_local_skip_as_fatal(self):
        from assistant_monitor import run
        from assistant_settings import Settings
        from contextlib import nullcontext
        from test_assistant_monitor import list_result,inbox_result
        stop=threading.Event();text=MagicMock();attachment=MagicMock()
        first=dict(status='completed',report_name='last-run.json',inbox=inbox_result(),
            profiles=dict(profiles.report(5),status='profiles-completed',skipped_unready_chat=1,
                recovery_events=[dict(status='recovered',return_verified=True,send_attempted=False)]))
        nav=MagicMock(side_effect=lambda operation,*args,**kwargs: list_result() if operation=='list' else dict(list_result(),state='search-ready'))
        def wait(_):stop.set();return True
        out=run(Settings(errors_enabled=True),stop,MagicMock(),initial=MagicMock(return_value=first),
            inbox=MagicMock(return_value=inbox_result()),navigator=nav,lock=nullcontext,
            write=lambda _: 'last-monitor.json',wait=wait,alert=text,json_alert=attachment)
        self.assertEqual(out['status'],'cancelled');self.assertEqual(out['passes_completed'],1)
        text.assert_not_called();attachment.assert_not_called()
