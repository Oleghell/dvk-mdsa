"""Regression tests for bursts, contact arrivals, pacing and verified exits."""
import json, threading, tempfile, unittest
from pathlib import Path
from unittest.mock import MagicMock
import assistant_guided_chain as guided
import assistant_settings as cfg
from assistant_authorization import RunAuthorization
from assistant_exit_notify import notify_exit
from test_inbox_profiles import Base,WHO,msg,snap,nav
from conversation_engine import QUESTIONS, CONTACT_TEXT

class Burst(Base):
    def prepared(self):
        self.journal();chain=self.chain();chain.consume(snap())
        first=snap(msg(1002,'Привет'),msg(1003,'Как ты?'))
        _,action=chain.proposal(first)
        return chain,first,action

    def test_two_messages_at_once_make_one_action(self):
        chain,first,action=self.prepared()
        self.assertEqual(action['kind'],'question')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ai_draft_inputs').fetchone()[0],2)

    def test_new_arrival_during_typing_replans_all_unsent_inputs(self):
        self.journal();chain=self.chain()
        first=snap(msg(1002,'Привет'))
        fresh=snap(msg(1002,'Привет'),msg(1003,'Я на работе'))
        after=snap(msg(1002,'Привет'),msg(1003,'Я на работе'),msg(1004,QUESTIONS[0],True))
        approve=MagicMock(return_value=True);sender=MagicMock(return_value=dict(attempted=True,handler_returned=True))
        out=guided.walk(chain,WHO,self.stop,approve,MagicMock(side_effect=[first,fresh,fresh,after]),sender,
                        approved=True,greetings=('Привет 🙂',),pause=lambda _:False,until_waiting=True,max_polls=8)
        self.assertEqual(out['status'],'chain-waiting');self.assertEqual(out['stage'],'wait-mood')
        self.assertEqual(out['diagnostics']['incoming_draft_refreshes'],1)
        self.assertEqual(sender.call_count,1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ai_draft_inputs').fetchone()[0],2)

    def test_restart_unsent_draft_with_more_incoming_replans_one_batch(self):
        chain,first,action=self.prepared()
        fresh=snap(*first['messages'][1:],msg(1004,'И ещё вопрос'))
        stage,new_action=chain.proposal(fresh)
        self.assertEqual(stage,'pending-question');self.assertEqual(new_action,action)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ai_draft_inputs').fetchone()[0],3)

    def test_ai_replan_sees_full_burst_once_before_one_send(self):
        chain,first,action=self.prepared()
        # Set up the AI path from a fresh journal in a different test database.
        chain.responder=MagicMock(return_value=dict(decision='reply',text=QUESTIONS[0]))
        fresh=snap(*first['messages'][1:],msg(1004,'И ещё вопрос'))
        self.assertTrue(chain.refresh_unsubmitted(first,fresh,action))
        _,action=chain.proposal(fresh)
        self.assertEqual(set(chain.responder.call_args.args[1]['_reply_ids']),{'1002','1003','1004'})
        self.assertEqual(chain.responder.call_count,1)
        self.assertEqual(len(chain.responder.call_args.args[1]['messages']),4)

    def test_unknown_attempt_must_never_be_reset_by_new_arrival(self):
        chain,first,action=self.prepared();chain.reserve_confirmed(WHO,action)
        fresh=snap(*first['messages'][1:],msg(1004,'Ещё сообщение'))
        self.assertFalse(chain.refresh_unsubmitted(first,fresh,action))
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'reserved-unknown')

    def test_new_own_or_edited_message_cannot_refresh(self):
        chain,first,action=self.prepared()
        self.assertFalse(chain.refresh_unsubmitted(first,snap(*first['messages'][1:],msg(1004,'Вручную',True)),action))
        self.assertFalse(chain.refresh_unsubmitted(first,snap(msg(1002,'Изменён'),msg(1003,'Как ты?'),msg(1004,'Ещё')),action))

    def test_contact_arrives_with_first_observation_of_our_request(self):
        chain,first,action=self.prepared();chain.reserve_confirmed(WHO,action);chain.finish(WHO,action,True)
        q=msg(1004,action['text'],True);base=first['messages'][1:]+[q]
        chain.proposal(snap(*base))
        mood=msg(1005,'Хорошо');_,request=chain.proposal(snap(*base,mood))
        chain.reserve_confirmed(WHO,request);chain.finish(WHO,request,True)
        incoming=dict(snap(*base,mood,msg(1006,request['text'],True),msg(1007,'791234567890'),msg(1008,'Это мой номер')),peer_name='Тест')
        stage,action=chain.proposal(incoming)
        self.assertEqual(stage,'done');self.assertIsNone(action)
        notifier=MagicMock(return_value=True)
        self.assertEqual(chain.notify(WHO,notifier,self.stop.is_set),'accepted')
        self.assertEqual(chain.notify(WHO,notifier,self.stop.is_set),'nothing-pending')
        self.assertEqual(notifier.call_count,1)

    def test_pending_unknown_contact_request_not_promoted(self):
        chain,first,action=self.prepared();chain.reserve_confirmed(WHO,action)
        fresh=dict(snap(*first['messages'][1:],msg(1004,CONTACT_TEXT,True),msg(1005,'791234567890')),peer_name='Тест')
        self.assertNotEqual(chain.proposal(fresh)[0],'done')

class ExitReasons(Base):
    def test_once_per_state_across_restart_and_no_private_content(self):
        self.journal();chain=self.chain();chain.consume(snap())
        result=dict(reason='wait-contact',diagnostics={})
        sender=MagicMock(return_value=True)
        event=notify_exit(chain,WHO,result,sender=sender)
        self.assertEqual(event['notification'],'accepted')
        event=notify_exit(self.chain(),WHO,result,sender=sender)
        self.assertEqual(event['notification'],'already-attempted');self.assertEqual(sender.call_count,1)
        self.assertNotIn('Привет',sender.call_args.args[0]);self.assertNotIn('791234567890',sender.call_args.args[0])
        chain.consume(snap(msg(1002,'Привет')))
        self.assertEqual(notify_exit(chain,WHO,result,sender=sender)['notification'],'accepted')

    def test_unknown_telegram_result_not_retried(self):
        self.journal();chain=self.chain();chain.consume(snap())
        sender=MagicMock(side_effect=RuntimeError('PRIVATE'))
        self.assertEqual(notify_exit(chain,WHO,dict(reason='wait-contact'),sender=sender)['notification'],'unknown')
        notify_exit(chain,WHO,dict(reason='wait-contact'),sender=sender)
        self.assertEqual(sender.call_count,1)

    def test_exit_notification_only_after_verified_back(self):
        self.journal();chain=self.chain();chain.consume(snap())
        notice=MagicMock(return_value=True)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[snap()],chain=chain,exit_notifier=notice)
        self.assertEqual(out['exit_events'][0]['reason'],'wait-reply');self.assertEqual(notice.call_count,1)

class PacingAndSettings(unittest.TestCase):
    def test_35_words_take_60_seconds_and_stop_cancels(self):
        stop=threading.Event();wait=MagicMock(return_value=False)
        self.assertTrue(RunAuthorization(stop,wait=wait)('question',' '.join(['слово']*35),lambda:False))
        self.assertAlmostEqual(sum(c.args[0] for c in wait.call_args_list),60)
        wait=MagicMock(side_effect=lambda _:stop.set() or True)
        self.assertFalse(RunAuthorization(stop,wait=wait)('greeting','Привет',lambda:False))
        self.assertEqual(wait.call_count,1)

    def test_independent_timers_and_legacy_300_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'workflow-settings.json').write_text(json.dumps(dict(settings_version=5,contacts_enabled=True,reply_interval=300)))
            value=cfg.load(folder)
            self.assertEqual((value.reply_interval,value.profile_interval),(5,300))
            value=cfg.Settings(reply_interval=10,profile_interval=450)
            cfg.save(value,folder);self.assertEqual(cfg.load(folder),value)
        for interval in (True,0,29,86401):
            with self.assertRaises(Exception):cfg.Settings(profile_interval=interval).check()

    def test_bad_legacy_poll_interval_not_silently_repaired(self):
        with tempfile.TemporaryDirectory() as folder:
            for value in (True,0,4000,'300'):
                Path(folder,'workflow-settings.json').write_text(json.dumps(dict(settings_version=5,contacts_enabled=True,reply_interval=value)))
                with self.assertRaises(Exception):cfg.load(folder)

    def test_busy_inbox_cannot_starve_due_profile_batch(self):
        from contextlib import nullcontext
        import assistant_monitor as monitor
        from test_assistant_monitor import inbox_result,list_result
        stop=threading.Event();now=[0];batches=[]
        def initial(*a,**kw):return dict(status='completed',report_name='last-run.json')
        def read(*a,**kw):now[0]=300;return inbox_result(dialogs_processed=1)
        def repeat(*a,**kw):batches.append(now[0]);stop.set();return initial()
        def navf(op,*a,**kw):return list_result() if op=='list' else dict(list_result(),state='search-ready')
        out=monitor.run(cfg.Settings(),stop,lambda _:True,initial=initial,inbox=read,repeat=repeat,navigator=navf,
                        lock=nullcontext,write=lambda _:'last-monitor.json',clock=lambda:now[0],wait=lambda _:False)
        self.assertEqual(batches,[300]);self.assertEqual(out['immediate_rechecks'],3)

    def test_start_has_no_modal(self):
        text=Path(__file__).resolve().parents[1].joinpath('assistant_app.py').read_text(encoding='utf-8')
        begin=text.split("    def begin(mode='full'):",1)[1].split('    def configure():',1)[0]
        self.assertNotIn('askyesno',begin)
