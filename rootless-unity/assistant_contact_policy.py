"""Durable MuMu contact-only boundary. No generic post-proposal conversation."""
def enable(store):
    from assistant_reply_window import tables
    with store.connection() as db:
        tables(db)
        db.execute("INSERT OR REPLACE INTO inbox_reply_policy VALUES('contact-only',1)")


def active(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inbox_reply_policy'").fetchone()
        and db.execute("SELECT 1 FROM inbox_reply_policy WHERE key='contact-only' AND value=1").fetchone())


def should_close(db, snapshot, stage, incoming, *, requested, max_choice=False, number_choice=False):
    if stage not in ('wait-contact','pending-contact','pending-clarify','pending-followup'):return False
    if not requested or not active(db):return False
    # Prepared contextual drafts from older versions must not reach approval.
    # Their hashes/statuses are retained, including unknown attempts.
    if stage=='pending-followup':return True
    if not incoming:return False
    chat=snapshot['identity']['chat']
    clarify=db.execute("SELECT 1 FROM chain_actions WHERE chat=? AND kind='clarify'",(chat,)).fetchone()
    from assistant_contact_clarify import chosen
    from assistant_contact_intent import visible,APP
    import re
    for message in incoming:
        text=visible(message.get('text'))
        for clause in re.split(r'[?？]',text)[:-1]:
            # A personal/off-topic question is not messenger selection, even
            # when another message in this same packet names an available app.
            personal=re.search(r'женат|замужем|откуда|живешь|живёшь|работаешь|занимаешься|каком городе',clause)
            related=APP.search(clause) or re.search(r'телеграм|telegram|ватсап|ватцап|whatsapp|\bтг\b|номер|контакт|мессенджер',clause)
            if personal or not related:return True
    choice=chosen(incoming)
    if stage=='pending-clarify':return not choice
    if clarify:return True # current contacts are handled BEFORE this policy
    return not (choice or max_choice or number_choice)
