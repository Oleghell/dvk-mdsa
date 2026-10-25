"""Durable encrypted AI drafts; network outside SQLite and never after send reservation."""
import json
from contextlib import nullcontext
from assistant_chain import text_hash
from groq_reply import GroqError, decision, continuation, public_context, MOOD_QUESTION, context_gate


def initialize(store):
    with store.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS ai_drafts(chat TEXT,kind TEXT,payload BLOB,status TEXT NOT NULL,PRIMARY KEY(chat,kind))')
        db.execute('CREATE TABLE IF NOT EXISTS ai_draft_inputs(chat TEXT,kind TEXT,message TEXT,PRIMARY KEY(chat,kind,message))')


def restore(chain, chat, kind, expected_hash, connection=None, snapshot=None):
    with (chain.store.connection() if connection is None else nullcontext(connection)) as db:
        row = db.execute('SELECT payload,status FROM ai_drafts WHERE chat=? AND kind=?', (chat, kind)).fetchone()
    if row is None or row[1] == 'needed':
        return None
    try:
        if row[1] != 'ready' or not isinstance(row[0], bytes) or len(row[0]) > 8192:
            raise ValueError()
        history=public_context(snapshot) if snapshot is not None else []
        value = decision(json.loads(chain.unseal(row[0])), kind,
            mood_asked=any(m['speaker']=='self' and MOOD_QUESTION.search(m['text']) for m in history))
        context_gate(value, history)
        if value['decision'] != 'reply' or text_hash(value['text']) != expected_hash:
            raise ValueError()
        return value['text']
    except GroqError as error:
        # Old prepared text is never silently rehashed/replaced. Block just this
        # chat if it contains a repeated greeting or cannot restore a validated draft.
        if str(error) == 'groq-repeat-greeting':
            raise
        raise GroqError('groq-draft-unavailable') from None
    except Exception:
        raise GroqError('groq-draft-unavailable') from None


def prepare(chain, snapshot, action):
    chat, kind = snapshot['identity']['chat'], action['kind']
    from assistant_contact_clarify import MAX_TEXT,max_selected,NUMBER_TEXT,indifferent_selected,alternative_text,selected_alternative_text
    forced_max = kind=='clarify' and max_selected([m for m in snapshot['messages'] if m['sender']==snapshot['identity']['peer']])
    with chain.store.connection() as db:
        forced_number = kind=='clarify' and indifferent_selected(db,snapshot)
        selected_text=selected_alternative_text(db,snapshot) if kind=='clarify' else None
        forced_text = MAX_TEXT if forced_max else selected_text or (NUMBER_TEXT if forced_number else None)
        row = db.execute('SELECT status FROM ai_drafts WHERE chat=? AND kind=?', (chat, kind)).fetchone()
        if row is None:
            if chain.responder is None and not forced_text:
                return None, action
            db.execute("INSERT INTO ai_drafts VALUES(?,?,NULL,'needed')", (chat, kind))
            trigger = db.execute('SELECT trigger FROM chain_actions WHERE chat=? AND kind=?', (chat,kind)).fetchone()
            if trigger:
                db.execute('INSERT OR IGNORE INTO ai_draft_inputs VALUES(?,?,?)', (chat,kind,trigger[0]))
    if row is not None and chain.responder is None and not forced_text:
        raise GroqError('groq-configuration-required')
    text = restore(chain, chat, kind, text_hash(action['text']), snapshot=snapshot)
    if text is not None:
        if forced_text and text != forced_text:raise GroqError('groq-draft-unavailable')
        return None, dict(kind=kind, text=text)
    if chain.responder is None and not forced_text:
        raise GroqError('groq-configuration-required')
    # Only generated drafts may be retried after an API failure, not sends.
    with chain.store.connection() as db:
        reply_ids = [r[0] for r in db.execute('SELECT message FROM ai_draft_inputs WHERE chat=? AND kind=?', (chat,kind))]
    context = dict(snapshot, _reply_ids=reply_ids)
    value = continuation(dict(decision='reply',text=forced_text) if forced_text else chain.responder(kind, context), kind, snapshot=context)
    if value['decision'] != 'reply':
        stage = 'declined' if value['decision'] == 'decline' else 'manual-review'
        with chain.store.connection() as db:
            db.execute("UPDATE chain_dialogs SET stage=? WHERE chat=? AND stage=?", (stage, chat, 'pending-' + kind))
            db.execute("UPDATE ai_drafts SET status='blocked' WHERE chat=? AND kind=?", (chat, kind))
            if stage == 'manual-review':
                db.execute("INSERT INTO chain_review_reasons VALUES(?,'ai-context-review') ON CONFLICT(chat) DO NOTHING",(chat,))
        return stage, None
    try:
        payload = chain.seal(json.dumps(value, ensure_ascii=False).encode())
        if not isinstance(payload, bytes) or not payload or len(payload) > 8192:
            raise ValueError()
    except Exception:
        raise GroqError('groq-draft-protection-failed') from None
    with chain.store.connection() as db:
        cur = db.execute("UPDATE chain_actions SET text_hash=? WHERE chat=? AND kind=? AND text_hash=? AND status='awaiting-approval'",
                         (text_hash(value['text']), chat, kind, text_hash(action['text'])))
        if cur.rowcount != 1:
            raise GroqError('groq-draft-unavailable')
        db.execute("UPDATE ai_drafts SET payload=?,status='ready' WHERE chat=? AND kind=? AND status='needed'", (payload, chat, kind))
    return None, dict(kind=kind, text=value['text'])
