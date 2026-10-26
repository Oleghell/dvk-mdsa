"""Reports 275/276/278: synthetic HTTP and journals, no live service/device."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock,patch
import io,tempfile,types,unittest,urllib.error
import assistant_key_pool as pool
import mumu_ai as ai
import groq_reply as g
import gemini_reply as google
import assistant_reply_window as window
import cloud_database as cloud
from assistant_store import Store
from assistant_guided_chain import GuidedChain
from test_guided_chain import WHO,GREETING,snapshot
from test_mumu1313_providers import google as response_body,chat,client,REPLY
from test_cloud_database import FakeRaw
import test_cloud_database as driver_tests

class FullFailover(unittest.TestCase):
    def setUp(self):
        self.cache=dict(pool._CACHE);pool._CACHE.clear();self.addCleanup(self.restore)
    def restore(self):pool._CACHE.clear();pool._CACHE.update(self.cache)
    def responder(self,keys,success=None):
        self.clients={};self.pools={}
        def factory(provider,model,values,cancelled):
            def adapter(**kwargs):
                key=kwargs['key_loader']();c=client(response_body() if provider=='gemini' else chat())
                if key!=success:
                    c.open.side_effect=urllib.error.HTTPError('https://example.invalid',429,'limit',{'Retry-After':'60'},io.BytesIO(b'{}'))
                self.clients[key]=c
                module=google if provider=='gemini' else g
                return module.Responder(**kwargs,opener=c,rules_loader=lambda:'Правила')
            result=pool.Responder(provider,model,values,cancelled,factory=adapter,clock=lambda:0)
            self.pools[provider]=result;return result
        return ai.Responder('gemini',google.MODEL,collector=lambda p:keys.get(p,[]),factory=factory)
    def history(self):return snapshot(('Норм',False),('Привет',False))
    def test_fourth_key_remains_available_after_three_real_http_rate_limits(self):
        keys=['AQ.'+str(i)*40 for i in range(1,5)]
        r=self.responder({'gemini':keys},keys[-1])
        self.assertEqual(r('question',self.history()),REPLY)
        self.assertEqual(r.calls,4)
        self.assertEqual([x['code'] for x in r.failure_summary],['gemini-rate-limit']*3)
        self.assertTrue(all(x['retry_in_seconds']==60 for x in r.failure_summary))
    def test_next_provider_available_after_three_real_http_rate_limits(self):
        keys=['AQ.'+str(i)*40 for i in range(1,4)];groq='gsk_'+'a'*40
        r=self.responder({'gemini':keys,'groq':[groq]},groq)
        self.assertEqual(r('question',self.history()),REPLY)
        self.assertEqual(r.provider_calls['gemini'],3);self.assertEqual(r.provider_calls['groq'],1)
    def test_provider_cooldowns_are_not_cleared_or_bypassed(self):
        keys=['AQ.'+str(i)*40 for i in range(1,5)];r=self.responder({'gemini':keys})
        with self.assertRaisesRegex(g.GroqError,'gemini-key-pool-exhausted'):r('question',self.history())
        self.assertEqual(r.calls,4)
        with self.assertRaisesRegex(g.GroqError,'gemini-key-pool-exhausted'):r('question',self.history())
        self.assertEqual(r.calls,4)
        self.assertTrue(all(x['cooldown'] for x in r.failure_summary))
    def test_original_transport_timeout_not_shortened_by_mumu_wrapper(self):
        key='AQ.'+'a'*40;r=self.responder({'gemini':[key]},key)
        r('question',self.history())
        self.assertEqual(self.clients[key].open.call_args.kwargs['timeout'],30)

class SessionLifetime(unittest.TestCase):
    def setUp(self):
        self.old=getattr(cloud._local,'idle',[]);cloud._local.idle=[]
        self.addCleanup(self.restore)
    def restore(self):cloud.close_idle_connections();cloud._local.idle=self.old
    def test_only_one_idle_session_per_thread(self):
        a,b=FakeRaw(),FakeRaw();cloud.Connection(a,{},{}).close();cloud.Connection(b,{},{}).close()
        self.assertEqual(len(cloud._local.idle),1);self.assertFalse(a.closed);self.assertTrue(b.closed)
    def test_cleanup_does_not_close_active_transaction(self):
        idle,active=FakeRaw(),FakeRaw();cloud.Connection(idle,{},{}).close()
        current=cloud.Connection(active,{},{});current.execute('BEGIN IMMEDIATE')
        cloud.close_idle_connections();self.assertTrue(idle.closed);self.assertFalse(active.closed)
        current.execute('ROLLBACK');current.close()
    def test_callback_releases_idle_session_even_when_failed(self):
        from assistant_pass import host_worker
        raw=FakeRaw()
        def fail():cloud.Connection(raw,{},{}).close();raise RuntimeError('PRIVATE')
        with self.assertRaises(RuntimeError):host_worker(fail,())
        self.assertTrue(raw.closed);self.assertEqual(cloud._local.idle,[])
    def test_connect_network_failure_retried_only_before_any_journal_body(self):
        class Network(Exception):sqlstate='08006'
        raw=FakeRaw();driver=types.SimpleNamespace(connect=Mock(side_effect=[Network('PRIVATE'),raw]))
        with patch.dict('sys.modules',psycopg=driver),patch.object(cloud.time,'sleep'):
            self.assertIs(cloud.raw_connect(driver_tests.CloudDriverSettings().config()),raw)
        self.assertEqual(driver.connect.call_count,2)
        self.assertFalse(any('BEGIN' in q or 'UPDATE' in q for q,_ in raw.queries))
    def test_connect_permission_denied_not_retried(self):
        class Denied(Exception):sqlstate='28P01'
        driver=types.SimpleNamespace(connect=Mock(side_effect=Denied('PRIVATE PASSWORD')))
        with patch.dict('sys.modules',psycopg=driver),patch.object(cloud.time,'sleep') as sleep:
            with self.assertRaises(cloud.CloudDatabaseError) as caught:cloud.raw_connect(driver_tests.CloudDriverSettings().config())
        self.assertEqual(driver.connect.call_count,1);sleep.assert_not_called()
        self.assertEqual(cloud.diagnostic(caught.exception)['code'],'cloud-database-permission')
        self.assertNotIn('PRIVATE',str(caught.exception))
    def test_capacity_retry_is_bounded_and_correctly_classified(self):
        class Capacity(Exception):sqlstate='53300'
        driver=types.SimpleNamespace(connect=Mock(side_effect=Capacity('PRIVATE SERVER')))
        with patch.dict('sys.modules',psycopg=driver),patch.object(cloud.time,'sleep'):
            with self.assertRaises(cloud.CloudDatabaseError) as caught:cloud.raw_connect(driver_tests.CloudDriverSettings().config())
        self.assertEqual(driver.connect.call_count,2)
        self.assertEqual(cloud.diagnostic(caught.exception),dict(code='cloud-database-capacity',operation='connect',automatic_retry=False))

class ReadOnlyPolicies(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db',Path(self.temp.name)/'old')
        self.chain=GuidedChain(self.store,seal=lambda b:b,unseal=lambda b:b)
        self.chain.bind(snapshot(),(GREETING,),approved=True);window.enable(self.store)
    def test_normal_exclusion_checks_never_take_writer_lock(self):
        with patch.object(self.store,'connection',side_effect=AssertionError('No empty writer')):
            self.assertIsNone(window.reason(self.store,WHO))
            self.assertEqual(window.eligible_groups(self.store,[WHO],[]),([WHO],[]))
    def test_only_obsolete_age_exclusions_migrated(self):
        with self.store.connection() as db:
            db.execute('INSERT INTO inbox_reply_exclusions VALUES(?,?,?)',(WHO['account'],WHO['peer'],'reply-age-unverified'))
            db.execute("INSERT INTO inbox_reply_exclusions VALUES('100','201','new-start-excluded')")
        self.assertIsNone(window.reason(self.store,WHO))
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT peer,reason FROM inbox_reply_exclusions').fetchall(),[('201','new-start-excluded')])
    def test_empty_deferral_and_read_round_do_not_take_writer_lock(self):
        import assistant_history_wait as history
        import assistant_inbox as inbox
        history.initialize(self.store);inbox.read_round(self.chain,[WHO])
        with patch.object(self.store,'connection',side_effect=AssertionError('No empty writer')):
            history.clear(self.store,WHO)
            self.assertEqual(inbox.read_round(self.chain,[WHO]),[WHO])
            inbox.reset_read_round(self.chain)
    def test_read_round_still_resets_when_every_peer_was_checked(self):
        import assistant_inbox as inbox
        inbox.read_round(self.chain,[WHO]);inbox.record_checked(self.chain,WHO)
        self.assertEqual(inbox.read_round(self.chain,[WHO]),[WHO])
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM inbox_read_round').fetchone(),(0,))
