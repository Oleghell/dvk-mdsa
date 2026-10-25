"""Opt-in parallel startup regression; all writes are SESSION TEMP tables only.
Usage: python smoke_cloud_startup.py /private/connection.json
Five concurrent sessions clone the private schema server-side, run the real
journal initialization with one shared TEST advisory lock, then discard copies.
No real sends, production mutations, config/row contents or credentials printed.
"""
import sys,json,pathlib,tempfile,time,threading,concurrent.futures
from unittest.mock import patch
from contextlib import nullcontext
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import cloud_database as cloud
from cloud_sql import schema_info,ident
from mumu_store import SharedStore
from assistant_reply_window import enable
from assistant_contact_policy import enable as contact
if len(sys.argv)!=2:raise SystemExit('Private connection JSON path required')
cfg=cloud.validate(json.loads(pathlib.Path(sys.argv[1]).read_text()))
local=threading.local();barrier=threading.Barrier(5)
class TempConnection(cloud.Connection):
 def close(self):
  if self.in_transaction:self.execute('ROLLBACK')
  self.closed=True
class Proxy:
 def __getattr__(self,n):return getattr(local.raw,n)
 def execute(self,sql,*a,**kw):
  try:return local.raw.execute(sql,*a,**kw)
  except Exception as e:
   print('SQL failure port',local.port,'SQLSTATE',getattr(e,'sqlstate',None),'operation',sql.split()[0],flush=True);raise
def connect(*a,**kw):return TempConnection(Proxy(),cfg,local.schemas)
def worker(port):
 local.port=port;raw=cloud.raw_connect(cfg);local.raw=raw
 try:
  rows=raw.execute('SELECT name,sqlite_sql FROM dvk_private._dvk_schema').fetchall()
  local.schemas={n:schema_info(s) for n,s in rows}
  statements=['CREATE TEMP TABLE _dvk_schema AS SELECT * FROM dvk_private._dvk_schema']
  for n,s in rows:statements+=['CREATE TEMP TABLE '+ident(n)+' (LIKE dvk_private.'+ident(n)+' INCLUDING ALL)','INSERT INTO pg_temp.'+ident(n)+' SELECT * FROM dvk_private.'+ident(n)]
  raw.execute(';'.join(statements),prepare=False);raw.execute('SET search_path TO pg_temp,pg_catalog')
  barrier.wait(timeout=90);start=time.monotonic()
  with tempfile.TemporaryDirectory() as folder, cloud.journal_initialization():
   store=SharedStore(pathlib.Path(folder)/'assistant.sqlite3',device_port=port)
   enable(store,new_only=False)
   contact(store)
  print('PASS',port,round(time.monotonic()-start,2),flush=True);return True
 except Exception as e:
  print('FAIL',port,type(e).__name__,getattr(e,'code',None),flush=True);return False
 finally:raw.close()
with patch('mumu_store.connect',connect),patch('cloud_database.connect',connect),patch.object(cloud,'LOCK_ID',732489102130):
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(worker,(5557,5559,5561,5563,5565)))
print('Initialization passed',sum(results),'of',len(results),flush=True)
raise SystemExit(0 if all(results) else 1)
