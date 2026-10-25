"""Only verified contact receipt or explicit refusal creates a global ban.

A local closed chain, timeout, profile visit or greeting is not such evidence.
All writes use the caller's transaction; contact data/bodies never enter this table.
"""
import re

REASONS={'contact-received','contact-refused'}

def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS mumu_peer_blocks(
      peer TEXT PRIMARY KEY,reason TEXT NOT NULL,device TEXT NOT NULL,
      account TEXT NOT NULL,chat TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def record(db,who,reason,device):
    if reason not in REASONS:raise ValueError('Not a terminal contact outcome')
    db.execute('INSERT OR IGNORE INTO mumu_peer_blocks(peer,reason,device,account,chat) VALUES(?,?,?,?,?)',
        (who['peer'],reason,device,who['account'],who['chat']))


def backfill_contacts(db):
    # Existing DONE is the engine's accepted self-shared-contact state. An
    # encrypted receipt is also evidence, independent of Telegram delivery.
    # DECLINED is ambiguous (budget/off-topic/availability); never infer refusal.
    names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in sorted(names):
        match=re.fullmatch(r'(?:m([0-9]{4,5})__)?chain_dialogs',table)
        if not match:continue
        device=match[1] or '5563';prefix=table[:-len('chain_dialogs')]
        outbox=prefix+'chain_contact_outbox'
        condition="stage='done'"
        if outbox in names:condition+=" OR EXISTS(SELECT 1 FROM "+outbox+" o WHERE o.chat=c.chat)"
        for account,peer,chat in db.execute('SELECT account,peer,chat FROM '+table+' c WHERE '+condition).fetchall():
            record(db,dict(account=account,peer=peer,chat=chat),'contact-received',device)


def explicit_refusal(messages,*,requested):
    # Use the existing verified refusal inputs, but not absence of apps or an
    # off-topic policy closure. Quotes/questions are not fresh contact refusals.
    from conversation_engine import normalized,REFUSAL
    from assistant_contact_intent import visible,private_refusal,stay_here
    from assistant_contact_followup import BARE_STAY,STAY,EXTENDED_STAY
    for message in messages:
        text=visible(message.get('text'));plain=normalized(text)
        if not plain:continue
        if REFUSAL.search(plain):return True  # explicit do-not-contact also wins
        if requested and (private_refusal(text) or stay_here(text)
            or BARE_STAY.fullmatch(plain) or STAY.fullmatch(plain) or EXTENDED_STAY.fullmatch(plain)
            or re.fullmatch(r'(?:нет|нету|не хочу|не надо)[.!?,)\s]*',plain)):
            return True
    return False


from assistant_store import StateError

class PeerCommunicationBlocked(StateError):
    """A verified global terminal outcome forbids further peer messages."""
    def __init__(self):super().__init__('peer-contact-blocked')


def ensure_communication_allowed(store,who,*,db=None):
    """Deny-only guard. No permits, replay, state reset or identity guessing.

    Reservation and adapter-entry callers pass their current IMMEDIATE SQLite
    transaction so a previously committed outcome cannot be missed there.
    A send already entered before a concurrent outcome cannot be recalled.
    """
    if getattr(store,'mumu_shared_claims',False) is not True:return
    from one_chat_probe import identity
    who=identity(who)
    if db is None:
        with store.connection() as connection:
            return ensure_communication_allowed(store,who,db=connection)
    if db.execute('SELECT 1 FROM mumu_peer_blocks WHERE peer=?',(who['peer'],)).fetchone() is not None:
        raise PeerCommunicationBlocked()
