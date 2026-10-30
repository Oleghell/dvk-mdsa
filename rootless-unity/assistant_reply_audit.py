"""Durable reply receipts. Reading a message is never proof of answering it.

Only message IDs and existing salted fingerprints are persisted. Confirmation
requires an exact returned outgoing already verified by the chain, not UI unread
badges, numeric ordering, elapsed time, or the success of a send API call.
"""
from assistant_chain import fingerprint,text_hash


DDL = '''CREATE TABLE IF NOT EXISTS chain_reply_receipts(
      chat TEXT,message TEXT,fingerprint TEXT,status TEXT NOT NULL,
      reply_message TEXT,PRIMARY KEY(chat,message))'''

def initialize(db):
    db.execute(DDL)


def observe(chain,snapshot,input_ids=None):
    who=snapshot['identity'];chat=who['chat'];chain.authorized(who)
    chain.store.ensure_tables(DDL)
    with chain.store.read_connection() as db:
        row=db.execute('SELECT stage,salt FROM chain_dialogs WHERE chat=?',(chat,)).fetchone()
        if row is None or row[0] in ('done','declined','manual-review'):return
        seen={r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?',(chat,))}
        existing={r[0] for r in db.execute('SELECT message FROM chain_reply_receipts WHERE chat=?',(chat,))}
    incoming=[m for m in snapshot['messages'] if m['sender']==who['peer'] and m['id'] not in existing
              and (m['id'] not in seen or m['id'] in (input_ids or ()))]
    if incoming:
        with chain.store.connection() as db:
            current=db.execute('SELECT stage,salt FROM chain_dialogs WHERE chat=?',(chat,)).fetchone()
            if current==row:
                for m in incoming:
                    db.execute("INSERT OR IGNORE INTO chain_reply_receipts VALUES(?,?,?,'pending',NULL)",
                               (chat,m['id'],fingerprint(m,row[1])))
    synchronize(chain,snapshot)


def synchronize(chain,snapshot):
    who=snapshot['identity'];chat=who['chat'];chain.store.ensure_tables(DDL)
    # Nothing pending means nothing to synchronize, NOT delivery proof. Avoid a
    # global cloud writer lock on every already-handled read/proposal/exit.
    with chain.store.read_connection() as db:
        pending_rows=dict(db.execute("SELECT message,fingerprint FROM chain_reply_receipts WHERE chat=? AND status='pending'",(chat,)))
        if not pending_rows:return
        state=db.execute('SELECT stage,salt FROM chain_dialogs WHERE chat=?',(chat,)).fetchone()
        if not state:return
        terminal=state[0] in ('done','declined')
        changes=[]
        if not terminal:
            actions=db.execute("SELECT a.kind,a.text_hash,i.message FROM chain_actions a JOIN ai_draft_inputs i ON i.chat=a.chat AND i.kind=a.kind WHERE a.chat=? AND a.status='outgoing-observed'",(chat,)).fetchall()
            for kind,digest,message in actions:
                if message not in pending_rows:continue
                outgoing=[m for m in snapshot['messages'] if m['sender']==who['account'] and isinstance(m['text'],str) and text_hash(m['text'])==digest]
                incoming=[m for m in snapshot['messages'] if m['id']==message and m['sender']==who['peer']]
                if len(outgoing)==len(incoming)==1 and fingerprint(incoming[0],state[1])==pending_rows[message]:
                    changes.append((kind,digest,message,outgoing[0]['id'],pending_rows[message]))
    if not terminal and not changes:return
    with chain.store.connection() as db:
        if db.execute('SELECT stage,salt FROM chain_dialogs WHERE chat=?',(chat,)).fetchone()!=state:return
        if terminal:
            db.execute("UPDATE chain_reply_receipts SET status=? WHERE chat=? AND status='pending'",('contact-received' if state[0]=='done' else 'declined',chat));return
        for kind,digest,message,outgoing,digest_input in changes:
            db.execute("""UPDATE chain_reply_receipts SET status='answered',reply_message=?
              WHERE chat=? AND message=? AND fingerprint=? AND status='pending'
              AND EXISTS(SELECT 1 FROM chain_actions a JOIN ai_draft_inputs i ON i.chat=a.chat AND i.kind=a.kind
                WHERE a.chat=? AND a.kind=? AND a.text_hash=? AND a.status='outgoing-observed' AND i.message=?)""",
                (outgoing,chat,message,digest_input,chat,kind,digest,message))


def pending(chain,who):
    chain.store.ensure_tables(DDL)
    with chain.store.read_connection() as db:
        return [r[0] for r in db.execute("SELECT message FROM chain_reply_receipts WHERE chat=? AND status='pending' ORDER BY message",(who['chat'],))]


def owed(chain,who,snapshot=None):
    """v1.3.97: the pending receipts that still carry OWED work in this history.

    The ledger (chain_reply_receipts) durably records every peer message read
    but not draft-confirmed-answered - that record is append-only history and
    stays untouched. Whether a receipt still DEMANDS work is a property of the
    current verified history, not of the ledger alone: the moment ANY message
    from our own account follows her message (the bot's confirmed outgoing or
    the operator's manual reply from the same account), our side has had the
    last word after her message and nothing is owed on it - the receipt no
    longer defers the chat, no longer fires the «ответ ещё не подтверждён»
    notice, no longer blocks the workless marker and no longer postpones the
    read-round bookkeeping. Her genuinely NEW message (nothing of ours after
    it - the badge-less, already-read, fast reply included) stays owed and the
    next pass answers it exactly as before. Absence of a verified snapshot or
    of her message inside it stays OWED (conservative: no evidence, no
    release) - the previous behaviour, never a silent drop.
    """
    remaining=pending(chain,who)
    if not isinstance(snapshot,dict) or not isinstance(snapshot.get('messages'),list):
        return remaining
    messages=snapshot['messages']
    out=[]
    for message in remaining:
        index=next((i for i,m in enumerate(messages)
                    if isinstance(m,dict) and m.get('id')==message
                    and m.get('sender')==who['peer']),None)
        if index is None:
            out.append(message)
            continue
        if not any(isinstance(m,dict) and m.get('sender')==who['account']
                   for m in messages[index+1:]):
            out.append(message)
    return out


def recycle_followup(chain,snapshot):
    """A NEW contextual answer after an observed earlier one, never a send retry."""
    if chain.responder is None:return
    who=snapshot['identity'];chat=who['chat']
    synchronize(chain,snapshot)
    with chain.store.read_connection() as db:
        state=db.execute('SELECT stage FROM chain_dialogs WHERE chat=?',(chat,)).fetchone()
        if not state or state[0]!='wait-contact':return
        seen={r[0] for r in db.execute('SELECT message FROM chain_seen WHERE chat=?',(chat,))}
        if not any(m['sender']==who['peer'] and m['id'] not in seen and isinstance(m['text'],str) and m['text'].strip() for m in snapshot['messages']):return
        row=db.execute("SELECT status FROM chain_actions WHERE chat=? AND kind='followup'",(chat,)).fetchone()
        if row!=('outgoing-observed',):return
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
