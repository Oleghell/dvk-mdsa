"""Durable reply receipts. Reading a message is never proof of answering it.

Only message IDs and existing salted fingerprints are persisted. Confirmation
requires an exact returned outgoing already verified by the chain, not UI unread
badges, numeric ordering, elapsed time, or the success of a send API call.
"""
from assistant_chain import fingerprint,text_hash


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS chain_reply_receipts(
      chat TEXT,message TEXT,fingerprint TEXT,status TEXT NOT NULL,
      reply_message TEXT,PRIMARY KEY(chat,message))''')


def observe(chain,snapshot,input_ids=None):
    who=snapshot['identity'];chat=who['chat']
    chain.authorized(who)
    with chain.store.connection() as db:
        initialize(db)
        row=db.execute('SELECT stage,salt FROM chain_dialogs WHERE chat=?',(chat,)).fetchone()
        if row is None or row[0] in ('done','declined','manual-review'):return
        seen={r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?',(chat,))}
        for m in snapshot['messages']:
            if m['sender']==who['peer'] and (m['id'] not in seen or m['id'] in (input_ids or ())):
                db.execute("INSERT OR IGNORE INTO chain_reply_receipts VALUES(?,?,?,'pending',NULL)",
                           (chat,m['id'],fingerprint(m,row[1])))
    synchronize(chain,snapshot)


def synchronize(chain,snapshot):
    who=snapshot['identity'];chat=who['chat']
    with chain.store.connection() as db:
        initialize(db)
        state=db.execute('SELECT stage,salt FROM chain_dialogs WHERE chat=?',(chat,)).fetchone()
        if not state:return
        if state[0] in ('done','declined'):
            db.execute("UPDATE chain_reply_receipts SET status=? WHERE chat=? AND status='pending'",
                       ('contact-received' if state[0]=='done' else 'declined',chat))
            return
        actions=db.execute("SELECT kind,text_hash FROM chain_actions WHERE chat=? AND status='outgoing-observed'",(chat,)).fetchall()
        for kind,digest in actions:
            outgoing=[m for m in snapshot['messages'] if m['sender']==who['account'] and isinstance(m['text'],str) and text_hash(m['text'])==digest]
            if len(outgoing)!=1:continue
            inputs={r[0] for r in db.execute('SELECT message FROM ai_draft_inputs WHERE chat=? AND kind=?',(chat,kind))}
            for m in snapshot['messages']:
                if m['sender']==who['peer'] and m['id'] in inputs:
                    db.execute("UPDATE chain_reply_receipts SET status='answered',reply_message=? WHERE chat=? AND message=? AND fingerprint=? AND status='pending'",
                               (outgoing[0]['id'],chat,m['id'],fingerprint(m,state[1])))


def pending(chain,who):
    with chain.store.connection() as db:
        initialize(db)
        return [r[0] for r in db.execute("SELECT message FROM chain_reply_receipts WHERE chat=? AND status='pending' ORDER BY message",(who['chat'],))]


def recycle_followup(chain,snapshot):
    """A NEW contextual answer after an observed earlier one, never a send retry."""
    if chain.responder is None:return
    who=snapshot['identity'];chat=who['chat']
    synchronize(chain,snapshot)
    with chain.store.connection() as db:
        state=db.execute('SELECT stage FROM chain_dialogs WHERE chat=?',(chat,)).fetchone()
        if not state or state[0]!='wait-contact':return
        from assistant_contact_budget import exhausted
        if exhausted(db,chat):return
        seen={r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?',(chat,))}
        incoming=[m for m in snapshot['messages'] if m['sender']==who['peer'] and m['id'] not in seen and isinstance(m['text'],str) and m['text'].strip()]
        if not incoming:return
        action=db.execute("SELECT trigger,text_hash,status FROM chain_actions WHERE chat=? AND kind='followup'",(chat,)).fetchone()
        if not action or action[2]!='outgoing-observed':return
        # Keep every old reservation and its input IDs in an append-only ledger.
        db.execute('''CREATE TABLE IF NOT EXISTS chain_followup_archive(
          chat TEXT,trigger TEXT,text_hash TEXT,status TEXT,inputs TEXT,
          PRIMARY KEY(chat,trigger))''')
        import json
        inputs=[r[0] for r in db.execute("SELECT message FROM ai_draft_inputs WHERE chat=? AND kind='followup'",(chat,))]
        db.execute('INSERT INTO chain_followup_archive VALUES(?,?,?,?,?)',(chat,*action,json.dumps(inputs)))
        db.execute("DELETE FROM chain_actions WHERE chat=? AND kind='followup' AND status='outgoing-observed'",(chat,))
        db.execute("DELETE FROM ai_drafts WHERE chat=? AND kind='followup'",(chat,))
        db.execute("DELETE FROM ai_draft_inputs WHERE chat=? AND kind='followup'",(chat,))
