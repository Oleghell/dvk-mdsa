"""Synthetic wire protocol, cancellation and unchanged target/CLI boundaries."""
import os,socket,struct,unittest
from unittest.mock import patch,MagicMock
from pathlib import Path
import tempfile
import mumu_fast_adb as fast
from test_device import TARGET,PACKAGE,BOOT_ID,TestError
from target_only import TargetOnlyAdb
from mumu_common import MumuError as CloudError

BOOT='12345678-1234-1234-1234-123456789abc'
def packet(kind,value):return bytes([kind])+struct.pack('<I',len(value))+value
class Sock:
 def __init__(self,reply=None,state=b'device',fail=False,chunk=2):self.buffer=b'';self.sent=[];self.reply=reply;self.state=state;self.fail=fail;self.closed=False;self.chunk=chunk;self.options=[]
 def __enter__(self):return self
 def __exit__(self,*_):self.closed=True
 def setsockopt(self,*v):self.options.append(v)
 def settimeout(self,v):pass
 def sendall(self,value):
  size=int(value[:4],16);assert size==len(value[4:]);command=value[4:].decode();self.sent.append(command)
  if self.fail:self.buffer+=b'FAIL000cPRIVATE TEXT';return
  self.buffer+=b'OKAY'
  if command.startswith('host-serial:'):self.buffer+=('%04x'%len(self.state)).encode()+self.state
  elif command.startswith('shell,v2,raw:'):
   content=(BOOT+'\n').encode() if command.endswith(BOOT_ID) else b'1\n' if command.endswith('sys.boot_completed') else ('package:'+PACKAGE+'\n').encode()
   self.buffer+=self.reply if self.reply is not None else packet(1,content)+packet(3,b'\0')
 def recv(self,n):
  block=self.buffer[:min(n,self.chunk)];self.buffer=self.buffer[len(block):];return block

class ReadProtocol(unittest.TestCase):
 def execute(self,command,**kw):
  self.sock=Sock(**kw)
  def connect(address,timeout):self.assertEqual(address,('127.0.0.1',5037));return self.sock
  return fast.read(TARGET,command,lambda:False,socket_factory=connect)
 def test_exact_four_read_commands_and_v2_frames(self):
  for command,expected in [(['get-state'],'device'),(['shell','cat',BOOT_ID],BOOT),(['shell','getprop','sys.boot_completed'],'1'),(['shell','pm','list','packages',PACKAGE],'package:'+PACKAGE)]:
   self.assertEqual(self.execute(command),expected);self.assertTrue(self.sock.closed)
   self.assertIn((socket.IPPROTO_TCP,socket.TCP_NODELAY,1),self.sock.options)
   self.assertTrue(all(TARGET in c or c.startswith('shell,v2,raw:') for c in self.sock.sent))
 def test_no_arbitrary_shell_forward_send_or_implicit_target(self):
  create=MagicMock()
  for command in (['shell','input','tap','1','1'],['shell','reboot'],['forward','tcp:0','tcp:27042'],['devices']):
   with self.assertRaises(fast.ReadFailure):fast.read(TARGET,command,lambda:False,socket_factory=create)
  create.assert_not_called()
 def test_failures_truncation_stderr_exit_and_bounds_rejected(self):
  for reply in (packet(1,b'PRIVATE'),packet(3,b'\1'),packet(2,b'PRIVATE')+packet(3,b'\0'),packet(3,b'\0\0'),bytes([1])+struct.pack('<I',65537),bytes([99])+struct.pack('<I',0)):
   with self.assertRaises(fast.ReadFailure) as e:self.execute(['shell','cat',BOOT_ID],reply=reply)
   self.assertNotIn('PRIVATE',str(e.exception));self.assertTrue(self.sock.closed)
 def test_service_fail_body_not_exposed_or_retried(self):
  with self.assertRaises(fast.ReadFailure) as e:self.execute(['get-state'],fail=True)
  self.assertEqual(str(e.exception),'service-failed');self.assertEqual(len(self.sock.sent),1)
 def test_cancel_before_socket(self):
  create=MagicMock()
  with self.assertRaisesRegex(fast.ReadFailure,'cancelled'):fast.read(TARGET,['get-state'],lambda:True,socket_factory=create)
  create.assert_not_called()
 def test_timeout_and_get_state_size_validation(self):
  for value in (True,0,-1,float('nan'),float('inf'),121):
   with self.assertRaises(fast.ReadFailure):fast.read(TARGET,['get-state'],lambda:False,value)
  with self.assertRaises(fast.ReadFailure):self.execute(['get-state'],state=b'A'*33)
 def test_no_eof_is_success_without_exit(self):
  with self.assertRaises(fast.ReadFailure):self.execute(['shell','cat',BOOT_ID],reply=packet(1,(BOOT+'\n').encode()))

class WorkerRouting(unittest.TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,{'DVK_MUMU_MULTI':'1'});self.env.start();self.addCleanup(self.env.stop)
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  path=Path(self.temp.name);(path/'adb.exe').write_text('synthetic');self.adb=TargetOnlyAdb(str(path/'adb.exe'),path)
 def test_fixed_reads_skip_cli_and_are_never_cached(self):
  opened=[]
  def connect(*a,**kw):s=Sock();opened.append(s);return s
  original=TargetOnlyAdb.run
  with patch('test_device.subprocess.run') as cli:
   with fast.transport(TARGET,socket_factory=connect) as timings:
    for _ in range(2):self.assertEqual(self.adb.run(['-s',TARGET,'shell','cat',BOOT_ID]),BOOT)
    self.assertEqual(timings.snapshot()['socket_read']['calls'],2)
   cli.assert_not_called()
  self.assertIs(TargetOnlyAdb.run,original);self.assertEqual(len(opened),2)
 def test_changed_boot_still_stops_after_fresh_socket_read(self):
  from target_only import preflight,recheck
  calls=[]
  def connect(*args,**kw):
   calls.append(1)
   if len(calls)==6:return Sock(reply=packet(1,b'87654321-1234-1234-1234-123456789abc\n')+packet(3,b'\0'))
   return Sock()
  with patch.object(TargetOnlyAdb,'run',MagicMock(return_value='local-cli')):
   with fast.transport(TARGET,socket_factory=connect):
    boot=preflight(self.adb)
    with self.assertRaises(TestError):recheck(self.adb,boot)
  self.assertEqual(len(calls),6)
 def test_cli_forward_lifecycle_not_intercepted(self):
  original=MagicMock(return_value='32123')
  with patch.object(TargetOnlyAdb,'run',original):
   with fast.transport(TARGET,socket_factory=MagicMock()) as timings:
    self.assertEqual(self.adb.run(['-s',TARGET,'forward','tcp:0','tcp:27042']),'32123')
    self.adb.forward_port=32123;self.adb.run(['-s',TARGET,'forward','--remove','tcp:32123'])
    self.assertEqual(timings.snapshot()['cli']['calls'],2)
  self.assertEqual(original.call_count,2)
 def test_allowlist_before_read_or_cli(self):
  connect=MagicMock()
  with fast.transport(TARGET,socket_factory=connect):
   for args in (['devices'],['-s','127.0.0.1:33333','get-state'],['-s',TARGET,'shell','input','tap','1','1']):
    with self.assertRaises(TestError):self.adb.run(args)
  connect.assert_not_called()
 def test_restore_after_error_no_retry_private_output(self):
  original=TargetOnlyAdb.run;opened=[]
  def connect(*a,**kw):s=Sock(fail=True);opened.append(s);return s
  with self.assertRaises(TestError) as e:
   with fast.transport(TARGET,socket_factory=connect):self.adb.run(['-s',TARGET,'get-state'])
  self.assertIs(TargetOnlyAdb.run,original);self.assertEqual(len(opened),1);self.assertNotIn('PRIVATE',str(e.exception))
 def test_not_available_to_mumu_other_target_or_nested(self):
  with patch.dict(os.environ,{'DVK_MUMU_MULTI':'0'}),self.assertRaises(CloudError):
   with fast.transport(TARGET):pass
  with self.assertRaises(CloudError):
   with fast.transport('127.0.0.1:33333'):pass
  with fast.transport(TARGET):
   with self.assertRaises(CloudError):
    with fast.transport(TARGET):pass
 def test_metrics_contain_only_aggregate_numbers_and_fixed_fields(self):
  with fast.transport(TARGET,socket_factory=lambda *a,**kw:Sock()) as timings:
   self.adb.run(['-s',TARGET,'shell','cat',BOOT_ID]);s=timings.snapshot()
  self.assertNotIn(BOOT,str(s));self.assertNotIn(TARGET,str(s));self.assertNotIn('shell',str(s))
  self.assertFalse(s['read_cache']);self.assertEqual(s['socket_read']['calls'],1)
