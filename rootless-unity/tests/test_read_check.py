"""Synthetic histories only. No account, device, sender or Telegram access."""
import copy,json,sqlite3,tempfile,threading,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock,patch

import assistant_read_check as r
import assistant_cycle as cycle
from assistant_store import Store
from assistant_chain import Chain
from assistant_settings import Settings
from one_chat_device import ReadStopped
from test_assistant_dialogs import nav_result

WHO=dict(account='100',peer='200',chat='300')
GREETING='Привет 🙂'


def snapshot(who=WHO,reply='Привет'):
    messages=[dict(id='1001',sender=who['account'],text=GREETING)]
    if reply is not None:
        messages.append(dict(id='1002',sender=who['peer'],text=reply))
    return dict(identity=dict(who),messages=messages)


class ReadCheck(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'assistant.sqlite3'
        self.store=Store(self.path,Path(self.tmp.name)/'old')
        self.add_peer(WHO)
        self.stop=threading.Event()
        self.nav=MagicMock(side_effect=[nav_result('opened',WHO),nav_result('returned',WHO),nav_result('search-ready')])
        self.reader=MagicMock(return_value=snapshot())

    def add_peer(self,who):
        action=self.store.reserve(dict(attempt=1,account=who['account'],peer=who['peer'],chat='-1',variant=0),GREETING,approved=True)
        self.store.finish(action,dict(send_attempted=True,send_handler_returned=True))

    def walk(self,**kwargs):
        return r.walk(Settings(contacts_enabled=True),self.stop,navigator=self.nav,reader=self.reader,journal_path=self.path,**kwargs)

    def test_preview_reads_and_analyzes_without_external_or_durable_side_effects(self):
        before=self.path.read_bytes()
        with patch('one_chat_send_device.submit') as send,patch('telegram_notify.load') as creds, \
             patch('telegram_notify.send_contact') as notify,patch('assistant_chain.step') as step, \
             patch.object(Chain,'finish') as finish,patch.object(Chain,'notify') as chain_notify, \
             patch('assistant_store.Store',side_effect=AssertionError('No persistent Store')):
            out=self.walk()
        self.assertEqual(out['status'],'dialogs-completed');self.assertTrue(out['return_verified'])
        self.assertEqual(out['dialogs_read'],1);self.assertEqual(out['dialogs_processed'],1)
        self.assertEqual(out['states']['pending-question'],1);self.assertEqual(out['preview_actions']['question'],1)
        self.assertEqual(out['observed_messages'],2);self.assertEqual(out['incoming_messages'],1)
        self.assertTrue(out['chat_content_read']);self.assertTrue(out['journal_read_only'])
        self.assertEqual(out['messages_sent'],0);self.assertEqual(out['reply_submission_calls'],0)
        self.assertEqual(self.path.read_bytes(),before)
        for mock in (send,creds,notify,step,finish,chain_notify):mock.assert_not_called()
        self.assertEqual(self.reader.call_args.args[3],WHO);self.assertEqual(self.reader.call_args.kwargs,{})
        self.assertEqual([c.args[0] for c in self.nav.call_args_list],['open','back','return'])
        for private in ('Привет','peer','account','salt','text_hash','1001','300','200'):
            self.assertNotIn(private,json.dumps(out,ensure_ascii=False))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='chain_actions'").fetchone())

    def test_five_dialog_limit_removes_visited_peers_and_returns(self):
        people=[dict(WHO,peer=str(200+i),chat=str(300+i)) for i in range(6)]
        for who in people[1:]:self.add_peer(who)
        results=[]
        for who in people[:5]:results.extend([nav_result('opened',who),nav_result('returned',who)])
        results.append(nav_result('search-ready'));self.nav.side_effect=results
        self.reader.side_effect=[snapshot(who) for who in people[:5]]
        before=self.path.read_bytes();out=self.walk()
        self.assertEqual(out['dialogs_read'],5);self.assertEqual(out['reason'],'visible-pass-limit')
        self.assertEqual(out['navigation_dialogs_checked'],5);self.assertEqual(out['preview_actions']['question'],5)
        self.assertTrue(out['return_verified']);self.assertFalse(out['all_dialogs_covered'])
        opens=[c for c in self.nav.call_args_list if c.args[0]=='open']
        self.assertEqual([len(c.kwargs['allowed']) for c in opens],[6,5,4,3,2])
        self.assertEqual([c.kwargs['entry'] for c in opens],['search']+['dialogs']*4)
        self.assertEqual(self.path.read_bytes(),before)

    def test_untracked_dialog_is_not_read(self):
        self.nav.side_effect=[nav_result('opened',dict(WHO,peer='999'))]
        out=self.walk();self.reader.assert_not_called();self.assertEqual(out['status'],'dialogs-stopped')
        self.assertEqual(self.nav.call_count,1)

    def test_authorization_failure_is_checked_before_read(self):
        with patch.object(Chain,'authorized',side_effect=ValueError('PRIVATE_ID')):
            out=self.walk()
        self.reader.assert_not_called();self.assertEqual(out['reason'],'journal-binding-check-stopped')
        self.assertNotIn('PRIVATE',json.dumps(out))

    def test_changed_reader_binding_stops_without_another_navigation(self):
        self.reader.return_value=snapshot(dict(WHO,chat='999'))
        out=self.walk();self.assertEqual(out['reason'],'history-check-stopped');self.assertEqual(self.nav.call_count,1)
        self.assertFalse(out['return_verified'])

    def test_exact_navigation_failure_is_kept(self):
        failed=nav_result('stopped');failed['diagnostic'].update(stage='navigation-stopped',error='handle-limit',destination_verified=False)
        self.nav.side_effect=[failed];out=self.walk()
        self.assertEqual(out['reason'],'handle-limit');self.reader.assert_not_called()

    def test_private_reader_exception_is_not_exported_or_retried(self):
        self.reader.side_effect=ReadStopped('PRIVATE_TOKEN_AND_BODY')
        out=self.walk();self.assertEqual(out['reason'],'history-check-stopped')
        self.assertNotIn('PRIVATE',json.dumps(out));self.assertEqual(self.reader.call_count,1)
        self.assertEqual(self.nav.call_count,1);self.assertTrue(out['ui_may_remain_open'])

    def test_valid_reader_failure_checkpoints_are_body_free(self):
        info=dict(stage='navigation-stopped',metadata_checkpoint='ready',read_checkpoint='identity',wait_reason='not-checked',frames=2,managed_calls=50,
                  scalar_checkpoint='peer-id',scalar_state='positive',identity_checkpoint='saved-binding',message_slot=-1,message_kind='not-read',message_direction='not-read',private_body='PRIVATE')
        self.reader.side_effect=ReadStopped('identity-not-bound',info)
        out=self.walk();self.assertEqual(out['reason'],'identity-not-bound')
        self.assertEqual(out['last_reader']['identity_checkpoint'],'saved-binding');self.assertNotIn('PRIVATE',json.dumps(out))

    def test_stop_before_start_does_not_open_journal_or_device(self):
        self.stop.set()
        with patch.object(r,'preview_chain') as clone:
            out=self.walk()
        clone.assert_not_called();self.nav.assert_not_called();self.reader.assert_not_called()
        self.assertEqual(out['status'],'dialogs-cancelled')

    def test_stop_after_open_does_not_read_or_return(self):
        def opened(*a,**k):self.stop.set();return nav_result('opened',WHO)
        self.nav.side_effect=opened;out=self.walk()
        self.assertEqual(out['status'],'dialogs-cancelled');self.reader.assert_not_called();self.assertEqual(self.nav.call_count,1)

    def test_stop_after_read_does_not_analyze_or_return(self):
        def read(*a,**k):self.stop.set();return snapshot()
        self.reader.side_effect=read
        with patch.object(Chain,'consume') as consume:out=self.walk()
        consume.assert_not_called();self.assertEqual(out['status'],'dialogs-cancelled');self.assertEqual(self.nav.call_count,1)

    def test_missing_journal_does_not_create_it_or_touch_device(self):
        self.path.unlink();out=self.walk()
        self.assertEqual(out['status'],'dialogs-empty');self.assertFalse(self.path.exists());self.nav.assert_not_called()

    def test_terminal_dialogs_are_excluded(self):
        chain=Chain(self.store);chain.consume(snapshot(reply=None));chain.mark_review(WHO)
        before=self.path.read_bytes();out=self.walk()
        self.assertEqual(out['status'],'dialogs-empty');self.nav.assert_not_called();self.reader.assert_not_called()
        self.assertEqual(self.path.read_bytes(),before)

    def test_not_invoked_dialogs_are_excluded(self):
        with self.store.connection() as db:db.execute("UPDATE manual_actions SET status='not-invoked'")
        out=self.walk();self.assertEqual(out['status'],'dialogs-empty');self.nav.assert_not_called()

    def test_existing_chain_preview_does_not_advance_persistent_stage(self):
        chain=Chain(self.store);chain.consume(snapshot(reply=None))
        before=self.path.read_bytes();out=self.walk()
        self.assertEqual(out['preview_actions']['question'],1);self.assertEqual(self.path.read_bytes(),before)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs').fetchone()[0],'wait-reply')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_actions').fetchone()[0],0)

    def test_next_contact_question_is_only_a_preview(self):
        from conversation_engine import QUESTIONS
        chain=Chain(self.store,choose=lambda:0)
        chain.consume(snapshot(reply=None));chain.consume(snapshot())
        previous=snapshot();previous['messages'].append(dict(id='1003',sender='100',text=QUESTIONS[0]))
        stage,action=chain.consume(previous);self.assertEqual(stage,'wait-mood');self.assertIsNone(action)
        current=copy.deepcopy(previous);current['messages'].append(dict(id='1004',sender='200',text='Хорошо'))
        self.reader.return_value=current;before=self.path.read_bytes();out=self.walk()
        self.assertEqual(out['preview_actions']['contact'],1);self.assertEqual(out['states']['pending-contact'],1)
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(out['reply_submission_calls'],0)

    def test_second_preview_does_not_consume_a_persistent_send_reservation(self):
        before=self.path.read_bytes()
        for _ in range(2):
            self.nav.side_effect=[nav_result('opened',WHO),nav_result('returned',WHO),nav_result('search-ready')]
            out=self.walk();self.assertEqual(out['preview_actions']['question'],1)
        self.assertEqual(self.path.read_bytes(),before)

    def test_incomplete_original_greeting_is_review_not_an_action(self):
        self.reader.return_value=snapshot(reply=None)
        self.reader.return_value['messages'][0]['text']='PRIVATE DIFFERENT GREETING'
        out=self.walk();self.assertEqual(out['states']['manual-review'],1);self.assertEqual(out['preview_actions']['none'],1)
        self.assertTrue(out['return_verified']);self.assertNotIn('PRIVATE',json.dumps(out))

    def test_decline_and_nontext_are_not_used_for_an_action(self):
        for text in ('Не пиши мне больше',None):
            with self.subTest(text=text):
                self.nav.side_effect=[nav_result('opened',WHO),nav_result('returned',WHO),nav_result('search-ready')]
                self.reader.return_value=snapshot(reply='x');self.reader.return_value['messages'][1]['text']=text
                out=self.walk();self.assertEqual(out['preview_actions']['none'],1);self.assertTrue(out['return_verified'])

    def test_empty_or_twenty_message_snapshot_reads_but_never_recommends_send(self):
        for count in (0,20):
            self.nav.side_effect=[nav_result('opened',WHO),nav_result('returned',WHO),nav_result('search-ready')]
            self.reader.return_value=dict(identity=WHO,messages=[dict(id=str(1001+i),sender='100',text='PRIVATE') for i in range(count)])
            out=self.walk();self.assertEqual(out['states']['manual-review'],1);self.assertEqual(out['dialogs_read'],1)
            self.assertEqual(out['preview_actions']['none'],1);self.assertTrue(out['return_verified'])

    def test_malformed_snapshot_never_reaches_analysis(self):
        bad=[]
        value=snapshot();value['peer_name']='PRIVATE';bad.append(value)
        value=snapshot();value['messages'][0]['text']='x'*2049;bad.append(value)
        value=snapshot();value['messages'][1]['id']='1001';bad.append(value)
        value=snapshot();value['messages'][1]['sender']='999';bad.append(value)
        for value in bad:
            self.nav.side_effect=[nav_result('opened',WHO)];self.reader.return_value=value
            with patch.object(Chain,'consume') as consume:out=self.walk()
            consume.assert_not_called();self.assertEqual(out['status'],'dialogs-stopped');self.assertNotIn('PRIVATE',json.dumps(out))

    def test_visible_exhaustion_returns_without_reading(self):
        self.nav.side_effect=[nav_result('exhausted'),nav_result('search-ready')]
        out=self.walk();self.assertEqual(out['reason'],'visible-exhausted');self.assertTrue(out['return_verified'])
        self.reader.assert_not_called();self.assertFalse(out['chat_content_read'])

    def test_bad_return_binding_does_not_claim_success(self):
        self.nav.side_effect=[nav_result('opened',WHO),nav_result('returned',dict(WHO,chat='999'))]
        out=self.walk();self.assertEqual(out['dialogs_read'],1);self.assertFalse(out['return_verified'])
        self.assertEqual(self.nav.call_count,2)

    def test_invalid_navigation_diagnostic_is_not_exported(self):
        value=nav_result('opened',WHO);value['diagnostic']['PRIVATE']='secret';self.nav.side_effect=[value]
        out=self.walk();self.assertIsNone(out['last_navigation']);self.reader.assert_not_called()
        self.assertNotIn('PRIVATE',json.dumps(out))

    def test_corrupt_and_oversize_journal_stop_before_navigation(self):
        with patch.object(r,'MAX_JOURNAL_BYTES',0):out=self.walk()
        self.assertEqual(out['reason'],'journal-check-stopped');self.nav.assert_not_called()
        self.path.write_bytes(b'PRIVATE');out=self.walk()
        self.assertEqual(out['reason'],'journal-check-stopped');self.nav.assert_not_called();self.assertNotIn('PRIVATE',json.dumps(out))

    def test_gui_entry_writes_read_check_report_and_never_runs_auto_pass(self):
        result=r.report();result.update(status='dialogs-completed',dialogs_read=3)
        with patch.object(r,'run_read_check',return_value=result) as run,patch('assistant_dialogs.run_pass') as automatic, \
             patch('assistant_navigation_check.run_navigation_check') as nav,patch.object(cycle,'data_directory',return_value=Path(self.tmp.name)):
            out=cycle.start(Settings(contacts_enabled=True),self.stop)
        run.assert_called_once();automatic.assert_not_called();nav.assert_not_called();self.assertEqual(out['dialogs_read'],3)
        saved=json.loads((Path(self.tmp.name)/'messages-pass-check.json').read_text())
        self.assertEqual(saved['tool_version'],'0.4.5');self.assertEqual(saved['dialog_limit'],5)
        self.assertTrue(saved['read_only_check']);self.assertFalse(saved['telegram_used'])

    def test_native_read_uses_scoped_handles_and_retains_guards(self):
        import one_chat_probe as probe
        source=probe.build(WHO,scoped_traversal=True)
        for text in ('const scope=(body,retainResult=false)=>{','const current=scope(()=>resolve(candidate),true);',
                     'scope(()=>checkView(current))',"if(held.length>=64)fail('handle-limit')",'JSON.stringify(state.sample)!==JSON.stringify(sample)'):
            self.assertIn(text,source)
        self.assertNotIn('OnSend',source);self.assertNotIn('get_Name',source)
        self.assertLess(source.index('JSON.stringify(who)!==JSON.stringify(expectedIdentity)'),source.index('const messages=[],seenIds'))


if __name__=='__main__':unittest.main()
