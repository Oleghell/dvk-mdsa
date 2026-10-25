"""Global initial-greeting claims, separate from terminal communication bans."""
import re


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
            db.execute('INSERT OR IGNORE INTO mumu_greeting_claims(peer,device,account) '
                       'SELECT peer,?,account FROM '+name+' WHERE peer IS NOT NULL',
                       (match[1] or '5563',))
