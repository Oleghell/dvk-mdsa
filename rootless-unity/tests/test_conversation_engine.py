import json,tempfile,unittest,sqlite3
from pathlib import Path
from dataclasses import replace
import conversation_engine as p

class Clock:
    value=100.
    def __call__(self):return self.value
    def advance(self):self.value+=1.01
class Backend:
    def __init__(self):self.calls=[];self.fail=False
    def send_reply(self,*args):
        self.calls.append(args)
        if self.fail:raise RuntimeError('PRIVATE')
        return True
class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'dialogs.sqlite';self.backend=Backend();self.clock=Clock();self.e=p.Engine(self.path,self.backend,clock=self.clock,choose=lambda:0)
    def tearDown(self):self.e.close();self.tmp.cleanup()
    def snapshot(self,*extras,chat='50',peer='20',**kw):
        return p.Snapshot('10',peer,chat,'Тест',tuple([p.Message('1','10','Привет 🙂')]+list(extras)),**kw)
    def incoming(self,id,text):return p.Message(str(id),'20',text)
    def own(self,id,text):return p.Message(str(id),'10',text)
    def enroll(self):self.e.register(self.snapshot(),approved=True)
    def test_whole_flow_waits_for_actual_question_ack(self):
        self.enroll();reply=self.incoming(2,'Привет!');a=self.snapshot(reply)
        self.assertEqual(self.e.handle(a),'handler_returned');self.assertEqual(self.backend.calls[0][3],p.QUESTIONS[0])
        self.assertEqual(self.e.handle(a),'await_confirmation');self.assertEqual(len(self.backend.calls),1)
        self.clock.advance();q=self.own(3,p.QUESTIONS[0]);m=self.incoming(4,'Все хорошо')
        self.assertEqual(self.e.handle(self.snapshot(reply,q,m)),'handler_returned');self.assertEqual(self.backend.calls[1][3],p.CONTACT_TEXT)
        self.clock.advance();invite=self.own(5,p.CONTACT_TEXT);contact=self.incoming(6,'Мой телеграм @test_user')
        self.assertEqual(self.e.handle(self.snapshot(reply,q,m,invite,contact)),'contact_saved');self.assertEqual(self.e.state('50'),'done')
        calls=[];self.e.notifier=lambda body:calls.append(body) or True
        self.assertEqual(self.e.notify_one(),'accepted');self.assertEqual(calls,[dict(name='Тест',contacts=['@test_user'])])
        self.assertEqual(self.e.notify_one(),'nothing_pending');self.assertEqual(len(self.backend.calls),2)
    def test_unknown_send_never_retried_after_restart(self):
        self.enroll();self.backend.fail=True;s=self.snapshot(self.incoming(2,'Привет'))
        self.assertEqual(self.e.handle(s),'unknown');self.e.close();self.e=p.Engine(self.path,self.backend,clock=self.clock)
        self.clock.advance();self.assertEqual(self.e.handle(s),'await_confirmation');self.assertEqual(len(self.backend.calls),1)
        self.assertNotIn('PRIVATE',json.dumps(self.e.summary()))
    def test_reserved_before_process_crash_stays_pending(self):
        self.enroll()
        def crash(*a):raise KeyboardInterrupt
        self.backend.send_reply=crash
        with self.assertRaises(KeyboardInterrupt):self.e.handle(self.snapshot(self.incoming(2,'Привет')))
        self.e.close();self.e=p.Engine(self.path,Backend(),clock=self.clock)
        self.assertEqual(self.e.handle(self.snapshot(self.incoming(2,'Привет'))),'await_confirmation')
    def test_burst_cannot_trigger_two_replies(self):
        self.enroll();s=self.snapshot(self.incoming(2,'Привет'),self.incoming(3,'Кто это?'))
        self.e.handle(s);self.clock.advance();self.e.handle(s);self.assertEqual(len(self.backend.calls),1)
    def test_refusal_before_contact_does_not_notify(self):
        self.enroll();self.assertEqual(self.e.handle(self.snapshot(self.incoming(2,'Не пиши мне. @test_user'))),'declined')
        self.assertEqual(self.backend.calls,[]);self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0],0)
    def test_negative_mood_and_nontext_stop_for_manual_review(self):
        for text in ('Плохо',None,''):
            self.e.db.execute('DELETE FROM dialogs');self.enroll()
            self.assertEqual(self.e.handle(self.snapshot(self.incoming(2,text))),'manual_review')
        self.assertEqual(self.backend.calls,[])
    def test_untracked_never_sent(self):
        self.assertEqual(self.e.handle(self.snapshot(self.incoming(2,'Привет'))),'untracked');self.assertEqual(self.backend.calls,[])
    def test_different_account_and_peer_rejected(self):
        self.enroll()
        for s in (replace(self.snapshot(),peer='21'),replace(self.snapshot(),account='11')):
            with self.assertRaises(p.PolicyError):self.e.handle(s)
        with self.assertRaises(p.PolicyError):self.e.register(replace(self.snapshot(),chat='60',account='11'),approved=True)
    def test_enrollment_explicit_greeting_and_max_ten(self):
        with self.assertRaises(p.PolicyError):self.e.register(self.snapshot())
        with self.assertRaises(p.PolicyError):self.e.register(replace(self.snapshot(),messages=(p.Message('1','20','Привет'),)),approved=True)
    def test_limit_and_duplicate_peer(self):
        self.enroll();self.assertFalse(self.e.register(self.snapshot(),approved=True))
        with self.assertRaises(p.PolicyError):self.e.register(self.snapshot(chat='51'),approved=True)
        for i in range(1,10):self.e.register(self.snapshot(chat=str(50+i),peer=str(20+i)),approved=True)
        with self.assertRaises(p.PolicyError):self.e.register(self.snapshot(chat='70',peer='40'),approved=True)
        self.assertEqual(self.e.summary()['dialogs'],10)
    def test_one_second_gate_for_actions(self):
        self.enroll();self.e.register(self.snapshot(chat='51',peer='21'),approved=True)
        self.e.handle(self.snapshot(self.incoming(2,'Привет')))
        s=self.snapshot(p.Message('2','21','Привет'),chat='51',peer='21')
        self.assertEqual(self.e.handle(s),'delay');self.clock.advance();self.assertEqual(self.e.handle(s),'handler_returned')
    def test_duplicate_outgoing_and_manual_intervention_stop(self):
        self.enroll();s=self.snapshot(self.incoming(2,'Привет'));self.e.handle(s)
        out=self.snapshot(self.incoming(2,'Привет'),self.own(3,'Неизвестный ручной ответ'))
        self.assertEqual(self.e.handle(out),'manual_review');self.assertEqual(len(self.backend.calls),1)
    def test_bad_snapshot_never_sends(self):
        self.enroll()
        for kw in (dict(fully_loaded=False),dict(loading=True),dict(identity_verified=False),dict(chronological=False),dict(samples=1),dict(samples=True)):
            with self.assertRaises(p.PolicyError):self.e.handle(self.snapshot(self.incoming(2,'Привет'),**kw))
        with self.assertRaises(p.PolicyError):self.e.handle(self.snapshot(self.incoming(1,'duplicate')))
        self.assertEqual(self.backend.calls,[])
    def test_notification_unknown_not_retried(self):
        self.enroll();self.e.handle(self.snapshot(self.incoming(2,'+7 (999) 123-45-67')))
        calls=[]
        def fail(body):calls.append(body);raise RuntimeError('PRIVATE')
        self.e.notifier=fail;self.assertEqual(self.e.notify_one(),'unknown');self.clock.advance();self.assertEqual(self.e.notify_one(),'nothing_pending');self.assertEqual(len(calls),1)
    def test_no_body_or_contacts_in_summary(self):
        self.enroll();text='PRIVATE BODY +79991234567';self.e.handle(self.snapshot(self.incoming(2,text)))
        summary=json.dumps(self.e.summary());self.assertNotIn('79991234567',summary)
        self.e.db.execute('PRAGMA wal_checkpoint(FULL)')
        self.assertNotIn('PRIVATE BODY',self.path.read_bytes().decode('utf-8','ignore'))

class Parsing(unittest.TestCase):
    def test_contacts(self):
        for text,expected in [('@test_user',['@test_user']),('https://t.me/test_user',['@test_user']),('https://telegram.me/Test_User',['@Test_User']),('+7 (999) 123-45-67',['+79991234567']),('89991234567',['+79991234567'])]:self.assertEqual(p.contacts(text),expected)
    def test_not_contacts(self):
        for text in ('a@example.com','1234567890','4111111111111111','19.10.2026','evil.t.me/test_user','https://evil.t.me/test_user','@abc','@12345'):
            self.assertEqual(p.contacts(text),[],text)
