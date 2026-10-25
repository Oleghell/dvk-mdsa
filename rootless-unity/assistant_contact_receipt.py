"""Receipt of a self-shared contact is NOT confirmation of an outgoing send."""
import json,re
from shared_contact import self_shared,OTHER
from conversation_engine import REFUSAL


def requested(db,who,messages):
    """An already observed, exact journal contact proposal in this same chat.

    No collection ordering, numeric ID ordering or AI classification is used.
    Extra own messages do not invalidate receipt and are not marked delivered.
    """
    from assistant_chain import text_hash
    digests={r[0] for r in db.execute("SELECT text_hash FROM chain_actions WHERE chat=? AND kind IN ('contact','clarify','followup') AND status='outgoing-observed'",(who['chat'],))}
    # Followups can be archived, but the contact proposal itself is never reset.
    return any(m['sender']==who['account'] and isinstance(m.get('text'),str)
               and text_hash(m['text']) in digests for m in messages)


def packet_blocked(incoming):
    # Quotes cannot supply a contact or consent. Unquoted prohibitions and
    # third-party attribution in another message still apply to the packet.
    for m in incoming:
        text=m.get('text')
        if not isinstance(text,str):continue
        plain=' '.join(line for line in text.splitlines() if not line.lstrip().startswith('>'))
        if (REFUSAL.search(plain) or OTHER.search(plain) or
            re.search(r'не\s+(?:мой|моя|мо[её]|передавай|пересылай|делись)|никому',plain,re.I)):
            return True
    return False


def save(chain,db,snapshot,message,items):
    """One transactional, encrypted outbox; no journal/draft resets or sends."""
    from assistant_store import StateError
    from shared_contact import display_name,payload
    who=snapshot['identity'];chat=who['chat']
    if chain.contact_notifications:
        try:display_name(snapshot.get('peer_name'))
        except ValueError:raise StateError('contact-name-required') from None
        try:data=payload(snapshot.get('peer_name'),items)
        except ValueError:raise StateError('contact-payload-invalid') from None
        try:
            protected=chain.seal(json.dumps(data,ensure_ascii=False).encode('utf-8'))
            if not isinstance(protected,bytes) or not protected:raise ValueError()
            db.execute("INSERT OR IGNORE INTO chain_contact_outbox VALUES(?,?,?,'pending')",(chat,message['id'],protected))
        except Exception as error:
            import sqlite3
            if isinstance(error,sqlite3.Error):raise
            raise StateError('contact-protection-failed') from None
    from assistant_statistics import received
    received(db,who['account'],who['peer'],chat,items)
    if getattr(chain.store,'mumu_shared_claims',False) is True:
        chain.store.record_peer_outcome(db,who,'contact-received')


def reviewable(db,chat):
    return db.execute("""SELECT 1 FROM chain_dialogs c JOIN chain_review_reasons r ON r.chat=c.chat
      WHERE c.chat=? AND c.stage='manual-review' AND c.greeting IS NOT NULL
        AND r.reason='contact-batch-ambiguous'
        AND EXISTS(SELECT 1 FROM chain_actions a WHERE a.chat=c.chat AND a.kind='contact' AND a.status='outgoing-observed')
        AND NOT EXISTS(SELECT 1 FROM chain_contact_outbox o WHERE o.chat=c.chat)""",(chat,)).fetchone() is not None


def candidates(store):
    with store.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS chain_contact_review_probes(chat TEXT PRIMARY KEY,status TEXT NOT NULL)')
        # Same receipt-only predicates as reviewable(), evaluated in one query.
        return set(db.execute("""SELECT c.account,c.peer,c.chat FROM chain_dialogs c
          JOIN chain_review_reasons r ON r.chat=c.chat
          WHERE c.stage='manual-review' AND c.greeting IS NOT NULL
            AND r.reason='contact-batch-ambiguous'
            AND c.chat NOT IN (SELECT chat FROM chain_contact_review_probes)
            AND EXISTS(SELECT 1 FROM chain_actions a WHERE a.chat=c.chat AND a.kind='contact' AND a.status='outgoing-observed')
            AND NOT EXISTS(SELECT 1 FROM chain_contact_outbox o WHERE o.chat=c.chat)"""))


def reserve_probe(chain,who):
    if (who['account'],who['peer'],who['chat']) not in candidates(chain.store):return False
    with chain.store.connection() as db:
        return db.execute("INSERT OR IGNORE INTO chain_contact_review_probes VALUES(?,'read-attempted')",(who['chat'],)).rowcount==1


def reconcile(chain,previous,current):
    """A receipt-only reconciliation of ONE old contact ambiguity, never a reset.

    Two complete, identical same-chat reads must expose the SAME native latest
    peer-owned contact after the observed contact request. Collection/ID order
    is irrelevant. All saved history hashes must still match. Other reviews and
    declined/unknown sends cannot be reauthorized by this path.
    """
    from assistant_guided_chain import same_snapshot
    from assistant_chain import fingerprint
    from assistant_contact_followup import refused
    from one_chat_send import checked
    a=checked({k:previous[k] for k in ('identity','messages')})
    b=checked({k:current[k] for k in ('identity','messages')})
    if not same_snapshot(a,b):return False
    who=b['identity'];chain.authorized(who);chat=who['chat']
    latest=previous.get('latest_message_id')
    if not latest or latest!=current.get('latest_message_id'):return False
    tail=[m for m in b['messages'] if m['id']==latest and m['sender']==who['peer']]
    if len(tail)!=1:return False
    items=self_shared(tail[0]['text'],requested=True)
    if not items:return False
    with chain.store.connection() as db:
        if not reviewable(db,chat) or not requested(db,who,b['messages']):return False
        salt=db.execute('SELECT salt FROM chain_dialogs WHERE chat=?',(chat,)).fetchone()[0]
        old=dict(db.execute('SELECT message,fingerprint FROM chain_seen WHERE chat=?',(chat,)))
        now={m['id']:fingerprint(m,salt) for m in b['messages']}
        if not old or not set(old)<=set(now) or any(now[k]!=v for k,v in old.items()):return False
        peer=[m for m in b['messages'] if m['sender']==who['peer']]
        if packet_blocked(peer) or refused(peer,requested=True,contact_shared=True):return False
        save(chain,db,current,tail[0],items)
        for m in b['messages']:
            db.execute('INSERT OR IGNORE INTO chain_seen VALUES(?,?,?)',(chat,m['id'],now[m['id']]))
        # Keep original review reason, every action and every encrypted draft.
        db.execute("UPDATE chain_dialogs SET stage='done' WHERE chat=? AND stage='manual-review'",(chat,))
        db.execute('CREATE TABLE IF NOT EXISTS chain_contact_review_probes(chat TEXT PRIMARY KEY,status TEXT NOT NULL)')
        db.execute("INSERT OR REPLACE INTO chain_contact_review_probes VALUES(?,'contact-received')",(chat,))
    return True
