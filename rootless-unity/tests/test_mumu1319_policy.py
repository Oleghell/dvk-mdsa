"""Synthetic window, persistent new-start and pre-send guards; no device/API."""
import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from types import SimpleNamespace
import assistant_reply_window as window
import assistant_contact_followup as follow
import assistant_contact_clarify as clarify
from assistant_scan_retry import readonly_list_changed
from mumu_recovery import recoverable
from mumu_store import SharedStore
import test_mumu1311_context as fixtures
from test_guided_chain import snapshot,WHO
from test_inbox_profiles import Base,nav,msg,snap,QUESTIONS
import test_assistant_monitor as monitoring

class Preferences(unittest.TestCase):
    chain=fixtures.Refusals.chain
    def test_actual_peer_phrases_and_future_arrivals_are_terminal(self):
        for text in ('Общаюсь только тут...', 'Общаюсь только тут…','Я общаюсь только тут','Мне тут удобно','Мне удобно только здесь',
                     'Удобнее мне тут.До тех пор пока не сложиться нормальное общение-я соц.сети не раздаю',
                     'Удобнее мне тут.До тех пор пока не сложится нормальное общение-я соц.сети не раздаю'):
            self.assertTrue(follow.refused([dict(text=text)],requested=True),text)
            c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
            self.assertEqual(c.proposal(snapshot(*h,(text,False))),('declined',None))
            self.assertEqual(c.proposal(snapshot(*h,(text,False),('Ты в Питере?',False))),('declined',None))
            c.responder.assert_not_called()
    def test_old_answered_preference_still_stops_without_new_action(self):
        c,store,h=self.chain();h += [('Общаюсь только тут...',False)]
        with patch('assistant_contact_followup.refused',return_value=False),patch('assistant_chain.contact_refused',return_value=False):
            _,a=c.proposal(snapshot(*h));c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
            h += [(a['text'],True)];c.proposal(snapshot(*h))
        with store.connection() as db:previous=db.execute('SELECT * FROM chain_actions').fetchall()
        c.responder=MagicMock(side_effect=AssertionError('No AI'))
        self.assertEqual(c.proposal(snapshot(*h,('Давай',False))),('declined',None))
        with store.connection() as db:self.assertEqual(previous,db.execute('SELECT * FROM chain_actions').fetchall())
        c.responder.assert_not_called()
    def test_max_sitting_choice_is_fixed_contact_request(self):
        c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
        stage,a=c.proposal(snapshot(*h,('Я сижу только в Максе',False)))
        self.assertEqual(stage,'pending-clarify');self.assertEqual(a['text'],clarify.MAX_TEXT)
        c.responder.assert_not_called()
    def test_negative_questions_quotes_persons_not_interpreted_as_preference(self):
        for text in ('Общаюсь только тут?', 'Не общаюсь только тут', '> Общаюсь только тут\nДавай MAX', 'Удобнее мне тут найти твой номер?', 'Я сижу только с Максом'):
            self.assertFalse(follow.refused([dict(text=text)],requested=True),text)
            if 'Давай MAX' not in text:self.assertFalse(clarify.max_selected([dict(text=text)]),text)

class Window(Base):
    def set_age(self,age):
        with self.store.connection() as db:
            db.execute("UPDATE manual_actions SET created_at=datetime('now',?)",('-'+str(age)+' seconds',))
    def test_exact_one_hour_and_persistent_expiration(self):
        self.journal();window.enable(self.store)
        with self.store.connection() as db:created=db.execute("SELECT CAST(strftime('%s',created_at) AS INTEGER) FROM manual_actions").fetchone()[0]
        self.assertIsNone(window.reason(self.store,WHO,clock=lambda:created+3599.999))
        self.assertEqual(window.reason(self.store,WHO,clock=lambda:created+3600),'reply-window-expired')
        # Restart/clock rollback do not reopen the skipped conversation.
        self.assertEqual(window.reason(self.store,WHO,clock=lambda:created+5),'reply-window-expired')
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT status FROM manual_actions').fetchone()[0],'handler-returned-unconfirmed')
    def test_expired_targets_never_open_or_read(self):
        self.journal();window.enable(self.store);self.set_age(3601)
        out=self.walk([],[])
        self.assertEqual(out['status'],'inbox-empty');self.nav.assert_not_called();self.reader.assert_not_called()
        self.assertEqual(self.sent,[])
    def test_fresh_targets_remain_eligible(self):
        self.journal();window.enable(self.store)
        a,u=__import__('assistant_inbox').inbox_targets(self.chain())
        self.assertEqual(len(a)+len(u),1)
    def test_no_reliable_greeting_time_is_not_invented(self):
        c=self.chain();c.bind(snap(),(snap()['messages'][0]['text'],),approved=True)
        window.enable(self.store)
        self.assertEqual(window.reason(self.store,WHO),'reply-age-unverified')
        self.assertEqual(__import__('assistant_inbox').inbox_targets(c),([],[]))
    def test_new_start_excludes_old_even_if_new_incoming_but_not_new_peers(self):
        self.journal();window.enable(self.store,new_only=True)
        self.assertEqual(window.reason(self.store,WHO),'new-start-excluded')
        new=dict(account='100',peer='222',chat='333');self.journal(new)
        self.assertIsNone(window.reason(self.store,new))
        reopened=__import__('assistant_store').Store(self.store.path,self.store.legacy)
        self.assertEqual(window.reason(reopened,WHO),'new-start-excluded')
        self.assertIn(WHO['peer'],reopened.visited_peers())
    def test_guard_blocks_proposal_without_ai_or_action_changes(self):
        self.journal();c=self.chain();c.bind(snap(),(snap()['messages'][0]['text'],),approved=True)
        window.enable(self.store);self.set_age(3601)
        c.responder=MagicMock(side_effect=AssertionError('No AI'))
        self.assertEqual(c.proposal(snap(msg(1002,'Привет'))),('reply-excluded',None))
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_actions').fetchone()[0],0)
        c.responder.assert_not_called()
    def test_expiration_during_typing_never_reserves_or_sends(self):
        self.journal();window.enable(self.store)
        def expire(*a):self.set_age(3601);return True
        self.approve.side_effect=expire
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[snap(msg(1002,'Привет')),snap(msg(1002,'Привет'))])
        self.assertEqual(out['status'],'inbox-completed');self.assertEqual(self.sent,[])
        self.assertEqual(out['submission_calls'],0)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='question'").fetchone()[0],'awaiting-approval')

class Namespace(unittest.TestCase):
    def test_new_start_is_port_scoped_claims_are_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db.sqlite3';old=Path(temp)/'legacy'
            a=SharedStore(path,old,device_port=5563);b=SharedStore(path,old,device_port=5557)
            for store,peer in ((a,'200'),(b,'201')):
                store.reserve(dict(account='100',peer=peer,chat='-1',attempt=1,variant=0),'Привет',approved=True)
            window.enable(a,new_only=True);window.enable(b)
            self.assertEqual(window.reason(a,dict(account='100',peer='200')),'new-start-excluded')
            self.assertIsNone(window.reason(b,dict(account='100',peer='201')))
            with a.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM mumu_peer_claims').fetchone()[0],0)

class Scan(Base):
    def failed(self):
        value=nav('exhausted');value.update(state='stopped',identity=None)
        value['diagnostic'].update(stage='navigation-stopped',error='selection-count-changed',phase='scan',metadata_checkpoint='ready',selection_checkpoint='model-list',action_attempted=False,action_completed=False,destination_verified=False)
        return value
    def test_retries_scan_no_open_action_then_sends_once(self):
        self.journal()
        h=msg(1002,'Привет');q=msg(1003,QUESTIONS[0],True)
        out=self.walk([self.failed(),nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[snap(h),snap(h),snap(h,q)])
        self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['list_scan_retries'],1)
        self.assertEqual(self.sent,[QUESTIONS[0]])
        self.assertEqual(self.nav.call_args_list[1].kwargs['entry'],'dialogs')
    def test_bounded_scan_failure_has_safe_supervisor_recovery(self):
        self.journal();out=self.walk([self.failed()]*3,[])
        self.assertEqual(out['status'],'inbox-stopped');self.assertEqual(self.nav.call_count,3);self.reader.assert_not_called()
        report=dict(status='stopped',reason='initial-pass-stopped',initial_run=dict(status='stopped',inbox=out))
        self.assertTrue(recoverable(report))
    def test_action_identity_or_metadata_ambiguity_not_retried(self):
        for key,value in [('action_attempted',True),('action_completed',True),('phase','open'),('metadata_checkpoint','not-ready'),('error','identity-changed')]:
            v=self.failed();v['diagnostic'][key]=value
            self.assertFalse(readonly_list_changed('open',v))
        v=self.failed();v['identity']=WHO
        self.assertFalse(readonly_list_changed('open',v));self.assertFalse(readonly_list_changed('back',self.failed()))
    def test_unrelated_host_failure_not_made_recoverable(self):
        self.assertFalse(recoverable(dict(status='stopped',reason='initial-pass-stopped',initial_run=dict(status='stopped',inbox=dict(host_failure='state-check-failed')))))

class NewMonitor(unittest.TestCase):
    setUp=monitoring.Monitor.setUp
    lock=monitoring.Monitor.lock
    write=monitoring.Monitor.write
    wait_stop=monitoring.Monitor.wait_stop
    run_monitor=monitoring.Monitor.run_monitor
    def test_new_start_runs_profiles_before_inbox(self):
        self.run_monitor(mode='new')
        self.assertEqual(self.initial.call_args.kwargs['mode'],'profiles')
        self.assertEqual(self.initial.call_count,1)
