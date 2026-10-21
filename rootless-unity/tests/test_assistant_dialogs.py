import copy,json
from pathlib import Path
import tempfile,threading,unittest
from unittest.mock import MagicMock,patch
from assistant_store import Store
from assistant_chain import Chain,QUESTIONS,step
from assistant_settings import Settings
import assistant_dialogs as d
from test_assistant_chain import WHO,GREETING,msg,snap


def diag():
    return dict(stage='navigation-ready',error='none',phase='done',metadata_checkpoint='ready',selection_checkpoint='verify-chat',rows_scanned=2,scan_batches=1,action_attempted=True,action_completed=True,destination_verified=True)


def nav_result(state,who=None):return dict(state=state,identity=dict(who) if who else None,diagnostic=diag())


class DialogPass(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'assistant.sqlite3'
        self.store=Store(self.path,Path(self.tmp.name)/'old')
        a=self.store.reserve(dict(attempt=1,account=WHO['account'],peer=WHO['peer'],chat='-1',variant=0),GREETING,approved=True)
        self.store.finish(a,dict(send_attempted=True,send_handler_returned=True))
        self.chain=Chain(self.store,choose=lambda:0)
        self.stop=threading.Event();self.settings=Settings()
        self.nav=MagicMock(side_effect=[nav_result('opened',WHO),nav_result('returned',WHO),nav_result('search-ready')])
        self.reader=MagicMock(return_value=snap())
        self.sender=MagicMock(return_value=dict(attempted=True,handler_returned=True))

    def walk(self,**kwargs):
        return d.walk(self.settings,self.stop,kwargs.pop('progress',lambda x:None),kwargs.pop('chain',self.chain),navigator=self.nav,reader=self.reader,sender=self.sender,pause=lambda _:False,**kwargs)

    def test_greeting_reply_advances_once_and_returns_to_search(self):
        self.reader.side_effect=[snap(msg(1002,'Привет')),snap(msg(1002,'Привет'),msg(1003,QUESTIONS[0],True))]
        def sender(*args,**kwargs):
            with self.store.connection() as db:self.assertEqual(db.execute("SELECT status FROM chain_actions").fetchone()[0],'reserved-unknown')
            return dict(attempted=True,handler_returned=True)
        self.sender.side_effect=sender
        out=self.walk()
        self.assertEqual(out['status'],'dialogs-completed');self.assertTrue(out['return_verified'])
        self.assertEqual(out['dialogs_processed'],1);self.assertEqual(out['reply_submission_calls'],1);self.assertEqual(out['outgoing_observed'],1)
        self.assertEqual(self.sender.call_count,1);self.assertEqual(self.sender.call_args.kwargs['text'],QUESTIONS[0])
        self.assertEqual([x.args[0] for x in self.nav.call_args_list],['open','back','return'])
        self.assertFalse(out['live_cycle_available']);self.assertFalse(out['all_dialogs_covered'])
        self.assertNotIn('Привет',json.dumps(out));self.assertNotIn('peer',json.dumps(out))

    def test_no_new_reply_does_not_send_or_notify(self):
        notify=MagicMock()
        out=self.walk(notifier=notify)
        self.assertEqual(out['states']['wait-reply'],1);self.sender.assert_not_called();notify.assert_not_called()
        self.assertEqual(self.reader.call_args.kwargs,dict(read_name=True))

    def test_authorization_checked_before_history_collection(self):
        self.nav.side_effect=[nav_result('opened',dict(WHO,peer='201'))]
        out=self.walk()
        self.assertEqual(out['status'],'dialogs-stopped');self.reader.assert_not_called();self.sender.assert_not_called()

    def test_correct_row_but_changed_reader_identity_never_sends(self):
        self.reader.return_value=dict(snap(),identity=dict(WHO,chat='301'))
        out=self.walk();self.assertEqual(out['status'],'dialogs-stopped');self.sender.assert_not_called()
        self.assertEqual(self.nav.call_count,1)

    def test_transport_or_history_error_has_no_private_exception_or_retry(self):
        self.reader.side_effect=RuntimeError('PRIVATE_TOKEN_BODY')
        out=self.walk();self.assertEqual(out['status'],'dialogs-stopped');self.assertTrue(out['ui_may_remain_open'])
        self.assertNotIn('PRIVATE',json.dumps(out));self.sender.assert_not_called();self.assertEqual(self.nav.call_count,1)

    def test_unknown_send_never_retries_after_restart(self):
        self.reader.return_value=snap(msg(1002,'Привет'))
        self.sender.side_effect=TimeoutError('PRIVATE')
        out=self.walk();self.assertEqual(out['reason'],'reply-outcome-unknown');self.assertEqual(self.nav.call_count,1)
        self.sender.reset_mock();self.sender.side_effect=None
        self.chain=Chain(Store(self.path,Path(self.tmp.name)/'old'))
        self.nav.reset_mock(side_effect=True);self.nav.side_effect=[nav_result('opened',WHO),nav_result('returned',WHO),nav_result('search-ready')]
        out=self.walk();self.sender.assert_not_called();self.assertEqual(out['states']['pending-question'],1)

    def test_stop_before_read_and_after_reservation(self):
        def nav(*args,**kwargs):self.stop.set();return nav_result('opened',WHO)
        self.nav.side_effect=nav
        out=self.walk();self.assertEqual(out['status'],'dialogs-cancelled');self.reader.assert_not_called();self.sender.assert_not_called()

    def test_stop_published_by_progress_opens_nothing(self):
        out=self.walk(progress=lambda _:self.stop.set())
        self.assertEqual(out['status'],'dialogs-cancelled');self.nav.assert_not_called();self.reader.assert_not_called()

    def test_terminal_dialogs_and_not_invoked_greetings_not_selected(self):
        self.reader.return_value=snap(msg(1002,'Не пиши мне'))
        out=self.walk();self.assertEqual(out['states']['declined'],1)
        self.nav.reset_mock();self.reader.reset_mock();out=self.walk()
        self.assertEqual(out['status'],'dialogs-empty');self.assertFalse(out['return_verified']);self.nav.assert_not_called();self.reader.assert_not_called()
        with self.store.connection() as db:
            db.execute('DELETE FROM chain_dialogs');db.execute("UPDATE manual_actions SET status='not-invoked'")
        out=self.walk();self.assertEqual(out['status'],'dialogs-empty')

    def test_empty_visible_list_returns_search_without_reading_or_sending(self):
        self.nav.side_effect=[nav_result('exhausted'),nav_result('search-ready')]
        out=self.walk();self.assertEqual(out['reason'],'visible-exhausted');self.assertTrue(out['return_verified'])
        self.reader.assert_not_called();self.sender.assert_not_called()

    def test_back_failure_stops_before_next_dialog_or_search_switch(self):
        self.nav.side_effect=[nav_result('opened',WHO),RuntimeError('PRIVATE')]
        out=self.walk();self.assertEqual(out['status'],'dialogs-stopped');self.assertEqual(self.nav.call_count,2)
        self.assertFalse(out['return_verified'])

    def test_diagnostic_extra_values_never_enter_report(self):
        bad=nav_result('opened',WHO);bad['diagnostic']['body']='PRIVATE';self.nav.side_effect=[bad]
        out=self.walk();self.assertEqual(out['status'],'dialogs-stopped');self.assertIsNone(out['last_navigation'])
        self.assertNotIn('PRIVATE',json.dumps(out));self.reader.assert_not_called()

    def test_contact_only_name_forwarded_once_no_conversation(self):
        def seal(value):return bytes(x^91 for x in value)
        self.chain=Chain(self.store,contact_notifications=True,seal=seal,unseal=seal)
        self.reader.return_value=dict(snap(msg(1002,'мой тг @myprivatecontact')),peer_name='Анна')
        notify=MagicMock(return_value=True)
        out=self.walk(notifier=notify)
        self.assertEqual(out['notifications']['accepted'],1);self.assertEqual(out['states']['done'],1)
        self.assertEqual(notify.call_args.args,(dict(name='Анна',contacts=['@myprivatecontact']),))
        self.sender.assert_not_called();self.assertNotIn('myprivatecontact',json.dumps(out));self.assertNotIn('Анна',json.dumps(out))
        self.assertNotIn(b'myprivatecontact',self.path.read_bytes())
        self.nav.reset_mock();notify.reset_mock();out=self.walk(notifier=notify)
        self.nav.assert_not_called();notify.assert_not_called()

    def test_active_target_list_uses_bound_chat_not_draft(self):
        self.assertEqual(d.journal_targets(self.chain),[dict(WHO,chat='-1')])
        step(self.chain,snap(),lambda *a:None)
        self.assertEqual(d.journal_targets(self.chain),[WHO])

    def test_multiple_peers_are_visited_once_using_list_entry(self):
        other=dict(account='100',peer='201',chat='301')
        action=self.store.reserve(dict(attempt=1,account='100',peer='201',chat='-2',variant=0),GREETING,approved=True)
        self.store.finish(action,dict(send_attempted=True,send_handler_returned=True))
        self.nav.side_effect=[nav_result('opened',WHO),nav_result('returned',WHO),nav_result('opened',other),nav_result('returned',other),nav_result('search-ready')]
        self.reader.side_effect=[snap(),dict(identity=other,messages=[dict(id='2001',sender='100',text=GREETING)])]
        out=self.walk()
        self.assertEqual(out['dialogs_processed'],2);self.assertEqual(out['status'],'dialogs-completed')
        opens=[c for c in self.nav.call_args_list if c.args[0]=='open']
        self.assertEqual(opens[0].kwargs['entry'],'search');self.assertEqual(opens[1].kwargs['entry'],'dialogs')
        self.assertEqual(opens[1].kwargs['allowed'],[dict(other,chat='-2')]);self.sender.assert_not_called()

    def test_ambiguous_greeting_is_blocked_without_faking_a_greeting_id(self):
        self.reader.return_value=snap(msg(1002,'Другой исходящий текст',True))
        out=self.walk();self.assertEqual(out['status'],'dialogs-completed');self.assertEqual(out['states']['manual-review'],1)
        self.sender.assert_not_called()
        with self.store.connection() as db:
            greeting,stage=db.execute('SELECT greeting,stage FROM chain_dialogs').fetchone()
        self.assertIsNone(greeting);self.assertEqual(stage,'manual-review')
        self.assertEqual(d.journal_targets(self.chain),[])

    def test_reader_failure_exports_only_allowlisted_checkpoints(self):
        from one_chat_device import ReadStopped
        info=dict(stage='navigation-stopped',metadata_checkpoint='ready',read_checkpoint='identity',wait_reason='not-checked',frames=2,managed_calls=50,
                  scalar_checkpoint='peer-id',scalar_state='positive',identity_checkpoint='saved-binding',message_slot=-1,message_kind='not-read',message_direction='not-read',private_body='PRIVATE')
        self.reader.side_effect=ReadStopped('identity-not-bound',info)
        out=self.walk()
        self.assertEqual(out['last_reader']['identity_checkpoint'],'saved-binding')
        self.assertNotIn('PRIVATE',json.dumps(out));self.sender.assert_not_called()

    def test_saved_opt_out_does_not_load_or_send_telegram(self):
        with patch.object(d,'walk',return_value={}) as walk,patch('assistant_lock.operation_lock'),patch('telegram_notify.load') as load:
            d.run_pass(self.settings,self.stop,store=self.store,notifier=MagicMock())
            load.assert_not_called();self.assertIsNone(walk.call_args.kwargs['notifier'])

class PassEntry(unittest.TestCase):
    def test_start_writes_the_new_body_free_report(self):
        import assistant_cycle as cycle
        from assistant_read_check import report
        result=report();result.update(status='dialogs-completed',reason='visible-exhausted',return_verified=True)
        with tempfile.TemporaryDirectory() as temp,patch('assistant_read_check.run_read_check',return_value=result) as run,patch.object(cycle,'data_directory',return_value=Path(temp)):
            out=cycle.start(Settings(),threading.Event())
            saved=json.loads((Path(temp)/'messages-pass-check.json').read_text())
        self.assertEqual(out['status'],'dialogs-completed');self.assertEqual(out['report_name'],'messages-pass-check.json')
        self.assertEqual(saved['mode'],'visible-journal-dialog-read-check');self.assertFalse(saved['live_cycle_available'])
        self.assertEqual(run.call_count,1)

    def test_credential_failure_is_not_exported_as_secret_text(self):
        import assistant_cycle as cycle
        from telegram_notify import TelegramError
        with tempfile.TemporaryDirectory() as temp,patch('assistant_read_check.run_read_check',side_effect=TelegramError('PRIVATE_TOKEN')),patch.object(cycle,'data_directory',return_value=Path(temp)):
            out=cycle.start(Settings(),threading.Event())
            text=(Path(temp)/out['report_name']).read_text()
        self.assertEqual(out['reason'],'journal-or-device-start-stopped');self.assertNotIn('PRIVATE',text)

    def test_stop_before_start_touches_no_device_or_report(self):
        import assistant_cycle as cycle
        stop=threading.Event();stop.set()
        with patch.object(d,'run_pass') as run,patch.object(cycle,'data_directory') as directory:
            out=cycle.start(Settings(),stop)
        self.assertEqual(out['status'],'cancelled');run.assert_not_called();directory.assert_not_called()


if __name__=='__main__':unittest.main()
