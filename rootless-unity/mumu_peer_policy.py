"""Only verified contact receipt or explicit refusal creates a global ban.

A local closed chain, timeout, profile visit or greeting is not such evidence.
All writes use the caller's transaction; contact data/bodies never enter this table.
"""
from cloud_database import connect as primary_connect, readonly as primary_readonly, available as primary_available
import re

REASONS={'contact-received','contact-refused','manual-block'}

def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS mumu_peer_blocks(
      peer TEXT PRIMARY KEY,reason TEXT NOT NULL,device TEXT NOT NULL,
      account TEXT NOT NULL,chat TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    db.execute('CREATE TABLE IF NOT EXISTS mumu_manual_silences(peer TEXT PRIMARY KEY)')


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
        # Set-based backfill: do not hold the shared PostgreSQL write lock
        # across one network round-trip for every historical contact.
        # SQLite OR IGNORE skipped NOT NULL violations; preserve that behavior
        # explicitly because PG ON CONFLICT only skips uniqueness conflicts.
        db.execute("INSERT OR IGNORE INTO mumu_peer_blocks(peer,reason,device,account,chat) "
            "SELECT c.peer,'contact-received',?,c.account,c.chat FROM "+table+
            " c WHERE ("+condition+") AND c.peer IS NOT NULL AND c.account IS NOT NULL AND c.chat IS NOT NULL",(device,))


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


def _operator_led(db, who):
    """v1.3.86: a durable operator binding proves the operator himself started
    and keeps leading this dialog. An AUTOMATIC terminal outcome recorded by
    any port (a contact received or a classified refusal elsewhere) must not
    strand a chat the operator is actively writing: he decides to continue it.
    An explicit manual /num order stays authoritative and is NOT exempted, and
    a binding for a different account or peer never applies here.
    """
    try:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operator_bindings'"
                      ).fetchone() is None:
            return False
        return db.execute('SELECT 1 FROM operator_bindings WHERE account=? AND peer=?',
                          (who['account'], who['peer'])).fetchone() is not None
    except Exception:
        return False


AUTOMATIC_REASONS = frozenset({'contact-received', 'contact-refused'})


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
    from mumu_namespace import ensure_account
    ensure_account(store,who,db)
    row = db.execute('SELECT reason FROM mumu_peer_blocks WHERE peer=?', (who['peer'],)).fetchone()
    if row is not None:
        if row[0] in AUTOMATIC_REASONS and _operator_led(db, who):
            # v1.3.86: the operator leads this dialog himself; the automatic
            # cross-port outcome does not forbid assisting HIS conversation.
            # Manual /num blocks and any other reason still deny below.
            return
        raise PeerCommunicationBlocked()


def manual_block(peer,path=None):
    # Serialize Telegram /num with first cloud cutover, not with a whole live
    # MuMu pass. Workers may keep running while ordinary /num updates commit.
    import os
    from pathlib import Path
    from assistant_lock import operation_lock
    if os.environ.get('DVK_MORELOGIN')=='1':raise ValueError('MuMu registry only')
    if path is None:
        from mumu_common import root_directory
        path=root_directory()/'assistant.sqlite3'
    with operation_lock(Path(path).parent/'database-cutover.lock'):
        return _manual_block(peer,path)


def _manual_block(peer, path=None):
    """Human-entered deny only. Existing terminal outcomes and journals stay intact.

    Never creates a missing DB/registry or invents an account/contact receipt.
    No Telegram credentials or message bodies are accepted by this interface.
    """
    import os
    import sqlite3
    from pathlib import Path
    from conversation_engine import identifier
    peer = identifier(peer)
    if os.environ.get('DVK_MORELOGIN') == '1':
        raise ValueError('MuMu registry only')
    if path is None:
        from mumu_common import root_directory
        path = root_directory() / 'assistant.sqlite3'
    path = Path(path)
    if not primary_available(path):
        raise ValueError('MuMu registry unavailable')
    db = primary_connect(path,timeout=5)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            # The real shared schema must exist. Do not initialize a replacement.
            db.execute('SELECT peer,reason,device,account,chat FROM mumu_peer_blocks LIMIT 0')
            db.execute('CREATE TABLE IF NOT EXISTS mumu_manual_silences(peer TEXT PRIMARY KEY)')
            db.execute('INSERT OR IGNORE INTO mumu_manual_silences(peer) VALUES(?)',(peer,))
            exists = db.execute('SELECT 1 FROM mumu_peer_blocks WHERE peer=?', (peer,)).fetchone()
            inserted = False
            if exists is None:
                cursor = db.execute(
                    "INSERT INTO mumu_peer_blocks(peer,reason,device,account,chat) VALUES(?,?,?,?,?)",
                    (peer, 'manual-block', 'telegram', '', ''))
                if cursor.rowcount != 1:
                    raise ValueError('MuMu deny was not written')
                inserted = True
        return inserted
    finally:
        db.close()


def without_manual_blocks(store,rows):
    """Fresh deny-only queue filter; no cache, receipt, read flag or send permit."""
    rows=list(rows)
    if not rows or getattr(store,'mumu_shared_claims',False) is not True:return rows
    from conversation_engine import identifier
    peers=list(dict.fromkeys(identifier(who['peer']) for who in rows))
    blocked=set()
    with store.read_connection() as db:
        for offset in range(0,len(peers),1000):
            part=peers[offset:offset+1000]
            query="SELECT b.peer FROM mumu_peer_blocks b LEFT JOIN mumu_manual_silences m ON m.peer=b.peer WHERE (b.reason=? OR m.peer IS NOT NULL) AND b.peer IN ("+','.join('?' for _ in part)+')'
            blocked.update(row[0] for row in db.execute(query,('manual-block',*part)))
    return [who for who in rows if who['peer'] not in blocked]


def manually_blocked(store,who):
    return not without_manual_blocks(store,[who])
