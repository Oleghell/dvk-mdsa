"""Read-only adoption of operator-led dialogs into the tracked inbox.

The operator starts and leads some chats himself, outside the send journal.
Those dialogs carry no greeting reservation and no guided binding, so the
dialog pass never opened them: replies piled up unread and voluntary contacts
(numbers sent by the peer) were never captured or notified. Adoption closes
that gap WITHOUT inventing a greeting authorization. The native open already
proves the row needs a reply; the fixed reader proves the bound history; the
structure check below proves the operator's own messages exist. Only then does
ONE durable binding row turn the chat into a normal journal target, and every
existing reply/contact/refusal gate then applies to it unchanged.

No chronology is inferred from collection positions or numeric message IDs.
The native Chat.LastMessage evidence (latest_message_id) must name exactly one
peer-owned message; the chain's behavior depends only on the seen set (every
current id except that verified latest) and the wait-reply stage. The recorded
anchor message is a durable participation proof, never a temporal claim.
"""
import secrets

from one_chat_probe import identity

TABLES = (
    'CREATE TABLE IF NOT EXISTS operator_bindings('
    'account TEXT,peer TEXT,chat TEXT UNIQUE,anchor_hash TEXT,PRIMARY KEY(account,peer))',
    'CREATE TABLE IF NOT EXISTS operator_rejects('
    'account TEXT,peer TEXT,chat TEXT UNIQUE,last_message TEXT,reason TEXT,PRIMARY KEY(account,peer))',
)


def ensure_tables(store):
    store.ensure_tables(*TABLES)


def _table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                      (name,)).fetchone() is not None


def tracked(store, who):
    """Real eligibility: guided binding, send journal or an operator adoption.

    Reject rows are skip markers only and never make a chat a target.
    """
    who = identity(who)
    with store.read_connection() as db:
        for table in ('guided_bindings', 'operator_bindings'):
            if (_table(db, table) and db.execute(
                    'SELECT 1 FROM ' + table + ' WHERE account=? AND peer=?',
                    (who['account'], who['peer'])).fetchone()):
                return True
        return bool(_table(db, 'manual_actions') and db.execute(
            'SELECT 1 FROM manual_actions WHERE account=? AND peer=? AND status!=?',
            (who['account'], who['peer'], 'not-invoked')).fetchone())


def reject_targets(store):
    """Pseudo-targets so the native scan skips rejected rows until their last
    message changes. Never real journal targets; deduplicated by the caller
    against the real target list before any transport upload.
    """
    if not _has_rejects(store):
        return []
    out = []
    with store.read_connection() as db:
        rows = db.execute('SELECT account,peer,chat,last_message FROM operator_rejects').fetchall()
    for account, peer, chat, last in rows:
        # A missing latest marker (unverified read) never skips anything: the
        # row simply retries on the next pass.
        if not isinstance(last, str) or not last:
            continue
        try:
            out.append(dict(account=account, peer=peer, chat=chat, seen_ids=[last]))
        except Exception:
            continue
    return out


def _has_rejects(store):
    with store.read_connection() as db:
        return _table(db, 'operator_rejects')


def record_reject(store, who, latest, reason):
    """One durable skip marker. A NEW last message reopens the row next pass."""
    who = identity(who)
    if isinstance(latest, str) and latest:
        pass
    else:
        latest = None
    with store.connection() as db:
        db.execute('INSERT OR REPLACE INTO operator_rejects VALUES(?,?,?,?,?)',
                   (who['account'], who['peer'], who['chat'], latest, reason))


def adopt(chain, snapshot):
    """Verify the structure and write ONE adoption binding atomically.

    Returns (True, 'adopted') or (False, reason). Never resets an existing
    chain, binding, reservation, receipt or review quarantine.
    """
    from one_chat_send import checked
    from assistant_chain import fingerprint, text_hash
    plain = checked({k: snapshot[k] for k in ('identity', 'messages')})
    who, messages = plain['identity'], plain['messages']
    latest = snapshot.get('latest_message_id')
    if type(latest) is not str or not latest:
        return False, 'latest-unverified'
    tail = [m for m in messages if m['id'] == latest and m['sender'] == who['peer']]
    if len(tail) != 1:
        return False, 'latest-not-peer'
    own = [m for m in messages if m['sender'] == who['account']
           and isinstance(m['text'], str) and m['text'].strip()]
    if not own:
        # A stranger-initiated chat the operator never answered is not ours.
        return False, 'no-own-messages'
    # The anchor records the operator's participation. WHICH own message is
    # chosen never affects chain logic: the seen set and the wait-reply stage
    # drive every later decision.
    anchor = own[-1]
    salt = secrets.token_hex(32)
    store = chain.store
    ensure_tables(store)
    with store.connection() as db:
        if db.execute('SELECT 1 FROM manual_actions WHERE account=? AND peer=?',
                      (who['account'], who['peer'])).fetchone():
            return False, 'journal-exists'
        if db.execute('SELECT 1 FROM guided_bindings WHERE account=? AND peer=?',
                      (who['account'], who['peer'])).fetchone():
            return False, 'guided-exists'
        if db.execute('SELECT 1 FROM operator_bindings WHERE account=? AND peer=?',
                      (who['account'], who['peer'])).fetchone():
            return False, 'already-adopted'
        if db.execute('SELECT 1 FROM chain_dialogs WHERE account=? AND peer=?',
                      (who['account'], who['peer'])).fetchone():
            return False, 'chain-exists'
        for table in ('chain_seen', 'chain_actions', 'chain_review_reasons'):
            if db.execute('SELECT 1 FROM ' + table + ' WHERE chat=?',
                          (who['chat'],)).fetchone():
                return False, 'persisted-state-protected'
        db.execute('INSERT INTO operator_bindings VALUES(?,?,?,?)',
                   (who['account'], who['peer'], who['chat'], text_hash(anchor['text'])))
        db.execute('INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)',
                   (who['account'], who['peer'], who['chat'], anchor['id'], 'wait-reply', salt))
        # Everything except the native-verified latest peer message is already
        # observed history; the latest becomes the one new incoming reply the
        # normal chain flow answers.
        for m in messages:
            if m['id'] != latest:
                db.execute('INSERT INTO chain_seen VALUES(?,?,?)',
                           (who['chat'], m['id'], fingerprint(m, salt)))
        db.execute('DELETE FROM operator_rejects WHERE chat=?', (who['chat'],))
    return True, 'adopted'


def probe(chain, who, read, cancelled, progress=lambda _text: None):
    """One read-only structure probe of an untracked dialog.

    Never stops the pass: a failed read is a benign skip that retries on the
    next pass; a structure reject records the last-message skip marker. Only a
    verified operator-led dialog receives the durable binding, after which the
    caller continues the normal per-chat flow in the SAME cycle.
    """
    ensure_tables(chain.store)
    who = identity(who)
    try:
        snapshot = read(who)
    except Exception:
        return 'read-failed'
    if cancelled():
        return 'cancelled'
    try:
        bound = identity(snapshot.get('identity')) if isinstance(snapshot, dict) else None
    except Exception:
        return 'read-failed'
    if bound != who or not isinstance(snapshot, dict):
        return 'read-failed'
    try:
        from mumu_namespace import ensure_account
        ensure_account(chain.store, snapshot['identity'])
    except Exception:
        # Ownership cannot be verified right now (including shared-database
        # pressure): retry on a later pass, never a reject and never a stop.
        return 'read-failed'
    try:
        adopted, reason = adopt(chain, snapshot)
    except Exception:
        # A structure/validation failure is never a pass-stopping device error.
        return 'read-failed'
    if adopted:
        progress('Диалог оператора подтверждён • привязываю и работаю дальше.')
        return 'adopted'
    record_reject(chain.store, who, snapshot.get('latest_message_id'), reason)
    return 'rejected'
