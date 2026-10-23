"""No real Frida/ADB/phone. Exercise actual inspector and worker-scoped leases."""
import os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from contextlib import nullcontext,contextmanager
import morelogin_session as pooled
from morelogin_fast_adb import Timings
from morelogin_common import CloudError
from target_only import TargetOnlyAdb
from test_device import TARGET,TestError

class Guard(nullcontext):
 def cancel(self):pass

class Connections(unittest.TestCase):
 def setUp(self):
  p=patch.dict(os.environ,{'DVK_MORELOGIN':'1'});p.start();self.addCleanup(p.stop)
  d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);self.path=Path(d.name);(self.path/'adb.exe').write_text('synthetic')
  self.adb=lambda:TargetOnlyAdb(str(self.path/'adb.exe'),self.path)
  self.original=MagicMock(return_value='32123');p=patch.object(TargetOnlyAdb,'run',self.original);p.start();self.addCleanup(p.stop)
  self.exports=SimpleNamespace(runtime=lambda:dict(frida_version='17.24.1',arch='arm64',platform='linux'),root=MagicMock(return_value={'synthetic':True}),cancel=MagicMock())
  self.script=MagicMock();self.script.exports_sync=self.exports
  self.session=MagicMock();self.session.create_script.return_value=self.script
  self.device=MagicMock();self.device.is_lost=False;self.device.enumerate_processes.return_value=[SimpleNamespace(pid=42,name='Gadget')];self.device.attach.return_value=self.session
  self.manager=MagicMock();self.manager.add_remote_device.return_value=self.device
  self.api=SimpleNamespace(__version__='17.24.1',get_device_manager=MagicMock(return_value=self.manager),Cancellable=MagicMock(side_effect=Guard))
  self.timings=Timings()
 def open(self,adb):
  value=adb.run(['-s',TARGET,'forward','tcp:0','tcp:27042']);adb.forward_port=int(value);return value
 def release(self,adb):return adb.run(['-s',TARGET,'forward','--remove','tcp:'+str(adb.forward_port)])
 @contextmanager
 def context(self):
  with pooled.transport(TARGET,lambda:False,self.timings,frida_api=self.api) as lease:
   self.api.get_device_manager();yield lease
 def test_two_real_inspectors_one_connection_forward_but_fresh_sessions(self):
  from search_online import inspect
  get_manager=self.api.get_device_manager
  with self.context():
   for _ in range(2):
    adb=self.adb();port=self.open(adb)
    self.assertEqual(inspect(int(port),'synthetic-token',lambda:False,frida_api=self.api,source_function='fixed-synthetic',validator=lambda v:v),{'synthetic':True})
    self.release(adb)
   self.manager.add_remote_device.assert_called_once_with('127.0.0.1:32123',token='synthetic-token')
   self.manager.remove_remote_device.assert_not_called()
   self.assertEqual(self.original.call_count,1)
  self.assertIs(self.api.get_device_manager,get_manager)
  self.assertEqual(self.original.call_count,2);self.manager.remove_remote_device.assert_called_once_with('127.0.0.1:32123')
  self.assertEqual(self.device.enumerate_processes.call_count,2);self.assertEqual(self.device.attach.call_count,2)
  self.assertEqual(self.script.unload.call_count,2);self.assertEqual(self.session.detach.call_count,2)
  self.assertEqual(self.timings.snapshot()['gadget_rpc']['calls'],4)
 def test_wrong_address_token_target_and_overlapping_lease_rejected(self):
  with self.context() as lease:
   a=self.adb();self.open(a)
   with self.assertRaises(TestError):self.open(self.adb())
   with self.assertRaises(TestError):lease.add_remote_device('127.0.0.1:32124',token='test')
   lease.add_remote_device(lease.address,token='test')
   with self.assertRaises(TestError):lease.add_remote_device(lease.address,token='test')
   with self.assertRaises(TestError):self.release(a)
   lease.remove_remote_device(lease.address);self.release(a);self.open(a)
   with self.assertRaises(TestError):lease.add_remote_device(lease.address,token='changed')
   self.release(a)
   with self.assertRaises(TestError):a.run(['-s','127.0.0.1:22222','forward','tcp:0','tcp:27042'])
  self.manager.add_remote_device.assert_called_once()
 def test_lost_device_never_reconnects_or_replays(self):
  with self.context() as lease:
   a=self.adb();self.open(a);lease.add_remote_device(lease.address,token='test');lease.remove_remote_device(lease.address);self.release(a)
   self.device.is_lost=True;self.open(a)
   with self.assertRaises(TestError):lease.add_remote_device(lease.address,token='test')
   self.release(a)
  self.manager.add_remote_device.assert_called_once();self.device.attach.assert_not_called()
 def test_actual_inspector_still_rejects_ambiguous_process(self):
  from search_online import inspect
  self.device.enumerate_processes.return_value=[SimpleNamespace(pid=1,name='Gadget'),SimpleNamespace(pid=2,name='Gadget')]
  with self.context():
   a=self.adb();port=self.open(a)
   with self.assertRaises(Exception):inspect(int(port),'test',lambda:False,frida_api=self.api,source_function='synthetic',validator=lambda v:v)
   self.release(a)
  self.device.attach.assert_not_called();self.exports.root.assert_not_called()
 def test_cleanup_failure_blocks_next_operation_not_silently_reused(self):
  with self.context() as lease:
   a=self.adb();self.open(a);d=lease.add_remote_device(lease.address,token='test');session=d.attach(42)
   self.session.detach.side_effect=RuntimeError('PRIVATE')
   with self.assertRaises(RuntimeError):session.detach()
   lease.remove_remote_device(lease.address);self.release(a)
   with self.assertRaises(TestError):self.open(a)
  self.assertEqual(self.device.attach.call_count,1)
 def test_cancelled_no_open_and_restore_on_exception(self):
  method=TargetOnlyAdb.run;get_manager=self.api.get_device_manager
  with self.assertRaises(TestError):
   with pooled.transport(TARGET,lambda:True,self.timings,frida_api=self.api):self.open(self.adb())
  self.assertIs(TargetOnlyAdb.run,method);self.assertIs(self.api.get_device_manager,get_manager);self.original.assert_not_called()
 def test_mumu_nested_and_wrong_target_not_allowed(self):
  with patch.dict(os.environ,{'DVK_MORELOGIN':'0'}),self.assertRaises(CloudError):
   with self.context():pass
  with self.assertRaises(CloudError):
   with pooled.transport('127.0.0.1:22222',lambda:False,self.timings,frida_api=self.api):pass
  with self.context(),self.assertRaises(CloudError):
   with self.context():pass
 def test_no_arbitrary_command_or_unbound_gadget(self):
  with self.context() as lease:
   with self.assertRaises(TestError):lease.add_remote_device('127.0.0.1:32123',token='test')
   with self.assertRaises(TestError):self.adb().run(['shell','reboot'])
  self.original.assert_not_called();self.manager.add_remote_device.assert_not_called()
 def test_metrics_have_no_address_token_text_source(self):
  with self.context() as lease:
   a=self.adb();self.open(a);lease.add_remote_device(lease.address,token='PRIVATE');lease.remove_remote_device(lease.address);self.release(a)
  report=str(self.timings.snapshot())
  for private in ('PRIVATE','32123',TARGET):self.assertNotIn(private,report)
