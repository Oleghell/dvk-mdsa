"""MuMu reply lifetime from durable greeting reservation, never message-ID order.

Opt-in at worker startup. Exclusions are persistent, port/account scoped and do
not alter reservations, draft hashes, receipts, peer claims or contact outboxes.
"""
import math
import time

HOUR = 3600

def tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS inbox_reply_policy(key TEXT PRIMARY KEY,value INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS inbox_reply_exclusions(account TEXT,peer TEXT,reason TEXT NOT NULL,PRIMARY KEY(account,peer))')

def enable(store, *, new_only=False):
    with store.connection() as db:
        tables(db)
        db.execute("INSERT OR REPLACE INTO inbox_reply_policy VALUES('enabled',1)")
        if new_only:
            # SQL sources exist only after their corresponding engine initialized.
            for table in ('manual_actions','guided_bindings','chain_dialogs'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    db.execute('INSERT OR IGNORE INTO inbox_reply_exclusions SELECT account,peer,? FROM '+table,('new-start-excluded',))

def active(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inbox_reply_policy'").fetchone()
                and db.execute("SELECT 1 FROM inbox_reply_policy WHERE key='enabled' AND value=1").fetchone())

def exclusion(db, who, now):
    old=db.execute('SELECT reason FROM inbox_reply_exclusions WHERE account=? AND peer=?',(who['account'],who['peer'])).fetchone()
    if old:return old[0]
    row=db.execute("SELECT CAST(strftime('%s',created_at) AS INTEGER) FROM manual_actions WHERE account=? AND peer=?",(who['account'],who['peer'])).fetchone()
    created=row[0] if row else None
    code=('reply-age-unverified' if type(created) is not int or not math.isfinite(now) or now<created
          else 'reply-window-expired' if now-created>=HOUR else None)
    if code:db.execute('INSERT OR IGNORE INTO inbox_reply_exclusions VALUES(?,?,?)',(who['account'],who['peer'],code))
    return code

def reason(store, who, *, clock=time.time):
    with store.connection() as db:
        return exclusion(db,who,clock()) if active(db) else None

def eligible(store, rows):
    if not rows:return []
    # One transaction for the entire list, not one SQLite write-lock per peer.
    with store.connection() as db:
        if not active(db):return list(rows)
        now=time.time()
        return [who for who in rows if exclusion(db,who,now) is None]
