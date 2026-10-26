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
    with store.read_connection() as db:
        if not active(db):return None
        row=db.execute('SELECT reason FROM inbox_reply_exclusions WHERE account=? AND peer=?',(who['account'],who['peer'])).fetchone()
        if not row or row[0] not in LEGACY_AGE_REASONS:return row[0] if row else None
    # Only an actual obsolete age exclusion needs a writer. Re-read under lock
    # so a newer new-start exclusion can never be cleared using stale evidence.
    with store.connection() as db:
        return exclusion(db,who) if active(db) else None


def eligible_groups(store,*groups):
    """One fresh exclusion snapshot for the pass, not a transaction per group."""
    if not any(groups):return tuple([] for _ in groups)
    with store.read_connection() as db:
        if not active(db):return tuple(list(rows) for rows in groups)
        obsolete=db.execute('SELECT 1 FROM inbox_reply_exclusions WHERE reason IN (?,?) LIMIT 1',LEGACY_AGE_REASONS).fetchone()
        if not obsolete:blocked=set(db.execute('SELECT account,peer FROM inbox_reply_exclusions'))
    if obsolete:
        with store.connection() as db:
            clear_legacy_age_exclusions(db)
            blocked=set(db.execute('SELECT account,peer FROM inbox_reply_exclusions'))
    return tuple([who for who in rows if (who['account'],who['peer']) not in blocked] for rows in groups)


def eligible(store,rows):
    return eligible_groups(store,rows)[0]
