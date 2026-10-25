"""Reports 139/140: real failure boundaries, not screenshot-based send replay."""
import copy,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch,call
from assistant_contact_photo import capture_profile,ProfileReturnUnverified
from assistant_store import StateError
from assistant_error_notify import diagnostic_json,reasons
from one_chat_device import ReadStopped
import one_chat_send_device as device_send
from test_extensions126 import png
from test_mumu139_unavailable import timeout
from test_inbox_profiles import Base,WHO,snap,msg,nav
from test_mumu1328_send_proof import no_attempt
from test_one_chat_preview import snap as send_snapshot
from test_guided_chain import snapshot,GREETING
import test_guided_chain as guided_fixtures
from conversation_engine import QUESTIONS

class Profile(unittest.TestCase):
    def device(self):
        dev=MagicMock();dev.screen.return_value=png();return dev
    def test_verified_profile_is_backed_once_without_chat_probe_on_profile(self):
        dev=self.device();events=[]
        def chat(*a):events.append('chat');return snap()
        def profile(*a):events.append('profile');return True
        dev.run.side_effect=lambda args:events.append('back' if args[-1]=='4' else 'tap')
        image=capture_profile('adb','folder',WHO,device_factory=lambda *a:dev,chat_reader=chat,profile_reader=profile)
        self.assertEqual(image,png());self.assertEqual(events,['chat','tap','profile','profile','back','chat'])
    def test_only_post_back_observations_retry_without_second_back(self):
        dev=self.device();read=MagicMock(side_effect=[snap(),timeout(),snap()]);pause=MagicMock()
        self.assertEqual(capture_profile('adb','folder',WHO,device_factory=lambda *a:dev,chat_reader=read,profile_reader=lambda *a:True,read_pause=pause),png())
        self.assertEqual(dev.run.call_args_list.count(call(['shell','input','keyevent','4'])),1)
        self.assertEqual(read.call_count,3);pause.assert_called_once_with(.2)
    def test_persistent_post_back_budget_is_bounded_and_distinguished(self):
        dev=self.device();read=MagicMock(side_effect=[snap(),timeout(),timeout(),timeout()])
        with self.assertRaises(ProfileReturnUnverified) as caught:
            capture_profile('adb','folder',WHO,device_factory=lambda *a:dev,chat_reader=read,profile_reader=lambda *a:True,read_pause=lambda _:None)
        self.assertEqual(read.call_count,4);self.assertEqual(dev.run.call_args_list.count(call(['shell','input','keyevent','4'])),1)
        detail=caught.exception.diagnostic
        self.assertEqual(detail['photo_checkpoint'],'profile-after-back');self.assertEqual(detail['photo_read_retries'],2)
        self.assertTrue(detail['chat_back_completed']);self.assertEqual(detail['last_read_failure']['error'],'transition-timeout')
    def test_wrong_chat_never_retries_or_returns_image(self):
        dev=self.device();wrong=snap();wrong['identity']=dict(WHO,peer='999');read=MagicMock(side_effect=[snap(),wrong])
        with self.assertRaises(ProfileReturnUnverified):
            capture_profile('adb','folder',WHO,device_factory=lambda *a:dev,chat_reader=read,profile_reader=lambda *a:True,read_pause=MagicMock(side_effect=AssertionError()))
        self.assertEqual(read.call_count,2);self.assertEqual(dev.run.call_args_list.count(call(['shell','input','keyevent','4'])),1)
    def test_validation_failure_like_140_is_not_treated_as_transient(self):
        dev=self.device();read=MagicMock(side_effect=[snap(),ValueError('PRIVATE')])
        with self.assertRaises(ProfileReturnUnverified) as caught:
            capture_profile('adb','folder',WHO,device_factory=lambda *a:dev,chat_reader=read,profile_reader=lambda *a:True)
        self.assertEqual(read.call_count,2);self.assertEqual(caught.exception.diagnostic['host_failure'],'validation-failed')
        self.assertEqual(caught.exception.diagnostic['photo_checkpoint'],'profile-after-back')
        self.assertNotIn('PRIVATE',str(caught.exception.diagnostic))
    def test_unknown_back_response_is_never_replayed(self):
        dev=self.device()
        def action(args):
            if args[-1]=='4':raise TimeoutError('PRIVATE')
        dev.run.side_effect=action;reader=MagicMock(return_value=snap())
        with self.assertRaises(ProfileReturnUnverified) as caught:
            capture_profile('adb','folder',WHO,device_factory=lambda *a:dev,chat_reader=reader,profile_reader=lambda *a:True)
        self.assertEqual(reader.call_count,1);self.assertFalse(caught.exception.diagnostic['chat_back_completed'])
        self.assertEqual(caught.exception.diagnostic['photo_checkpoint'],'profile-back-call')
        self.assertEqual(dev.run.call_args_list.count(call(['shell','input','keyevent','4'])),1)
    def test_profile_proof_lost_after_image_requires_fresh_proof_before_back(self):
        dev=self.device();profiles=MagicMock(side_effect=[True,StateError('profile-not-verified'),True])
        reader=MagicMock(side_effect=[snap(),RuntimeError(),snap()])
        with self.assertRaisesRegex(StateError,'profile-photo-unavailable'):
            capture_profile('adb','folder',WHO,device_factory=lambda *a:dev,chat_reader=reader,profile_reader=profiles)
        self.assertEqual(profiles.call_count,3);self.assertEqual(dev.run.call_args_list.count(call(['shell','input','keyevent','4'])),1)

class CaptureProof(unittest.TestCase):
    def evidence(self,stage='adb-preflight',check='test-state',reason='device-offline'):
        error=ReadStopped('PRIVATE')
        error._dvk_failure=dict(stage=stage,error='startup-'+stage+'-failed',error_type='OtherError',adb_check=check,adb_reason=reason)
        return error
    def test_recoverable_adb_before_inspector_has_positive_no_rpc_proof(self):
        with patch.object(device_send,'capture',side_effect=self.evidence()),patch.object(device_send,'inspect_submission') as invoke:
            with self.assertRaises(device_send.SubmissionNotStarted) as caught:device_send.submit('adb','folder',send_snapshot())
        self.assertEqual(caught.exception.stage,'capture-setup');invoke.assert_not_called()
    def test_plain_exception_before_inspector_is_not_enough(self):
        error=TimeoutError('PRIVATE')
        with patch.object(device_send,'capture',side_effect=error):
            with self.assertRaises(TimeoutError) as caught:device_send.submit('adb','folder',send_snapshot())
        self.assertIs(caught.exception,error)
    def test_post_inspector_adb_failure_never_becomes_no_rpc_proof(self):
        error=self.evidence('device-recheck-after','test-state','device-offline')
        def capture(*args,inspector,**kw):
            inspector(1234,'PRIVATE',lambda:False,WHO);raise error
        with patch.object(device_send,'capture',side_effect=capture),patch.object(device_send,'inspect_submission',return_value=dict(attempted=True,handler_returned=True)):
            with self.assertRaises(ReadStopped) as caught:device_send.submit('adb','folder',send_snapshot())
        self.assertIs(caught.exception,error);self.assertNotIsInstance(caught.exception,device_send.SubmissionNotStarted)
    def test_inspector_exception_never_becomes_capture_setup_proof(self):
        error=TimeoutError('PRIVATE')
        def capture(*args,inspector,**kw):return inspector(1234,'PRIVATE',lambda:False,WHO)
        with patch.object(device_send,'capture',side_effect=capture),patch.object(device_send,'inspect_submission',side_effect=error):
            with self.assertRaises(TimeoutError) as caught:device_send.submit('adb','folder',send_snapshot())
        self.assertIs(caught.exception,error)
    def test_wrong_device_boot_evidence_does_not_allow_retry(self):
        with patch.object(device_send,'capture',side_effect=self.evidence(reason='identity-mismatch')):
            with self.assertRaises(ReadStopped) as caught:device_send.submit('adb','folder',send_snapshot())
        self.assertNotIsInstance(caught.exception,device_send.SubmissionNotStarted)

class SnapshotRefresh(unittest.TestCase):
    setUp=guided_fixtures.WholeChain.setUp
    walk=guided_fixtures.WholeChain.walk
    send=guided_fixtures.WholeChain.send
    def test_new_peer_burst_after_native_precheck_replans_only_unsent_draft(self):
        before=snapshot(('Добрый вечер)',False));new=snapshot(('Добрый вечер)',False),('У тебя как?',False))
        after=snapshot(('Добрый вечер)',False),('У тебя как?',False),(QUESTIONS[0],True))
        self.chain.bind(snapshot(),(GREETING,),approved=True)
        with patch.object(self,'send',side_effect=[no_attempt('submission-snapshot-changed'),dict(attempted=True,handler_returned=True)]) as send:
            result=self.walk([before,before,new,new,after],until_waiting=True)
        self.assertEqual(result['status'],'chain-waiting');self.assertEqual(result['stage'],'wait-mood')
        self.assertEqual(result['diagnostics']['send_snapshot_refreshes'],1);self.assertEqual(send.call_count,2)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT outcome FROM chain_send_attempts ORDER BY id').fetchall(),[('not-invoked',),('handler-returned',)])
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('outgoing-observed',)])
    def test_continuous_peer_burst_is_bounded_at_two_replans(self):
        before=snapshot(('Здравствуйте',False))
        first=snapshot(('Здравствуйте',False),('Все хорошо',False))
        second=snapshot(('Здравствуйте',False),('Все хорошо',False),('У тебя как?',False))
        self.chain.bind(snapshot(),(GREETING,),approved=True)
        with patch.object(self,'send',return_value=no_attempt('submission-snapshot-changed')) as send:
            result=self.walk([before,before,first,first,second,second],until_waiting=True)
        self.assertEqual(result['reason'],'send-preflight-deferred');self.assertEqual(send.call_count,3)
        self.assertEqual(result['diagnostics']['send_snapshot_refreshes'],2)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT outcome FROM chain_send_attempts').fetchall(),[('not-invoked',)]*3)
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('awaiting-approval',)])
    def test_new_own_message_is_not_replanned_as_peer_burst(self):
        before=snapshot(('Здравствуйте',False));changed=snapshot(('Здравствуйте',False),('Новый ответ',True))
        self.chain.bind(snapshot(),(GREETING,),approved=True)
        with patch.object(self,'send',return_value=no_attempt('submission-snapshot-changed')) as send:
            result=self.walk([before,before,changed],until_waiting=True)
        self.assertEqual(result['reason'],'send-preflight-deferred');send.assert_called_once()
        self.assertNotIn('send_snapshot_refreshes',result['diagnostics'])
    def test_unknown_native_attempt_never_enters_snapshot_refresh(self):
        before=snapshot(('Добрый вечер)',False));self.chain.bind(snapshot(),(GREETING,),approved=True)
        result=no_attempt('submission-snapshot-changed');result['attempted']=True
        with patch.object(self,'send',return_value=result) as send:out=self.walk([before,before],until_waiting=True)
        self.assertEqual(out['reason'],'send-outcome-unknown');send.assert_called_once()
        self.assertNotIn('send_snapshot_refreshes',out['diagnostics'])

class Diagnostic(unittest.TestCase):
    def test_139_city_error_is_closed_not_masked(self):
        for error in ('city-not-found','city-results-incomplete','city-query-changed','city-ambiguous'):
            payload=dict(last_profile_run=dict(profiles=dict(last_error=error,last_city_navigation=dict(error=error,
                city_checkpoint='results',city_prepare='ready',city_identity='none',city_visible_rows=0,city_total_rows=0,city_query_completed=True,city_select_attempted=False,city_name='PRIVATE'))))
            data=diagnostic_json(payload);n=json.loads(data)['diagnostic']['last_profile_run']['profiles']
            self.assertEqual(n['last_error'],error);self.assertEqual(n['last_city_navigation']['city_checkpoint'],'results')
            self.assertNotIn(b'PRIVATE',data)
    def test_retained_send_failure_has_stage_but_no_session_or_body(self):
        raw=diagnostic_json(dict(send_failure_events=[dict(reason='send-outcome-unknown',diagnostic=dict(
            send_host_failure='native-transport-error',send_transport_failure=dict(stage='script-run',error='startup-script-run-failed',error_type='TimedOutError'),
            body='PRIVATE',session='PRIVATE'))]))
        safe=json.loads(raw)['diagnostic']['send_failure_events'][0]
        self.assertEqual(safe['diagnostic']['send_transport_failure']['stage'],'script-run');self.assertNotIn(b'PRIVATE',raw)
    def test_retained_diagnostic_list_is_bounded(self):
        safe=json.loads(diagnostic_json(dict(send_failure_events=[dict(reason='send-outcome-unknown')]*10)))
        self.assertEqual(len(safe['diagnostic']['send_failure_events']),3)

class InboxHistory(Base):
    def test_failed_send_is_retained_after_later_successful_dialog(self):
        other=dict(account='100',peer='201',chat='301');self.journal(WHO,WHO['chat']);self.journal(other,other['chat'])
        bad=snap(msg(1002,'Добрый вечер)'));next_chat=snap(msg(1003,'Не пиши мне',who=other),who=other)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('opened',other),nav('returned',other),nav('search-ready')],
            [bad,bad,next_chat],sender=MagicMock(side_effect=TimeoutError('PRIVATE')))
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['last_chat_diagnostics']['failure_point'],'none')
        self.assertEqual(out['send_failure_events'][0]['reason'],'send-outcome-unknown')
        self.assertEqual(out['send_failure_events'][0]['diagnostic']['send_host_failure'],'device-timeout')
        self.assertNotIn('PRIVATE',json.dumps(out))

class MonitorRetention(unittest.TestCase):
    def test_send_failure_survives_later_empty_passes_and_is_bounded(self):
        from test_assistant_monitor import Monitor,inbox_result
        fixture=Monitor(methodName='test_local_unknown_send_does_not_pause_next_passes');fixture.setUp()
        counter=[0]
        def inbox(*args,**kwargs):
            counter[0]+=1
            if counter[0]<=4:return inbox_result(send_failure_events=[dict(reason='send-outcome-unknown',diagnostic=dict(read_retries=counter[0]))])
            return inbox_result()
        def wait(seconds):
            if counter[0]>=5:fixture.stop.set();return True
            return False
        fixture.inbox.side_effect=inbox
        out=fixture.run_monitor(mode='inbox',wait=wait)
        self.assertEqual(out['status'],'cancelled');self.assertEqual(len(out['send_failure_events']),3)
        self.assertEqual([e['diagnostic']['read_retries'] for e in out['send_failure_events']],[2,3,4])
        self.assertNotIn('send_failure_events',out['last_pass'])

class CancelReservation(unittest.TestCase):
    setUp=guided_fixtures.WholeChain.setUp
    walk=guided_fixtures.WholeChain.walk
    send=guided_fixtures.WholeChain.send
    def test_stop_after_reservation_does_not_manufacture_unknown_send(self):
        before=snapshot(('Добрый вечер)',False));self.chain.bind(snapshot(),(GREETING,),approved=True)
        original=self.chain.reserve_confirmed
        def reserve(*args):
            session=original(*args);self.stop.set();return session
        with patch.object(self.chain,'reserve_confirmed',side_effect=reserve),patch.object(self,'send') as send:
            result=self.walk([before,before],until_waiting=True)
        self.assertEqual(result['status'],'chain-cancelled');send.assert_not_called()
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('awaiting-approval',)])
            self.assertEqual(db.execute('SELECT status FROM chain_send_authorizations').fetchall(),[('not-invoked',)])
            self.assertEqual(db.execute('SELECT * FROM chain_send_attempts').fetchall(),[])
    def test_empty_attempt_cancel_cannot_release_an_entered_or_unknown_attempt(self):
        import assistant_send_safety as safety
        before=snapshot(('Добрый вечер)',False));self.chain.bind(snapshot(),(GREETING,),approved=True)
        _,action=self.chain.proposal(before);session=self.chain.reserve_confirmed(WHO,action)
        safety.begin(self.chain,session,WHO,action)
        with self.assertRaises(StateError):safety.defer_unstarted(self.chain,session,WHO,action)
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('reserved-unknown',)])
