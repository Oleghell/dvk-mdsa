"""Atomic shared city allocation. No database transaction spans native UI work.

Pending reservations survive failures/restarts: an unknown city transition is
never guessed or repeated. Explicit history clearing releases this port only.
"""
import re
import secrets
import search_city
from assistant_store import StateError


def initialize(db):
    # Migrate old sessions exactly once; future selections commit claims and
    # local session together. Never reclaim from stale history on restart.
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='mumu_city_claims'").fetchone():return
    db.execute('CREATE TABLE IF NOT EXISTS mumu_city_claims(city TEXT PRIMARY KEY,device TEXT NOT NULL,state TEXT NOT NULL,token TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS mumu_city_used(city TEXT PRIMARY KEY)')
    names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for name in names:
        match=re.fullmatch(r'(?:m([1-9][0-9]{3,4})__)?search_session',name)
        if not match:continue
        device=match[1] or '5563'
        # Never overwrite a live/pending claim using stale per-port history.
        if db.execute('SELECT 1 FROM mumu_city_claims WHERE device=?',(device,)).fetchone():continue
        row=db.execute('SELECT value FROM '+name+' WHERE key=?',('city',)).fetchone()
        if row:
            city=search_city.normalize_city(row[0])
            db.execute('INSERT OR IGNORE INTO mumu_city_claims VALUES(?,?,?,?)',(city,device,'active','legacy'))
            db.execute('INSERT OR IGNORE INTO mumu_city_used VALUES(?)',(city,))


def owns(store, city):
    if not city:return False
    with store.connection() as db:
        rows=db.execute('SELECT city,state FROM mumu_city_claims WHERE device=?',(str(store.device_port),)).fetchall()
    return rows==[(search_city.normalize_city(city),'active')]


def reserve(store, cities):
    allowed={search_city.normalize_city(c):c for c in search_city.check_cities(list(cities))}
    device=str(store.device_port);token=secrets.token_hex(16)
    with store.connection() as db:
        rows=db.execute('SELECT city,device,state FROM mumu_city_claims').fetchall()
        if any(d==device and state=='pending' for _,d,state in rows):
            raise StateError('city-reservation-unresolved')
        occupied={c for c,_,_ in rows}
        free=[c for c in allowed if c not in occupied]
        if not free:raise StateError('city-pool-exhausted')
        used={r[0] for r in db.execute('SELECT city FROM mumu_city_used')}
        fresh=[c for c in free if c not in used]
        if not fresh:
            db.execute('DELETE FROM mumu_city_used');fresh=free;used=set()
        # Leave enough free alternatives for other configured ports. Reserve at
        # most six exact native query candidates, never the entire city list.
        from mumu_common import load_ports,DEFAULT_PORTS,MumuError
        try:count=len(load_ports())
        except MumuError:count=len(DEFAULT_PORTS)
        secrets.SystemRandom().shuffle(fresh)
        candidates=fresh[:min(6,max(1,len(free)//max(1,count)))]
        for city in candidates:
            db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',(city,device,'pending',token))
        current=[c for c,d,state in rows if d==device and state=='active' and c in allowed]
        # Native needs the old city name for strict diagnostics. It is already
        # reserved by this port, so it is also a safe alternative if UI moved.
        selected=candidates+current[:max(0,6-len(candidates))]
    return token,[allowed[c] for c in selected],[allowed[c] for c in used if c in allowed]


def complete(store, token, cities, value):
    search_city.validate_next(value,cities)
    n=value['navigation']
    if n['stage']!='navigation-ready' or n['city_verified'] is not True or n['online_verified'] is not True:
        raise StateError('city-not-verified')
    city=search_city.normalize_city(n['city_selected_name']);device=str(store.device_port)
    with store.connection() as db:
        row=db.execute('SELECT device,state,token FROM mumu_city_claims WHERE city=?',(city,)).fetchone()
        pending=db.execute("SELECT 1 FROM mumu_city_claims WHERE device=? AND token=? AND state='pending'",(device,token)).fetchone()
        if not pending or not row or row[0]!=device or row[1] not in ('active','pending') or row[1]=='pending' and row[2]!=token:
            raise StateError('city-not-verified')
        db.execute('DELETE FROM mumu_city_claims WHERE device=?',(device,))
        db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',(city,device,'active',token))
        db.execute('INSERT OR IGNORE INTO mumu_city_used VALUES(?)',(city,))
        db.execute('CREATE TABLE IF NOT EXISTS search_session(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute('INSERT INTO search_session VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('city',n['city_selected_name']))


def change(store, cities, capture):
    token,allowed,used=reserve(store,cities)
    # Exceptions deliberately leave pending claims held. No retry/TTL.
    value=capture(allowed,used)
    search_city.validate_next(value,allowed)
    if value['navigation']['stage']=='navigation-ready':complete(store,token,allowed,value)
    return value,allowed
