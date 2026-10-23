"""Bounded, identity-verified history loading; durable peer-local retry cooldown."""
import math
import time
from one_chat_probe import identity
from chat_limits import MAX_MESSAGES

WAIT_SECONDS = 15.0
WAIT_INTERVAL = 1.0
MAX_READ_ATTEMPTS = 16
COOLDOWN_SECONDS = 60.0
BUDGET_READ_ATTEMPTS = 4
BUDGET_RETRY_INTERVAL = 0.5

class HistoryWaitExpired(Exception):
    """Only the fixed bound reader's verified loading state may raise this."""


class HistoryReadBudgetExpired(Exception):
    """Read-only frame budget exhausted; SAME-chat back is still mandatory."""


def verified_read_budget(value):
    # Only authored read-budget failures, including an unfinished identity
    # recheck. NEVER accept this as a verified identity or permission to send.
    # Fresh reads restart all checks; local deferral requires a verified SAME-chat back.
    return (isinstance(value, dict)
        and value.get("error") == "frame-budget"
        and value.get("stage") == "navigation-stopped"
        and value.get("metadata_checkpoint") == "ready"
        and ((value.get("read_checkpoint") == "last-message"
                and value.get("scalar_checkpoint") in ("message-id", "message-sender-id", "message-chat-id"))
             or (value.get("read_checkpoint") in ("identity", "recheck")
                and value.get("scalar_checkpoint") in ("account-id", "peer-id", "chat-id")))
        and value.get("identity_checkpoint") == "recheck"
        and value.get("scalar_state") == "positive"
        and value.get("wait_reason") == "none"
        and type(value.get("message_slot")) is int
        and 0 <= value["message_slot"] < MAX_MESSAGES)


def verified_loading(value):
    return (isinstance(value, dict)
        and value.get('error') == 'history-not-ready'
        and value.get('stage') == 'navigation-stopped'
        and value.get('metadata_checkpoint') == 'ready'
        and value.get('read_checkpoint') == 'recheck'
        and value.get('identity_checkpoint') == 'recheck'
        and value.get('scalar_checkpoint') == 'chat-id'
        and value.get('scalar_state') == 'positive'
        and value.get('wait_reason') in ('history-loading','history-not-loaded'))


def initialize(store):
    with store.connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS inbox_history_deferrals(
            account TEXT NOT NULL,peer TEXT NOT NULL,chat TEXT NOT NULL,
            retry_after REAL NOT NULL,PRIMARY KEY(account,peer))''')


def instant(clock):
    value=clock()
    if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid cooldown clock')
    return value


def eligible(store, attention, unread, *, clock=time.time):
    now=instant(clock)
    with store.connection() as db:
        # Only journal-local identities/timestamps; no message bodies or keys.
        blocked=set(db.execute('SELECT account,peer FROM inbox_history_deferrals WHERE retry_after>?',(now,)))
    filtered=lambda items:[x for x in items if (x['account'],x['peer']) not in blocked]
    skipped={(x['account'],x['peer']) for x in attention+unread if (x['account'],x['peer']) in blocked}
    return filtered(attention),filtered(unread),len(skipped)


def defer(store, who, *, clock=time.time):
    who=identity(who)
    until=instant(clock)+COOLDOWN_SECONDS
    with store.connection() as db:
        db.execute('''INSERT INTO inbox_history_deferrals VALUES(?,?,?,?)
            ON CONFLICT(account,peer) DO UPDATE SET chat=excluded.chat,retry_after=excluded.retry_after''',
            (who['account'],who['peer'],who['chat'],until))


def clear(store, who):
    who=identity(who)
    with store.connection() as db:
        db.execute('DELETE FROM inbox_history_deferrals WHERE account=? AND peer=?',
                   (who['account'],who['peer']))


class HistorySnapshotTooLarge(Exception):
    """Bound history exceeds the verified snapshot contract; never truncate."""

def verified_oversized(value):
    return (isinstance(value,dict) and value.get('error')=='snapshot-too-large'
        and value.get('stage')=='navigation-stopped'
        and value.get('metadata_checkpoint')=='ready'
        and value.get('read_checkpoint')=='last-message'
        and value.get('identity_checkpoint')=='recheck'
        and value.get('scalar_checkpoint') in ('chat-id','message-chat-id')
        and value.get('scalar_state')=='positive'
        and value.get('wait_reason')=='none')
