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
    # This classifies an interrupted READ, never proves its identity or content.
    # Only the fixed reader's authored stages/scalars are accepted. A fresh read
    # starts from scratch with expected identity; local deferral still needs an
    # independently verified SAME-chat Back. Identity/schema errors never match.
    if not isinstance(value, dict):return False
    phase=value.get("read_checkpoint")
    scalar=value.get("scalar_checkpoint")
    identity_scalar=scalar in ("account-id", "peer-id", "chat-id")
    message_scalar=scalar in ("message-id", "message-sender-id", "message-chat-id")
    phase_ok=(phase in ("identity", "model", "manager", "loaded-flag", "count", "recheck", "sample") and identity_scalar
              or phase == "last-message" and (identity_scalar or message_scalar)
              # read_latest rechecks the last message header AFTER collection,
              # at sample. Report 137 stopped here with message-chat-id. This
              # is still an interrupted read, never identity or send proof.
              or phase == "sample" and message_scalar
                 and type(value.get("message_slot")) is int
                 and 0 <= value["message_slot"] < MAX_MESSAGES)
    # A budget expiry during initial ID getters is an interrupted observation,
    # NOT an identity mismatch. Retry only the fixed reader with the SAME expected
    # identity, from scratch; a later Back still independently checks that ID.
    # A getter can return a positive scalar before the frame expires in another
    # getter/recheck. It is still an INCOMPLETE initial observation, not a bound
    # identity. Permit the same bounded read-only recovery as for not-read.
    initial_ids=(value.get('identity_checkpoint')=='initial-ids'
        and phase=='identity' and scalar in ('account-id','peer-id','chat-id')
        and value.get('scalar_state') in ('not-read', 'positive'))
    # IDs were read, but the frame expired before IsActual/IsDraft finished.
    # This is not identity proof: only a new SAME-bound read or verified Back
    # can proceed. In particular, identity-not-bound still never matches.
    actual_ids=(value.get('identity_checkpoint')=='actual-server-chat'
        and phase=='identity' and scalar=='chat-id'
        and value.get('scalar_state')=='positive')
    # Report 247: the fixed reader permits a negative *own-message* ChatId
    # only with independent peer anchoring. A frame may expire before that
    # anchoring/recheck completes. This is NO identity/content proof: discard
    # the sample, then retry only the SAME-bound reader under existing limits.
    local_own_interrupted=(phase in ('last-message','sample')
        and scalar=='message-chat-id' and value.get('scalar_state')=='negative'
        and value.get('identity_checkpoint')=='recheck'
        and value.get('message_direction')=='own'
        and value.get('message_kind') in ('text','non-text')
        and type(value.get('message_slot')) is int
        and 0 <= value['message_slot'] < MAX_MESSAGES)
    return (value.get("error") in ("frame-budget", "transition-timeout")
        and value.get("stage") == "navigation-stopped"
        and value.get("metadata_checkpoint") == "ready"
        and (initial_ids or actual_ids or phase_ok and value.get("identity_checkpoint") == "recheck")
        and (value.get("scalar_state") in ("positive", "not-read") or local_own_interrupted)
        and value.get("wait_reason") in ("none", "not-checked")
        and type(value.get("message_slot")) is int
        and -1 <= value["message_slot"] < MAX_MESSAGES)


def verified_loading(value):
    return (isinstance(value, dict)
        and value.get('error') == 'history-not-ready'
        and value.get('stage') == 'navigation-stopped'
        and value.get('metadata_checkpoint') == 'ready'
        and value.get('read_checkpoint') in ('recheck', 'last-message')
        and value.get('identity_checkpoint') == 'recheck'
        and value.get('scalar_checkpoint') == 'chat-id'
        and value.get('scalar_state') == 'positive'
        and value.get('wait_reason') in ('history-loading','history-not-loaded'))


def initialize(store):
    store.ensure_tables('''CREATE TABLE IF NOT EXISTS inbox_history_deferrals(
            account TEXT NOT NULL,peer TEXT NOT NULL,chat TEXT NOT NULL,
            retry_after REAL NOT NULL,PRIMARY KEY(account,peer))''')


def instant(clock):
    value=clock()
    if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid cooldown clock')
    return value


def eligible(store, attention, unread, *, clock=time.time):
    now=instant(clock)
    with store.read_connection() as db:
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
    with store.read_connection() as db:
        row=db.execute('SELECT 1 FROM inbox_history_deferrals WHERE account=? AND peer=?',(who['account'],who['peer'])).fetchone()
    if row is None:return
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


class HistoryMessageInvalid(Exception):
    """Fixed reader rejected a message; contents remain unusable for sending."""


def verified_message_invalid(value):
    """Classify a local rejection, NOT proof of identity or a successful send.

    Native SAME-chat Back must independently verify identity and destination.
    Missing/foreign identity, transport, schema and arbitrary errors never match.
    """
    return (isinstance(value, dict)
        and value.get('error') == 'message-invalid'
        and value.get('stage') == 'navigation-stopped'
        and value.get('metadata_checkpoint') == 'ready'
        and value.get('read_checkpoint') == 'last-message'
        and value.get('identity_checkpoint') == 'recheck'
        and value.get('scalar_checkpoint') in ('chat-id','message-id','message-sender-id','message-chat-id')
        and value.get('scalar_state') == 'positive'
        and value.get('wait_reason') == 'none'
        and value.get('message_kind') in ('text','non-text')
        and value.get('message_direction') in ('own','not-own')
        and type(value.get('message_slot')) is int
        and 0 <= value['message_slot'] < MAX_MESSAGES)
