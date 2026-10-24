"""At most two additional outgoing attempts after the contact proposal.

An awaiting-approval draft is not a send. Unknown and returned reservations
still consume a slot, and are never erased/retried by this policy. Archived
observed followups count after restarts too. No peer text is persisted here.
"""
LIMIT = 2


def exhausted(db, chat):
    total = db.execute("SELECT COUNT(*) FROM chain_actions WHERE chat=? AND kind IN ('clarify','followup') AND status!='awaiting-approval'", (chat,)).fetchone()[0]
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chain_followup_archive'").fetchone():
        total += db.execute("SELECT COUNT(*) FROM chain_followup_archive WHERE chat=?", (chat,)).fetchone()[0]
    return total >= LIMIT


def can_close(db, chat, stage):
    # Never turn an unresolved send into a confirmed or retryable send.
    if stage == 'wait-contact':
        return exhausted(db, chat)
    if stage in ('pending-clarify','pending-followup'):
        row = db.execute('SELECT status FROM chain_actions WHERE chat=? AND kind=?',
                         (chat, stage.removeprefix('pending-'))).fetchone()
        return bool(row and row[0] == 'awaiting-approval' and exhausted(db, chat))
    return False
