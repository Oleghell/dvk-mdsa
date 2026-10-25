"""Opt-in 5-worker regression through inbox preparation and first native boundary.
Private schema data is cloned server-side into SESSION TEMP tables only.
No actual navigation, AI, notification, real send, or production mutation.
Usage: python smoke_cloud_startup.py /private/connection.json
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
  local.schemas.update(self.schemas)
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
  statements=['CREATE TEMP TABLE _dvk_schema (LIKE dvk_private._dvk_schema INCLUDING ALL)', 'INSERT INTO pg_temp._dvk_schema SELECT * FROM dvk_private._dvk_schema']
  for n,s in rows:statements+=['CREATE TEMP TABLE '+ident(n)+' (LIKE dvk_private.'+ident(n)+' INCLUDING ALL)','INSERT INTO pg_temp.'+ident(n)+' SELECT * FROM dvk_private.'+ident(n)]
  raw.execute(';'.join(statements),prepare=False);raw.execute('SET search_path TO pg_temp,pg_catalog')
  barrier.wait(timeout=90);start=time.monotonic()
  with tempfile.TemporaryDirectory() as folder:
   with cloud.journal_initialization():
    store=SharedStore(pathlib.Path(folder)/'assistant.sqlite3',device_port=port)
    enable(store,new_only=False)
    contact(store)
   local.stage='inbox-database'
   prepared=SharedStore(pathlib.Path(folder)/'assistant.sqlite3',device_port=port)
   local.stage='inbox-chain'
   from assistant_inbox import InboxChain,inbox_targets
   import assistant_history_wait as history
   chain=InboxChain(prepared,responder=object());chain.media_required=True
   local.stage='inbox-targets'
   history.initialize(prepared)
   attention,unread=inbox_targets(chain)
   history.eligible(prepared,attention,unread)
   local.stage='inbox-seen-ids'
   from assistant_inbox import with_seen_ids
   with_seen_ids(chain,attention+unread)
   local.stage='inbox-first-navigation'
   from assistant_inbox import walk
   from types import SimpleNamespace
   reached=[]
   def boundary(*args,**kwargs):
    reached.append(True)
    raise RuntimeError('synthetic-native-boundary')
   def forbidden(*a,**kw):raise AssertionError('A real device/send adapter must not be called')
   result=walk(SimpleNamespace(adb='synthetic',folder='synthetic'),threading.Event(),lambda *a:False,lambda *a:None,chain,navigator=boundary,reader=forbidden,sender=forbidden,notifier=None)
   if attention or unread:assert reached,'Inbox did not reach native navigation boundary'
   assert result['submission_calls']==0



  print('PASS',port,round(time.monotonic()-start,2),flush=True);return True
 except Exception as e:
  print('FAIL',port,getattr(local,'stage','bootstrap'),type(e).__name__,getattr(e,'code',None),flush=True);return False
 finally:raw.close()
with patch('mumu_store.connect',connect),patch('cloud_database.connect',connect),patch.object(cloud,'LOCK_ID',732489102132):
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(worker,(5557,5559,5561,5563,5565)))
print('Initialization passed',sum(results),'of',len(results),flush=True)
raise SystemExit(0 if all(results) else 1)
