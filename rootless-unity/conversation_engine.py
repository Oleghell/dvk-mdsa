"""Durable bounded reply policy. No Android implementation is implied by this module.

Snapshots must come from a verified backend in chronological order. Text is used
in memory only; the DB retains bindings, stages, message IDs and notification contacts.
"""
from dataclasses import dataclass
from contextlib import contextmanager
import json,re,secrets,sqlite3,time,unicodedata
from greetings import GREETINGS
LIMIT=10
QUESTIONS=('Как дела?)','Как настроение?)')
CONTACT_TEXT='Супер, у меня тоже. Ты есть в телеграме или ватцапе? А то я тут не часто бываю 😅'
class PolicyError(Exception):pass

def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,18}',value) or int(value)>2**63-1:raise PolicyError('Invalid identifier')
    return value

@dataclass(frozen=True)
class Message:
    id:str
    sender:str
    text:str|None

@dataclass(frozen=True)
class Snapshot:
    account:str
    peer:str
    chat:str
    name:str
    messages:tuple
    fully_loaded:bool=True
    loading:bool=False
    samples:int=2
    identity_verified:bool=True
    chronological:bool=True
    def check(self):
        for value in (self.account,self.peer,self.chat):identifier(value)
        if self.account==self.peer:raise PolicyError('Self dialog')
        if not isinstance(self.name,str) or len(self.name)>128:raise PolicyError('Invalid display name')
        if self.fully_loaded is not True or self.loading is not False or type(self.samples) is not int or self.samples!=2 or self.identity_verified is not True or self.chronological is not True:raise PolicyError('Unverified history')
        if type(self.messages) is not tuple or not 1<=len(self.messages)<=128:raise PolicyError('Invalid history size')
        seen=set()
        for m in self.messages:
            if not isinstance(m,Message):raise PolicyError('Invalid message')
            identifier(m.id);identifier(m.sender)
            if m.id in seen or m.sender not in (self.account,self.peer) or (m.text is not None and (not isinstance(m.text,str) or len(m.text)>4096)):raise PolicyError('Invalid message binding')
            seen.add(m.id)
        return self

REFUSAL=re.compile(r'\b(?:не\s+пиши(?:те)?|не\s+хочу\s+(?:общаться|знакомиться)|отстань(?:те)?|оставь(?:те)?\s+меня|не\s+интересует|не\s+дам|не\s+буду\s+давать|stop|unsubscribe|не\s+нужны\s+знакомства)\b',re.I)
NEGATIVE=re.compile(r'\b(?:плохо|ужасно|ужас|горе|умер(?:ла)?|беда|болею|не\s+очень|депрессия)\b',re.I)
HANDLE=re.compile(r'(?<![\w@])@([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_])')
TGLINK=re.compile(r'(?<![\w./])(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_/])',re.I)
PHONE=re.compile(r'(?<!\w)(\+?\d[\d ()\-]{8,24}\d)(?!\w)')

def normalized(text):return unicodedata.normalize('NFKC',text).casefold()
def contacts(text):
    out=[]
    for regex in (HANDLE,TGLINK):
        for m in regex.finditer(text):
            c='@'+m.group(1)
            if c.casefold() not in {x.casefold() for x in out}:out.append(c)
    for m in PHONE.finditer(text):
        raw=m.group(1);digits=re.sub(r'\D','',raw)
        if not 10<=len(digits)<=15:continue
        if raw.startswith('+'):c='+'+digits
        elif len(digits)==11 and digits[0] in '78':c='+7'+digits[1:]
        else:continue # Ambiguous numeric IDs are not assumed to be phone numbers.
        if c not in out:out.append(c)
    return out[:4]

class Engine:
    def __init__(self,path,backend,notifier=None,clock=time.time,choose=lambda:secrets.randbelow(2)):
        self.db=sqlite3.connect(path,timeout=10,isolation_level=None);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dialogs(chat TEXT PRIMARY KEY,account TEXT NOT NULL,peer TEXT NOT NULL UNIQUE,greeting TEXT NOT NULL,anchor TEXT NOT NULL,stage TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY,chat TEXT NOT NULL,kind TEXT NOT NULL,trigger TEXT NOT NULL,text TEXT NOT NULL,status TEXT NOT NULL,UNIQUE(chat,kind));
        CREATE TABLE IF NOT EXISTS outbox(chat TEXT PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL);
        ''')
        self.backend=backend;self.notifier=notifier;self.clock=clock;self.choose=choose
    def close(self):self.db.close()
    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:yield;self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
    def register(self,snapshot,*,approved=False):
        s=snapshot.check()
        if approved is not True:raise PolicyError('Explicit dialog approval required')
        first=s.messages[0]
        if first.sender!=s.account or first.text not in GREETINGS:raise PolicyError('Approved outgoing greeting required')
        with self.tx():
            account=self.db.execute("SELECT value FROM meta WHERE key='account'").fetchone()
            if account and account[0]!=s.account:raise PolicyError('Different account')
            row=self.db.execute('SELECT * FROM dialogs WHERE chat=?',(s.chat,)).fetchone()
            if row:
                if (row['account'],row['peer'],row['greeting'])!=(s.account,s.peer,first.id):raise PolicyError('Different dialog binding')
                return False
            if self.db.execute('SELECT COUNT(*) FROM dialogs').fetchone()[0]>=LIMIT:raise PolicyError('Ten dialog limit reached')
            if self.db.execute('SELECT 1 FROM dialogs WHERE peer=?',(s.peer,)).fetchone():raise PolicyError('Peer already enrolled')
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('account',?)",(s.account,))
            self.db.execute('INSERT INTO dialogs VALUES(?,?,?,?,?,?)',(s.chat,s.account,s.peer,first.id,first.id,'wait_reply'))
        return True
    def state(self,chat):
        r=self.db.execute('SELECT stage FROM dialogs WHERE chat=?',(chat,)).fetchone()
        return r[0] if r else None
    def summary(self):
        # Export counts only. Never export IDs, names, tokens, text or contacts.
        rows=self.db.execute('SELECT stage,COUNT(*) FROM dialogs GROUP BY stage').fetchall()
        return dict(limit=LIMIT,dialogs=sum(r[1] for r in rows),stages={r[0]:r[1] for r in rows},live_backend_available=False)
    def _gate(self):
        now=self.clock();r=self.db.execute("SELECT value FROM meta WHERE key='last_action'").fetchone()
        if r and now<float(r[0])+1:return False
        self.db.execute("INSERT OR REPLACE INTO meta VALUES('last_action',?)",(str(now),));return True
    def handle(self,snapshot):
        s=snapshot.check();event=None
        with self.tx():
            row=self.db.execute('SELECT * FROM dialogs WHERE chat=?',(s.chat,)).fetchone()
            if not row:return 'untracked'
            if (row['account'],row['peer'])!=(s.account,s.peer):raise PolicyError('Different dialog binding')
            first=s.messages[0]
            if (first.id,first.sender)!=(row['greeting'],s.account) or first.text not in GREETINGS:raise PolicyError('Greeting identity changed')
            stage=row['stage']
            if stage in ('done','declined','manual_review'):return stage
            positions={m.id:i for i,m in enumerate(s.messages)}
            if row['anchor'] not in positions:return 'incomplete_history'
            anchor=positions[row['anchor']]
            if stage.startswith('pending_'):
                action=self.db.execute('SELECT * FROM actions WHERE chat=? AND kind=?',(s.chat,stage[8:])).fetchone()
                if not action:raise PolicyError('Pending action missing')
                candidates=[m for m in s.messages[anchor+1:] if m.sender==s.account]
                if not candidates:return 'await_confirmation'
                if len(candidates)!=1 or candidates[0].text!=action['text']:
                    self.db.execute("UPDATE dialogs SET stage='manual_review' WHERE chat=?",(s.chat,));return 'manual_review'
                own=candidates[0];stage='wait_mood' if action['kind']=='question' else 'wait_contact';anchor=positions[own.id]
                self.db.execute("UPDATE actions SET status='observed' WHERE id=?",(action['id'],))
                self.db.execute('UPDATE dialogs SET stage=?,anchor=? WHERE chat=?',(stage,own.id,s.chat))
            after=s.messages[anchor+1:]
            if any(m.sender==s.account for m in after):
                self.db.execute("UPDATE dialogs SET stage='manual_review' WHERE chat=?",(s.chat,));return 'manual_review'
            incoming=[m for m in after if m.sender==s.peer]
            if not incoming:return 'waiting'
            texts=[m.text for m in incoming if m.text is not None];joined='\n'.join(texts)
            if REFUSAL.search(normalized(joined)):
                self.db.execute("UPDATE dialogs SET stage='declined' WHERE chat=?",(s.chat,));return 'declined'
            found=contacts(joined)
            if found:
                payload=json.dumps({'name':s.name,'contacts':found},ensure_ascii=False)
                self.db.execute("INSERT OR IGNORE INTO outbox VALUES(?,?,'pending')",(s.chat,payload))
                self.db.execute("UPDATE dialogs SET stage='done' WHERE chat=?",(s.chat,));return 'contact_saved'
            if any(m.text is None or not m.text.strip() for m in incoming) or NEGATIVE.search(normalized(joined)):
                self.db.execute("UPDATE dialogs SET stage='manual_review' WHERE chat=?",(s.chat,));return 'manual_review'
            if stage=='wait_contact':return 'waiting_contact'
            if not self._gate():return 'delay'
            kind='question' if stage=='wait_reply' else 'contact'
            if kind=='question':
                choice=self.choose()
                if type(choice) is not int or choice not in (0,1):raise PolicyError('Invalid question variant')
                text=QUESTIONS[choice]
            else:text=CONTACT_TEXT
            trigger=incoming[-1].id
            # Reservation is committed BEFORE the side effect. Never auto-resend
            # an action after timeout, exception, crash, or lost acknowledgement.
            cur=self.db.execute("INSERT INTO actions(chat,kind,trigger,text,status) VALUES(?,?,?,?,'reserved')",(s.chat,kind,trigger,text))
            self.db.execute('UPDATE dialogs SET stage=?,anchor=? WHERE chat=?',('pending_'+kind,trigger,s.chat))
            event=(cur.lastrowid,text,trigger)
        action,text,trigger=event
        try:
            # Live adapter must freshly revalidate account/peer/chat/last incoming
            # and perform only one typed OnSendText invocation, never a generic RPC.
            accepted=self.backend.send_reply(s.account,s.chat,s.peer,text,trigger)
            status='handler_returned' if accepted is True else 'unknown'
        except Exception:status='unknown'
        with self.tx():self.db.execute('UPDATE actions SET status=? WHERE id=?',(status,action))
        return status
    def notify_one(self):
        if self.notifier is None:return 'not_configured'
        with self.tx():
            row=self.db.execute("SELECT * FROM outbox WHERE status='pending' ORDER BY rowid LIMIT 1").fetchone()
            if not row:return 'nothing_pending'
            if not self._gate():return 'delay'
            self.db.execute("UPDATE outbox SET status='attempted' WHERE chat=?",(row['chat'],))
            payload=json.loads(row['payload']);chat=row['chat']
        try:status='accepted' if self.notifier(payload) is True else 'unknown'
        except Exception:status='unknown'
        with self.tx():self.db.execute('UPDATE outbox SET status=? WHERE chat=?',(status,chat))
        return status
