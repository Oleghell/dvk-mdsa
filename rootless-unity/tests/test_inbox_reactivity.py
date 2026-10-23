"""New arrivals, direct contact responses and idle outbox: synthetic, no network."""
from pathlib import Path
import json,tempfile,threading,unittest
from unittest.mock import MagicMock,patch
from contextlib import nullcontext
import assistant_monitor as monitor
import assistant_settings as settings
import assistant_inbox as inbox
import telegram_notify
from shared_contact import self_shared,payload
from test_inbox_profiles import Base,WHO,nav,snap,msg
from test_assistant_monitor import inbox_result,list_result
from conversation_engine import QUESTIONS,CONTACT_TEXT

# Deliberately non-country-coded synthetic 12-digit candidate, not user data.
CANDIDATE='791234567890'

class ContextContact(unittest.TestCase):
    def test_direct_digits_preserved_without_inventing_country_or_validity(self):
        self.assertEqual(self_shared(CANDIDATE,requested=True),[CANDIDATE])
        self.assertEqual(self_shared(CANDIDATE,requested=False),[])
        self.assertEqual(self_shared('мой номер '+CANDIDATE),[CANDIDATE])
        self.assertEqual(payload('Тест',[CANDIDATE])['contacts'],[CANDIDATE])
        with patch.object(telegram_notify,'send',return_value=True) as send:
            self.assertTrue(telegram_notify.send_contact('token','chat',payload('Тест',[CANDIDATE])))
        text=send.call_args.args[2]
        self.assertIn(CANDIDATE,text);self.assertIn('не подтверждены',text)
        self.assertNotIn('+'+CANDIDATE,text)

    def test_negative_third_party_quoted_codes_still_rejected(self):
        for text in ('номер заказа '+CANDIDATE,'номер моей подруги '+CANDIDATE,
                     'не пересылай '+CANDIDATE,'код '+CANDIDATE,'"'+CANDIDATE+'"',
                     CANDIDATE+'?',CANDIDATE+'0000','123456789'):
            self.assertEqual(self_shared(text,requested=True),[],text)

    def test_normalized_known_phone_and_handle_unchanged(self):
        self.assertEqual(self_shared('89991234567',requested=True),['+79991234567'])
        self.assertEqual(self_shared('@myhandle',requested=True),['@myhandle'])

class ContactFlow(Base):
    def waiting(self):
        self.journal();chain=self.chain();chain.consume(snap())
        hello=msg(1002,'Привет');q=msg(1003,QUESTIONS[0],True)
        mood=msg(1004,'Хорошо');request=msg(1005,CONTACT_TEXT,True)
        for before,after in ((snap(hello),snap(hello,q)),(snap(hello,q,mood),snap(hello,q,mood,request))):
            _,action=chain.proposal(before);chain.reserve_confirmed(WHO,action);chain.finish(WHO,action,True)
            chain.proposal(after)
        return chain,[hello,q,mood,request]

    def test_candidate_contact_is_notified_once_not_answered_with_ai(self):
        chain,messages=self.waiting();candidate=dict(snap(*messages,msg(1006,CANDIDATE)),peer_name='Тест')
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[candidate],chain=chain)
        self.assertEqual(out['contacts_forwarded'],1);self.assertEqual(out['contacts_detected'],1)
        self.assertEqual(out['contact_delivery_pending'],0)
        self.assertEqual(out['submission_calls'],0);self.assertFalse(self.sent)
        self.assertEqual(self.notifier.call_args.args[0]['contacts'],[CANDIDATE])
        second=self.walk([],[],chain=chain)
        self.assertEqual(second['status'],'inbox-empty');self.nav.assert_not_called()
        self.assertEqual(self.notifier.call_count,1)

    def test_disabled_contact_delivery_does_not_pause_or_reopen_done_chat(self):
        chain,messages=self.waiting();candidate=dict(snap(*messages,msg(1006,CANDIDATE)),peer_name='Тест')
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[candidate],chain=chain,notifier=None)
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['contact_delivery_pending'],1)
        self.assertFalse(set(out['outcomes']) & inbox.PAUSE_OUTCOMES)
        self.assertEqual(inbox.inbox_targets(chain),([],[]))
        second=self.walk([],[],chain=chain,notifier=None)
        self.assertEqual(second['status'],'inbox-empty');self.nav.assert_not_called()
        third=self.walk([],[],chain=chain)
        self.assertEqual(third['contacts_forwarded'],1);self.nav.assert_not_called()
        self.assertEqual(third['contact_delivery_pending'],0)

    def test_unknown_telegram_delivery_is_not_retried_and_other_chats_can_run(self):
        chain,messages=self.waiting();candidate=dict(snap(*messages,msg(1006,CANDIDATE)),peer_name='Тест')
        notifier=MagicMock(side_effect=RuntimeError('PRIVATE'))
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[candidate],chain=chain,notifier=notifier)
        self.assertFalse(set(out['outcomes']) & inbox.PAUSE_OUTCOMES)
        second=self.walk([],[],chain=chain,notifier=notifier)
        self.assertEqual(notifier.call_count,1);self.nav.assert_not_called()
        self.assertEqual(second['contacts_forwarded'],0)

class IdleLoop(unittest.TestCase):
    def run_loop(self,results,wait,*,mode='inbox',clock=lambda:0,repeat=None):
        self.stop=threading.Event();self.calls=[]
        def navf(op,*a,**kw):
            self.calls.append(op)
            return list_result() if op=='list' else dict(list_result(),state='search-ready')
        inboxf=MagicMock(side_effect=results)
        initial=MagicMock(return_value=dict(status='completed',report_name='last-run.json'))
        out=monitor.run(settings.Settings(),self.stop,lambda _:True,mode=mode,inbox=inboxf,
            initial=initial,navigator=navf,lock=nullcontext,write=lambda _:'last-monitor.json',
            wait=lambda delay:wait(delay,self.stop),clock=clock,repeat=repeat)
        return out,inboxf

    def test_new_arrival_is_drained_before_idle_or_profiles(self):
        events=[]
        def wait(delay,stop):events.append(('wait',delay));stop.set();return True
        def results(*a,**k):
            events.append(('inbox',None))
            return inbox_result(dialogs_processed=1) if len(events)==1 else inbox_result()
        out,read=self.run_loop(results,wait)
        self.assertEqual(events,[('inbox',None),('inbox',None),('wait',5)])
        self.assertEqual(out['immediate_rechecks'],1);self.assertTrue(out['dialogs_verified'])

    def test_repeated_profile_batch_returns_and_checks_inbox_before_sleep(self):
        now=[0];events=[]
        def results(*a,**k):events.append('inbox');return inbox_result()
        def repeat(*a,**k):events.append('profiles');return dict(status='completed',report_name='last-run.json')
        def wait(delay,stop):
            events.append('wait')
            if 'profiles' not in events:now[0]=300;return False
            stop.set();return True
        out,read=self.run_loop(results,wait,mode='full',clock=lambda:now[0],repeat=repeat)
        self.assertEqual(events,['inbox','wait','inbox','profiles','inbox','wait'])
        self.assertTrue(out['dialogs_verified'])
        self.assertEqual(self.calls[-1],'list')

    def test_busy_burst_is_bounded_and_does_not_start_profiles_over_pending_replies(self):
        def wait(delay,stop):self.assertEqual(delay,5);stop.set();return True
        out,read=self.run_loop(lambda *a,**k:inbox_result(dialogs_processed=1),wait)
        self.assertEqual(read.call_count,4);self.assertEqual(out['immediate_rechecks'],3)

    def test_disabled_tg_is_visible_but_does_not_stop_monitor(self):
        def wait(delay,stop):stop.set();return True
        out,read=self.run_loop(lambda *a,**k:inbox_result(contact_delivery_pending=1,outcomes={'telegram-disabled':1}),wait)
        self.assertEqual(out['status'],'cancelled')
        out['status']='waiting'
        self.assertIn('передача выключена',monitor.summary(out))

class SettingsMigration(unittest.TestCase):
    def test_old_30_second_default_migrates_custom_intervals_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'workflow-settings.json'
            p.write_text(json.dumps(dict(settings_version=4,contacts_enabled=False,reply_interval=30)))
            self.assertEqual(settings.load(folder).reply_interval,5)
            p.write_text(json.dumps(dict(settings_version=4,contacts_enabled=False,reply_interval=60)))
            self.assertEqual(settings.load(folder).reply_interval,5);self.assertEqual(settings.load(folder).profile_interval,60)
            settings.save(settings.Settings(reply_interval=30),folder)
            self.assertEqual(settings.load(folder).reply_interval,30)

class ProfileInterleaving(unittest.TestCase):
    def test_monitor_supplies_callback_to_initial_and_checks_serially(self):
        now=[0];stop=threading.Event();events=[]
        def navf(operation,*a,**k):
            events.append(operation)
            return list_result() if operation=='list' else dict(list_result(),state='search-ready')
        def initial(*args,between_profiles=None,**kwargs):
            events.append('profile-one');now[0]=6
            self.assertIsNone(between_profiles)
            events.append('profile-two')
            return dict(status='completed',report_name='last-run.json')
        def inboxf(*a,**k):events.append('inbox');return inbox_result()
        def wait(delay):stop.set();return True
        out=monitor.run(settings.Settings(),stop,lambda _:True,initial=initial,inbox=inboxf,navigator=navf,
            lock=nullcontext,write=lambda _:'last-monitor.json',clock=lambda:now[0],wait=wait)
        self.assertEqual(out['status'],'cancelled');self.assertEqual(out['between_profile_checks'],0)
        begin=events.index('profile-one');end=events.index('profile-two')
        self.assertEqual(events[begin:end],['profile-one'])
        self.assertTrue(out['dialogs_verified'])

    def test_callback_failure_stops_next_profile_cycle(self):
        import assistant_profiles as profiles
        from test_inbox_profiles import Config
        from assistant_store import Store,StateError
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db',Path(folder)/'old');profiles.Session(store).set('city','Псков')
            cycle=MagicMock()
            def fail():raise StateError('between-profile-inbox-stopped')
            result=profiles.walk(settings.Settings(),threading.Event(),lambda _:True,lambda _:None,store,
                cycle=cycle,config=Config(),limit=1,between_profiles=fail)
        cycle.assert_not_called()
        self.assertEqual(result['status'],'profiles-stopped')
        self.assertEqual(result['reason'],'between-profile-inbox-stopped')
        self.assertFalse(result['send_attempts_unknown'])

    def test_completed_cycle_precedes_next_callback_and_cancel_stops_before_next(self):
        import assistant_profiles as profiles
        from test_inbox_profiles import Config,cycle_result
        from assistant_store import Store
        events=[];stop=threading.Event()
        def checkpoint():events.append('inbox')
        def cycle(*a,**k):events.append('native-cycle-complete');stop.set();return cycle_result()
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db',Path(folder)/'old');profiles.Session(store).set('city','Псков')
            result=profiles.walk(settings.Settings(),stop,lambda _:True,lambda _:None,store,
                cycle=cycle,config=Config(),limit=2,between_profiles=checkpoint)
        self.assertEqual(events,['inbox','native-cycle-complete'])
        self.assertEqual(result['status'],'profiles-cancelled')
