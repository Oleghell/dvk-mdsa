"""MuMu multi-device contracts. Synthetic IDs only; no keys, Android or network."""
from contextlib import closing
from dataclasses import replace
import copy
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
from unittest.mock import MagicMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mumu_common as common
from mumu_store import SharedStore,SharedPeerClaimed
from assistant_store import Store,StateError
import assistant_pass as manual
from mumu_bundle import VerifiedBundle
from assistant_settings import Settings
from test_assistant import pending
from test_chat_batch import cycle

ROOT=Path(__file__).resolve().parents[1]

class Configuration(unittest.TestCase):
    def test_ports_and_future_devices(self):
        self.assertEqual(common.parse('5557\n5559\n5561\n5563\n5565\n16790'),[5557,5559,5561,5563,5565,16790])
        self.assertEqual(common.parse('127.0.0.1:5557\n5563'),[5557,5563])
        for value in ('','5557\n5557','remote:5557','0.0.0.0:5557','5037','27042','65536','05557','True','5557,5559'):
            with self.assertRaises(common.MumuError,msg=value):common.parse(value)
        for value in (True,1.5,None,[],{}):
            with self.assertRaises(common.MumuError):common.port(value)

    def test_save_no_secrets_and_legacy_report_path(self):
        with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,LOCALAPPDATA=t):
            self.assertEqual(common.load_ports(),list(common.DEFAULT_PORTS))
            common.save_ports([5557,5563,16790]);self.assertEqual(common.load_ports(),[5557,5563,16790])
            self.assertEqual(common.device_directory(5563),Path(t)/'DvkAssistant')
            self.assertEqual(common.device_directory(5557),Path(t)/'DvkAssistant/devices/5557')
            f=common.root_directory()/'mumu-devices.json'
            self.assertEqual(set(json.loads(f.read_text(encoding='utf-8'))),{'schema','ports'})
            f.write_text('{bad')
            with self.assertRaises(common.MumuError):common.load_ports()

class SharedDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'assistant.sqlite3';self.legacy=Path(self.tmp.name)/'old'
    def store(self,n):return SharedStore(self.path,self.legacy,device_port=n)

    def test_old_journal_preserved_and_new_greetings_globally_claimed(self):
        old=Store(self.path,self.legacy)
        action=old.reserve(pending(), 'Hi',approved=True)
        old.finish(action,dict(send_attempted=False,send_handler_returned=False))
        a,b=self.store(5557),self.store(5563)
        self.assertEqual(a.visited_peers(),['200'])
        self.assertEqual(b.visited_peers(),['200'])
        with self.assertRaises(SharedPeerClaimed):a.reserve(pending(account='101'), 'Hi',approved=True)
        self.assertFalse(a.peer_terminal(pending(account='101')))
        self.assertEqual(b.summary()['statuses'],{'not-invoked':1})
        self.assertEqual(old.summary(),b.summary())
        self.assertNotIn(b'Hi',self.path.read_bytes())

    def test_same_port_atomic_race_exactly_one_winner(self):
        a,b=self.store(5557),self.store(5557)
        barrier=threading.Barrier(2);results=[];lock=threading.Lock()
        def race(store,account):
            barrier.wait()
            try:store.reserve(pending(account=account), 'Hi',approved=True);v='won'
            except SharedPeerClaimed:v='claimed'
            with lock:results.append(v)
        threads=[threading.Thread(target=race,args=(a,'100')),threading.Thread(target=race,args=(b,'101'))]
        for t in threads:t.start()
        for t in threads:t.join(10);self.assertFalse(t.is_alive())
        self.assertEqual(sorted(results),['claimed','won'])
        self.assertEqual(a.summary()['reserved'],1)
        self.assertEqual(b.summary()['reserved'],1)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM mumu_peer_claims').fetchone()[0],0)

    def test_same_port_process_race_not_just_threads(self):
        a=self.store(5557)
        script="""import sys,time
from pathlib import Path
from mumu_store import SharedStore,SharedPeerClaimed
s=SharedStore(sys.argv[1],sys.argv[2],device_port=int(sys.argv[3]))
Path(sys.argv[4]).touch()
while not Path(sys.argv[5]).exists():time.sleep(.01)
p=dict(attempt=1,account=sys.argv[6],peer='222',chat='-1',variant=0)
try:s.reserve(p,'Synthetic greeting',approved=True);print('won')
except SharedPeerClaimed:print('claimed')
"""
        env=dict(os.environ,PYTHONPATH=str(ROOT));children=[];go=Path(self.tmp.name)/'go'
        try:
            for n in (5557,5559):
                ready=Path(self.tmp.name)/str(n)
                child=subprocess.Popen([sys.executable,'-c',script,str(self.path),str(self.legacy),'5557',str(ready),str(go),str(n+100)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                children.append((child,ready))
            import time
            until=time.monotonic()+15
            while not all(ready.exists() for _,ready in children):
                self.assertLess(time.monotonic(),until);time.sleep(.02)
            go.touch();outputs=[]
            for child,_ in children:
                out,err=child.communicate(timeout=15);self.assertEqual(child.returncode,0,err);outputs.append(out.strip())
            self.assertEqual(sorted(outputs),['claimed','won'])
        finally:
            for child,_ in children:
                if child.poll() is None:child.kill()
                child.communicate()

    def test_unknown_initial_greeting_never_released_on_any_port(self):
        a=self.store(5557);action=a.reserve(pending(),'Hello',approved=True)
        from assistant_profiles import clear_history
        clear_history(a)
        self.assertTrue(self.store(5557).peer_claimed(pending(account='777')))
        self.assertTrue(self.store(5559).peer_claimed(pending(account='777')))
        with self.assertRaises(SharedPeerClaimed):self.store(5557).reserve(pending(account='777'),'Hi',approved=True)
        a.finish(action,dict(send_attempted=True,send_handler_returned=False))
        self.assertTrue(self.store(5557).peer_claimed(pending(account='777')))
        self.assertTrue(self.store(5559).peer_claimed(pending(account='777')))

    def test_unapproved_and_invalid_do_not_claim(self):
        a=self.store(5557)
        for approval in (False,None,1,'yes'):
            with self.assertRaises(StateError):a.reserve(pending(),'Hi',approved=approval)
        self.assertFalse(a.peer_claimed(pending()))
        with self.assertRaises(Exception):a.reserve(pending(peer='x'), 'Hi',approved=True)
        self.assertFalse(a.peer_claimed(pending()))

    def test_same_chat_ids_and_city_sessions_are_device_isolated(self):
        from assistant_chain import Chain
        from assistant_profiles import Session
        a,b,old=self.store(5557),self.store(5559),self.store(5563)
        for s,c in ((a,'A'),(b,'B'),(old,'Old')):Session(s).set('city',c)
        self.assertEqual([Session(s).get('city') for s in (a,b,old)],['A','B','Old'])
        for s in (a,b,old):
            Chain(s)
            with s.connection() as db:
                db.execute('INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)',('100','200','300','400','wait-reply','a'*64))
        self.assertEqual(old.prefix,'')
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_dialogs').fetchone()[0],1)

    def test_bound_text_not_rewritten_by_namespace_adapter(self):
        a=self.store(5557)
        from assistant_profiles import Session
        Session(a).set('city','manual_actions search_session')
        self.assertEqual(Session(a).get('city'),'manual_actions search_session')

class SharedSkip(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,DVK_MUMU_MULTI='1');self.env.start();self.addCleanup(self.env.stop)
    def done(self):
        done=MagicMock();done.wait.return_value=False;done.is_set.return_value=False;return done
    def test_precheck_does_not_type_reserve_or_authorize(self):
        script,store,approve=MagicMock(),MagicMock(),MagicMock()
        store.mumu_shared_claims=True;store.peer_claimed.return_value=True
        script.exports_sync.cohortpending.return_value=pending();script.exports_sync.cohortack.return_value=True
        state={};manual.monitor(script,store,'Hi',approve,self.done(),lambda:False,state,preclaimed=frozenset({'200'}))
        store.peer_claimed.assert_not_called()
        approve.assert_not_called();store.reserve.assert_not_called()
        script.exports_sync.cohortack.assert_called_once_with(dict(pending(),skip=True))
        self.assertEqual(state,dict(shared_peer_skipped=True))
    def test_losing_race_uses_skip_not_second_send(self):
        script,store=MagicMock(),MagicMock();store.mumu_shared_claims=True;store.peer_claimed.return_value=False
        store.reserve.side_effect=SharedPeerClaimed('claimed')
        script.exports_sync.cohortpending.return_value=pending();script.exports_sync.cohortack.return_value=True
        state={};manual.monitor(script,store,'Hi',lambda *a:True,self.done(),lambda:False,state)
        script.exports_sync.cohortack.assert_called_once_with(dict(pending(),skip=True));self.assertNotIn('action_id',state)
    def test_failed_skip_never_becomes_send_ack(self):
        script,store=MagicMock(),MagicMock();store.mumu_shared_claims=True;store.peer_claimed.return_value=True
        script.exports_sync.cohortpending.return_value=pending();script.exports_sync.cohortack.return_value=False
        state={};manual.monitor(script,store,'Hi',lambda *a:True,self.done(),lambda:False,state,preclaimed=frozenset({'200'}))
        self.assertIn('error',state);store.reserve.assert_not_called();script.exports_sync.cancel.assert_called_once()
    def test_source_has_verified_back_without_faking_send(self):
        source=manual.build('Hi')
        self.assertIn('cohortRejected===reservationKey',source)
        self.assertIn("n.shared_peer_skipped=true;n.phase='close-chat'",source)
        self.assertIn('JSON.stringify(reservation)!==JSON.stringify(cohortPending)',source)
        self.assertNotIn("n.history_status='not-empty'",source)
    def skipped(self):
        value=cycle();n=value['navigation'];n.update(cycle_timeout_ms=90000,shared_peer_skipped=True,profile_read_budget_retries=0,profile_ready_waits=0,greeting_frame_splits=1,submit_frame_retries=0,
            send_attempted=False,send_handler_returned=False,messages_sent=0,greeting_variant=None)
        return value
    def test_skip_validation_requires_host_and_native_evidence(self):
        value=self.skipped();manual.validate(value,shared_peer_skipped=True)
        with self.assertRaises(ValueError):manual.validate(value)
        for k,v in [('return_verified',False),('history_fully_loaded',False),('send_attempted',True),('samples',1),('shared_peer_skipped',False)]:
            changed=copy.deepcopy(value);changed['navigation'][k]=v
            with self.assertRaises(ValueError,msg=k):manual.validate(changed,shared_peer_skipped=True)
        with patch.dict(os.environ,DVK_MUMU_MULTI='0'):
            with self.assertRaises(ValueError):manual.validate(value,shared_peer_skipped=True)

class BundleCache(unittest.TestCase):
    def test_only_verified_unchanged_files_cached(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)
            for name in ('base.apk','split-001.apk'):(folder/name).write_bytes(b'fixture')
            check=MagicMock(return_value='token');cache=VerifiedBundle(check)
            self.assertEqual(cache(folder),'token');self.assertEqual(cache(folder),'token');self.assertEqual(check.call_count,1)
            (folder/'base.apk').write_bytes(b'changed fixture')
            cache(folder);self.assertEqual(check.call_count,2)
            (folder/'base.apk').unlink()
            with self.assertRaises(OSError):cache(folder)
    def test_failed_or_racing_integrity_never_cached(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)
            for name in ('base.apk','split-001.apk'):(folder/name).write_bytes(b'fixture')
            check=MagicMock(side_effect=ValueError('bad hash'));cache=VerifiedBundle(check)
            for _ in range(2):
                with self.assertRaises(ValueError):cache(folder)
            self.assertEqual(check.call_count,2)
            def racing(f):(f/'base.apk').write_bytes(b'replaced');return 'not-safe'
            cache=VerifiedBundle(racing)
            with self.assertRaises(OSError):cache(folder)
            self.assertEqual(cache.cache,{})

class ParallelController(unittest.TestCase):
    def test_fail_one_others_continue_parallel(self):
        from mumu_controller import run_many
        barrier=threading.Barrier(3);seen=[]
        def worker(n,*args):
            barrier.wait(timeout=3);seen.append(n)
            if n==5559:raise RuntimeError('PRIVATE')
            return 'ok'
        progress=MagicMock();out=run_many([5557,5559,5563],Settings(),'inbox',False,threading.Event(),progress,worker=worker,spacing=0)
        self.assertEqual(set(seen),{5557,5559,5563});self.assertEqual(out[5557],'ok');self.assertEqual(out[5563],'ok')
        self.assertNotIn('PRIVATE',json.dumps(out));self.assertNotIn('PRIVATE',str(progress.call_args_list))
    def test_stop_before_start_never_launches_workers(self):
        from mumu_controller import run_many
        stop=threading.Event();stop.set();worker=MagicMock()
        run_many([5557,5559],Settings(),'full',True,stop,MagicMock(),worker=worker);worker.assert_not_called()

class WorkerIsolation(unittest.TestCase):
    def test_configures_target_before_all_engine_imports(self):
        script="""import sys,os,json
from mumu_worker import configure
configure(5557)
from test_device import TARGET
from target_only import TargetOnlyAdb
from assistant_store import Store,data_directory,credential_directory
from assistant_monitor import run
from assistant_contact_photo import TARGET as photo
from one_chat_device import TARGET as read
from assistant_settings import Settings
from assistant_statistics import database_path
assert TARGET==photo==read=='127.0.0.1:5557'
assert Store.__module__=='mumu_store'
assert str(data_directory()).endswith('devices'+os.sep+'5557')
assert database_path()==credential_directory()/'assistant.sqlite3'
try:configure(5559)
except Exception:pass
else:raise AssertionError('rebind allowed')
print('isolated')
"""
        with tempfile.TemporaryDirectory() as t:
            env=dict(os.environ,LOCALAPPDATA=t,PYTHONPATH=str(ROOT));env.pop('DVK_MORELOGIN',None)
            r=subprocess.run([sys.executable,'-c',script],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),'isolated')
    def test_run_uses_saved_pacing_and_120s_without_touching_saved_settings(self):
        # Static assertions supplement full engine authorization/monitor unit tests.
        text=(ROOT/'mumu_worker.py').read_text(encoding='utf-8')
        self.assertIn('profile_interval=120,reply_interval=5',text)
        self.assertIn('RunAuthorization(stopped,immediate_greeting=True,progress=progress,words_per_minute=current.typing_words_per_minute,typing_delay_enabled=current.typing_delay_enabled,fast_runtime=True)',text);self.assertIn('continuous=True',text)
        self.assertIn('preflight(adb)',text);self.assertIn('recheck(adb,boot)',text)
        self.assertNotIn('time.sleep',text)
        spec=(ROOT/'mumu.spec').read_text(encoding='utf-8');self.assertIn('console=True',spec);self.assertIn('console=False',spec)
        self.assertEqual(spec.count('Analysis('),1)

class WorkerStartupIntegration(unittest.TestCase):
    def test_actual_run_reaches_monitor_and_rejects_alias_device(self):
        # Exercise the REAL worker.run scopes, database, target binding and locks.
        # Only APK validation and physical ADB responses are synthetic.
        script="""import json,sys,threading,time
from pathlib import Path
from dataclasses import asdict
import mumu_worker
base=Path(sys.argv[1]);n=int(sys.argv[2]);ready=base/(str(n)+'.ready');go=base/'finish'
original=mumu_worker.configure
def configure(value):
 result=original(value)
 import test_device,target_only
 test_device.bundle_token=lambda folder:'synthetic-token'
 target_only.preflight=lambda adb:'11111111-1111-1111-1111-111111111111'
 target_only.recheck=lambda adb,boot:None
 return result
mumu_worker.configure=configure
def runner(settings,stopped,approve,progress,**kwargs):
 assert settings.profile_interval==120 and settings.reply_interval==5
 assert approve.words_per_minute == settings.typing_words_per_minute == 70
 assert approve.automatic_send is True
 assert approve.immediate_greeting is True and kwargs['continuous'] is True
 ready.touch()
 while not go.exists():time.sleep(.01)
 from assistant_monitor import report
 out=report('inbox');out.update(status='cancelled',reason='cancelled')
 return out
try:
 out=mumu_worker.run(dict(port=n,settings=dict(adb=str(base/'adb'),folder=str(base/'apks'),typing_words_per_minute=70),mode='inbox',fresh=False),threading.Event(),runner=runner)
 assert out['device_port']==n and out['shared_database'] is True
 print('ok')
except mumu_worker.MumuError:print('blocked');sys.exit(3)
"""
        import time
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);(base/'adb').touch();(base/'apks').mkdir()
            env=dict(os.environ,LOCALAPPDATA=t,PYTHONPATH=str(ROOT));env.pop('DVK_MORELOGIN',None)
            first=subprocess.Popen([sys.executable,'-c',script,t,'5557'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                until=time.monotonic()+15
                while not (base/'5557.ready').exists():
                    if first.poll() is not None:
                        out,err=first.communicate();self.fail(out+err)
                    self.assertLess(time.monotonic(),until);time.sleep(.02)
                second=subprocess.run([sys.executable,'-c',script,t,'5559'],env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(second.returncode,3,second.stderr);self.assertEqual(second.stdout.strip(),'blocked')
                self.assertFalse((base/'5559.ready').exists())
                report=json.loads((base/'DvkAssistant/devices/5559/last-startup.json').read_text(encoding='utf-8'))
                self.assertEqual(report['stage'],'device-identity-lock')
                self.assertFalse(report['automatic_retry'])
                (base/'finish').touch();out,err=first.communicate(timeout=15)
                self.assertEqual(first.returncode,0,err);self.assertEqual(out.strip(),'ok')
                report=json.loads((base/'DvkAssistant/devices/5557/last-monitor.json').read_text(encoding='utf-8'))
                self.assertEqual(report['tool_version'],common.VERSION);self.assertEqual(report['device_scope'],'127.0.0.1:5557')
            finally:
                if first.poll() is None:first.kill()
                first.communicate()

    def test_bad_settings_get_current_stage_not_generic_device_error(self):
        with tempfile.TemporaryDirectory() as t:
            env=dict(os.environ,LOCALAPPDATA=t,PYTHONPATH=str(ROOT));env.pop('DVK_MORELOGIN',None)
            raw=json.dumps(dict(port=5557,settings=dict(adb=' PRIVATE ',folder='x'),mode='inbox',fresh=False))+'\n'
            result=subprocess.run([sys.executable,str(ROOT/'mumu_worker.py'),'--mumu-worker'],input=raw,env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertNotIn('PRIVATE',result.stdout)
            report=json.loads((Path(t)/'DvkAssistant/devices/5557/last-startup.json').read_text(encoding='utf-8'))
            self.assertEqual(report['stage'],'settings-check');self.assertEqual(report['error_type'],'StateError')
            self.assertNotIn('PRIVATE',json.dumps(report))
