"""Global initial-greeting claims, separate from terminal communication bans.

v1.3.87 user rule: «если на одном порту уже написали приветствие одной анкете,
то на другом порту с другой анкете этого уже невозможно сделать и анкета
пропускается ... больше с другого порта нельзя написать, можно через сутки».
A greeting claim therefore shields one peer from the OTHER ports' new
greetings for CLAIM_WINDOW_SECONDS only; after that another анкета may greet
the same peer again. The claiming port's own journal (manual_actions) keeps
its permanent same-account protection, and terminal contact outcomes in
mumu_peer_blocks (number received / explicit refusal / manual /num) never
expire on any port.
"""
import re

CLAIM_WINDOW_SECONDS = 24 * 3600


def claim_cutoff(now=None):
    """UTC text stamp; claims created before it no longer deny a new greeting.

    The text format matches the engine's SQLite/PostgreSQL CURRENT_TIMESTAMP
    default exactly ('YYYY-MM-DD HH:MM:SS', UTC), so a plain string
    comparison stays correct on both storages.
    """
    from datetime import datetime, timedelta, timezone
    moment = datetime.now(timezone.utc) if now is None else now
    return (moment - timedelta(seconds=CLAIM_WINDOW_SECONDS)).strftime('%Y-%m-%d %H:%M:%S')


def claim_stamp(now=None):
    """UTC text stamp for a (re)greeted claim row; same format as the default."""
    from datetime import datetime, timezone
    moment = datetime.now(timezone.utc) if now is None else now
    return moment.strftime('%Y-%m-%d %H:%M:%S')


def initialize(db):
    # Creation + full backfill are one transaction. Existing table is the
    # durable completion marker; normal constructors do not rescan history.
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='mumu_greeting_claims'").fetchone():return
    db.execute('''CREATE TABLE IF NOT EXISTS mumu_greeting_claims(
        peer TEXT PRIMARY KEY,device TEXT NOT NULL,account TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    names=[row[0] for row in db.execute('SELECT name FROM sqlite_master WHERE type=\'table\'')]
    for name in names:
        match=re.fullmatch(r'(?:m([1-9][0-9]{3,4})__)?manual_actions',name)
        if match:
            # Every persisted reservation remains protective, including unknown
            # outcomes. Never rewrite or infer delivery from the old journal.
            # v1.3.87: the imported claim keeps the journal row's own greeting
            # age, so a historical greeting older than the 24-hour window does
            # not deny another port's fresh greeting after migration.
            db.execute('INSERT OR IGNORE INTO mumu_greeting_claims(peer,device,account,created_at) '
                       'SELECT peer,?,account,created_at FROM '+name+' WHERE peer IS NOT NULL',
                       (match[1] or '5563',))
