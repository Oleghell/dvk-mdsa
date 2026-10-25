"""Explicit read-only settings check. No device, Frida, account or send needed."""
import copy,json,os,sqlite3,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import MagicMock,patch
import mumu_profile_id as probe

ROOT=Path(__file__).resolve().parents[1]
PEER='4470000001'

def raw(peer=PEER):
    return dict(navigation=dict(stage='navigation-ready',error='none',phase='done',metadata_checkpoint='ready',
        destination_verified=True,action_attempted=False,action_completed=False,cleanup_failed=False,
        handles_acquired=8,handles_released=8,private_profile_peer=peer))

def result(peer=PEER,status='not-blocked',reason='none'):
    return dict(peer=peer,block_status=status,block_reason=reason,samples=2,read_only=True)


class ReadOnly(unittest.TestCase):
    def test_source_is_current_profile_only_and_denies_mutator_invocation(self):
        s=probe.build();self.assertIn('expectedIdentity=null',s)
        self.assertNotIn('peer!==expectedIdentity.peer',s)
        self.assertIn("if(k!=='contact-profile')fail('wrong-screen')",s)
        self.assertIn("if(entry.kind===1||entry.routeChecked)fail('signature-mismatch')",s)
        start=s.index("if(k!=='contact-profile')fail('wrong-screen')");end=s.index('\n  } catch(e)',start)
        tick=s[start:end]
        for action in ('switchTab(','s.chatBack','OnSendText','OnMessageButton','set_Text','get_Text','swipe','tap'):
            self.assertNotIn(action,tick)
        self.assertIn('id64(s.peerId,user)!==peer',tick)
    def test_full_bounded_evidence_and_int64_id_required(self):
        self.assertEqual(probe.validated_peer(raw()),PEER)
        for changes in (dict(stage='navigation-stopped'),dict(error='frame-budget'),dict(destination_verified=1),
            dict(action_attempted=True),dict(action_completed=True),dict(cleanup_failed=True),
            dict(handles_released=7),dict(handles_acquired=True),dict(private_profile_peer='0'),
            dict(private_profile_peer=str(2**63)),dict(private_profile_peer=4470000001)):
            value=raw();value['navigation'].update(changes)
            with self.assertRaises(probe.ProfileIdError):probe.validated_peer(value)
    def capture(self,exe,folder,cancelled,*,inspector):
        self.assertEqual((exe,folder),('synthetic-adb','synthetic-folder'))
        return inspector(37149,'synthetic-private-token',cancelled,None)
    def test_two_independent_reads_return_only_same_id(self):
        inspect=MagicMock(return_value=PEER)
        value=probe.read_profile('synthetic-adb','synthetic-folder',lambda:False,capture_fn=self.capture,inspect_fn=inspect)
        self.assertEqual(value,PEER);self.assertEqual(inspect.call_count,2)
    def test_profile_change_and_cancel_never_return_an_id(self):
        with self.assertRaises(probe.ProfileIdError):
            probe.read_profile('synthetic-adb','synthetic-folder',lambda:False,capture_fn=self.capture,
                inspect_fn=MagicMock(side_effect=[PEER,'4470000002']))
        inspect=MagicMock()
        with self.assertRaises(probe.ProfileIdError):
            probe.read_profile('synthetic-adb','synthetic-folder',lambda:True,capture_fn=self.capture,inspect_fn=inspect)
        inspect.assert_not_called()
    def test_transport_exception_no_guess_and_no_retry_after_root(self):
        inspect=MagicMock(side_effect=TimeoutError('PRIVATE'))
        with self.assertRaises(TimeoutError):
            probe.read_profile('synthetic-adb','synthetic-folder',lambda:False,capture_fn=self.capture,inspect_fn=inspect)
        inspect.assert_called_once()
    def test_missing_and_incomplete_registry_is_unknown_and_never_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'missing.db';self.assertEqual(probe.lookup(p,PEER),('unavailable','registry-unavailable'))
            self.assertFalse(p.exists())
            with closing(sqlite3.connect(p)):pass
            before=p.read_bytes();self.assertEqual(probe.lookup(p,PEER),('unavailable','registry-unavailable'))
            self.assertEqual(before,p.read_bytes())
    def test_registry_read_only_exact_id_and_no_schema_journal_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'state.db'
            with closing(sqlite3.connect(p)) as db, db:
                db.execute('CREATE TABLE mumu_peer_blocks(peer TEXT PRIMARY KEY,reason TEXT)')
                db.execute('INSERT INTO mumu_peer_blocks VALUES(?,?)',(PEER,'contact-refused'))
                db.execute('INSERT INTO mumu_peer_blocks VALUES(?,?)',('4470000002','contact-received'))
                db.execute('INSERT INTO mumu_peer_blocks VALUES(?,?)',('4470000003','PRIVATE'))
            before=p.read_bytes()
            self.assertEqual(probe.lookup(p,PEER),('blocked','contact-refused'))
            self.assertEqual(probe.lookup(p,'4470000002'),('blocked','contact-received'))
            self.assertEqual(probe.lookup(p,'4470000003'),('unavailable','registry-unavailable'))
            self.assertEqual(probe.lookup(p,'4470000004'),('not-blocked','none'))
            self.assertEqual(before,p.read_bytes())
    def test_result_has_closed_schema_and_does_not_claim_footer_match(self):
        self.assertEqual(probe.checked_result(result()),result())
        self.assertIn('не сравнивали',probe.display(result()))
        self.assertIn('Совпадает',probe.display(result(),PEER))
        self.assertIn('НЕ совпадает',probe.display(result(),'4470000002'))
        self.assertIn('не разрешение на отправку',probe.display(result()).lower())
        for changes in (dict(text='PRIVATE'),dict(samples=True),dict(read_only=1),dict(block_status='allowed'),dict(block_reason='PRIVATE')):
            with self.assertRaises(probe.ProfileIdError):probe.checked_result(dict(result(),**changes))
    def test_run_keeps_id_only_in_return_value(self):
        from assistant_settings import Settings
        with tempfile.TemporaryDirectory() as tmp,patch('mumu_common.root_directory',return_value=Path(tmp)),patch.object(probe,'read_profile',return_value=PEER):
            out=probe.run(Settings(),lambda:False)
            self.assertEqual(out,result(status='unavailable',reason='registry-unavailable'))
            self.assertEqual(list(Path(tmp).iterdir()),[])
    def test_source_checks_never_depend_on_system_text_encoding(self):
        original=Path.read_text
        def explicit(path,*args,**kwargs):
            self.assertEqual(kwargs.get('encoding'),'utf-8')
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',explicit):
            self.test_ui_button_and_worker_branch_are_explicit_and_packaged()
    def test_registry_fixtures_and_lookups_close_every_sqlite_connection(self):
        original=sqlite3.connect;connections=[]
        def tracked(*args,**kwargs):
            db=original(*args,**kwargs);connections.append(db);return db
        with patch.object(sqlite3,'connect',side_effect=tracked):
            self.test_missing_and_incomplete_registry_is_unknown_and_never_created()
            self.test_registry_read_only_exact_id_and_no_schema_journal_changes()
        self.assertTrue(connections)
        for db in connections:
            with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')
    def test_ui_button_and_worker_branch_are_explicit_and_packaged(self):
        app=(ROOT/'assistant_app.py').read_text(encoding='utf-8');worker=(ROOT/'mumu_worker.py').read_text(encoding='utf-8')
        self.assertIn("text='Проверить ID',command=check_profile_id",app)
        self.assertIn("'profile-id',False,id_stop",app)
        self.assertIn('if busy:return',app)
        self.assertIn("id_stop.set()",app)
        branch=worker[worker.index("if spec['mode']=='profile-id':"):worker.index("stage='journal-initialization'")]
        self.assertIn('return out',branch)
        self.assertNotIn('Store()',branch.replace('# No Store()', '#'))
        self.assertNotIn('monitor(',branch)
        self.assertIn("'mumu_profile_id'",(ROOT/'mumu.spec').read_text(encoding='utf-8'))


class Worker(unittest.TestCase):
    def test_actual_worker_mode_skips_store_monitor_and_id_report(self):
        script="""import json,sys,threading
from pathlib import Path
import mumu_worker
base=Path(sys.argv[1]);original=mumu_worker.configure
peer='4470000001'
def configure(n):
 result=original(n)
 import test_device,target_only,assistant_store,mumu_profile_id
 test_device.bundle_token=lambda folder:'synthetic-token'
 target_only.preflight=lambda adb:'11111111-1111-1111-1111-111111111111'
 target_only.recheck=lambda adb,boot:None
 def forbidden(*a,**k):raise AssertionError('No database initialization')
 assistant_store.Store.__init__=forbidden
 mumu_profile_id.run=lambda *a:dict(peer=peer,block_status='unavailable',block_reason='registry-unavailable',samples=2,read_only=True)
 return result
mumu_worker.configure=configure
out=mumu_worker.run(dict(port=5557,settings=dict(adb=str(base/'adb'),folder=str(base/'apks')),mode='profile-id',fresh=False),threading.Event())
assert out['peer']==peer
assert not list(base.rglob('*.sqlite3'))
for path in base.rglob('*.json'):assert peer not in path.read_text(encoding='utf-8')
print('read-only-ok')
"""
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'adb').touch();(p/'apks').mkdir()
            env=dict(os.environ,LOCALAPPDATA=tmp,PYTHONPATH=str(ROOT));env.pop('DVK_MORELOGIN',None)
            run=subprocess.run([sys.executable,'-c',script,tmp],capture_output=True,text=True,env=env,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(run.stdout.strip(),'read-only-ok')
