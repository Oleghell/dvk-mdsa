"""Explicit new bounded cohort. Durable reservation precedes every greeting.

Only fixed reserve/ack RPCs are exposed; no chat text or IDs enter reports.
This is enrollment, NOT an Android reply-monitor implementation.
"""
import json,os,re,sqlite3
from contextlib import contextmanager
from pathlib import Path
import chat_batch
from conversation_engine import identifier
from greetings import get_greeting
from uikit_profile_navigation import replace_once

class CohortError(Exception):pass

class Store:
    def __init__(self,path):self.path=Path(path)
    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=5,isolation_level=None)
        try:
            db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE');yield db;db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()
    def create(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cohort(singleton INTEGER PRIMARY KEY CHECK(singleton=1),state TEXT NOT NULL)')
            if db.execute('SELECT 1 FROM cohort').fetchone():raise CohortError('Новая десятка уже запускалась. Журнал сохранён; повтор не выполняется.')
            db.execute('CREATE TABLE bindings(attempt INTEGER PRIMARY KEY,account TEXT NOT NULL,peer TEXT NOT NULL UNIQUE,initial_chat TEXT NOT NULL,variant INTEGER NOT NULL,status TEXT NOT NULL)')
            db.execute("INSERT INTO cohort VALUES(1,'reserved')")
    @staticmethod
    def check(value):
        if not isinstance(value,dict) or set(value)!={'attempt','account','peer','chat','variant'}:raise CohortError('Invalid reservation')
        if type(value['attempt']) is not int or not 1<=value['attempt']<=10:raise CohortError('Invalid attempt')
        identifier(value['account']);identifier(value['peer'])
        if value['account']==value['peer']:raise CohortError('Self dialog')
        # Draft chat IDs may not exist yet. Preserve the actual signed Int64;
        # never invent a positive server ID or use it as the peer identity.
        v=value['chat']
        if not isinstance(v,str) or not re.fullmatch(r'0|[1-9][0-9]{0,18}|-[1-9][0-9]{0,18}',v) or not -(2**63)<=int(v)<2**63:raise CohortError('Invalid chat ID')
        get_greeting(value['variant'])
        return value
    def reserve(self,value):
        p=self.check(value);values=tuple(p[k] for k in ('attempt','account','peer','chat','variant'))
        with self.connection() as db:
            row=db.execute('SELECT state FROM cohort').fetchone()
            if not row or row[0]!='reserved':raise CohortError('Cohort closed')
            old=db.execute('SELECT attempt,account,peer,initial_chat,variant FROM bindings WHERE attempt=?',(p['attempt'],)).fetchone()
            if old:
                if old!=values:raise CohortError('Reservation changed')
                return
            account=db.execute('SELECT account FROM bindings LIMIT 1').fetchone()
            if account and account[0]!=p['account']:raise CohortError('Account changed')
            if db.execute('SELECT COUNT(*) FROM bindings').fetchone()[0]>=10:raise CohortError('Cohort full')
            db.execute("INSERT INTO bindings VALUES(?,?,?,?,?,'reserved-unknown')",values)
    def finish(self,batch):
        with self.connection() as db:
            for item in batch.get('items',[]):
                if item.get('send_attempted') is True:
                    row=db.execute('SELECT variant FROM bindings WHERE attempt=?',(item['number'],)).fetchone()
                    if row is None or row[0]!=item.get('greeting_variant'):
                        raise CohortError('Submission has no matching durable reservation')
                # Handler return is NOT delivery confirmation. Unknown stays held.
                if item.get('send_handler_returned') is True:
                    db.execute("UPDATE bindings SET status='handler-returned-unconfirmed' WHERE attempt=?",(item['number'],))
            db.execute("UPDATE cohort SET state='closed'")
    def summary(self):
        with self.connection() as db:
            count=db.execute('SELECT COUNT(*) FROM bindings').fetchone()[0]
            returned=db.execute("SELECT COUNT(*) FROM bindings WHERE status='handler-returned-unconfirmed'").fetchone()[0]
        return dict(limit=10,reserved=count,handlers_returned=returned,identity_keys_in_report=False,
                    delivery_confirmed=False,live_replies_available=False)

SETUP=r'''
  s.cohortManagerClass=getClass('DV.Messages.dll','DV.Messages','MessagesManager');
  if(s.cohortManagerClass.isNull())throw new Error('metadata');
  s.cohortManager=checked(s.chatModel,'get_MessagesManager',18,s.cohortManagerClass);
  s.cohortAccount=checked(s.cohortManagerClass,'get_CurrentUserId',10);
  s.cohortChat=checked(s.chatModel,'get_Id',10);
'''
RESERVE=r'''
   const manager=call(s.cohortManager,chat);if(manager.isNull())fail('unexpected-object');own(manager);
   if(!f.objectClass(manager).equals(s.cohortManagerClass))fail('unexpected-object');
   const account=longInteger(s.cohortAccount,manager),peer=longInteger(s.batchId,user),chatId=longInteger(s.cohortChat,chat);
   if(account.compare(0)<=0||peer.compare(0)<=0||account.compare(peer)===0||peer.toString()!==batchCandidateKey)fail('identity-changed');
   const reservation={attempt:batchAttempts,account:account.toString(),peer:peer.toString(),chat:chatId.toString(),variant:batchVariants[batchAttempts-1]};
   const reservationKey=JSON.stringify(reservation);
   if(cohortApproved!==reservationKey){
    if(cohortApproved!==null||cohortPending!==null&&JSON.stringify(cohortPending)!==reservationKey)fail('identity-changed');
    cohortPending=reservation;state.nextActionAt=Date.now()+1000;return;
   }
'''
GLOBALS=r'''
let cohortPending=null,cohortApproved=null;
function cohortReservation(){return cohortPending===null?null:JSON.parse(JSON.stringify(cohortPending));}
function cohortAcknowledge(value){
 if(cohortPending===null||JSON.stringify(value)!==JSON.stringify(cohortPending))return false;
 cohortApproved=JSON.stringify(cohortPending);cohortPending=null;return true;
}
'''
def build(variants=None):
    source=chat_batch.build(variants)
    source=replace_once(source,"  s.input=checked(s.chatModel,'get_IsInputEnabled',2);", "  s.input=checked(s.chatModel,'get_IsInputEnabled',2);"+SETUP)
    source=replace_once(source,"   if(batchSent.has(batchCandidateKey))fail('send-already-attempted');",RESERVE+"   if(batchSent.has(batchCandidateKey))fail('send-already-attempted');")
    source=replace_once(source,' batchActive=true;batchAttempts++;',' batchActive=true;batchAttempts++;cohortPending=null;cohortApproved=null;')
    return GLOBALS+source

def build_random():
    from greetings import choose_index
    return build([choose_index() for _ in range(10)])
validate=chat_batch.validate
run=chat_batch.run

def monitor(script,store,stop,cancelled,failed):
    """Only this host path can ACK, and only after a successful FULL commit."""
    while not stop.wait(0.05):
        try:
            pending=script.exports_sync.cohortpending()
            if pending is None:continue
            if cancelled():script.exports_sync.cancel();return
            store.reserve(pending)
            if stop.is_set() or cancelled():script.exports_sync.cancel();return
            if not script.exports_sync.cohortack(pending):raise CohortError('Stale reservation')
        except Exception:
            failed.set()
            try:script.exports_sync.cancel()
            except Exception:pass
            return

def default_path():
    base=os.environ.get('LOCALAPPDATA')
    if not base:raise CohortError('Нужна папка LOCALAPPDATA текущего пользователя Windows.')
    return Path(base)/'DvkRootless'/'new-ten.sqlite3'

def start(adb,folder,progress=lambda text:None,cancelled=lambda:False,*,path=None):
    from diagnose_device import diagnose,TestError
    try:
        store=Store(default_path() if path is None else path);store.create()
    except (CohortError,sqlite3.Error,OSError) as error:
        raise TestError(str(error) if isinstance(error,CohortError) else 'Не удалось создать локальный журнал новой десятки.') from None
    # Explicitly separate from the legacy one-shot pass. Its lock is untouched.
    return diagnose(adb,folder,progress,cancelled,automatic_probe=True,cohort_store=store)
