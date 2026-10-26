"""Uploaded 170-175: transport setup and profile history; no production data."""
import json,itertools,threading,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import cloud_database as cloud
import one_chat_device as device
import assistant_pass as native
from startup_failure import record
from assistant_error_notify import diagnostic_json
import test_cloud_database as database_harness
import test_one_chat as read_harness
from test_one_chat import WHO
from test_target_only import BOOT,OTHER_BOOT
from test_device import TestError

PRIVATE='PRIVATE TOKEN SQL HOST PASSWORD'

class Pool(unittest.TestCase):
    def setUp(self):
        self.cfg=database_harness.CloudDriverSettings().config()
        self.local=SimpleNamespace(idle=[])
        self.patchers=[patch.object(cloud,'_local',self.local),patch.object(cloud,'enabled',return_value=True),patch.object(cloud,'load',return_value=self.cfg),patch.object(cloud.time,'monotonic',return_value=100)]
        for p in self.patchers:p.start();self.addCleanup(p.stop)
    def fresh(self):
        r=MagicMock();r.closed=False
        r.execute.return_value.fetchone.return_value=(cloud.PROTOCOL,self.cfg['dataset'],True)
        r.execute.return_value.fetchall.return_value=[]
        return r
    def test_dead_idle_socket_replaced_before_begin_not_write_replayed(self):
        stale=self.fresh();stale.execute.side_effect=OSError(PRIVATE);fresh=self.fresh()
        self.local.idle=[(self.cfg,stale,{},0)]
        with patch.object(cloud,'raw_connect',return_value=fresh) as connect:
            db=cloud.connect('local');self.assertIs(db.raw,fresh)
        connect.assert_called_once();stale.close.assert_called_once()
        self.assertTrue(all(not str(c.args[0]).startswith(('BEGIN','INSERT','UPDATE','COMMIT')) for c in stale.execute.call_args_list))
        db.close()
    def test_recent_idle_session_has_no_additional_roundtrip(self):
        raw=self.fresh();self.local.idle=[(self.cfg,raw,{},99)]
        db=cloud.connect('local');raw.execute.assert_not_called();db.close()
    def test_idle_dataset_change_is_hard_failure_not_silent_reconnect(self):
        raw=self.fresh();raw.execute.return_value.fetchone.return_value=(cloud.PROTOCOL,'other',True)
        self.local.idle=[(self.cfg,raw,{},0)]
        with patch.object(cloud,'raw_connect') as fresh,self.assertRaisesRegex(cloud.CloudDatabaseError,'cloud-dataset-not-ready'):cloud.connect('local')
        fresh.assert_not_called();raw.close.assert_called_once()
    def test_unknown_commit_never_replayed_or_reused(self):
        raw=database_harness.FakeRaw();db=cloud.Connection(raw,self.cfg,{});db.execute('BEGIN')
        raw.execute=MagicMock(side_effect=OSError(PRIVATE))
        with self.assertRaises(cloud.CloudDatabaseError):db.execute('COMMIT')
        db.close();self.assertTrue(raw.closed);self.assertEqual(self.local.idle,[])
        self.assertEqual(sum(c.args[0]=='COMMIT' for c in raw.execute.call_args_list),1)

class ProfileHistory(unittest.TestCase):
    def test_sqlite_history_uses_read_transaction_no_ddl_or_write_lock(self):
        from mumu_store import SharedStore
        with tempfile.TemporaryDirectory() as folder:
            s=SharedStore(Path(folder)/'db',device_port=5567)
            from mumu_store import connect as real_connect
            sql=[]
            def traced(*a,**kw):
                db=real_connect(*a,**kw);db.set_trace_callback(sql.append);return db
            with patch('mumu_store.connect',side_effect=traced):self.assertEqual(s.visited_peers(),[])
            self.assertIn('BEGIN',sql);self.assertFalse(any('IMMEDIATE' in q or 'CREATE' in q for q in sql))
    def test_history_failure_is_before_any_native_execution_and_keeps_cloud_code(self):
        error=cloud.CloudDatabaseError('cloud-database-lock-timeout');error.operation='lock'
        s=MagicMock();s.visited_peers.side_effect=error;f=MagicMock();f.__version__='17.24.1'
        with self.assertRaises(cloud.CloudDatabaseError):native.inspect(37149,PRIVATE,lambda:False,'Hi',s,MagicMock(),frida_api=f)
        self.assertTrue(error._dvk_profile_not_executed);f.get_device_manager.assert_not_called();s.reserve.assert_not_called()
        value=error._dvk_preparation;self.assertEqual(value['stage'],'profile-history')
        report=dict(last_preparation_failure=value)
        exported=json.loads(diagnostic_json(report))['diagnostic']['last_preparation_failure']
        self.assertEqual(exported['database']['code'],'cloud-database-lock-timeout');self.assertNotIn(PRIVATE,json.dumps(exported))

class ReaderStages(unittest.TestCase):
    def test_actual_readonly_inspector_marks_transport_only_not_validation_or_identity(self):
        f=read_harness.Inspector().fake();err=type('TransportError',(Exception,),{})(PRIVATE)
        f.create_script=MagicMock(side_effect=err)
        with self.assertRaises(Exception):device.inspect(37149,PRIVATE,lambda:False,WHO,frida_api=f)
        self.assertTrue(device.verified_readonly_transport(err));self.assertEqual(err._dvk_failure['stage'],'script-create')
        self.assertTrue(f.detached and f.removed)
    def test_read_root_failure_is_readonly_but_never_send_permission(self):
        f=read_harness.Inspector().fake();err=type('TransportError',(Exception,),{})(PRIVATE);original=f.create_script
        def create(*a,**kw):
            value=original(*a,**kw);f.exports_sync.root=MagicMock(side_effect=err);return value
        f.create_script=create
        with self.assertRaises(Exception):device.inspect(37149,PRIVATE,lambda:False,WHO,frida_api=f)
        self.assertTrue(device.verified_readonly_transport(err));self.assertFalse(getattr(err,'_dvk_profile_not_executed',False))
        self.assertEqual(err._dvk_failure['stage'],'script-run');self.assertNotIn(PRIVATE,json.dumps(err._dvk_failure))

class ReaderReconnect(read_harness.ReadTransport):
    def capture_actual(self,fake):
        import sys
        with self.patched(),patch.object(device,'TargetOnlyAdb',return_value=self.adb),patch.object(device,'bundle_token',return_value=PRIVATE),patch.dict(sys.modules,frida=fake):
            return device.capture('adb',self.folder,expected=WHO)
    def flaky(self,count):
        f=read_harness.Inspector().fake();original=f.create_script;calls=[]
        def create(*a,**kw):
            calls.append(1)
            if len(calls)<=count:raise type('TransportError',(Exception,),{})(PRIVATE)
            return original(*a,**kw)
        f.create_script=create;return f,calls
    def test_two_read_failures_reopen_channel_and_preserve_bound_identity(self):
        self.identities=itertools.repeat(BOOT);f,calls=self.flaky(2)
        self.assertEqual(self.capture_actual(f)['identity'],WHO);self.assertEqual(len(calls),3)
        self.assertEqual(sum('tcp:0' in c for c in self.calls),3)
        self.assertEqual(sum('--remove' in c for c in self.calls),3)
    def test_read_transport_retries_bounded_at_two(self):
        self.identities=itertools.repeat(BOOT);f,calls=self.flaky(9)
        with self.assertRaises(Exception):self.capture_actual(f)
        self.assertEqual(len(calls),3)
    def test_changed_boot_no_second_read(self):
        self.identities=iter([BOOT,BOOT,OTHER_BOOT]);f,calls=self.flaky(2)
        with self.assertRaises(TestError):self.capture_actual(f)
        self.assertEqual(len(calls),1)
    def test_custom_mutating_inspector_cannot_borrow_readonly_proof(self):
        err=type('TransportError',(Exception,),{})(PRIVATE);record(err,'script-run');err._dvk_readonly_transport=True
        reader=MagicMock(side_effect=err)
        with self.assertRaises(Exception):self.run_capture(reader)
        reader.assert_called_once()

# Reusing transport fixture helpers must not run their entire inherited suite twice.
for name in dir(read_harness.ReadTransport):
    if name.startswith('test_') and name not in ReaderReconnect.__dict__:setattr(ReaderReconnect,name,None)


class ReadNotice(unittest.TestCase):
    def test_read_reason_uses_closed_fields_not_private_payload(self):
        from assistant_exit_notify import read_failure_explanation
        text=read_failure_explanation(dict(last_read_failure=dict(error='wrong-screen',read_checkpoint='last-message',body=PRIVATE)))
        self.assertIn('wrong-screen',text);self.assertNotIn(PRIVATE,text)
    def test_transport_notice_keeps_stage_and_type_without_exception_body(self):
        from assistant_exit_notify import read_failure_explanation
        text=read_failure_explanation(dict(last_navigation_failure=dict(stage='script-create',error_type='TransportError',body=PRIVATE)))
        self.assertIn('script-create',text);self.assertIn('TransportError',text);self.assertNotIn(PRIVATE,text)
