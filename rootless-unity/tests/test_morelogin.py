"""Synthetic multi-phone/API/SSH/database tests. Never use real account credentials."""
from contextlib import contextmanager, closing
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from morelogin_common import CloudError, ids_from_text, fingerprint, phone_id
from morelogin_client import Client, plan
from morelogin_store import SharedStore, SharedPeerClaimed, TABLES
from assistant_chain import Chain, text_hash
from assistant_guided_chain import GuidedChain
from assistant_inbox import InboxChain, inbox_targets, read_round, record_checked
from assistant_settings import Settings

PIN='SHA256:'+'A'*43

def entry(cloud_id='101'):
    return dict(id=cloud_id,supportAdb=True,enableAdb=True,envStatus=4,
        adbPassword='SYNTHETIC-PASSWORD-NOT-REAL',remark='',
        command='ssh -oHostKeyAlgorithms=+ssh-rsa user_101@127.0.0.1 -p 1824 -L 9897:adb-proxy:14566 -Nf')

def pending(peer='2',account='1',chat='55'):
    return dict(attempt=1,account=account,peer=peer,chat=chat,variant=0)

class Configuration(unittest.TestCase):
    def test_ids_are_explicit_new_unique_list(self):
        self.assertEqual(ids_from_text('101\n202\n'),['101','202'])
        for value in ('','101\n101','0','1;whoami','../12','1\n'+ '\n'.join(map(str,range(2,203)))):
            with self.subTest(value=value[:40]),self.assertRaises(CloudError):ids_from_text(value)
    def test_fingerprint_format(self):
        self.assertEqual(fingerprint(PIN),PIN)
        for value in ('SHA256:x','MD5:abc','SHA256:'+'A'*44):
            with self.assertRaises(CloudError):fingerprint(value)
    def test_scope_is_separate_from_mumu(self):
        from assistant_store import data_directory,credential_directory
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'LOCALAPPDATA':temp,'DVK_MORELOGIN':'1','DVK_MORELOGIN_PHONE_ID':'101'}):
            self.assertEqual(data_directory(),Path(temp)/'DvkAssistantMoreLogin/phones/101')
            self.assertEqual(credential_directory(),Path(temp)/'DvkAssistantMoreLogin')
        with patch.dict(os.environ,{'LOCALAPPDATA':'/safe','DVK_MORELOGIN':'0'}):
            self.assertEqual(data_directory(),Path('/safe/DvkAssistant'))
    def test_credentials_dpapi_writer_no_plaintext_fallback(self):
        from morelogin_credentials import save,load
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'credentials.dpapi'
            with self.assertRaises(Exception): save('app','test-secret',path=path,encoder=lambda _: (_ for _ in ()).throw(ValueError()))
            self.assertFalse(path.exists())
            save('app','test-secret',path=path,encoder=lambda x:b'ENCRYPTED:'+x[::-1])
            self.assertNotIn(b'test-secret',path.read_bytes())
            self.assertEqual(load(path=path,decoder=lambda x:x[10:][::-1]),('app','test-secret'))

class ApiTests(unittest.TestCase):
    def client(self,values):
        calls=[]
        class Opener:
            def open(self,request,timeout):
                calls.append(request)
                return io.BytesIO(json.dumps(values.pop(0)).encode())
        return Client('APP_ID','SYNTHETIC-SECRET',opener=Opener()),calls
    def auth(self):return dict(code=0,data={'access_token':'synthetic_token_0123456789'})
    def test_oauth_maps_app_and_secret_then_queries_exact_ids(self):
        c,calls=self.client([self.auth(),dict(code=0,data=[entry()])])
        self.assertEqual(c.query(['101'])['101']['id'],'101')
        body=json.loads(calls[0].data)
        self.assertEqual(body,dict(client_id='APP_ID',client_secret='SYNTHETIC-SECRET',grant_type='client_credentials'))
        self.assertEqual(calls[1].full_url,'https://api.morelogin.com/cloudphone/batchAdbInfo')
        self.assertEqual(json.loads(calls[1].data),{'envIds':['101']})
        self.assertNotIn('SYNTHETIC-SECRET',calls[1].get_header('Authorization'))
    def test_missing_phone_is_individual_not_whole_batch_failure(self):
        c,_=self.client([self.auth(),dict(code=0,data=[entry()])])
        self.assertIsNone(c.query(['101','202'])['202'])
    def test_duplicate_or_unrequested_id_rejected(self):
        for rows in ([entry(),entry()],[entry('999')]):
            c,_=self.client([self.auth(),dict(code=0,data=rows)])
            with self.assertRaises(CloudError):c.query(['101'])
    def test_no_raw_error_or_secret_export(self):
        c,_=self.client([dict(code=35002,msg='SECRET SERVER BODY')])
        with self.assertRaisesRegex(CloudError,'^api-denied$'):c.query(['101'])
    def test_no_mutation_endpoints(self):
        c,_=self.client([])
        for endpoint in ('/cloudphone/powerOn','/cloudphone/create','/cloudphone/updateAdb','https://other.test'):
            with self.assertRaises(CloudError):c.post(endpoint,{})
    def test_auth_header_injection_blocked(self):
        c,_=self.client([dict(code=0,data={'access_token':'abc\r\nINJECT: yes'})])
        with self.assertRaises(CloudError):c.query(['101'])
    def test_proxy_and_redirect_disabled(self):
        client=Client('app','synthetic-secret')
        import urllib.request
        self.assertTrue(any(isinstance(x,__import__('morelogin_client').NoRedirect) for x in client.opener.handlers))
        self.assertFalse(any(isinstance(x,urllib.request.ProxyHandler) and x.proxies for x in client.opener.handlers))

class PlanTests(unittest.TestCase):
    def test_documented_ssh_plan_not_executed(self):
        p=plan(entry(),'101')
        self.assertEqual((p.host,p.ssh_port,p.user,p.remote_host,p.remote_port),('127.0.0.1',1824,'user_101','adb-proxy',14566))
        self.assertNotIn('SYNTHETIC',repr(p))
    def test_reject_shell_arbitrary_options_and_destinations(self):
        original=entry()['command']
        for command in (original+' ; whoami',original+' -oProxyCommand=whoami',original+' -R 20:host:22',
                        original.replace('adb-proxy','evil.test'),original.replace('9897','999999'),
                        original.replace('127.0.0.1','example.com'),original.replace('ssh ','cmd /c '),
                        original+' -p 23',original.replace('-Nf','whoami')):
            with self.subTest(command=command),self.assertRaises(CloudError):plan(dict(entry(),command=command),'101')
    def test_no_missing_or_switched_id(self):
        with self.assertRaises(CloudError):plan(entry(),'202')
        with self.assertRaises(CloudError):plan(None,'101')
    def test_offline_or_adb_disabled_not_ready(self):
        for changes in ({'envStatus':3},{'enableAdb':False},{'supportAdb':False},{'remark':'not available'},{'command':''}):
            with self.subTest(changes=changes),self.assertRaises(CloudError):plan(dict(entry(),**changes),'101')

class SshTests(unittest.TestCase):
    def test_changed_key_never_gets_password(self):
        import morelogin_ssh as ssh
        class Key:
            def asbytes(self):return b'synthetic-key'
        class Transport:
            calls=[]
            def get_remote_server_key(self):return Key()
            def auth_password(self,*args,**kwargs):self.calls.append('AUTH')
        transport=Transport()
        @contextmanager
        def fake(_):yield transport
        with patch.object(ssh,'handshake',fake),self.assertRaisesRegex(CloudError,'ssh-key-changed'):
            with ssh.tunnel(plan(entry(),'101'),PIN):pass
        self.assertEqual(transport.calls,[])
    def test_probe_observes_without_authentication(self):
        import morelogin_ssh as ssh
        class Key:
            def asbytes(self):return b'key'
        class Transport:
            def get_remote_server_key(self):return Key()
            def auth_password(self,*_):raise AssertionError('Password leaked before trust')
        @contextmanager
        def fake(_):yield Transport()
        with patch.object(ssh,'handshake',fake):
            fingerprint(ssh.probe(plan(entry(),'101')))
    def test_tunnel_listens_only_loopback_ephemeral_and_closes(self):
        import morelogin_ssh as ssh
        class Key:
            def asbytes(self):return b'key'
        class Transport:
            def __init__(self):self.closed=False;self.auth=False
            def get_remote_server_key(self):return Key()
            def auth_password(self,user,password,fallback):self.auth=(user,password,fallback)
            def is_authenticated(self):return True
            def set_keepalive(self,_):pass
            def close(self):self.closed=True
        transport=Transport()
        @contextmanager
        def fake(_):yield transport
        with patch.object(ssh,'handshake',fake):
            with ssh.tunnel(plan(entry(),'101'),ssh.key_fingerprint(Key())) as serial:
                self.assertTrue(serial.startswith('127.0.0.1:'))
                self.assertNotEqual(serial,'127.0.0.1:9897')
        self.assertTrue(transport.closed)
        self.assertFalse(transport.auth[2])

class SharedDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'shared.sqlite3'
        self.a=SharedStore(self.path,cloud_id='101')
        self.b=SharedStore(self.path,cloud_id='202')
    def test_one_file_and_namespaced_same_chat_keys(self):
        ca=GuidedChain(self.a,seal=lambda x:x,unseal=lambda x:x)
        cb=GuidedChain(self.b,seal=lambda x:x,unseal=lambda x:x)
        for store,account in ((self.a,'1'),(self.b,'3')):
            with store.connection() as db:
                db.execute('INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)',(account,'2','55','9','wait-reply','ab'*32))
                db.execute('INSERT INTO chain_actions VALUES(?,?,?,?,?)',('55','question','8','hash','awaiting-approval'))
                db.execute('INSERT INTO ai_drafts VALUES(?,?,?,?)',('55','question',b'private','reserved'))
        with self.a.connection() as db:
            db.execute("UPDATE chain_dialogs SET stage='manual-review' WHERE chat=?",('55',))
        with self.b.connection() as db:
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs').fetchone()[0],'wait-reply')
        self.assertEqual(self.a.path,self.b.path)
        self.assertEqual(list(Path(self.temp.name).glob('*.sqlite3')),[self.path])
    def test_shared_visit_visible_across_ids(self):
        self.a.record_visit('2',{'profile_verified':True,'friends_count':10,'history_status':'empty'})
        self.assertIn('2',self.b.visited_peers())
    def test_unverified_visit_not_recorded(self):
        self.a.record_visit('2',{'profile_verified':False})
        self.assertEqual(self.b.visited_peers(),[])
    def test_atomic_global_claim_prevents_parallel_duplicate_greeting(self):
        barrier=threading.Barrier(2)
        results=[]
        def reserve(store,account):
            barrier.wait()
            try:store.reserve(pending(account=account),'Привет',approved=True);results.append('reserved')
            except SharedPeerClaimed:results.append('conflict')
        threads=[threading.Thread(target=reserve,args=args) for args in ((self.a,'1'),(self.b,'3'))]
        for t in threads:t.start()
        for t in threads:t.join(10)
        self.assertEqual(sorted(results),['conflict','reserved'])
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM global_peer_claims').fetchone()[0],1)
        self.assertEqual(self.a.summary()['reserved']+self.b.summary()['reserved'],1)
    def test_claim_survives_restart_unknown_and_no_invocation(self):
        action=self.a.reserve(pending(),'Привет',approved=True)
        self.a.finish(action,dict(send_attempted=False,send_handler_returned=False))
        restarted=SharedStore(self.path,cloud_id='202')
        with self.assertRaises(SharedPeerClaimed):restarted.reserve(pending(account='3'),'Привет',approved=True)
    def test_unapproved_never_claims(self):
        with self.assertRaises(Exception):self.a.reserve(pending(),'Привет',approved=False)
        self.assertEqual(self.b.visited_peers(),[])
    def test_transaction_rollback_includes_global_claim(self):
        # Force local uniqueness failure: the global row must roll back too.
        with self.a.connection() as db:
            db.execute("INSERT INTO manual_actions(account,peer,initial_chat,text_hash,confirmed,status) VALUES('1','2','55','hash',1,'reserved-unknown')")
        with self.assertRaises(sqlite3.IntegrityError):self.a.reserve(pending(),'Привет',approved=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM global_peer_claims').fetchone()[0],0)
    def test_schema_queries_and_bound_values_not_rewritten(self):
        Chain(self.a)
        with self.a.connection() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn('manual_actions',tables)
            self.assertNotIn('global_peer_claims',tables)
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",('manual_actions',)).fetchone())
            db.execute("INSERT INTO chain_actions VALUES(?,?,?,?,?)",('55','question','chain_actions','manual_actions','awaiting-approval'))
            self.assertEqual(db.execute('SELECT trigger,text_hash FROM chain_actions').fetchone(),('chain_actions','manual_actions'))
    def test_executemany_stays_in_phone_scope(self):
        Chain(self.a);Chain(self.b)
        with self.a.connection() as db:
            db.executemany('INSERT INTO chain_seen VALUES(?,?,?)',[('55','1','hash'),('55','2','hash')])
        with self.b.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_seen').fetchone()[0],0)
    def test_city_and_search_sessions_are_independent(self):
        from assistant_profiles import Session
        a,b=Session(self.a),Session(self.b)
        a.set('city','Москва');b.set('city','Омск')
        self.assertEqual(a.get('city'),'Москва')
        self.assertEqual(b.get('city'),'Омск')
    def test_shared_store_does_not_import_mumu_journals(self):
        self.assertIsNone(self.a.check_legacy('1','2'))
    def test_complete_chain_and_inbox_targets_are_isolated(self):
        a=InboxChain(self.a,seal=lambda x:x,unseal=lambda x:x)
        b=InboxChain(self.b,seal=lambda x:x,unseal=lambda x:x)
        self.a.reserve(pending(),'Привет',approved=True)
        attention,unread=inbox_targets(a)
        self.assertEqual(unread,[dict(account='1',peer='2',chat='55')])
        self.assertEqual(inbox_targets(b),([],[]))

class SupervisorTests(unittest.TestCase):
    def test_two_phones_start_concurrently_and_one_error_does_not_stop_other(self):
        from morelogin_supervisor import run
        barrier=threading.Barrier(2)
        seen=[]
        stop=threading.Event()
        def target(spec,stopped,publish):
            barrier.wait(timeout=5)
            publish(spec['id'],'error' if spec['id']=='101' else 'finished','synthetic')
        run(Settings(),['101','202'],{'101':PIN,'202':PIN},{'101':entry(),'202':entry('202')},'inbox',stop,lambda *args:seen.append(args),target=target)
        self.assertEqual({x[0] for x in seen},{'101','202'})
        self.assertFalse(stop.is_set())
    def test_missing_phone_and_untrusted_key_do_not_spawn(self):
        from morelogin_supervisor import run
        seen=[]
        run(Settings(),['101','202'],{},{'101':entry(),'202':None},'full',threading.Event(),lambda *x:seen.append(x),target=lambda *_:self.fail('Must not spawn'))
        self.assertEqual({x[-1] for x in seen},{'ssh-key-untrusted','phone-unavailable'})
    def test_worker_secrets_never_in_command_line(self):
        from morelogin_supervisor import worker_command
        self.assertEqual(worker_command()[-1],'--cloud-worker')
        self.assertNotIn('SYNTHETIC',str(worker_command()))
    def test_target_binding_happens_in_fresh_process(self):
        code='''import sys,os
sys.path.insert(0,sys.argv[1])
from morelogin_worker import configure_target
configure_target('127.0.0.1:25432','101')
import test_device,target_only,one_chat_device,assistant_contact_photo,assistant_store
assert test_device.TARGET == target_only.TARGET == one_chat_device.TARGET == assistant_contact_photo.TARGET == '127.0.0.1:25432'
assert assistant_store.Store.__name__=='SharedStore'
print('ok')
'''
        r=subprocess.run([sys.executable,'-c',code,str(Path(__file__).resolve().parents[1])],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stderr)
    def test_late_binding_rejected_not_silently_using_mumu(self):
        from morelogin_worker import configure_target
        with self.assertRaises(CloudError):configure_target('127.0.0.1:25432','101')

if __name__=='__main__':unittest.main()

class AdditionalIsolation(unittest.TestCase):
    def test_foreign_table_and_attach_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            a=SharedStore(Path(temp)/'shared.sqlite3',cloud_id='101')
            b=SharedStore(Path(temp)/'shared.sqlite3',cloud_id='202')
            for sql in ('SELECT * FROM p202__manual_actions', 'CREATE TABLE unexpected(x)',
                        "ATTACH DATABASE ':memory:' AS other"):
                with self.subTest(sql=sql),self.assertRaises(sqlite3.DatabaseError):
                    with a.connection() as db:db.execute(sql)
    def test_cloud_telegram_label(self):
        from telegram_notify import cloud_label
        with patch.dict(os.environ,{'DVK_MORELOGIN':'1','DVK_MORELOGIN_PHONE_ID':'101'}):
            self.assertEqual(cloud_label('Контакт'),'Cloud Phone 101\nКонтакт')
        with patch.dict(os.environ,{'DVK_MORELOGIN':'0'}):
            self.assertEqual(cloud_label('Контакт'),'Контакт')
