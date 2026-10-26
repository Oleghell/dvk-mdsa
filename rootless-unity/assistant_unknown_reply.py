"""Explicit MuMu policy: one audited retry of an uncertain REPLY, never greeting.

Absence in a full history is not a delivery guarantee. The user accepts that
risk. Original authorizations/attempts remain in the journal; a separate ledger
limits the new attempt across restarts. No terminal ban or history mismatch is
repaired here. Only two fresh identical same-chat reads can enter this path.
"""
from assistant_chain import fingerprint,text_hash,REPLIES
from one_chat_send import checked,checked_reply

DDL='''CREATE TABLE IF NOT EXISTS chain_unknown_reply_retries(
 chat TEXT,kind TEXT,text_hash TEXT,original_status TEXT,original_trigger TEXT,
 state TEXT NOT NULL,PRIMARY KEY(chat,kind))'''
STATUSES=('unknown','reserved-unknown','handler-returned-unconfirmed')
KINDS=('question','contact','clarify','followup')


def enable(chain):
    chain.store.ensure_tables(DDL)
    chain.retry_unknown_once=True


def candidate(chain,who):
    if getattr(chain,'retry_unknown_once',False) is not True:return False
    with chain.store.read_connection() as db:
        row=db.execute('''SELECT c.stage,a.kind,a.status FROM chain_dialogs c
          JOIN chain_actions a ON a.chat=c.chat
          WHERE c.account=? AND c.peer=? AND c.chat=?''',
          (who['account'],who['peer'],who['chat'])).fetchall()
    return any(kind in KINDS and stage=='pending-'+kind and status in STATUSES for stage,kind,status in row)


def targets(chain):
    """Only unspent recovery/approval may bypass already-reported-input hints."""
    if getattr(chain,'retry_unknown_once',False) is not True:return set()
    with chain.store.read_connection() as db:
        rows=db.execute('''SELECT c.account,c.peer,c.chat,c.stage,a.kind,a.status,r.state
          FROM chain_dialogs c JOIN chain_actions a ON a.chat=c.chat
          LEFT JOIN chain_unknown_reply_retries r ON r.chat=a.chat AND r.kind=a.kind
          WHERE c.stage IN ('pending-question','pending-contact','pending-clarify','pending-followup')
            AND a.status IN ('unknown','reserved-unknown','handler-returned-unconfirmed','awaiting-approval')''').fetchall()
    return {(account,peer,chat) for account,peer,chat,stage,kind,status,retry in rows
            if kind in KINDS and stage=='pending-'+kind and
            (retry is None and status in STATUSES or retry=='prepared' and status=='awaiting-approval')}


def recover(chain,previous,current):
    from assistant_guided_chain import same_snapshot
    from assistant_reply_window import reason
    from mumu_peer_policy import ensure_communication_allowed
    from assistant_contact_receipt import packet_blocked
    from assistant_contact_followup import scoped_messages,refused
    from assistant_contact_policy import should_close
    from assistant_contact_clarify import max_selected,indifferent_selected,selected_alternative_text
    from assistant_contact_budget import can_close
    from assistant_ai_drafts import restore
    from groq_reply import GroqError
    if getattr(chain,'retry_unknown_once',False) is not True:return 'disabled'
    if not same_snapshot(previous,current):return 'changing-history'
    snapshot=checked({key:current[key] for key in ('identity','messages')})
    who=snapshot['identity'];chat=who['chat'];chain.authorized(who)
    if reason(chain.store,who):return 'blocked'
    with chain.store.connection() as db:
        ensure_communication_allowed(chain.store,who,db=db)
        state=db.execute('SELECT stage,salt,greeting FROM chain_dialogs WHERE account=? AND peer=? AND chat=?',
            (who['account'],who['peer'],chat)).fetchone()
        if not state or not state[2] or not state[0].startswith('pending-'):return 'not-pending'
        stage,salt,_=state;kind=stage.removeprefix('pending-')
        if kind not in KINDS:return 'not-pending'
        row=db.execute('SELECT text_hash,status,trigger FROM chain_actions WHERE chat=? AND kind=?',(chat,kind)).fetchone()
        if not row or row[1] not in STATUSES:return 'not-pending'
        digest,status,trigger=row
        seen=dict(db.execute('SELECT message,fingerprint FROM chain_seen WHERE chat=?',(chat,)))
        now={m['id']:fingerprint(m,salt) for m in snapshot['messages']}
        if not seen or not set(seen)<=set(now) or any(now[key]!=value for key,value in seen.items()):return 'history-changed'
        incoming=[m for m in snapshot['messages'] if m['sender']==who['peer'] and m['id'] not in seen]
        requested=kind in ('contact','clarify','followup')
        refusal_inputs=scoped_messages(db,snapshot,[m['id'] for m in incoming],requested=requested)
        alternative=selected_alternative_text(db,snapshot,[m['id'] for m in incoming])
        if packet_blocked(incoming) or refused(refusal_inputs,requested=requested,
                alternative_selected=bool(alternative) or max_selected(incoming)):return 'blocked'
        outgoing=[m for m in snapshot['messages'] if m['sender']==who['account'] and m['id'] not in seen]
        retry=db.execute('SELECT text_hash,state FROM chain_unknown_reply_retries WHERE chat=? AND kind=?',(chat,kind)).fetchone()
        if outgoing:
            # Observe an exact NEW outgoing, never claim a handler returned.
            if len(outgoing)!=1 or not isinstance(outgoing[0]['text'],str) or text_hash(outgoing[0]['text'])!=digest:return 'outgoing-conflict'
            db.execute('INSERT OR IGNORE INTO chain_unknown_reply_retries VALUES(?,?,?,?,?,?)',
                (chat,kind,digest,status,trigger,'observed'))
            db.execute("UPDATE chain_unknown_reply_retries SET state='observed' WHERE chat=? AND kind=? AND text_hash=?",(chat,kind,digest))
            db.execute("UPDATE chain_actions SET status='outgoing-observed' WHERE chat=? AND kind=? AND text_hash=? AND status=?",(chat,kind,digest,status))
            db.execute('INSERT OR IGNORE INTO chain_seen VALUES(?,?,?)',(chat,outgoing[0]['id'],now[outgoing[0]['id']]))
            db.execute('UPDATE chain_dialogs SET stage=? WHERE chat=? AND stage=?',('wait-mood' if kind=='question' else 'wait-contact',chat,stage))
            return 'observed'
        if retry is not None:return 'retry-used'
        if can_close(db,chat,stage) or should_close(db,snapshot,stage,incoming,requested=requested,
                max_choice=max_selected(incoming),number_choice=indifferent_selected(db,snapshot,[m['id'] for m in incoming])):return 'blocked'
        try:text=restore(chain,chat,kind,digest,connection=db,snapshot=current)
        except GroqError:return 'draft-unavailable'
        text=text or next((text for text in REPLIES if text_hash(text)==digest),None)
        if text is None:return 'draft-unavailable'
        try:checked_reply(text)
        except ValueError:return 'draft-unavailable'
        # Claim the single retry durably before an old reservation can change.
        inserted=db.execute('INSERT OR IGNORE INTO chain_unknown_reply_retries VALUES(?,?,?,?,?,?)',
            (chat,kind,digest,status,trigger,'prepared')).rowcount
        if inserted!=1:return 'retry-used'
        from assistant_send_safety import tables
        tables(db)
        db.execute("UPDATE chain_send_authorizations SET status='superseded-unknown' WHERE chat=? AND kind=? AND text_hash=? AND status='active'",(chat,kind,digest))
        changed=db.execute("UPDATE chain_actions SET status='awaiting-approval' WHERE chat=? AND kind=? AND text_hash=? AND status=?",(chat,kind,digest,status)).rowcount
        if changed!=1:
            from assistant_store import StateError
            raise StateError('send-reservation-changed')
        return 'prepared'


def reserve(db,who,action):
    # Consumed on reservation, even if Stop/crash precedes the adapter. A later
    # process cannot turn the original uncertain attempt into an endless loop.
    db.execute("UPDATE chain_unknown_reply_retries SET state='reserved' WHERE chat=? AND kind=? AND text_hash=? AND state='prepared'",
        (who['chat'],action['kind'],text_hash(action['text'])))
