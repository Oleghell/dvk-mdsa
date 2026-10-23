"""Narrow adoption of an observed legacy question, never a send retry/reset.

Requires exact journal greeting + ONE fixed question + native Chat.LastMessage
verified as peer-owned within two complete SAME-chat samples. Collection order,
message-ID ordering and AI classification are not temporal evidence.
"""
import hashlib
import json
import secrets
from assistant_chain import fingerprint, text_hash
from one_chat_send import checked
from conversation_engine import QUESTIONS


def exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None


def candidates(store):
    """Only unbound placeholders; existing real chains/reviews are not reopened."""
    with store.connection() as db:
        if not exists(db,'chain_exit_notices'):return set()
        probe_filter=(' AND NOT EXISTS(SELECT 1 FROM chain_legacy_probes p WHERE p.chat=c.chat)'
                      if exists(db,'chain_legacy_probes') else '')
        return set(db.execute('''SELECT c.account,c.peer,c.chat FROM chain_dialogs c
          JOIN manual_actions m ON m.account=c.account AND m.peer=c.peer
          WHERE c.stage='manual-review' AND c.greeting IS NULL
            AND m.status='handler-returned-unconfirmed'
            AND NOT EXISTS(SELECT 1 FROM chain_seen s WHERE s.chat=c.chat)
            AND NOT EXISTS(SELECT 1 FROM chain_actions a WHERE a.chat=c.chat)
            AND NOT EXISTS(SELECT 1 FROM chain_review_reasons r WHERE r.chat=c.chat)
            AND EXISTS(SELECT 1 FROM chain_exit_notices e WHERE e.chat=c.chat)'''+probe_filter))


def reserve_probe(chain, who):
    """One inspection of an old placeholder, not an endless retry of all reviews."""
    if chain.responder is None or (who['account'],who['peer'],who['chat']) not in candidates(chain.store):return False
    with chain.store.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS chain_legacy_probes(chat TEXT PRIMARY KEY,status TEXT NOT NULL)')
        return db.execute("INSERT OR IGNORE INTO chain_legacy_probes VALUES(?,'attempted-before-read')",(who['chat'],)).rowcount==1


def legacy_notice(db, snapshot):
    # The old notification's signature proves THIS was the unbound-greeting
    # failure, not a generic manual review. No notices or other journals erased.
    if not exists(db,'chain_exit_notices'):return False
    who=snapshot['identity']
    excerpts=[m['text'] if isinstance(m['text'],str) else '[нет текста]'
              for m in snapshot['messages'] if m['sender']==who['peer']]
    batch=hashlib.sha256(json.dumps(excerpts,ensure_ascii=True).encode()).hexdigest()
    signature=hashlib.sha256(json.dumps(['greeting-not-verified',None,[],batch],ensure_ascii=True).encode()).hexdigest()
    return db.execute('SELECT 1 FROM chain_exit_notices WHERE chat=? AND signature=?',
                      (who['chat'],signature)).fetchone() is not None


def recover(chain, snapshot):
    def reject(reason):
        chain.legacy_recovery_reason=reason
        return False
    if chain.responder is None:return reject('ai-required')  # Contextual replies, not a blind template.
    plain=checked({k:snapshot[k] for k in ('identity','messages')})
    who=plain['identity'];chat=who['chat'];messages=plain['messages']
    latest=snapshot.get('latest_message_id')
    tail=[m for m in messages if m['id']==latest and m['sender']==who['peer']]
    if len(tail)!=1:return reject('native-latest-peer-not-verified')
    own=[m for m in messages if m['sender']==who['account']]
    if len(own)!=2:return reject('not-two-own-messages')
    with chain.store.connection() as db:
        legacy=db.execute('SELECT initial_chat,text_hash,status FROM manual_actions WHERE account=? AND peer=?',
                          (who['account'],who['peer'])).fetchone()
        if not legacy or legacy[2]!='handler-returned-unconfirmed' or int(legacy[0])>0 and legacy[0]!=chat:return reject('journal-not-eligible')
        greeting=[m for m in own if isinstance(m['text'],str) and text_hash(m['text'])==legacy[1]]
        if len(greeting)!=1:return reject('journal-greeting-mismatch')
        question=[m for m in own if m['id']!=greeting[0]['id'] and m['text'] in QUESTIONS]
        if len(question)!=1:return reject('fixed-question-not-verified')
        if db.execute('SELECT 1 FROM chain_actions WHERE chat=?',(chat,)).fetchone():return reject('persisted-state-protected')
        if db.execute('SELECT 1 FROM chain_seen WHERE chat=?',(chat,)).fetchone():return reject('persisted-state-protected')
        if db.execute('SELECT 1 FROM chain_review_reasons WHERE chat=?',(chat,)).fetchone():return reject('persisted-state-protected')
        old=db.execute('SELECT greeting,stage FROM chain_dialogs WHERE account=? AND peer=?',
                       (who['account'],who['peer'])).fetchone()
        if old is not None and (tuple(old)!=(None,'manual-review') or not legacy_notice(db,plain)):return reject('old-review-proof-missing')
        # A ready/unknown AI draft without a chain is also not a fresh baseline.
        if db.execute('SELECT 1 FROM ai_drafts WHERE chat=?',(chat,)).fetchone():return reject('persisted-state-protected')
        if db.execute('SELECT 1 FROM ai_draft_inputs WHERE chat=?',(chat,)).fetchone():return reject('persisted-state-protected')
        if old is not None and not db.execute('SELECT 1 FROM chain_dialogs WHERE account=? AND peer=? AND chat=?',(who['account'],who['peer'],chat)).fetchone():return reject('chat-binding-mismatch')
        salt=secrets.token_hex(32)
        if old is None:
            db.execute('INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)',
                       (who['account'],who['peer'],chat,greeting[0]['id'],'wait-mood',salt))
        else:
            db.execute("UPDATE chain_dialogs SET greeting=?,stage='wait-mood',salt=? WHERE account=? AND peer=? AND chat=? AND greeting IS NULL AND stage='manual-review'",
                       (greeting[0]['id'],salt,who['account'],who['peer'],chat))
        # Historical observation is NOT a returned send or proof of delivery.
        # NULL trigger: no chronology of older peer messages is manufactured.
        db.execute("INSERT INTO chain_actions VALUES(?,'question',NULL,?,'outgoing-observed')",
                   (chat,text_hash(question[0]['text'])))
        for m in messages:
            if m['id']!=latest:
                db.execute('INSERT INTO chain_seen VALUES(?,?,?)',(chat,m['id'],fingerprint(m,salt)))
        db.execute('''CREATE TABLE IF NOT EXISTS chain_recovered_anchors(
          chat TEXT PRIMARY KEY,greeting TEXT,question TEXT,latest_peer TEXT,basis TEXT NOT NULL)''')
        db.execute("INSERT INTO chain_recovered_anchors VALUES(?,?,?,?,'native-last-peer-exact-templates')",
                   (chat,greeting[0]['id'],question[0]['id'],latest))
    chain.legacy_recovery_reason='recovered'
    return True
