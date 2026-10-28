"""Approved latency changes: synthetic clocks, HTTP and temporary journals only."""
from contextlib import contextmanager
from pathlib import Path
import copy,json,tempfile,threading,time,unittest
from unittest.mock import Mock,patch
import assistant_ai_budget as budget
import assistant_authorization as authorization
import assistant_settings as settings
from assistant_notification_queue import Dispatcher
from assistant_polling import Schedule
from assistant_store import Store
import assistant_guided_chain as guided
import test_guided_chain as f
import test_inbox_reactivity as contact
from test_inbox_profiles import WHO,snap,msg,nav

class Deadlines(unittest.TestCase):
    def test_whole_budget_is_shared_by_attempts(self):
        clock=[0.0];b=budget.Budget(12,3,lambda:clock[0])
        self.assertEqual(b.claim(),6);clock[0]=7
        self.assertEqual(b.claim(),5);clock[0]=11
        self.assertEqual(b.claim(),1)
        with self.assertRaises(TimeoutError):b.claim()
    def test_late_http_is_discarded_and_does_not_block_caller(self):
        release=threading.Event();started=threading.Event()
        class Response:
            def __enter__(self):started.set();return self
            def __exit__(self,*a):pass
            def read(self,n):release.wait(2);return b'late'
        client=Mock();client.open.return_value=Response()
        try:
            with budget.generation(.08):
                with self.assertRaises(TimeoutError):budget.request(client,object(),30,lambda:False)
            self.assertTrue(started.is_set())
        finally:release.set()
    def test_cancel_checked_while_http_is_in_flight(self):
        release=threading.Event();cancelled=threading.Event()
        class Response:
            def __enter__(self):cancelled.set();return self
            def __exit__(self,*a):pass
            def read(self,n):release.wait(2);return b'late'
        client=Mock();client.open.return_value=Response()
        from groq_reply import GroqError
        try:
            with budget.generation(1):
                with self.assertRaises(GroqError) as caught:budget.request(client,object(),30,cancelled.is_set)
            self.assertEqual(str(caught.exception),'groq-cancelled')
        finally:release.set()
    def test_default_transport_unchanged_without_mumu_budget(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None);response.read.return_value=b'ok'
        client=Mock();client.open.return_value=response;request=object()
        self.assertEqual(budget.request(client,request,30,lambda:False),b'ok')
        client.open.assert_called_once_with(request,timeout=30)
    def test_read_budget_nests_without_extending_outer_deadline(self):
        import assistant_read_budget as r
        with r.limit(1):
            before=r.remaining()
            with r.limit(20):self.assertLessEqual(r.remaining(),before)
        self.assertEqual(r.remaining(),25)

class FastOptions(unittest.TestCase):
    def test_fast_typing_has_no_wait_but_still_rejects_cancel_invalid_text(self):
        stopped=threading.Event();wait=Mock()
        permit=authorization.RunAuthorization(stopped,wait=wait,typing_delay_enabled=False,fast_runtime=True)
        for kind in ('question','contact','clarify','followup'):self.assertTrue(permit(kind,'Тест ответа',lambda:False))
        wait.assert_not_called();stopped.set();self.assertFalse(permit('question','Тест',lambda:False))
    def test_schema9_roundtrips_switch_and_keeps_speed_and_old_schemas_load_fast(self):
        with tempfile.TemporaryDirectory() as folder:
            value=settings.Settings(typing_words_per_minute=70,typing_delay_enabled=True);settings.save(value,folder)
            self.assertEqual(settings.load(folder),value)
            p=Path(folder)/'workflow-settings.json';v=json.loads(p.read_text());v['settings_version']=8;v.pop('typing_delay_enabled');p.write_text(json.dumps(v))
            old=settings.load(folder);self.assertFalse(old.typing_delay_enabled);self.assertEqual(old.typing_words_per_minute,70)
    def test_active_polling_then_idle_backoff_never_changes_profile_timer(self):
        now=[10];schedule=Schedule(lambda:now[0],jitter=lambda seconds:seconds*1.6)
        self.assertEqual(schedule.delay(5),8)  # idle wait is jittered upward only
        schedule.record(dict(new_incoming_messages=1));self.assertEqual(schedule.delay(5),2)
        now[0]=41;self.assertEqual(schedule.delay(5),8)
    def test_idle_jitter_is_bounded_and_never_shortens_the_wait(self):
        from assistant_polling import IDLE_JITTER_RANGE, idle_jitter
        low,high=IDLE_JITTER_RANGE
        for _ in range(200):
            value=idle_jitter(5)
            self.assertGreaterEqual(value,5*low);self.assertLessEqual(value,5*high)
        self.assertLess(low,1.01);self.assertGreater(high,1.2)
    def test_runtime_fields_numeric_and_private_strings_never_exported(self):
        import assistant_runtime as runtime
        import assistant_error_notify as notify
        values={}
        with runtime.collect(values,lambda _:None):
            with runtime.phase('db_lock'):pass
            with runtime.phase('ai'):pass
        self.assertEqual(values['db_lock_calls'],1)
        data=notify.diagnostic_json(dict(diagnostic=values));self.assertIn(b'db_lock_ms',data)
        self.assertNotIn(b'SQL',data)

class DurableQueue(contact.ContactFlow):
    def ready(self):
        chain,messages=self.waiting();chain.media_required=False
        stage,_=chain.proposal(dict(snap(*messages,msg(1006,'@self_handle')),peer_name='Тест'))
        self.assertEqual(stage,'done');return chain
    def test_network_runs_once_in_background_without_native_access(self):
        chain=self.ready();dispatcher=Dispatcher(self.stop);self.addCleanup(dispatcher.close)
        chain.notification_dispatcher=dispatcher;started=threading.Event();release=threading.Event();calls=[]
        def slow(data):calls.append(data);started.set();release.wait(2);return True
        try:
            self.assertEqual(chain.notify(WHO,slow,self.stop.is_set),'queued')
            self.assertTrue(started.wait(1))
            self.assertIn(chain.notify(WHO,slow,self.stop.is_set),('queued','nothing-pending'))
            with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone(),('attempted-unknown',))
        finally:release.set()
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            with self.store.read_connection() as db:status=db.execute('SELECT status FROM chain_contact_outbox').fetchone()[0]
            if status=='accepted':break
            time.sleep(.01)
        self.assertEqual(status,'accepted');self.assertEqual(len(calls),1)
        self.assertEqual(chain.notify(WHO,slow,self.stop.is_set),'nothing-pending')
    def test_unknown_network_outcome_not_replayed_after_recreate(self):
        chain=self.ready();dispatcher=Dispatcher(self.stop);chain.notification_dispatcher=dispatcher
        called=threading.Event()
        def fail(data):called.set();raise OSError('PRIVATE')
        try:
            self.assertEqual(chain.notify(WHO,fail,self.stop.is_set),'queued');self.assertTrue(called.wait(1))
        finally:dispatcher.close()
        chain.notification_dispatcher=None
        self.assertEqual(chain.notify(WHO,Mock(side_effect=AssertionError('No retry'))),'nothing-pending')
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone(),('unknown',))
    def test_shutdown_leaves_unstarted_pending_rows_durable(self):
        chain=self.ready();stopped=threading.Event();stopped.set();dispatcher=Dispatcher(stopped);self.addCleanup(dispatcher.close)
        chain.notification_dispatcher=dispatcher
        self.assertEqual(chain.notify(WHO,Mock(),stopped.is_set),'cancelled')
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone(),('pending',))
for name in dir(contact.ContactFlow):
    if name.startswith('test_') and name not in DurableQueue.__dict__:setattr(DurableQueue,name,None)

class QueryCost(unittest.TestCase):
    def test_already_observed_receipts_do_not_acquire_writer_lock(self):
        import assistant_reply_audit as audit
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db',Path(folder)/'old');chain=guided.GuidedChain(store,seal=lambda v:v,unseal=lambda v:v)
            chain.bind(f.snapshot(),(f.GREETING,),approved=True);chain.proposal(f.snapshot(('Привет',False)))
            with store.connection() as db:db.execute("UPDATE chain_reply_receipts SET status='answered'")
            with patch.object(store,'connection',side_effect=AssertionError('No empty writer transaction')):
                audit.observe(chain,f.snapshot(('Привет',False)))
                audit.synchronize(chain,f.snapshot(('Привет',False)))
                self.assertEqual(audit.pending(chain,f.WHO),[])

class LockRecovery(unittest.TestCase):
    def raw(self,failures=0,target='pg_advisory_xact_lock'):
        from test_cloud_database import FakeRaw
        class LockTimeout(Exception):sqlstate='55P03'
        class Raw(FakeRaw):
            remaining=failures
            def execute(self,sql,params=None,**kwargs):
                result=super().execute(sql,params,**kwargs)
                if target in sql and self.remaining:
                    self.remaining-=1;raise LockTimeout('PRIVATE SQL')
                return result
        return Raw()
    def test_fifo_lock_acquired_once_before_caller_body(self):
        import cloud_database as cloud
        raw=self.raw();db=cloud.Connection(raw,{},{});db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE x SET y=?',(1,));db.execute('COMMIT')
        sql=[q for q,_ in raw.queries]
        self.assertEqual(sum('pg_advisory' in q for q in sql),1)
        self.assertEqual(sql.count('ROLLBACK'),0)
        self.assertEqual(sum(q.startswith('UPDATE') for q in sql),1)
        self.assertEqual(sql.count('COMMIT'),1)
        self.assertTrue(any("lock_timeout='10000'" in q for q in sql))
    def test_lock_deadline_exhaustion_never_enters_transaction_body(self):
        import cloud_database as cloud
        raw=self.raw(9);db=cloud.Connection(raw,{},{} )
        with self.assertRaises(cloud.CloudDatabaseError) as caught:db.execute('BEGIN IMMEDIATE')
        self.assertEqual(cloud.diagnostic(caught.exception),dict(code='cloud-database-lock-timeout',operation='lock',automatic_retry=False))
        self.assertEqual(sum('pg_advisory' in q for q,_ in raw.queries),1)
        self.assertFalse(db.in_transaction)
    def test_write_and_commit_failure_never_replayed(self):
        import cloud_database as cloud
        for target in ('UPDATE','COMMIT'):
            with self.subTest(target=target):
                raw=self.raw(2,target);db=cloud.Connection(raw,{},{});db.execute('BEGIN IMMEDIATE')
                with self.assertRaises(cloud.CloudDatabaseError):db.execute('UPDATE x SET y=1' if target=='UPDATE' else 'COMMIT')
                self.assertEqual(sum(target in q for q,_ in raw.queries),1)
                self.assertEqual(sum('pg_advisory' in q for q,_ in raw.queries),1)
    def test_bootstrap_keeps_original_one_attempt_longer_timeout(self):
        import cloud_database as cloud
        raw=self.raw(2);db=cloud.Connection(raw,{},{} )
        with cloud.journal_initialization():
            with self.assertRaises(cloud.CloudDatabaseError):db.execute('BEGIN IMMEDIATE')
        self.assertEqual(sum('pg_advisory' in q for q,_ in raw.queries),1)
        self.assertTrue(any("lock_timeout='60000'" in q for q,_ in raw.queries))
    def test_database_diagnostic_is_closed_and_does_not_export_sql(self):
        import assistant_error_notify as notify
        safe=dict(code='cloud-database-lock-timeout',operation='lock',automatic_retry=False)
        raw=notify.diagnostic_json(dict(diagnostic=dict(database=safe)))
        self.assertIn(b'cloud-database-lock-timeout',raw)
        raw=notify.diagnostic_json(dict(diagnostic=dict(database=dict(safe,sql='PRIVATE'))))
        self.assertNotIn(b'PRIVATE',raw)

class FreshBinding(unittest.TestCase):
    def test_bound_chat_uses_read_only_but_checks_current_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db',Path(folder)/'old');chain=guided.GuidedChain(store,seal=lambda v:v,unseal=lambda v:v)
            chain.bind(f.snapshot(),(f.GREETING,),approved=True)
            with patch.object(store,'connection',side_effect=AssertionError('No empty writer')):
                chain.bind(f.snapshot(),(f.GREETING,),approved=True)
            with store.connection() as db:db.execute('DELETE FROM chain_dialogs')
            from assistant_store import StateError
            with self.assertRaisesRegex(StateError,'guided-history-not-verified'):chain.bind(f.snapshot(),(f.GREETING,),approved=True)

class ErrorQueue(unittest.TestCase):
    def setUp(self):
        from mumu_store import SharedStore
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=SharedStore(Path(self.temp.name)/'db',Path(self.temp.name)/'old',device_port=5565)
        self.chain=guided.GuidedChain(self.store,seal=lambda v:b'ENC'+v,unseal=lambda v:v[3:])
        self.chain.bind(f.snapshot(),(f.GREETING,),approved=True)
        self.hints=[]
        self.chain.notification_dispatcher=Mock()
        self.chain.notification_dispatcher.exit_hint.side_effect=lambda *a:self.hints.append(a)
    def enqueue(self,sender=None):
        from assistant_exit_notify import notify_exit
        sender=sender or Mock(return_value=True)
        result=notify_exit(self.chain,f.WHO,dict(reason='send-outcome-unknown'),sender=sender)
        return result,sender
    def signature(self):
        with self.store.read_connection() as db:return db.execute('SELECT signature FROM chain_exit_notices').fetchone()[0]
    def test_durable_encrypted_queue_resumes_then_sends_once(self):
        import assistant_exit_queue as queue
        result,sender=self.enqueue();self.assertEqual(result['notification'],'queued');sender.assert_not_called()
        with self.store.read_connection() as db:
            body=db.execute('SELECT body FROM chain_exit_payloads').fetchone()[0]
            self.assertTrue(body.startswith(b'ENC'))
            self.assertEqual(db.execute('SELECT status FROM chain_exit_notices').fetchone(),('queued',))
        self.hints.clear();queue.resume(self.chain,sender,None,lambda:False);self.assertEqual(len(self.hints),1)
        signature=self.signature()
        self.assertEqual(queue.deliver(self.chain,f.WHO,signature,(sender,None),lambda:False),'accepted')
        self.assertEqual(queue.deliver(self.chain,f.WHO,signature,(sender,None),lambda:False),'nothing-pending')
        sender.assert_called_once()
    def test_unknown_http_not_replayed_on_resume(self):
        import assistant_exit_queue as queue
        _,sender=self.enqueue(Mock(side_effect=OSError('PRIVATE')))
        self.assertEqual(queue.deliver(self.chain,f.WHO,self.signature(),(sender,None),lambda:False),'unknown')
        self.hints.clear();queue.resume(self.chain,sender,None,lambda:False);self.assertEqual(self.hints,[])
        sender.assert_called_once()
    def test_stop_before_attempt_leaves_pending_for_next_start(self):
        import assistant_exit_queue as queue
        _,sender=self.enqueue()
        self.assertEqual(queue.deliver(self.chain,f.WHO,self.signature(),(sender,None),lambda:True),'cancelled');sender.assert_not_called()
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_exit_notices').fetchone(),('queued',))
    def test_manual_block_after_queue_prevents_network(self):
        import assistant_exit_queue as queue
        from mumu_peer_policy import record
        _,sender=self.enqueue()
        with self.store.connection() as db:record(db,f.WHO,'manual-block','telegram')
        self.assertEqual(queue.deliver(self.chain,f.WHO,self.signature(),(sender,None),lambda:False),'blocked');sender.assert_not_called()
    def test_encryption_failure_has_no_plaintext_network_fallback(self):
        self.chain.seal=Mock(side_effect=ValueError('PRIVATE'))
        result,sender=self.enqueue();self.assertEqual(result['notification'],'blocked');sender.assert_not_called()
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_exit_payloads').fetchone(),(0,))

class ErrorBodyDeadline(unittest.TestCase):
    def test_slow_error_body_cannot_extend_ai_deadline(self):
        import urllib.error
        release=threading.Event()
        class Body:
            def read(self,n):release.wait(2);return b'late error'
            def close(self):pass
        client=Mock();client.open.side_effect=urllib.error.HTTPError('https://example.invalid',429,'rate limit',{},Body())
        try:
            with budget.generation(.06):
                with self.assertRaises(TimeoutError):budget.request(client,object(),30,lambda:False)
        finally:release.set()

class ReadDeadline(f.WholeChain):
    def test_combined_read_retries_stop_at_shared_deadline(self):
        from test_1210_context_loading import Clock
        from test_1214_read_budget import budget as read_failure
        clock=Clock();self.chain.history_read_budget=1
        out=self.walk([read_failure()]*8,pause=clock.pause,read_clock=clock)
        self.assertEqual(out['reason'],'history-read-budget-timeout')
        self.assertTrue(out['diagnostics']['history_budget_exhausted'])
        self.assertEqual(clock.delays,[.5,.5]);self.assertFalse(self.sent)
    def test_loading_deadline_preserves_authored_loading_evidence(self):
        from test_1210_context_loading import Clock,loading
        clock=Clock();self.chain.history_read_budget=2
        out=self.walk([loading()]*8,pause=clock.pause,read_clock=clock)
        self.assertEqual(out['reason'],'history-loading-timeout')
        self.assertTrue(out['diagnostics']['history_wait_exhausted']);self.assertFalse(self.sent)
    def test_identity_error_at_deadline_is_not_reclassified(self):
        from test_1210_context_loading import Clock
        from one_chat_device import ReadStopped
        clock=Clock();self.chain.history_read_budget=1
        def read(who):clock.now=2;raise ReadStopped('identity-changed')
        out=guided.walk(self.chain,f.WHO,self.stop,self.approve,read,self.send,approved=True,read_clock=clock)
        self.assertEqual(out['reason'],'bound-chat-read-failed');self.assertFalse(self.sent)
for name in dir(f.WholeChain):
    if name.startswith('test_') and name not in ReadDeadline.__dict__:setattr(ReadDeadline,name,None)
