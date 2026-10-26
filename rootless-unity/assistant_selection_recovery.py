"""One read-only probe for a narrowly misclassified old platform selection.

Never clear global refusals, budgets, outgoing journals or arbitrary terminal
states. Only the exact latest consumed «В тг» family can restore wait-contact.
"""
import re
from assistant_chain import fingerprint
from one_chat_send import checked

DDL='''CREATE TABLE IF NOT EXISTS chain_selection_recovery(
 chat TEXT PRIMARY KEY,status TEXT NOT NULL,original_stage TEXT,
 message TEXT,fingerprint TEXT,original_receipt TEXT)'''

def enable(chain):
    chain.store.ensure_tables(DDL)
    chain.selection_recovery=True

def eligible(db,chat=None):
    sql="""SELECT c.account,c.peer,c.chat FROM chain_dialogs c
      WHERE c.stage='declined' AND c.greeting IS NOT NULL
        AND EXISTS(SELECT 1 FROM chain_actions a WHERE a.chat=c.chat AND a.kind='contact' AND a.status='outgoing-observed')
        AND NOT EXISTS(SELECT 1 FROM chain_actions a WHERE a.chat=c.chat AND (a.kind IN ('clarify','followup') OR a.status!='outgoing-observed'))
        AND NOT EXISTS(SELECT 1 FROM chain_contact_outbox o WHERE o.chat=c.chat)"""
    if chat is not None:return db.execute(sql+' AND c.chat=?',(chat,)).fetchall()
    return db.execute(sql+' AND NOT EXISTS(SELECT 1 FROM chain_selection_recovery r WHERE r.chat=c.chat) ORDER BY c.account,c.peer LIMIT 16').fetchall()

def targets(chain):
    if getattr(chain,'selection_recovery',False) is not True:return set()
    with chain.store.read_connection() as db:rows=eligible(db)
    from assistant_reply_window import reason
    from mumu_namespace import owns_account
    result=set()
    for account,peer,chat in rows:
        who=dict(account=account,peer=peer,chat=chat)
        if reason(chain.store,who) or not owns_account(chain.store,who):continue
        if getattr(chain.store,'mumu_shared_claims',False) is True:
            with chain.store.read_connection() as db:
                if db.execute('SELECT 1 FROM mumu_peer_blocks WHERE peer=?',(peer,)).fetchone():continue
        result.add((account,peer,chat))
    return result

def reserve(chain,who):
    if (who['account'],who['peer'],who['chat']) not in targets(chain):return False
    with chain.store.connection() as db:
        return db.execute("INSERT OR IGNORE INTO chain_selection_recovery(chat,status) VALUES(?,'read-attempted')",(who['chat'],)).rowcount==1

def recover(chain,previous,current):
    from assistant_guided_chain import same_snapshot
    from assistant_contact_receipt import requested,packet_blocked
    from assistant_contact_followup import refused
    from assistant_contact_intent import available_alternative,visible
    from assistant_contact_budget import exhausted
    from assistant_reply_window import reason
    from mumu_peer_policy import ensure_communication_allowed
    if getattr(chain,'selection_recovery',False) is not True:return False
    a=checked({k:previous[k] for k in ('identity','messages')})
    b=checked({k:current[k] for k in ('identity','messages')})
    if not same_snapshot(a,b):return False
    who=b['identity'];chain.authorized(who);chat=who['chat']
    latest=previous.get('latest_message_id')
    if not latest or latest!=current.get('latest_message_id') or reason(chain.store,who):return False
    tail=[m for m in b['messages'] if m['id']==latest and m['sender']==who['peer']]
    if len(tail)!=1 or not isinstance(tail[0]['text'],str):return False
    # Do not reinterpret broad old consent/ambiguous closures. Exact unquoted
    # platform-only selections are the known regression, no question/negation.
    text=tail[0]['text'].strip().lower()
    if not re.fullmatch(r'в\s+(?:тг|телеграм|telegram)[.!]*',text) or visible(text)!=text:return False
    if available_alternative(tail)!='telegram':return False
    peer=[m for m in b['messages'] if m['sender']==who['peer']]
    if packet_blocked(peer) or refused(peer,requested=True,alternative_selected=True):return False
    with chain.store.connection() as db:
        ensure_communication_allowed(chain.store,who,db=db)
        probe=db.execute('SELECT status FROM chain_selection_recovery WHERE chat=?',(chat,)).fetchone()
        if probe!=('read-attempted',) or not eligible(db,chat) or exhausted(db,chat) or not requested(db,who,b['messages']):return False
        salt=db.execute('SELECT salt FROM chain_dialogs WHERE chat=?',(chat,)).fetchone()[0]
        old=dict(db.execute('SELECT message,fingerprint FROM chain_seen WHERE chat=?',(chat,)))
        now={m['id']:fingerprint(m,salt) for m in b['messages']}
        if latest not in old or not set(old)<=set(now) or any(now[k]!=v for k,v in old.items()):return False
        receipt=db.execute('SELECT status,fingerprint FROM chain_reply_receipts WHERE chat=? AND message=?',(chat,latest)).fetchone()
        if receipt is not None and receipt!=('declined',now[latest]):return False
        db.execute("UPDATE chain_selection_recovery SET status='recovered',original_stage='declined',message=?,fingerprint=?,original_receipt=? WHERE chat=? AND status='read-attempted'",(latest,now[latest],receipt[0] if receipt else None,chat))
        db.execute("UPDATE chain_dialogs SET stage='wait-contact' WHERE chat=? AND stage='declined'",(chat,))
        db.execute('DELETE FROM chain_seen WHERE chat=? AND message=? AND fingerprint=?',(chat,latest,now[latest]))
        db.execute("UPDATE chain_reply_receipts SET status='pending' WHERE chat=? AND message=? AND status='declined' AND fingerprint=?",(chat,latest,now[latest]))
    return True
