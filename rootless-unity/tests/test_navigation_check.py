"""No real account: verify the GUI diagnostic cannot read/send or mutate journals."""
import json,sqlite3,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

import assistant_navigation_check as n
import assistant_cycle as cycle
from assistant_settings import Settings
from test_assistant_dialogs import WHO,diag,nav_result


class NavigationCheck(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'journal.sqlite3'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE manual_actions(id INTEGER,account TEXT,peer TEXT,initial_chat TEXT,status TEXT)')
            db.execute("INSERT INTO manual_actions VALUES(1,'100','200','-1','handler-returned-unconfirmed')")
        self.stop=threading.Event()
        self.nav=MagicMock(side_effect=[nav_result('opened',WHO),nav_result('returned',WHO),nav_result('search-ready')])

    def walk(self,**kwargs):
        return n.walk(Settings(contacts_enabled=True),self.stop,navigator=self.nav,journal_path=self.path,**kwargs)

    def test_one_roundtrip_never_reads_sends_notifies_or_changes_journal(self):
        before=self.path.read_bytes()
        with patch('one_chat_device.capture') as read,patch('one_chat_send_device.submit') as send, \
             patch('telegram_notify.load') as credentials,patch('telegram_notify.send_contact') as telegram, \
             patch('assistant_chain.step') as step:
            out=self.walk()
        self.assertEqual(out['status'],'dialogs-completed');self.assertTrue(out['return_verified'])
        self.assertEqual(out['navigation_dialogs_checked'],1);self.assertEqual(out['dialogs_opened'],1)
        self.assertEqual(out['reply_submission_calls'],0);self.assertEqual(out['dialogs_processed'],0)
        for mock in (read,send,credentials,telegram,step):mock.assert_not_called()
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual([c.args[0] for c in self.nav.call_args_list],['open','back','return'])
        for text in ('account','peer','PRIVATE','100','200','300'):
            self.assertNotIn(text,json.dumps(out))
        self.assertTrue(out['journal_read_only']);self.assertFalse(out['chat_content_read'])

    def test_exact_failure_category_survives_without_retry(self):
        result=nav_result('stopped')
        result['diagnostic'].update(stage='navigation-stopped',error='selection-list-changed',phase='scan',
                                    selection_checkpoint='stability',destination_verified=False)
        self.nav.side_effect=[result]
        out=self.walk()
        self.assertEqual(out['reason'],'selection-list-changed');self.assertEqual(self.nav.call_count,1)
        self.assertFalse(out['return_verified']);self.assertTrue(out['ui_may_remain_open'])

    def test_untracked_binding_is_rejected_before_back(self):
        self.nav.side_effect=[nav_result('opened',dict(WHO,peer='201'))]
        out=self.walk();self.assertEqual(out['status'],'dialogs-stopped')
        self.assertEqual(self.nav.call_count,1)

    def test_changed_back_binding_stops_before_return(self):
        self.nav.side_effect=[nav_result('opened',WHO),nav_result('returned',dict(WHO,chat='301'))]
        out=self.walk();self.assertFalse(out['return_verified']);self.assertEqual(self.nav.call_count,2)

    def test_unexpected_diagnostic_text_is_not_exported(self):
        result=nav_result('opened',WHO);result['diagnostic']['body']='PRIVATE'
        self.nav.side_effect=[result]
        out=self.walk();self.assertIsNone(out['last_navigation']);self.assertNotIn('PRIVATE',json.dumps(out))

    def test_stop_after_open_does_not_perform_another_action(self):
        def open_then_stop(*args,**kwargs):
            self.stop.set();return nav_result('opened',WHO)
        self.nav.side_effect=open_then_stop
        out=self.walk();self.assertEqual(out['status'],'dialogs-cancelled');self.assertEqual(self.nav.call_count,1)

    def test_stop_before_start_does_not_read_journal(self):
        self.stop.set()
        with patch.object(n,'read_targets') as read:
            out=self.walk()
        read.assert_not_called();self.nav.assert_not_called();self.assertEqual(out['status'],'dialogs-cancelled')

    def test_missing_journal_does_not_create_file_or_touch_device(self):
        self.path.unlink();out=self.walk()
        self.assertEqual(out['status'],'dialogs-empty');self.assertFalse(self.path.exists());self.nav.assert_not_called()

    def test_exhaustion_returns_without_claiming_a_chat_was_checked(self):
        self.nav.side_effect=[nav_result('exhausted'),nav_result('search-ready')]
        out=self.walk();self.assertTrue(out['return_verified']);self.assertEqual(out['navigation_dialogs_checked'],0)
        self.assertEqual([c.args[0] for c in self.nav.call_args_list],['open','return'])

    def test_terminal_and_not_invoked_bindings_are_excluded_read_only(self):
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE chain_dialogs(account TEXT,peer TEXT,chat TEXT,stage TEXT)')
            db.execute("INSERT INTO chain_dialogs VALUES('100','200','300','declined')")
        before=self.path.read_bytes();self.assertEqual(n.read_targets(self.path),[])
        self.assertEqual(self.path.read_bytes(),before)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE chain_dialogs SET stage='wait-reply'")
        self.assertEqual(n.read_targets(self.path),[WHO])
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE manual_actions SET status='not-invoked'")
        self.assertEqual(n.read_targets(self.path),[])

    def test_corrupt_journal_is_body_free_and_never_opened(self):
        self.path.write_bytes(b'PRIVATE')
        out=self.walk();self.assertEqual(out['status'],'dialogs-stopped')
        self.assertNotIn('PRIVATE',json.dumps(out));self.nav.assert_not_called()

    def test_gui_entry_calls_only_navigation_check_even_with_telegram_enabled(self):
        with patch.object(n,'run_navigation_check',return_value=n.report()) as check, \
             patch('assistant_dialogs.run_pass') as automatic, \
             patch.object(cycle,'data_directory',return_value=Path(self.temp.name)):
            cycle.start(Settings(contacts_enabled=True),self.stop)
        check.assert_called_once();automatic.assert_not_called()
        saved=json.loads((Path(self.temp.name)/'messages-pass-check.json').read_text())
        self.assertTrue(saved['navigation_only']);self.assertFalse(saved['telegram_used'])


if __name__=='__main__':unittest.main()
