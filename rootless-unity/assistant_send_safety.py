"""Bounded pre-invocation retries, never replay an unknown/entered native send.

Append-only per-authorization checks retain every old reservation and hash.
Only validated native no-invocation evidence can release THIS new authorization
back to an unsent draft; no screen text, timeout or absent message proves that.
"""
import secrets
from assistant_store import StateError
from assistant_chain import text_hash
from one_chat_send import no_submission_proof

MAX_PREFLIGHT_CHECKS=3


def tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS chain_send_authorizations(
      session TEXT PRIMARY KEY,chat TEXT NOT NULL,kind TEXT NOT NULL,text_hash TEXT NOT NULL,status TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS chain_send_attempts(
      id INTEGER PRIMARY KEY,session TEXT NOT NULL,outcome TEXT NOT NULL,error TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')


def authorize(db,who,action):
    tables(db);session=secrets.token_hex(32)
    db.execute("INSERT INTO chain_send_authorizations VALUES(?,?,?,?,'active')",
        (session,who['chat'],action['kind'],text_hash(action['text'])))
    return session


def matching(db,session,who,action):
    row=db.execute('SELECT chat,kind,text_hash,status FROM chain_send_authorizations WHERE session=?',(session,)).fetchone()
    if row!=(who['chat'],action['kind'],text_hash(action['text']),'active'):
        raise StateError('send-authorization-changed')
    row=db.execute('SELECT status,text_hash FROM chain_actions WHERE chat=? AND kind=?',
        (who['chat'],action['kind'])).fetchone()
    stage=db.execute('SELECT stage FROM chain_dialogs WHERE chat=?',(who['chat'],)).fetchone()
    if row!=('reserved-unknown',text_hash(action['text'])) or stage!=('pending-'+action['kind'],):
        raise StateError('send-reservation-changed')


def begin(chain,session,who,action):
    with chain.store.connection() as db:
        from mumu_peer_policy import ensure_communication_allowed
        ensure_communication_allowed(chain.store,who,db=db)
        matching(db,session,who,action)
        return db.execute("INSERT INTO chain_send_attempts(session,outcome) VALUES(?,'unknown')",(session,)).lastrowid


def completed(chain,session,attempt,result,proof):
    returned=isinstance(result,dict) and result.get('attempted') is True and result.get('handler_returned') is True
    outcome='not-invoked' if proof is not None else 'handler-returned' if returned else 'unknown'
    with chain.store.connection() as db:
        changed=db.execute("UPDATE chain_send_attempts SET outcome=?,error=? WHERE id=? AND session=? AND outcome='unknown'",
            (outcome,proof,attempt,session)).rowcount
        if changed!=1:raise StateError('send-attempt-changed')
        if proof is None:
            db.execute("UPDATE chain_send_authorizations SET status=? WHERE session=? AND status='active'",(outcome,session))


def defer_uninvoked(chain,session,who,action):
    with chain.store.connection() as db:
        matching(db,session,who,action)
        rows=db.execute('SELECT outcome FROM chain_send_attempts WHERE session=?',(session,)).fetchall()
        if not rows or any(row!=('not-invoked',) for row in rows):
            raise StateError('send-no-invocation-unverified')
        changed=db.execute("UPDATE chain_actions SET status='awaiting-approval' WHERE chat=? AND kind=? AND text_hash=? AND status='reserved-unknown'",
            (who['chat'],action['kind'],text_hash(action['text']))).rowcount
        if changed!=1:raise StateError('send-reservation-changed')
        db.execute("UPDATE chain_send_authorizations SET status='not-invoked' WHERE session=? AND status='active'",(session,))


def submit_checked(chain,session,who,action,before,sender,stopped,progress,diagnostics):
    for index in range(MAX_PREFLIGHT_CHECKS):
        attempt=begin(chain,session,who,action)  # durable unknown BEFORE any adapter
        # Exception/missing/invalid result leaves this check unknown forever.
        from one_chat_send_device import SubmissionNotStarted
        try:
            result=sender(before,action['text'])
            proof=no_submission_proof(result)
        except SubmissionNotStarted:
            # Only this fixed adapter exception attests that root was not called.
            # A generic timeout/ReadStopped/forged native flag never qualifies.
            result=dict(attempted=False,handler_returned=False)
            proof='send-setup-unavailable'
        completed(chain,session,attempt,result,proof)
        if proof is None:return result,False
        diagnostics.update(submission_attempted=False,submission_returned=False,last_send_failure=proof,
            send_preflight_retries=index)
        if proof=='submission-snapshot-changed' or index==MAX_PREFLIGHT_CHECKS-1 or stopped.is_set():
            defer_uninvoked(chain,session,who,action)
            diagnostics['send_no_invocation_verified']=True
            return result,True
        progress('Отправка ещё не вызывалась • повторяю проверку того же чата, без повторной отправки.')
        if stopped.wait(.2):
            defer_uninvoked(chain,session,who,action)
            diagnostics['send_no_invocation_verified']=True
            return result,True
    raise AssertionError('Preflight check limit')
