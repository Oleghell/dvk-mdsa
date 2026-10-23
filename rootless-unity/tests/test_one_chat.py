import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import one_chat_probe as p
from one_chat_store import TestChatStore
import one_chat_device as device
from test_chat_state_probe import ready
from test_target_only import TargetOnly, BOOT, OTHER_BOOT
from test_device import TARGET, WORKING, TestError

WHO = dict(account='100',peer='200',chat='300')


def message(mid='1001',sender='100',text='PRIVATE TEST TEXT'):
    return dict(id=mid,sender=sender,text=text)


def rpc(messages=None):
    messages=messages if messages is not None else [message()]
    value=ready(len(messages))
    value['navigation'].update(scalar_checkpoint='message-chat-id',scalar_state='positive',identity_checkpoint='recheck',message_slot=0 if messages else -1,message_kind='text' if messages else 'not-read',message_direction='own' if messages else 'not-read')
    value['navigation']['private_result']=dict(identity=dict(WHO),messages=messages)
    return value


class Schema(unittest.TestCase):
    def test_valid_private_snapshot_is_not_a_public_report(self):
        private=p.private_snapshot(rpc(),WHO)
        self.assertEqual(private['messages'][0]['text'],'PRIVATE TEST TEXT')
        public=device.report(dict(status='read-complete',observed_messages=1,incoming_messages=0,new_incoming=0,baseline_recorded=True))
        self.assertNotIn('PRIVATE',json.dumps(public))
        self.assertFalse(public['chronological_order_verified'])
        self.assertEqual(public['messages_sent'],0)

    def test_wrong_identity_bad_message_and_unknown_fields_fail(self):
        mutations=[lambda r:r['navigation']['private_result']['identity'].update(peer='201'),
                   lambda r:r['navigation']['private_result']['messages'][0].update(sender='999'),
                   lambda r:r['navigation']['private_result']['messages'][0].update(id=True),
                   lambda r:r['navigation']['private_result']['messages'][0].update(text='x'*8193),
                   lambda r:r['navigation']['private_result']['messages'][0].update(text='x\x00'),
                   lambda r:r['navigation'].update(private_extra='PRIVATE'),
                   lambda r:r['navigation'].update(messages_sent=1),
                   lambda r:r.update(main_thread_confirmed=False),
                   lambda r:r['navigation'].update(handles_released=0)]
        for change in mutations:
            value=rpc();change(value)
            with self.assertRaises(ValueError):p.private_snapshot(value,WHO)

    def test_duplicate_and_mismatched_counts_rejected(self):
        with self.assertRaises(ValueError):p.private_snapshot(rpc([message(),message()]),WHO)
        value=rpc();value['navigation']['private_result']['messages']=[]
        with self.assertRaises(ValueError):p.private_snapshot(value,WHO)

    def test_fixed_code_bound_before_bodies_no_actions_or_unsafe_ids(self):
        source=p.build(WHO)
        for forbidden in ('OnSend','set_Text','ShowSearchSettings','DismissWithCancel','OnMessageButton','NativeCallback','Interceptor.replace','class_get_methods','field_get_value'):
            self.assertNotIn(forbidden,source)
        self.assertLess(source.index("JSON.stringify(who)!==JSON.stringify(expectedIdentity)"),source.index('const messages=[],seenIds'))
        self.assertIn('JSON.stringify(state.sample)!==JSON.stringify(sample)',source)
        self.assertIn('first>128',source)
        self.assertIn('readS64()',source)
        self.assertNotIn('readS64().toNumber',source)
        for who in (dict(account='100',peer='200;evil()',chat='300'),dict(account='100',peer='100',chat='300'),dict(account='100',peer='200',chat='9223372036854775808')):
            with self.assertRaises(ValueError):p.build(who)
        p.build(dict(account='9007199254740993',peer='9007199254740994',chat='9223372036854775807'))

    def test_negative_own_chat_requires_peer_anchor_and_stable_collection_headers(self):
        source=p.build(WHO)
        self.assertIn("if(chunk.localOwn>0&&chunk.peerAnchors===0)fail('local-own-message-unanchored')", source)
        self.assertIn("(!chatId.startsWith('-')&&chatId!==who.chat)", source)
        self.assertIn("bits.sender===who.peer&&!bits.mine&&bits.chatId===who.chat", source)
        self.assertLess(source.index('if(chunk.localOwn>0&&chunk.peerAnchors===0)'),
                        source.index('const value=call(s.messageText,message)'))
        self.assertIn("message.toString()!==row.pointer", source)
        self.assertIn("JSON.stringify(messageHeader(message))!==JSON.stringify(row.bits)", source)
        self.assertIn("identity:who,messages,messageBindings", source)
        self.assertNotIn("Math.abs", source)
        # Local per-message marks never change the positive public identity schema.
        with self.assertRaises(ValueError):
            p.identity(dict(WHO,chat='-1'))
        self.assertIn("id64(s.chatId,chat,'chat-id')", source)

    def test_report_accepts_only_fixed_counters(self):
        for data in (dict(status='PRIVATE'),dict(status='read-complete',observed_messages=True,incoming_messages=0,new_incoming=0,baseline_recorded=True)):
            with self.assertRaises(ValueError):device.report(data)


class Durable(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'one-chat-check.sqlite3'
        self.store=TestChatStore(self.path);self.addCleanup(lambda:self.store.close())
        self.store.bind(WHO)

    def snap(self,extra=()):
        return dict(identity=dict(WHO),messages=[message(),message('1002','200')]+list(extra))

    def test_baseline_then_new_then_repeat_and_restart(self):
        self.assertEqual(self.store.consume(self.snap())['status'],'baseline-recorded')
        newer=self.snap([message('1003','200','CONTROL REPLY')])
        self.assertEqual(self.store.consume(newer)['new_incoming'],1)
        self.assertEqual(self.store.consume(newer)['new_incoming'],0)
        self.store.close();self.store=TestChatStore(self.path)
        self.assertEqual(self.store.consume(newer)['new_incoming'],0)
        self.assertEqual(self.store.bound(),WHO)

    def test_outgoing_not_counted_new_and_collection_order_irrelevant(self):
        self.store.consume(self.snap())
        newer=self.snap([message('1003','100')]);newer['messages'].reverse()
        self.assertEqual(self.store.consume(newer)['new_incoming'],0)

    def test_no_body_or_plain_message_ids_in_database(self):
        self.store.consume(self.snap())
        raw=self.path.read_bytes()
        self.assertNotIn(b'PRIVATE TEST TEXT',raw)
        rows=self.store.db.execute('SELECT message_key FROM test_seen').fetchall()
        self.assertTrue(all(len(row[0])==64 and row[0] not in ('1001','1002') for row in rows))

    def test_cannot_rebind_or_consume_unknown_dialog(self):
        different=dict(WHO,peer='201')
        with self.assertRaises(ValueError):self.store.bind(different)
        snap=self.snap();snap['identity']=different
        with self.assertRaises(ValueError):self.store.consume(snap)
        self.assertEqual(self.store.bound(),WHO)

    def test_changed_or_deleted_history_stops_without_consuming_new_event(self):
        original=self.snap();self.store.consume(original)
        for change in ('edit','delete'):
            newer=self.snap([message('1003','200')])
            if change=='edit':newer['messages'][0]['text']='edited'
            else:newer['messages'].pop(0)
            with self.assertRaises(ValueError):self.store.consume(newer)
        self.assertEqual(self.store.consume(self.snap([message('1003','200')]))['new_incoming'],1)

    def test_separate_path_never_opens_enrollment_or_review(self):
        for name in ('new-ten.sqlite3','reply-review.sqlite3','new-ten.sqlite3-wal'):
            with self.assertRaises(ValueError):TestChatStore(self.path.parent/name)
            self.assertFalse((self.path.parent/name).exists())


class ReadTransport(TargetOnly):
    """Reuses all fixed-endpoint ADB tests, adds the independent reader path."""
    def run_capture(self,inspector=lambda *args:dict(identity=WHO,messages=[])):
        with self.patched(),patch.object(device,'TargetOnlyAdb',return_value=self.adb),patch.object(device,'bundle_token',return_value='PRIVATE TOKEN'):
            return device.capture('adb',self.folder,expected=WHO,inspector=inspector)

    def test_reader_no_working_endpoint_and_forward_removed(self):
        private=self.run_capture()
        self.assertEqual(private['identity'],WHO)
        self.assertFalse(any(WORKING in a for a in self.calls))
        self.assertIn(['-s',TARGET,'forward','--remove','tcp:37149'],self.calls)

    def test_reader_rechecks_boot_after_read_before_return(self):
        self.identities=iter((BOOT,BOOT,OTHER_BOOT))
        with self.assertRaises(TestError):self.run_capture()
        self.assertIn(['-s',TARGET,'forward','--remove','tcp:37149'],self.calls)

    def test_reader_auth_error_no_retry_and_forward_removed(self):
        calls=[]
        def failed(*args):calls.append(1);raise RuntimeError('PRIVATE TOKEN')
        with self.assertRaises(RuntimeError):self.run_capture(failed)
        self.assertEqual(calls,[1])
        self.assertIn(['-s',TARGET,'forward','--remove','tcp:37149'],self.calls)

    def test_reader_cleanup_failure_prevents_returning_snapshot(self):
        old=self.adb_run
        def bad(adb,args,timeout=30):
            if '--remove' in args:raise TestError('cleanup')
            return old(adb,args,timeout)
        self.adb_run=bad
        with self.assertRaises(TestError):self.run_capture()

    def test_failure_stage_post_read_identity_and_cleanup_no_secrets(self):
        from startup_failure import clean
        self.identities=iter((BOOT,BOOT,OTHER_BOOT))
        with self.assertRaises(TestError) as raised:self.run_capture()
        self.assertEqual(clean(raised.exception._dvk_failure)['stage'],'device-recheck-after')

    def test_failure_stage_inspector_is_preserved_without_retry(self):
        from startup_failure import record
        e=RuntimeError('PRIVATE TOKEN');record(e,'script-run')
        from unittest.mock import MagicMock
        reader=MagicMock(side_effect=e)
        with self.assertRaises(RuntimeError) as raised:self.run_capture(reader)
        self.assertEqual(raised.exception._dvk_failure['stage'],'script-run')
        reader.assert_called_once()

    def test_failure_stage_cleanup_blocks_success(self):
        old=self.adb_run
        def bad(adb,args,timeout=30):
            if '--remove' in args:raise TestError('PRIVATE CLEANUP')
            return old(adb,args,timeout)
        self.adb_run=bad
        with self.assertRaises(TestError) as raised:self.run_capture()
        self.assertEqual(raised.exception._dvk_failure['stage'],'forward-close')



class Inspector(unittest.TestCase):
    def fake(self, result=None):
        from test_diagnose_device import FakeFrida
        class ReaderFake(FakeFrida):
            def create_script(self,source,name):
                super().create_script(source,name)
                self.exports_sync.root=lambda:result if result is not None else rpc()
                self.exports_sync.cancel=lambda:None
                return self
        return ReaderFake()

    def test_private_read_cleanup_and_fixed_rpc(self):
        f=self.fake()
        private=device.inspect(37149,'a'*64,lambda:False,WHO,frida_api=f)
        self.assertEqual(private['messages'][0]['text'],'PRIVATE TEST TEXT')
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
        self.assertNotIn('OnSend',f.script_source)
        self.assertNotIn('rpc.exports.send',f.script_source)

    def test_unknown_process_and_cancel_never_attach(self):
        for cancel,name in ((True,'Gadget'),(False,'other-process')):
            f=self.fake();f.name=name
            with self.assertRaises(device.ReadStopped):device.inspect(37149,'a'*64,lambda:cancel,WHO,frida_api=f)
            self.assertIsNone(f.attached_to)

    def test_failure_diagnostics_do_not_include_private_data(self):
        r=rpc();n=r['navigation'];n.update(stage='navigation-stopped',error='history-not-ready',private_result=None,history_status='unknown',message_count=None,samples=1)
        f=self.fake(r)
        with self.assertRaises(device.ReadStopped) as raised:device.inspect(37149,'a'*64,lambda:False,WHO,frida_api=f)
        self.assertNotIn('PRIVATE',json.dumps(raised.exception.diagnostic))
        self.assertNotIn('identity',raised.exception.diagnostic)
        self.assertNotIn('account',raised.exception.diagnostic)
        self.assertNotIn('peer',raised.exception.diagnostic)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)

    def test_gui_has_no_autostart(self):
        import sys
        from unittest.mock import MagicMock
        import diagnose_one_chat as gui
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk
        tk.Tk.return_value.winfo_height.return_value=560
        ttk.Frame.return_value.winfo_reqheight.return_value=530
        ttk.Frame.return_value.winfo_reqwidth.return_value=600
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}),patch.object(gui,'capture') as capture,patch.object(gui,'TestChatStore') as store,patch.object(gui.threading,'Thread') as thread:
            gui.launch_gui()
            capture.assert_not_called();store.assert_not_called();thread.assert_not_called()
            labels=[c.kwargs.get('text') for c in ttk.Button.call_args_list]
            self.assertIn('Старт',labels)
            self.assertIn('Стоп',labels)
            self.assertIn('Проверить один раз',labels)
            self.assertIn('Настройки',labels)
            self.assertNotIn('Тестовая отправка · один раз',labels)


class ScalarDiagnostics(unittest.TestCase):
    def test_closed_enums_no_raw_ids_or_private_values(self):
        for label in p.SCALAR_CHECKPOINTS:
            d=dict(scalar_checkpoint=label,scalar_state='not-read',identity_checkpoint='initial-ids',message_slot=-1,message_kind='not-read',message_direction='not-read')
            self.assertEqual(p.diagnostic(d),d)
        for key,bad in [('scalar_checkpoint','PRIVATE'),('scalar_state','-1234'),('identity_checkpoint','PRIVATE'),('message_slot',True),('message_slot',128)]:
            d=dict(scalar_checkpoint='message-id',scalar_state='zero',identity_checkpoint='recheck',message_slot=0,message_kind='text',message_direction='own')
            d[key]=bad
            with self.assertRaises(ValueError):p.diagnostic(d)

    def test_failed_nonpositive_id_reports_label_and_sign_not_value(self):
        value=rpc();n=value['navigation']
        n.update(stage='navigation-stopped',error='nonpositive-message-id',private_result=None,history_status='unknown',message_count=None,samples=0,scalar_checkpoint='message-id',scalar_state='negative')
        self.assertIsNone(p.private_snapshot(value,WHO))
        diag=p.diagnostic(n)
        self.assertEqual(diag['scalar_state'],'negative')
        self.assertNotIn('PRIVATE',json.dumps(diag))
        f=Inspector().fake(value)
        with self.assertRaises(device.ReadStopped) as exc:device.inspect(37149,'a'*64,lambda:False,WHO,frida_api=f)
        self.assertEqual(exc.exception.diagnostic['scalar_checkpoint'],'message-id')
        self.assertNotIn('PRIVATE',json.dumps(exc.exception.diagnostic))

    def test_diagnostic_fields_never_allow_unsafe_history_or_weaker_identity(self):
        source=p.build(WHO)
        self.assertIn("if(sign<=0&&!(sign<0&&allowLocalChat&&label==='message-chat-id'))fail",source)
        self.assertIn("message-chat-id',mine&&sender===who.account)",source)
        self.assertIn("if(expectedIdentity!==null&&JSON.stringify(who)!==JSON.stringify(expectedIdentity))fail('identity-not-bound')",source)
        self.assertIn("value=p.readS64()",source)
