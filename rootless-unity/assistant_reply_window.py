"""Explicit reply exclusions; greeting age is NEVER incoming-message age.

The current bound reader has no verified incoming sent_at. Therefore no age
expiry is enforced until that source exists. In particular, do not substitute
first observation time, a message ID, collection position or greeting time.
Manual/terminal peer bans live elsewhere and are never removed here.
"""
import time

HOUR = 3600  # Requested incoming-age limit; NOT active without verified sent_at.
LEGACY_AGE_REASONS = ('reply-window-expired', 'reply-age-unverified')


def tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS inbox_reply_policy(key TEXT PRIMARY KEY,value INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS inbox_reply_exclusions(account TEXT,peer TEXT,reason TEXT NOT NULL,PRIMARY KEY(account,peer))')


def clear_legacy_age_exclusions(db):
    # Only this port's obsolete age-only exclusions. Never touch new-start,
    # terminal states, send journals, receipts, reservations or mumu_peer_blocks.
    db.execute('DELETE FROM inbox_reply_exclusions WHERE reason IN (?,?)', LEGACY_AGE_REASONS)


def enable(store, *, new_only=False):
    with store.connection() as db:
        tables(db)
        clear_legacy_age_exclusions(db)
        db.execute("INSERT OR REPLACE INTO inbox_reply_policy VALUES('enabled',1)")
        if new_only:
            for table in ('manual_actions','guided_bindings','chain_dialogs'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    db.execute('INSERT OR IGNORE INTO inbox_reply_exclusions SELECT account,peer,? FROM '+table,('new-start-excluded',))


def active(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inbox_reply_policy'").fetchone()
                and db.execute("SELECT 1 FROM inbox_reply_policy WHERE key='enabled' AND value=1").fetchone())


def exclusion(db, who, now=None):
    old=db.execute('SELECT reason FROM inbox_reply_exclusions WHERE account=? AND peer=?',(who['account'],who['peer'])).fetchone()
    if old and old[0] in LEGACY_AGE_REASONS:
        # Also migrate databases already enabled by an earlier build, before
        # worker.enable() is called. A fresh peer reply must not stay hidden.
        db.execute('DELETE FROM inbox_reply_exclusions WHERE account=? AND peer=? AND reason IN (?,?)',
                   (who['account'],who['peer'],*LEGACY_AGE_REASONS))
        return None
    return old[0] if old else None


def reason(store, who, *, clock=time.time):
    # clock retained for API compatibility, never used as message-time evidence.
    with store.connection() as db:
        return exclusion(db,who) if active(db) else None


def eligible(store, rows):
    if not rows:return []
    with store.connection() as db:
        if not active(db):return list(rows)
        # Remove only obsolete age rules; terminal/manual/new-start exclusions
        # remain authoritative. Read their keys once, not once per dialog while
        # holding the shared PostgreSQL transaction lock.
        clear_legacy_age_exclusions(db)
        blocked=set(db.execute('SELECT account,peer FROM inbox_reply_exclusions'))
        return [who for who in rows if (who['account'],who['peer']) not in blocked]
