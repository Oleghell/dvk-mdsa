"""Reported skipped input batches: exact private IDs/hashes, never fake answers."""
from assistant_chain import fingerprint
from one_chat_probe import identity


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS inbox_reported_inputs(
        chat TEXT,message TEXT,fingerprint TEXT NOT NULL,
        PRIMARY KEY(chat,message))""")


def reported(chain,who,snapshot):
    who=identity(who)
    if not isinstance(snapshot,dict) or snapshot.get('identity')!=who:return 0
    chain.authorized(who)
    from assistant_reply_audit import initialize as receipts
    with chain.store.connection() as db:
        initialize(db);receipts(db)
        row=db.execute('SELECT salt FROM chain_dialogs WHERE chat=?',(who['chat'],)).fetchone()
        if not row:return 0
        pending=dict(db.execute("SELECT message,fingerprint FROM chain_reply_receipts WHERE chat=? AND status='pending'",(who['chat'],)))
        marked=0
        for m in snapshot['messages']:
            if m['sender']==who['peer'] and pending.get(m['id'])==fingerprint(m,row[0]):
                db.execute('INSERT OR IGNORE INTO inbox_reported_inputs VALUES(?,?,?)',(who['chat'],m['id'],pending[m['id']]))
                marked+=1
        return marked
