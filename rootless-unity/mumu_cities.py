"""Atomic shared city allocation. No database transaction spans native UI work.

Pending reservations survive failures/restarts: an unknown city transition is
never guessed or repeated. Read-only verified reconciliation releases this port only.
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
        current=[c for c,d,state in rows if d==device and state=='active' and c in allowed]
        # Native sees only this port's reserved candidates/current city. Its
        # used-history MUST be a subset of that same list, not the whole pool.
        selected=candidates+current[:max(0,6-len(candidates))]
        checked,seen=search_city.rotation_inputs(
            [allowed[c] for c in selected], [allowed[c] for c in selected if c in used])
        # Complete the pure argument preflight BEFORE committing any new claim.
        for city in candidates:
            db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',(city,device,'pending',token))
    return token,checked,seen


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
            raise StateError('city-claim-changed')
        db.execute('DELETE FROM mumu_city_claims WHERE device=?',(device,))
        db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',(city,device,'active',token))
        db.execute('INSERT OR IGNORE INTO mumu_city_used VALUES(?)',(city,))
        db.execute('CREATE TABLE IF NOT EXISTS search_session(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute('INSERT INTO search_session VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('city',n['city_selected_name']))


def remember_navigation(value,diagnostics):
    """Call only after strict validate_next; preserve evidence BEFORE DB CAS."""
    if diagnostics is None:return
    from navigation_root_diagnostic import extract
    n=value['navigation']
    fields=('stage','error','phase','frames','managed_calls','city_checkpoint','city_prepare',
        'city_visible_rows','city_total_rows','city_scan_samples','city_matches','city_select_attempted',
        'city_select_completed','city_verified','online_verified','return_verified',
        'open_attempted','open_completed','city_open_attempted','city_open_completed',
        'city_query_attempted','city_query_text_completed','city_query_completed','apply_attempted','apply_completed',
        'settings_checkpoint','city_transition_overruns','city_read_budget_retries','city_queries_started',
        'city_query_text_returns','city_query_returns','city_candidates_skipped','city_result_waits')
    diagnostics['last_city_navigation']={k:n[k] for k in fields if k in n}
    diagnostics['last_city_navigation']['root_probe']=extract(value)
    if n['stage']!='navigation-ready':diagnostics['last_error']=n['error']


def change(store, cities, capture, *, diagnostics=None):
    token,allowed,used=reserve(store,cities)
    # Exceptions deliberately leave pending claims held. No retry/TTL.
    value=capture(allowed,used)
    search_city.validate_next(value,allowed)
    remember_navigation(value,diagnostics)
    if value['navigation']['stage']=='navigation-ready':complete(store,token,allowed,value)
    return value,allowed


def recover_pending(store,cities,reader,*,cancelled=lambda:False,wait=None,progress=lambda _:None,diagnostics=None):
    """Observe actual search state, then reconcile ONLY this port with a CAS.

    No DB transaction spans the read. Transient screen/connection failures wait
    without releasing claims; malformed proof, identity and DB errors fail hard.
    Returns a city only when it is owned, configured, OnlineOnly and not nearby.
    """
    import time
    from search_city_state import validate
    from one_chat_device import ReadStopped,safe_read_failure
    from startup_failure import clean,recoverable_adb
    def cancellable_wait(delay):
        deadline=time.monotonic()+delay
        while not cancelled():
            remaining=deadline-time.monotonic()
            if remaining<=0:return False
            time.sleep(min(.1,remaining))
        return True
    wait=wait or cancellable_wait
    allowed={search_city.normalize_city(c) for c in search_city.check_cities(list(cities))}
    device=str(store.device_port);attempt=0
    retry={'wrong-screen','unexpected-screen','screen-not-ready','frame-limit','frame-budget',
           'call-limit','transition-timeout','observer-stopped'}
    while not cancelled():
        with store.connection() as db:
            expected=sorted(db.execute('SELECT city,state,token FROM mumu_city_claims WHERE device=?',(device,)).fetchall())
        if not any(state=='pending' for _,state,_ in expected):return None
        progress('Резерв города • автоматически проверяю фактический экран MuMu. Отправки не выполняются.')
        try:
            value=validate(reader())
        except Exception as error:
            failure=safe_read_failure(error) if isinstance(error,ReadStopped) else None
            preparation=clean(getattr(error,'_dvk_failure',None))
            city_transport=(getattr(error,'_dvk_city_readonly_transport',False) is True and preparation
                and preparation['stage'] in {'gadget-connect','gadget-process','gadget-attach','script-create','script-load','runtime-check','script-run'}
                and preparation['error_type'] in {'TransportError','ServerNotRunningError','TimedOutError'})
            if diagnostics is not None and preparation:
                diagnostics['last_city_recovery']=dict(state_verified=False,last_preparation_failure=preparation)
            if not (failure and failure.get('error') in retry or recoverable_adb(preparation) or city_transport):
                raise
            value=None
        if value is not None:
            n=value['navigation']
            from navigation_root_diagnostic import extract
            if diagnostics is not None:
                diagnostics['last_city_recovery']=dict(stage=n['stage'],error=n['error'],phase=n['phase'],
                    state_samples=n['state_samples'],state_verified=n['state_verified'],
                    frames=n['frames'],managed_calls=n['managed_calls'],root_probe=extract(value))
            # An early root timeout/window-not-ready has no navigation error:
            # it is NOT a new city transition and must not discard its claim.
            root_wait=(n['stage']=='not-attempted' and n['error']=='none'
                and value['stage'] in {'metadata-not-ready','runtime-not-ready','window-not-ready','callback-timeout'})
            if n['state_verified'] is not True:
                if n['error'] not in retry and not root_wait:raise StateError('city-reservation-unresolved')
            else:
                if cancelled():raise StateError('cancelled')
                name=n['observed_city'];city=search_city.normalize_city(name)
                with store.connection() as db:
                    actual=sorted(db.execute('SELECT city,state,token FROM mumu_city_claims WHERE device=?',(device,)).fetchall())
                    if actual!=expected:continue # A clear/new claim raced the observation; never overwrite it.
                    owner=db.execute('SELECT device FROM mumu_city_claims WHERE city=?',(city,)).fetchone()
                    db.execute('CREATE TABLE IF NOT EXISTS search_session(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                    db.execute('DELETE FROM mumu_city_claims WHERE device=?',(device,))
                    if owner and owner[0]!=device:
                        # A legacy duplicate/current city belongs to another
                        # port. Do not steal it or use profiles there; rotate.
                        db.execute('DELETE FROM search_session WHERE key=?',('city',))
                        progress('Резерв проверен • текущий город занят другим портом, выбираю свободный.')
                        return None
                    db.execute('INSERT INTO mumu_city_claims VALUES(?,?,?,?)',(city,device,'active',secrets.token_hex(16)))
                    db.execute('INSERT OR IGNORE INTO mumu_city_used VALUES(?)',(city,))
                    db.execute('INSERT INTO search_session VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('city',name))
                if n['online_only'] and not n['by_distance'] and city in allowed:
                    progress('Резерв города восстановлен автоматически • продолжаю текущий поиск.')
                    return name
                progress('Резерв проверен • выбираю настроенный город и включаю «Только онлайн».')
                return None
        attempt+=1
        progress('Экран города ещё не подтверждён • жду и повторяю только чтение; другие порты работают.')
        if wait(min(5,.5*2**min(attempt-1,4))) or cancelled():raise StateError('cancelled')
    raise StateError('cancelled')
