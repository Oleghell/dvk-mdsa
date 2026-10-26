"""1.3.53 regressions: import-time default lock and SQLite autoindex length."""
import os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from cloud_sql import ident,schema_info,create_sql
from mumu_store import SharedStore
ROOT=Path(__file__).resolve().parents[1]
DDL='''CREATE TABLE IF NOT EXISTS read_only_bindings(
 account TEXT NOT NULL,peer TEXT NOT NULL,chat TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(account,peer),UNIQUE(account,chat))'''

class Startup(unittest.TestCase):
    def test_identity_loader_imports_no_engine_or_default_operation_lock(self):
        code='''import sys
from mumu_installation import load
load()
assert not ({'assistant_lock','assistant_store','cohort_pass'} & set(sys.modules)), 'identity loader froze engine imports'
print('ok')
'''
        with tempfile.TemporaryDirectory() as t:
            env=dict(os.environ,LOCALAPPDATA=t,PYTHONPATH=str(ROOT))
            p=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),'ok')
    def test_two_real_worker_configurations_hold_different_default_locks(self):
        code='''import sys,time
from pathlib import Path
from mumu_worker import configure
port=configure(int(sys.argv[1]))
from assistant_lock import operation_lock,data_directory
from mumu_common import device_directory
assert data_directory()==device_directory(port), 'wrong default device-lock directory'
with operation_lock():
 Path(sys.argv[2],str(port)+'.ready').touch()
 deadline=time.monotonic()+12
 while not Path(sys.argv[2],'done').exists():
  assert time.monotonic()<deadline
  time.sleep(.01)
print('ok')
'''
        with tempfile.TemporaryDirectory() as t:
            env=dict(os.environ,LOCALAPPDATA=t,PYTHONPATH=str(ROOT));env.pop('DVK_MORELOGIN',None)
            children=[]
            try:
                for port in (5557,5559):
                    children.append(subprocess.Popen([sys.executable,'-c',code,str(port),t],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
                deadline=time.monotonic()+10
                while not all((Path(t)/(str(port)+'.ready')).exists() for port in (5557,5559)):
                    for child in children:
                        if child.poll() is not None:
                            out,err=child.communicate();self.fail(out+err)
                    self.assertLess(time.monotonic(),deadline);time.sleep(.02)
                self.assertFalse((Path(t)/'DvkAssistant/device.lock').exists())
                Path(t,'done').touch()
                for child in children:
                    out,err=child.communicate(timeout=15);self.assertEqual(child.returncode,0,err);self.assertEqual(out.strip(),'ok')
            finally:
                Path(t,'done').touch()
                for child in children:
                    if child.poll() is None:child.kill()
                    child.communicate()
    def test_long_sqlite_generated_index_is_not_a_postgres_identifier(self):
        name='i'+'a'*20+'_m5563__read_only_bindings'
        self.assertLessEqual(len(name),63);self.assertGreater(len('sqlite_autoindex_'+name+'_2'),63)
        info=schema_info(DDL.replace('read_only_bindings',name))
        self.assertEqual(info['pk'],['account','peer']);self.assertEqual(info['unique'],[['account','chat']])
        self.assertIn('UNIQUE ("account","chat")',create_sql(info))
        with self.assertRaises(ValueError):ident('a'*64)
        with self.assertRaises(ValueError):schema_info(DDL.replace('read_only_bindings','a'*64))
    def test_full_default_port_legacy_read_binding_migrates_without_reset(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'db';legacy=SharedStore(path,device_port=5563)
            with legacy.connection() as db:
                db.execute(DDL);db.execute("INSERT INTO read_only_bindings(account,peer,chat) VALUES('100','200','300')")
            store=SharedStore(path,device_port=5563,installation_id='a'*32)
            with store.read_connection() as db:
                self.assertEqual(db.execute('SELECT account,peer,chat FROM read_only_bindings').fetchall(),[('100','200','300')])
            with legacy.read_connection() as db:
                self.assertEqual(db.execute('SELECT account,peer,chat FROM read_only_bindings').fetchall(),[('100','200','300')])

if __name__=='__main__':unittest.main()
