"""Two laptops / identical ports, synthetic persistent journals, no Android."""
from contextlib import closing
import json,os,sqlite3,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from assistant_store import StateError
from mumu_common import MumuError
from mumu_store import SharedStore,SharedPeerClaimed,TABLES
import mumu_cities as cities
import mumu_installation as installation
from mumu_namespace import ensure_account
from assistant_profiles import Session
from assistant_chain import Chain
from test_assistant import pending

A='a'*32;B='b'*32

class Installation(unittest.TestCase):
    def test_persistent_machine_local_and_not_cloud_config(self):
        with tempfile.TemporaryDirectory() as t,patch.object(installation,'machine_fingerprint',return_value='c'*64):
            first=installation.load(Path(t)/'one');second=installation.load(Path(t)/'two')
            self.assertEqual(first,installation.load(Path(t)/'one'))
            self.assertNotEqual(first,second)
            data=json.loads((Path(t)/'one/installation.json').read_text())
            self.assertEqual(set(data),{'schema','installation_id','machine'})
            self.assertNotIn('password',str(data))
    def test_parallel_first_creation_one_identity(self):
        with tempfile.TemporaryDirectory() as t,patch.object(installation,'machine_fingerprint',return_value='c'*64):
            results=[];errors=[]
            def run():
                try:results.append(installation.load(t))
                except Exception as error:errors.append(error)
            threads=[threading.Thread(target=run) for _ in range(8)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(10);self.assertFalse(thread.is_alive())
            self.assertEqual(errors,[]);self.assertEqual(len(results),8);self.assertEqual(len(set(results)),1)
    def test_busy_bootstrap_write_is_retried_not_fatal(self):
        # v1.3.84 (CI run 40887491098, windows shard 3-of-3): the pre-lock
        # sentinel write raced the mandatory byte lock and surfaced a raw
        # PermissionError instead of the retried installation-id-busy form.
        from contextlib import contextmanager
        from mumu_common import MumuError as Busy
        with tempfile.TemporaryDirectory() as t,patch.object(installation,'machine_fingerprint',return_value='c'*64):
            original=installation.installation_lock;fired=[]
            @contextmanager
            def once_busy(path):
                if not fired:
                    fired.append(1)
                    raise Busy('installation-id-busy')
                with original(path) as scope:yield scope
            with patch.object(installation,'installation_lock',once_busy):
                value=installation.load(t)
            self.assertEqual(installation.load(t),value)
            self.assertEqual(fired,[1])
    def test_corrupt_or_copied_identity_never_silently_reset(self):
        with tempfile.TemporaryDirectory() as t,patch.object(installation,'machine_fingerprint',return_value='c'*64):
            installation.load(t);path=Path(t)/'installation.json';original=path.read_bytes()
            with patch.object(installation,'machine_fingerprint',return_value='d'*64):
                with self.assertRaisesRegex(MumuError,'copied'):installation.load(t)
            self.assertEqual(path.read_bytes(),original)
            path.write_text('{broken')
            with self.assertRaisesRegex(MumuError,'invalid'):installation.load(t)
            self.assertEqual(path.read_text(),'{broken')
    def test_normal_store_and_gui_labels_use_same_installation(self):
        with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,LOCALAPPDATA=t,DVK_MUMU_MULTI='0'):
            store=SharedStore(device_port=5567)
            self.assertEqual(store.installation_id,installation.load())
            from mumu_worker import telegram_device_label
            with patch.dict(os.environ,DVK_INSTALLATION_ID=store.installation_id):
                self.assertIn('ПК '+store.installation_id[:8],telegram_device_label(5567))

class Namespaces(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db';self.old=Path(self.tmp.name)/'old'
    def store(self,identity,port=5567):return SharedStore(self.path,self.old,device_port=port,installation_id=identity)
    def test_same_port_different_laptops_separate_journals_shared_greeting(self):
        a=self.store(A);b=self.store(B)
        self.assertNotEqual(a.prefix,b.prefix);self.assertNotEqual(a.device_owner,b.device_owner)
        a.reserve(pending(),'Synthetic',approved=True)
        self.assertEqual(a.summary()['reserved'],1);self.assertEqual(b.summary()['reserved'],0)
        with self.assertRaises(SharedPeerClaimed):b.reserve(pending(account='101'),'Synthetic',approved=True)
        self.assertTrue(b.peer_claimed(pending(account='101')))
        with a.connection() as db:a.record_peer_outcome(db,dict(account='100',peer='201',chat='300'),'contact-refused')
        self.assertTrue(b.peer_terminal(pending(account='101',peer='201')))
    def test_legacy_unknown_and_binary_receipts_preserved_once(self):
        legacy=SharedStore(self.path,self.old,device_port=5567)
        action=legacy.reserve(pending(),'Synthetic',approved=True)
        legacy.finish(action,dict(send_attempted=True,send_handler_returned=False))
        Chain(legacy,contact_notifications=False);Session(legacy).set('city','LegacyCity')
        with legacy.connection() as db:
            db.execute("INSERT INTO chain_contact_outbox VALUES('300','1001',?,'unknown')",(b'\x00\xffopaque',))
            before={name:db.execute('SELECT * FROM '+name).fetchall() for name in ('manual_actions','chain_contact_outbox')}
        a=self.store(A);b=self.store(B)
        for store in (a,b,self.store(A)):
            with store.read_connection() as db:
                for name,rows in before.items():self.assertEqual(db.execute('SELECT * FROM '+name).fetchall(),rows)
            self.assertIsNone(Session(store).get('city'))
            self.assertEqual(store.summary()['statuses'],{'attempted-unknown':1})
        with legacy.read_connection() as db:
            for name,rows in before.items():self.assertEqual(db.execute('SELECT * FROM '+name).fetchall(),rows)
        # Subsequent constructors never merge a stale legacy copy over new state.
        a.reserve(pending(account='101',peer='202'),'New synthetic',approved=True)
        self.assertEqual(self.store(A).summary()['reserved'],2)
        self.assertEqual(self.store(B).summary()['reserved'],1)
    def test_both_original_default_and_other_ports_migrate(self):
        for port in (5563,5557):
            legacy=SharedStore(self.path,self.old,device_port=port)
            legacy.reserve(pending(account=str(port+100),peer=str(port+200)),'Synthetic',approved=True)
            scoped=self.store(A,port)
            self.assertEqual(scoped.summary()['reserved'],1)
            self.assertLessEqual(max(len(scoped.prefix+t) for t in TABLES),63)
    def test_new_identity_malformed_or_truncated_collision_denied(self):
        for invalid in ('',True,'g'*32,'a'*31,'a'*33):
            with self.assertRaises(MumuError):self.store(invalid)
        self.store(A)
        with self.assertRaisesRegex(StateError,'collision'):self.store('a'*20+'b'*12)
    def test_same_account_other_scope_is_persistently_denied_not_transferred(self):
        a=self.store(A);b=self.store(B);who=dict(account='100',peer='200',chat='300')
        ensure_account(a,who);ensure_account(a,who)
        with self.assertRaisesRegex(StateError,'account-owned-by-other-scope'):ensure_account(b,who)
        with self.assertRaisesRegex(StateError,'account-owned-by-other-scope'):self.store(B).reserve(pending(peer='202'),'Synthetic',approved=True)
        self.assertEqual(b.summary()['reserved'],0)
        ensure_account(b,dict(who,account='101'))
    def test_fresh_bound_read_rejects_foreign_account_before_approval(self):
        import assistant_guided_chain as guided
        import test_guided_chain as fixture
        a=self.store(A);b=self.store(B);ensure_account(a,fixture.WHO)
        chain=guided.GuidedChain(b);reader=MagicMock(return_value=fixture.snapshot())
        approve=MagicMock(return_value=True);sender=MagicMock()
        result=guided.walk(chain,fixture.WHO,threading.Event(),approve,reader,sender,
                           approved=True,greetings=(fixture.GREETING,),pause=lambda _:False)
        self.assertEqual(result['reason'],'account-owned-by-other-scope')
        self.assertEqual(result['submission_calls'],0);approve.assert_not_called();sender.assert_not_called()
        from assistant_error_notify import reasons
        self.assertIn('account-owned-by-other-scope',reasons(result))
    def test_concurrent_scopes_cannot_claim_same_account(self):
        a=self.store(A);b=self.store(B);barrier=threading.Barrier(2);results=[]
        def run(store):
            barrier.wait()
            try:ensure_account(store,dict(account='100',peer='200',chat='300'));results.append('won')
            except StateError:results.append('blocked')
        threads=[threading.Thread(target=run,args=(s,)) for s in (a,b)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(10);self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(results),['blocked','won'])
    def test_city_claims_never_released_by_same_port_on_other_laptop(self):
        from test_search_city import ready_city
        a=self.store(A);b=self.store(B);names=['City '+chr(65+i) for i in range(20)]
        token,allowed,used=cities.reserve(a,names)
        other_token,other_allowed,_=cities.reserve(b,names)
        self.assertFalse(set(allowed)&set(other_allowed))
        value=ready_city();value['navigation'].update(city_selected_name=allowed[0],city_previous_name=None,city_round_reset=False)
        cities.complete(a,token,allowed,value)
        self.assertTrue(cities.owns(a,allowed[0]));self.assertFalse(cities.owns(b,allowed[0]))
        # Clearing B only releases B; it cannot invalidate A's pending/active CAS.
        from assistant_profiles import clear_history
        clear_history(b);self.assertTrue(cities.owns(a,allowed[0]))
        with a.read_connection() as db:
            self.assertEqual(db.execute('SELECT device FROM mumu_city_claims').fetchall(),[(a.device_owner,)])
    def test_legacy_city_claims_not_adopted_or_stolen(self):
        legacy=SharedStore(self.path,self.old,device_port=5567)
        with legacy.connection() as db:db.execute("INSERT INTO mumu_city_claims VALUES('city a','5567','active','old')")
        a=self.store(A);self.assertFalse(cities.owns(a,'City A'))
        token,allowed,_=cities.reserve(a,['City '+chr(65+i) for i in range(20)])
        self.assertNotIn('city a',set(x.lower() for x in allowed))
        with a.read_connection() as db:self.assertEqual(db.execute("SELECT device,token FROM mumu_city_claims WHERE city='city a'").fetchone(),('5567','old'))
    def test_copied_pending_outbox_neither_claims_account_nor_exports(self):
        legacy=SharedStore(self.path,self.old,device_port=5567);Chain(legacy,contact_notifications=True)
        with legacy.connection() as db:
            db.execute("INSERT INTO chain_dialogs VALUES('100','200','300','hash','done','salt')")
            db.execute("INSERT INTO chain_contact_outbox VALUES('300','1001',?,'pending')",(b'opaque-encrypted',))
        from assistant_inbox import InboxChain,walk
        from assistant_settings import Settings
        for installation_id in (A,B):
            store=self.store(installation_id);chain=InboxChain(store)
            chain.notify=MagicMock(side_effect=AssertionError('Copied contacts must not export'))
            nav=MagicMock(side_effect=AssertionError('No UI for terminal chat'))
            result=walk(Settings(),threading.Event(),lambda *args:False,lambda _:None,chain,
                        navigator=nav,reader=MagicMock(),sender=MagicMock())
            self.assertEqual(result['contacts_forwarded'],0);chain.notify.assert_not_called();nav.assert_not_called()
            with store.read_connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM mumu_account_owners').fetchone(),(0,))
                self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone(),('pending',))
    def test_cloud_cutover_protects_scoped_attempts_and_owner_registries(self):
        import cloud_migration as migration
        from cloud_database import CloudDatabaseError
        for name in ('i'+'a'*20+'_m5567__manual_actions',
                     'i'+'a'*20+'_m5567__chain_send_attempts',
                     'i'+'a'*20+'_m5567__chain_send_authorizations',
                     'mumu_account_owners','mumu_installation_scopes','mumu_manual_silences'):
            raw=MagicMock();raw.execute.return_value.fetchall.return_value=[(name,'unused')]
            with self.assertRaisesRegex(CloudDatabaseError,'older-than-upload'):
                migration.require_latest_journals(raw,MagicMock(),[])
    def test_failed_copy_rolls_back_all_destination_tables(self):
        legacy=SharedStore(self.path,self.old,device_port=5567)
        import mumu_namespace
        original=mumu_namespace.schema_info;calls=[]
        def fail_after_one(ddl):
            calls.append(ddl)
            if len(calls)==2:raise ValueError('synthetic failure')
            return original(ddl)
        with patch.object(mumu_namespace,'schema_info',side_effect=fail_after_one):
            with self.assertRaises(ValueError):self.store(A)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(any(name.startswith('i'+A[:20]) for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")))
        self.assertEqual(self.store(A).summary()['reserved'],0)

if __name__=='__main__':unittest.main()
