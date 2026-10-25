"""Aggregate contact and first-greeting events. No bodies, numbers or handles."""
from datetime import datetime,timedelta,time,timezone
from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import sqlite3

DDL=(
 '''CREATE TABLE IF NOT EXISTS global_greeting_statistics(
 event_key TEXT PRIMARY KEY,started_at TEXT NOT NULL,city TEXT NOT NULL,status TEXT NOT NULL)''',
 '''CREATE TABLE IF NOT EXISTS global_contact_statistics(
 event_key TEXT PRIMARY KEY,received_at TEXT NOT NULL,city TEXT NOT NULL,
 phone_count INTEGER NOT NULL,handle_count INTEGER NOT NULL,telegram TEXT NOT NULL)''',
 '''CREATE TABLE IF NOT EXISTS global_peer_city(peer_key TEXT PRIMARY KEY,city TEXT NOT NULL)''')

def initialize(db):
    for sql in DDL:db.execute(sql)

def peer_key(account,peer):
    return hashlib.sha256((str(account)+'/'+str(peer)).encode()).hexdigest()

def remember_city(db,account,peer):
    # This is the verified search city at greeting time, NOT the peer's residence.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",('search_session',)).fetchone():return
    row=db.execute("SELECT value FROM search_session WHERE key='city'").fetchone()
    if row and valid_city(row[0]):
        db.execute('INSERT OR IGNORE INTO global_peer_city VALUES(?,?)',(peer_key(account,peer),row[0]))

def valid_city(value):
    return isinstance(value,str) and 1<=len(value)<=80 and value==value.strip() and not any(ord(x)<32 or 127<=ord(x)<160 for x in value)

def received(db,account,peer,chat,contacts,now=None):
    initialize(db)
    key=hashlib.sha256((str(account)+'/'+str(peer)+'/'+str(chat)).encode()).hexdigest()
    row=db.execute('SELECT city FROM global_peer_city WHERE peer_key=?',(peer_key(account,peer),)).fetchone()
    city=row[0] if row and valid_city(row[0]) else 'Неизвестен'
    phones=sum(bool(re.fullmatch(r'\+?[0-9() .-]+',x)) and 7<=len(re.sub(r'\D','',x))<=15 for x in contacts)
    stamp=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec='seconds')
    db.execute('INSERT OR IGNORE INTO global_contact_statistics VALUES(?,?,?,?,?,?)',
               (key,stamp,city,phones,len(contacts)-phones,'pending'))

def notified(db,account,peer,chat,outcome):
    if outcome not in ('accepted','unknown','blocked'):return
    key=hashlib.sha256((str(account)+'/'+str(peer)+'/'+str(chat)).encode()).hexdigest()
    db.execute('UPDATE global_contact_statistics SET telegram=? WHERE event_key=?',(outcome,key))

def database_path():
    if os.environ.get('DVK_MORELOGIN')=='1':
        from morelogin_common import root_directory
        return root_directory()/'shared.sqlite3'
    from assistant_store import data_directory
    return data_directory()/'assistant.sqlite3'

def bounds(command,now=None):
    local=now or datetime.now().astimezone()
    day=local.date()
    if command=='/yesterday':first,last=day-timedelta(days=1),day
    elif command=='/today':first,last=day,day+timedelta(days=1)
    elif command=='/week':first,last=day-timedelta(days=6),day+timedelta(days=1)
    elif command=='/month':first,last=day-timedelta(days=29),day+timedelta(days=1)
    else:raise ValueError('Unknown period')
    def stamp(d):
        value=datetime.combine(d,time.min)
        if now is not None:value=value.replace(tzinfo=now.tzinfo)
        return value.astimezone(timezone.utc).isoformat(timespec='seconds')
    return stamp(first),stamp(last)

COMMANDS=('/today','/yesterday','/week','/month','/city')

def _render_contacts(command,path=None,now=None):
    if command not in COMMANDS:raise ValueError('Unknown command')
    path=database_path() if path is None else Path(path)
    label={'/today':'Сегодня','/yesterday':'Вчера','/week':'Последние 7 дней','/month':'Последние 30 дней','/city':'Города поиска — всё время'}[command]
    title='📊 '+label+'\n'
    if not path.exists():return title+'Новых событий пока нет. Учёт начнётся после обновления.'
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='global_contact_statistics'").fetchone():
            return title+'Новых событий пока нет. Старые контакты задним числом не учитываются.'
        if command=='/city':
            rows=db.execute('SELECT city,COUNT(*) FROM global_contact_statistics WHERE phone_count>0 GROUP BY city ORDER BY COUNT(*) DESC,city LIMIT 20').fetchall()
            total=db.execute('SELECT COUNT(*) FROM global_contact_statistics WHERE phone_count>0').fetchone()[0]
            return title+'С номером: '+str(total)+'\n'+('\n'.join(str(i+1)+'. '+c+' — '+str(n) for i,(c,n) in enumerate(rows)) or 'Пока нет номеров.')+'\nТоп-20. Это город поиска при знакомстве, не подтверждённое место жительства.'
        first,last=bounds(command,now)
        row=db.execute('''SELECT COUNT(*),COALESCE(SUM(phone_count>0),0),COALESCE(SUM(handle_count>0),0),
          COALESCE(SUM(telegram='accepted'),0),COALESCE(SUM(telegram='unknown'),0)
          FROM global_contact_statistics WHERE received_at>=? AND received_at<?''',(first,last)).fetchone()
    return title+f'Контакт дали: {row[0]} собеседников\n📱 С номером: {row[1]}\n💬 С ником/ссылкой: {row[2]}\n✅ Telegram принял: {row[3]}\n❔ Отправка не подтверждена: {row[4]}\nДни — по часовому поясу компьютера. Учёт с обновления, без старой истории.'



def greeting_reserved(db,account,peer,now=None):
    initialize(db)
    key=peer_key(account,peer)
    row=db.execute('SELECT city FROM global_peer_city WHERE peer_key=?',(key,)).fetchone()
    city=row[0] if row and valid_city(row[0]) else 'Неизвестен'
    stamp=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec='seconds')
    db.execute("INSERT OR IGNORE INTO global_greeting_statistics VALUES(?,?,?,'reserved-unknown')",(key,stamp,city))


def greeting_finished(db,account,peer,status):
    if status not in ('handler-returned-unconfirmed','attempted-unknown','not-invoked'):raise ValueError('Invalid greeting status')
    db.execute("UPDATE global_greeting_statistics SET status=? WHERE event_key=? AND status='reserved-unknown'",(status,peer_key(account,peer)))


def greeting_summary(command,path,now=None):
    path=Path(path)
    if not path.exists():return 'Первые приветствия: 0; учёт с обновления.'
    current=(now or datetime.now().astimezone()).astimezone(timezone.utc)
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='global_greeting_statistics'").fetchone():
            return 'Первые приветствия: учёт начнётся после обновления, без пересчёта старых резервов.'
        if command=='/city':
            row=db.execute("SELECT MIN(started_at) FROM global_greeting_statistics").fetchone()
            first=row[0] or current.isoformat(timespec='seconds');last=current.isoformat(timespec='seconds')
        else:first,last=bounds(command,now)
        confirmed,unknown=db.execute("""SELECT COALESCE(SUM(status='handler-returned-unconfirmed'),0),
          COALESCE(SUM(status IN ('reserved-unknown','attempted-unknown')),0)
          FROM global_greeting_statistics WHERE started_at>=? AND started_at<?""",(first,last)).fetchone()
        end=min(current,datetime.fromisoformat(last));begin=datetime.fromisoformat(first)
        hours=max(0.,(end-begin).total_seconds()/3600)
        average=confirmed/hours if hours>0 else 0.
        cities=[]
        if command=='/city':
            cities=db.execute("SELECT city,COUNT(*) FROM global_greeting_statistics WHERE status='handler-returned-unconfirmed' GROUP BY city ORDER BY COUNT(*) DESC,city LIMIT 10").fetchall()
    text=f'Новым собеседникам написано: {confirmed}\nНеизвестный исход первого приветствия: {unknown}\nСреднее новых за календарный час: {average:.2f}'
    if cities:text+='\nПервые приветствия по городам поиска:\n'+'\n'.join(c+' — '+str(n) for c,n in cities)
    return text+'\nСчитаются первые приветствия с возвратом обработчика, не доказанная доставка. Среднее — за прошедшие часы периода, включая простои; не сумма скоростей портов. Учёт с обновления и из проверенных записей журнала.'


def render(command,path=None,now=None):
    if command not in COMMANDS:raise ValueError('Unknown command')
    path=database_path() if path is None else Path(path)
    return _render_contacts(command,path,now)+'\n\n'+greeting_summary(command,path,now)



def greeting_backfill(db):
    """Import only explicit greeting journal statuses/timestamps, never infer delivery."""
    db.execute('CREATE TABLE IF NOT EXISTS inbox_reply_policy(key TEXT PRIMARY KEY,value INTEGER NOT NULL)')
    if db.execute("SELECT 1 FROM inbox_reply_policy WHERE key='greeting-statistics-v1' AND value=1").fetchone():return
    for account,peer,status,created in db.execute('SELECT account,peer,status,created_at FROM manual_actions').fetchall():
        if status not in ('reserved-unknown','handler-returned-unconfirmed','attempted-unknown','not-invoked'):continue
        try:
            stamp=datetime.fromisoformat(created)
            if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
        except (ValueError,TypeError):continue
        greeting_reserved(db,account,peer,now=stamp)
        if status!='reserved-unknown':greeting_finished(db,account,peer,status)
    db.execute("INSERT OR REPLACE INTO inbox_reply_policy VALUES('greeting-statistics-v1',1)")
