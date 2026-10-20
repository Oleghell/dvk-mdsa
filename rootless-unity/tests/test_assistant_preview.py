from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import assistant_preview as preview
from assistant_store import Store, StateError
from test_profile_batch import good, exhausted
from test_profile_navigation import ProfileFake, ready_profile


def result(count=13):
    value = good(count)
    value['navigation'].update(scan_yields=0, scan_slices=1)
    return value


def empty():
    value = exhausted()
    value['navigation'].update(scan_yields=0, scan_slices=3)
    return value


class Preview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/'assistant.sqlite3', Path(self.temp.name)/'old')

    def test_five_checked_and_durable_visits_without_send_reservations(self):
        calls = []
        def root():
            calls.append(1)
            return result((0,49,50,97,10)[len(calls)-1])
        out = preview.walk(root, lambda: str(len(calls)), self.store, [])
        self.assertEqual(len(calls), 5)
        self.assertEqual((out['checked'],out['eligible'],out['skipped']), (5,3,2))
        self.assertEqual(out['status'], 'preview-completed')
        self.assertEqual(out['chats_opened'], 0)
        self.assertEqual(out['messages_sent'], 0)
        self.assertEqual(Store(self.store.path).visited_peers(), ['1','2','3','4','5'])
        self.assertEqual(self.store.summary()['reserved'], 0)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT DISTINCT history_status FROM profile_visits').fetchall(), [('not-opened',)])

    def test_only_visible_exhaustion_not_end_of_feed(self):
        values = iter([result(), empty()])
        out = preview.walk(lambda: next(values), lambda: '1', self.store, [])
        self.assertEqual((out['status'],out['checked']), ('preview-exhausted',1))
        self.assertIn('Это не конец всей ленты', preview.status_text(out))

    def test_existing_send_reservation_is_excluded_and_never_reset(self):
        pending=dict(attempt=1,account='100',peer='200',chat='-1',variant=0)
        self.store.reserve(pending,'Hi',approved=True)
        before=self.store.summary()
        visited=self.store.visited_peers()
        self.assertEqual(visited,['200'])
        self.assertIn('batchSeen=new Set(["200"])',preview.build(visited))
        calls=[]
        def root():
            calls.append(1)
            return result()
        preview.walk(root,lambda:str(len(calls)),self.store,visited)
        self.assertEqual(self.store.summary(),before)

    def test_stop_before_start_and_between_profiles(self):
        for at in (0,2):
            calls = []
            def root():
                calls.append(1)
                return result()
            out = preview.walk(root, lambda: str(len(calls)), self.store, [],
                               cancelled=lambda: len(calls)>=at)
            self.assertEqual(len(calls),at)
            self.assertEqual(out['status'],'preview-cancelled')

    def test_stop_from_progress_does_not_start_another_profile(self):
        stopped = []
        root = MagicMock()
        out = preview.walk(root, lambda: '1', self.store, [],
                           cancelled=lambda: bool(stopped),
                           progress=lambda text: stopped.append(True))
        root.assert_not_called()
        self.assertEqual((out['attempts'],out['status']),(0,'preview-cancelled'))

    def test_rpc_failure_during_stop_remains_cancelled_and_uncertain(self):
        stopped=[]
        def root():
            stopped.append(True)
            raise RuntimeError('PRIVATE')
        out=preview.walk(root,lambda:'1',self.store,[],cancelled=lambda:bool(stopped))
        self.assertEqual(out['status'],'preview-cancelled')
        self.assertTrue(out['profile_may_remain_open'])

    def test_unknown_count_is_not_zero_and_stops(self):
        value = ready_profile()
        value['navigation'].update(scan_yields=0,scan_slices=1)
        out = preview.walk(lambda: value, lambda: '1', self.store, [])
        self.assertEqual((out['unknown'],out['checked'],out['eligible']),(1,0,0))
        self.assertEqual(out['reason'],'count-unavailable')

    def test_malformed_or_exception_result_is_sanitized_and_not_retried(self):
        bad = result()
        bad['navigation']['private'] = 'PRIVATE TOKEN'
        for root in (MagicMock(return_value=bad),MagicMock(side_effect=RuntimeError('PRIVATE TOKEN'))):
            out = preview.walk(root, lambda:'1',self.store,[])
            self.assertEqual(out['reason'],'probe-failed')
            self.assertTrue(out['profile_may_remain_open'])
            self.assertNotIn('PRIVATE',json.dumps(out))
            root.assert_called_once()
        self.assertEqual(self.store.visited_peers(),[])

    def test_journal_failure_or_repeated_identity_stops_before_next_profile(self):
        for peer in ('1',None,'1;code()'):
            root = MagicMock(return_value=result())
            with self.assertRaises(StateError):
                preview.walk(root,lambda:peer,self.store,['1'])
            root.assert_called_once()
        root = MagicMock(return_value=result())
        with patch.object(self.store,'record_visit',side_effect=OSError('PRIVATE TOKEN')):
            with self.assertRaisesRegex(StateError,'Не удалось сохранить'):
                preview.walk(root,lambda:'2',self.store,[])
        root.assert_called_once()

    def test_fixed_profile_only_source_and_visited_limits(self):
        source = preview.build(['7','8'])
        for text in ('batchSeen=new Set(["7", "8"])','batchAttempts>=5','batchAttempts>5',
                     'previewSelectedPeer=identityKey','scan_slices','get_FriendsCount'):
            self.assertIn(text,source)
        for text in ('OnSendText','OnMessageButton','set_Text','get_Text','get_PhoneNumber',
                     'ShowRegionPicker','input tap','cohortack','batchSeen.size>=10'):
            self.assertNotIn(text,source)
        for visited in (['1;code()'],['0'],[True],['1']*10001,{'1'}):
            with self.assertRaises(Exception):
                preview.build(visited)

    def test_strict_scan_validation_preserves_profile_guards(self):
        for key,value in (('scan_yields',9),('scan_slices',181),('scan_yields',True),
                          ('profile_verified',False),('ui_text_read',True)):
            v=result()
            v['navigation'][key]=value
            with self.assertRaises(ValueError):
                preview.validate(v)


class PreviewFake(ProfileFake):
    def create_script(self,source,name):
        super().create_script(source,name)
        self.roots=0
        def root():
            self.roots+=1
            return result()
        self.exports_sync.root=root
        self.exports_sync.selectedpeer=lambda:str(self.roots)
        return self


class Transport(unittest.TestCase):
    def test_single_script_with_existing_restricted_transport_and_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'assistant.sqlite3',Path(folder)/'old')
            f=PreviewFake()
            out=preview.inspect(37149,'a'*64,lambda:False,store,lambda text:None,frida_api=f)
            self.assertEqual((f.roots,out['checked']),(5,5))
            self.assertEqual(f.script_name,'dvk-assistant-profile-preview')
            self.assertTrue(f.script_unloaded and f.detached and f.removed)
            self.assertNotIn('send(',f.script_source)
            self.assertEqual(store.summary()['reserved'],0)

    def test_wrapper_uses_capture_and_shared_lock_not_legacy_diagnose(self):
        with tempfile.TemporaryDirectory() as folder, patch('assistant_lock.operation_lock') as lock, \
             patch('one_chat_device.capture',return_value='ok') as capture:
            self.assertEqual(preview.run('ADB',folder,store=MagicMock()),'ok')
            lock.return_value.__enter__.assert_called_once()
            self.assertEqual(capture.call_args.args[:2],('ADB',Path(folder).resolve()))

    def test_cancellation_summary_survives_capture_but_cleanup_error_does_not(self):
        from one_chat_device import ReadStopped
        for error in (ReadStopped('cancelled'),OSError('cleanup-failed')):
            with tempfile.TemporaryDirectory() as folder:
                summary=dict(status='preview-completed',checked=2)
                def capture(executable,directory,cancelled,*,inspector):
                    inspector(37149,'a'*64,cancelled,None)
                    raise error
                with patch('assistant_lock.operation_lock'),patch('one_chat_device.capture',side_effect=capture), \
                     patch.object(preview,'inspect',return_value=summary):
                    if isinstance(error,ReadStopped):
                        out=preview.run('ADB',folder,store=MagicMock())
                        self.assertEqual((out['status'],out['checked']),('preview-cancelled',2))
                    else:
                        with self.assertRaises(OSError):
                            preview.run('ADB',folder,store=MagicMock())


@contextmanager
def gui(consent=True):
    import assistant_app as app
    tk,ttk=MagicMock(),MagicMock()
    tk.ttk=ttk
    tk.StringVar.return_value.get.return_value='C:/private/test-apks'
    tk.BooleanVar.return_value.get.return_value=consent
    summary=dict(limit=5,status='preview-completed',reason='limit-reached',
                 attempts=5,visited=5,checked=5,eligible=3,skipped=2,unknown=0,
                 profile_may_remain_open=False,chats_opened=0,messages_sent=0)
    with tempfile.TemporaryDirectory() as folder, \
         patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}), \
         patch.object(app,'data_directory',return_value=Path(folder)), \
         patch.object(app,'preview_profiles',return_value=summary) as native, \
         patch.object(app,'run') as send,patch.object(app,'select_city') as city, \
         patch.object(app.threading,'Thread') as thread:
        app.launch()
        commands={c.kwargs.get('text'):c.kwargs.get('command') for c in ttk.Button.call_args_list}
        poll=next(c.args[1] for c in tk.Tk.return_value.after.call_args_list
                  if len(c.args)==2 and getattr(c.args[1],'__name__','')=='poll')
        yield tk,commands,poll,thread,native,send,city,Path(folder)


class Window(unittest.TestCase):
    def test_no_auto_start_or_preview_without_consent(self):
        with gui(False) as (tk,buttons,poll,thread,native,send,city,folder):
            thread.assert_not_called()
            buttons['Просмотреть до 5 анкет без сообщений']()
            thread.assert_not_called()
            native.assert_not_called()
            send.assert_not_called()
            city.assert_not_called()

    def test_busy_progress_stop_and_private_summary(self):
        with gui() as (tk,buttons,poll,thread,native,send,city,folder):
            buttons['Просмотреть до 5 анкет без сообщений']()
            def check_progress(executable,directory,cancelled,progress):
                progress('Анкета 1/5')
                poll()
                # Progress is not completion and must not unlock other buttons.
                buttons['Проверить одну анкету']()
                buttons['Выбрать город и онлайн']()
                buttons['Просмотреть до 5 анкет без сообщений']()
                thread.return_value.start.assert_called_once()
                buttons['Стоп']()
                self.assertTrue(cancelled())
                return native.return_value
            native.side_effect=check_progress
            thread.call_args.kwargs['target']('ADB','APKS')
            poll()
            report=json.loads((folder/'last-preview.json').read_text(encoding='utf-8'))
            self.assertEqual((report['messages_sent'],report['chats_opened']),(0,0))
            self.assertNotIn('private',json.dumps(report))
            send.assert_not_called()
            city.assert_not_called()