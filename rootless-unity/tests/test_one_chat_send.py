"""Owned synthetic manual-send and local transcript tests, no actual device."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from one_chat_actions import Actions,report_fields
from one_chat_store import TestChatStore
from one_chat_preview import TEST_TEXT,QUESTION
from one_chat_session import report
import one_chat_send as sender
import one_chat_send_device as transport
import one_chat_local as local
from test_one_chat import WHO,message,rpc
from test_one_chat_preview import snap


class DurableSend(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'one-chat-check.sqlite3'
        self.store=TestChatStore(self.path);self.addCleanup(lambda:self.store.close())
        self.store.bind(WHO);self.store.consume(snap())
        self.before=snap([message('1003','200',TEST_TEXT)])
        self.store.consume(self.before,preview=True);self.actions=Actions(self.store)

    def test_reservation_survives_restart_and_blocks_every_future_send(self):
        self.actions.reserve(self.before)
        self.assertEqual(self.actions.state(),'reserved-unknown')
        self.assertIsNone(self.store.db.execute('SELECT code FROM test_preview').fetchone())
        self.store.close();self.store=TestChatStore(self.path);self.actions=Actions(self.store)
        for result in (dict(attempted=True,handler_returned=True),dict(attempted=False,handler_returned=False)):
            with self.assertRaises(ValueError):self.actions.reserve(self.before)
        self.actions.finish(dict(attempted=True,handler_returned=True))
        with self.assertRaises(ValueError):self.actions.reserve(self.before)
        self.assertIsNone(report_fields(self.actions.state())['messages_sent'])

    def test_two_processes_cannot_reserve_the_same_draft(self):
        second=TestChatStore(self.path)
        try:
            other=Actions(second)
            self.actions.reserve(self.before)
            with self.assertRaises(ValueError):other.reserve(self.before)
        finally:second.close()

    def test_unknown_crash_does_not_reenable_on_new_test_phrase(self):
        self.actions.reserve(self.before)
        later=copy.deepcopy(self.before);later['messages'].append(message('1004','200',TEST_TEXT))
        self.assertTrue(self.store.consume(later,preview=True)['preview_available'])
        with self.assertRaises(ValueError):self.actions.reserve(later)

    def test_wrong_dialog_stale_history_or_missing_preview_never_reserves(self):
        for kind in ('peer','chat','edit','extra','missing-preview'):
            invalid=copy.deepcopy(self.before)
            if kind=='peer':invalid['identity']['peer']='201'
            if kind=='chat':invalid['identity']['chat']='301'
            if kind=='edit':invalid['messages'][0]['text']='EDIT'
            if kind=='extra':invalid['messages'].append(message('1004','200',TEST_TEXT))
            if kind=='missing-preview':self.store.db.execute('DELETE FROM test_preview')
            with self.assertRaises(ValueError):self.actions.reserve(invalid)
            self.assertEqual(self.actions.state(),'not-reserved')

    def test_no_invocation_still_keeps_one_attempt_limit(self):
        self.actions.reserve(self.before);self.actions.finish(dict(attempted=False,handler_returned=False))
        self.assertEqual(self.actions.state(),'not-invoked')
        self.assertEqual(report_fields(self.actions.state())['messages_sent'],0)
        with self.assertRaises(ValueError):self.actions.reserve(self.before)

    def test_observing_one_new_own_reply_is_not_recipient_delivery(self):
        self.actions.reserve(self.before);self.actions.finish(dict(attempted=True,handler_returned=True))
        self.assertEqual(self.actions.observe(self.before),'handler-returned')
        after=copy.deepcopy(self.before);after['messages'].insert(0,message('900','100',QUESTION))
        self.store.consume(after,preview=True)
        self.assertEqual(self.actions.observe(after),'outgoing-observed')
        public=report(send_state=self.actions.state())
        self.assertTrue(public['outgoing_observed']);self.assertFalse(public['delivery_confirmed'])
        self.assertIsNone(public['messages_sent']);self.assertFalse(public['retry_allowed'])
        self.assertFalse(public['automatic_replies_available'])
        self.store.close();self.store=TestChatStore(self.path);self.actions=Actions(self.store)
        self.assertEqual(self.actions.state(),'outgoing-observed')
        with self.assertRaises(ValueError):self.actions.reserve(after)

    def test_incoming_wrong_reply_or_multiple_delta_never_claim_success(self):
        self.actions.reserve(self.before)
        for extra in ([message('1004','200',QUESTION)], [message('1004','100','OTHER')],
                      [message('1004','100',QUESTION),message('1005','200','Reply')]):
            after=copy.deepcopy(self.before);after['messages']+=extra
            self.assertEqual(self.actions.observe(after),'reserved-unknown')
        changed=copy.deepcopy(self.before);changed['messages'][0]['text']='edited'
        with self.assertRaises(ValueError):self.actions.observe(changed)

    def test_ledger_never_saves_message_bodies_or_raw_message_ids(self):
        self.actions.reserve(self.before)
        status,baseline=self.store.db.execute('SELECT status,baseline FROM test_manual_send').fetchone()
        for text in (TEST_TEXT,QUESTION,'PRIVATE TEST TEXT'):
            self.assertNotIn(text,baseline)
        self.assertTrue(all(len(k)==len(v)==64 and k not in {'1001','1002','1003'} for k,v in json.loads(baseline).items()))

    def test_fixed_report_rejects_arbitrary_state_and_flags(self):
        with self.assertRaises(ValueError):report(send_state='PRIVATE')
        with self.assertRaises(ValueError):report(transcript_saved=1)
        public=report(send_state='reserved-unknown',transcript_saved=True)
        self.assertTrue(public['local_transcript_saved'])
        self.assertFalse(public['message_text_in_report'])
        self.assertNotIn(TEST_TEXT,json.dumps(public,ensure_ascii=False))

    def test_empty_or_full_history_is_not_submittable(self):
        for messages in ([],[message(str(2000+i),'200',TEST_TEXT) for i in range(20)]):
            with self.assertRaises(ValueError):sender.checked(dict(identity=WHO,messages=messages))


class SenderSchema(unittest.TestCase):
    def value(self,attempted=True,returned=True):
        r=rpc();r['navigation'].update(submission_attempted=attempted,submission_returned=returned,
            app_actions_attempted=attempted,messages_sent=None if attempted else 0)
        return r

    def test_fixed_text_exact_binding_two_snapshots_and_latch_before_call(self):
        source=sender.build(snap())
        self.assertIn('oneSubmissionAttempted=true',source)
        self.assertLess(source.index("JSON.stringify(who)!==JSON.stringify(expectedIdentity)"),source.index('call(s.submit,current,args)'))
        self.assertLess(source.index("canonical(messages)!==canonical("),source.index('oneSubmissionAttempted=true'))
        self.assertLess(source.index('oneSubmissionAttempted=true'),source.index('call(s.submit,current,args)'))
        self.assertEqual(source.count('call(s.submit,current,args)'),1)
        for forbidden in ('set_Text','OnMessageButton','ShowSearchSettings','DismissWithCancel','NativeCallback','Interceptor.replace'):
            self.assertNotIn(forbidden,source)
        self.assertIn(json.dumps(QUESTION),source)

    def test_strict_submission_flags_and_private_snapshot(self):
        before=dict(identity=WHO,messages=[message()])
        self.assertEqual(sender.validate(self.value(),before),dict(attempted=True,handler_returned=True))
        for change in [dict(submission_returned=1),dict(submission_attempted=False),dict(messages_sent=1),dict(app_actions_attempted=False)]:
            r=self.value();r['navigation'].update(change)
            with self.assertRaises(ValueError):sender.validate(r,before)
        r=self.value();r['navigation']['private_result']['messages'][0]['text']='CHANGED'
        with self.assertRaises(ValueError):sender.validate(r,before)

    def test_transport_cleanup_after_submission_and_after_timeout(self):
        from test_diagnose_device import FakeFrida
        r=self.value()
        class Fake(FakeFrida):
            def create_script(self,source,name):
                super().create_script(source,name)
                self.exports_sync.root=lambda:r
                self.exports_sync.cancel=lambda:None
                return self
        f=Fake()
        result=transport.inspect_submission(37149,'a'*64,lambda:False,dict(identity=WHO,messages=[message()]),frida_api=f)
        self.assertTrue(result['attempted'])
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
        f=Fake()
        with self.assertRaises(Exception):transport.inspect_submission(37149,'a'*64,lambda:True,dict(identity=WHO,messages=[message()]),frida_api=f)
        self.assertIsNone(f.attached_to)

    def test_submission_diagnostic_is_closed_and_contains_no_private_text(self):
        value=self.value()
        diag=sender.diagnostic(value)
        self.assertNotIn('PRIVATE',json.dumps(diag))
        with self.assertRaises(ValueError):sender.checked_diagnostic(dict(diag,navigation_error='PRIVATE'))
        with self.assertRaises(ValueError):sender.checked_diagnostic(dict(diag,private='TEXT'))
        public=report(send_state='handler-returned',submission_check=diag)
        self.assertEqual(public['submission_check'],diag)
        self.assertIsNone(report(failure=True,transcript_saved=None)['local_transcript_saved'])

    def test_submit_uses_existing_fixed_target_capture_without_fallback(self):
        before=snap()
        def capture(executable,folder,cancelled,expected,*,inspector):
            self.assertEqual(expected,WHO)
            return inspector(37149,'private',cancelled,expected)
        with patch.object(transport,'capture',side_effect=capture),patch.object(transport,'inspect_submission',return_value=dict(attempted=True,handler_returned=True)) as invoke:
            self.assertTrue(transport.submit('adb','test-apks',before)['handler_returned'])
            self.assertEqual(invoke.call_count,1)


class LocalTranscript(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)

    def test_explicit_save_is_local_plaintext_latest_snapshot(self):
        path=local.save(snap(),WHO,self.folder)
        self.assertEqual(path.name,'one-chat-transcript.json')
        data=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['messages'],list(reversed(snap()['messages'])))
        self.assertEqual(data['identity'],WHO)
        self.assertFalse(data['chronological_order_verified'])
        newer=snap([message('1003','200','new control')]);local.save(newer,WHO,self.folder)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['messages'],list(reversed(newer['messages'])))
        self.assertEqual(len(list(self.folder.iterdir())),1)
        if os.name!='nt':self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_view_and_file_reverse_newest_first_without_mutating_source(self):
        # Deliberately non-monotonic IDs: order is NEVER inferred from their value.
        sample=dict(identity=dict(WHO),messages=[message('8','200','NEWEST_TEXT'),
            message('100','100','MIDDLE_TEXT'),message('9','200','OLDEST_TEXT')])
        original=copy.deepcopy(sample)
        shown=local.display(sample,WHO)
        self.assertLess(shown.index('OLDEST_TEXT'),shown.index('MIDDLE_TEXT'))
        self.assertLess(shown.index('MIDDLE_TEXT'),shown.index('NEWEST_TEXT'))
        path=local.save(sample,WHO,self.folder)
        saved=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual([m['text'] for m in saved['messages']],['OLDEST_TEXT','MIDDLE_TEXT','NEWEST_TEXT'])
        self.assertEqual(saved['format'],'owned-test-chat-latest-snapshot-v2')
        self.assertEqual(saved['presentation_order'],'reversed-source-collection')
        self.assertFalse(saved['chronological_order_verified'])
        self.assertEqual(sample,original)
        # Output dictionaries are copies, not aliases into the source snapshot.
        copied=local.presentation_messages(sample,WHO);copied[0]['text']='CHANGED_COPY'
        self.assertEqual(sample,original)

    def test_empty_single_nontext_and_unicode_presentations(self):
        for messages in ([],[message('1','200','Привет 🌸')],
                         [message('2','200','Новое 👋'),message('1','100',None)]):
            sample=dict(identity=dict(WHO),messages=messages)
            self.assertEqual(local.presentation_messages(sample,WHO),list(reversed(messages)))
            path=local.save(sample,WHO,self.folder)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['messages'],list(reversed(messages)))
            local.display(sample,WHO)

    def test_view_and_save_do_not_affect_dedup_or_single_send_limit(self):
        path=self.folder/'one-chat-check.sqlite3';store=TestChatStore(path)
        try:
            store.bind(WHO);store.consume(snap())
            sample=snap([message('1003','200',TEST_TEXT)])
            store.consume(sample,preview=True);actions=Actions(store);actions.reserve(sample)
            local.display(sample,WHO);local.save(sample,WHO,self.folder)
            self.assertEqual(store.consume(sample,preview=True)['new_incoming'],0)
            self.assertEqual(actions.state(),'reserved-unknown')
            with self.assertRaises(ValueError):actions.reserve(sample)
        finally:store.close()

    def test_wrong_binding_or_invalid_data_never_writes(self):
        for bad in (dict(snap(),identity=dict(WHO,chat='301')),dict(snap(),messages=[message(text='bad\0')])):
            with self.assertRaises(ValueError):local.save(bad,WHO,self.folder)
        self.assertEqual(list(self.folder.iterdir()),[])

    def test_failed_replace_keeps_previous_snapshot_and_removes_temp(self):
        path=local.save(snap(),WHO,self.folder);raw=path.read_bytes()
        with patch.object(local.os,'replace',side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):local.save(snap([message('1003','200','new')]),WHO,self.folder)
        self.assertEqual(path.read_bytes(),raw)
        self.assertEqual(len(list(self.folder.iterdir())),1)

    def test_local_view_is_plain_text_no_claim_of_chronology(self):
        value=local.display(snap([message('1003','200',None)]),WHO)
        self.assertIn('НЕ подтверждён',value)
        self.assertIn('[Нетекстовое сообщение]',value)
        self.assertIn('PRIVATE TEST TEXT',value)


class AiTextTransport(unittest.TestCase):
    def test_safe_dynamic_text_reaches_native_source_through_real_submit(self):
        texts = ('Взаимно 🙂 Как настроение?', 'Понимаю. Обменяемся Telegram?',
                 'Ты написал «Привет». Как дела?')
        for text in texts:
            def capture(adb, folder, cancelled, expected, *, inspector):
                return inspector(1234, 'synthetic', cancelled, expected)
            def inspect(port, token, cancelled, before, *, text):
                return sender.build(before, text=text)
            with patch.object(transport, 'capture', side_effect=capture), patch.object(
                    transport, 'inspect_submission', side_effect=inspect):
                source = transport.submit('adb', 'test-apks', snap(), text=text)
            self.assertIn(json.dumps(text), source)
            self.assertEqual(source.count('call(s.submit,current,args)'), 1)

    def test_invalid_dynamic_text_never_opens_device(self):
        for text in ('Привет', 'Привет! Как настроение?', 'Как дела? @somebody', 'Как дела? https://example.com',
                     'Как дела?\n', '<script>Как дела?</script>', 'Как дела?' + 'x'*241, None, []):
            with patch.object(transport, 'capture') as capture:
                with self.assertRaises(ValueError):
                    transport.submit('adb', 'test-apks', snap(), text=text)
                capture.assert_not_called()


if __name__=='__main__':unittest.main()
