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
    # snapshot stays part of the fixed contract even though the v1.3.84 fix no
    # longer reads the clarify journal row here; callers pass the verified
    # binding and the signature must not drift per release.
    if stage not in ('wait-contact','pending-contact','pending-clarify','pending-followup'):return False
    if not requested or not active(db):return False
    # Prepared contextual drafts from older versions must not reach approval.
    # Their hashes/statuses are retained, including unknown attempts.
    if stage=='pending-followup':return True
    if not incoming:return False
    from assistant_contact_clarify import chosen
    from assistant_contact_intent import visible,APP
    import re
    from assistant_contact_intent import WA as _WA_SPELLINGS
    for message in incoming:
        text=visible(message.get('text'))
        for clause in re.split(r'[?？]',text)[:-1]:
            # A personal/off-topic question is not messenger selection, even
            # when another message in this same packet names an available app.
            personal=re.search(r'женат|замужем|откуда|живешь|живёшь|работаешь|занимаешься|каком городе',clause)
            # Reports y8zZxWkA (v1.3.73): «Есть? / Макс» closed the chain. The
            # bare availability echo answers our own contact proposal («Ты
            # есть в телеграме или ватцапе?»), so it stays contact-related;
            # the packet's messenger choice then drives one clarification.
            echo=re.fullmatch(r'(?:а\s+)?(?:у\s+(?:тебя|вас)\s+)?(?:ты\s+|вы\s+)?есть'
                              r'(?:\s+(?:что-?нибудь|какие?[-\s]?нибудь\s+мессенджеры))?',clause.strip())
            # Reports aPYyN7weMm (v1.3.78): the whole WhatsApp spelling family
            # (вотсап/вотапп/…) keeps such clauses contact-related instead of
            # letting an unrecognized spelling close the chain as off-topic.
            related=APP.search(clause) or re.search(r'телеграм|telegram|'+_WA_SPELLINGS+r'|whatsapp|\bтг\b|номер|контакт|мессенджер',clause)
            if personal or not (related or echo):return True
    choice=chosen(incoming)
    if stage=='pending-clarify':return not choice
    # Reports MuMu-5563 (v1.3.84): «Я в Максе сижу» closed the chain as declined
    # both before and after the one clarification. A RECOGNIZED fresh choice
    # (messenger, MAX presence or number indifference) is not an off-topic
    # arrival: the chain stays open so the app-specific number question can be
    # asked instead of closing without a new answer. Unrecognized off-topic
    # text still closes exactly as before, and current contacts are handled
    # BEFORE this policy.
    return not (choice or max_choice or number_choice)
