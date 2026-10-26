"""Encrypted durable error/skip notifications. No native/device code in delivery."""
DDL='''CREATE TABLE IF NOT EXISTS chain_exit_payloads(
 chat TEXT,signature TEXT,account TEXT,peer TEXT,body BLOB NOT NULL,photo BLOB,
 PRIMARY KEY(chat,signature))'''

def enqueue(chain,who,signature,text,photo,sender,photo_sender,cancelled):
    dispatcher=getattr(chain,'notification_dispatcher',None)
    if dispatcher is None:return False
    chain.store.ensure_tables(DDL)
    body=chain.seal(text.encode('utf-8'));image=chain.seal(photo) if photo is not None else None
    if not isinstance(body,bytes) or not body or image is not None and (not isinstance(image,bytes) or not image):raise ValueError('Notification protection failed')
    with chain.store.connection() as db:
        row=db.execute('SELECT status FROM chain_exit_notices WHERE chat=? AND signature=?',(who['chat'],signature)).fetchone()
        if row!=('attempted-unknown',):raise ValueError('Notification reservation changed')
        db.execute('INSERT OR IGNORE INTO chain_exit_payloads VALUES(?,?,?,?,?,?)',(who['chat'],signature,who['account'],who['peer'],body,image))
        db.execute("UPDATE chain_exit_notices SET status='queued' WHERE chat=? AND signature=? AND status='attempted-unknown'",(who['chat'],signature))
    dispatcher.exit_hint(chain,who,signature,sender,photo_sender,cancelled)
    return True

def resume(chain,sender,photo_sender,cancelled):
    dispatcher=getattr(chain,'notification_dispatcher',None)
    if dispatcher is None or sender is None:return
    chain.store.ensure_tables(DDL)
    with chain.store.read_connection() as db:
        rows=db.execute("""SELECT p.account,p.peer,p.chat,p.signature FROM chain_exit_payloads p
          JOIN chain_exit_notices n ON n.chat=p.chat AND n.signature=p.signature
          WHERE n.status='queued' ORDER BY p.chat,p.signature LIMIT 64""").fetchall()
    for account,peer,chat,signature in rows:
        dispatcher.exit_hint(chain,dict(account=account,peer=peer,chat=chat),signature,sender,photo_sender,cancelled)

def deliver(chain,who,signature,senders,cancelled):
    from mumu_peer_policy import manually_blocked
    from mumu_namespace import owns_account
    from one_chat_probe import identity
    who=identity(who)
    if cancelled():return 'cancelled'
    if not owns_account(chain.store,who) or manually_blocked(chain.store,who):return 'blocked'
    chain.authorized(who)
    with chain.store.connection() as db:
        row=db.execute("""SELECT p.body,p.photo FROM chain_exit_payloads p JOIN chain_exit_notices n
          ON n.chat=p.chat AND n.signature=p.signature WHERE p.account=? AND p.peer=? AND p.chat=? AND p.signature=? AND n.status='queued'""",
          (who['account'],who['peer'],who['chat'],signature)).fetchone()
        if row is None:return 'nothing-pending'
        try:
            text=chain.unseal(row[0]).decode('utf-8');photo=chain.unseal(row[1]) if row[1] is not None else None
            if not text or len(text)>950:raise ValueError()
            if photo is not None:
                from assistant_contact_photo import png_size
                png_size(photo)
        except Exception:
            db.execute("UPDATE chain_exit_notices SET status='blocked' WHERE chat=? AND signature=?",(who['chat'],signature));return 'blocked'
        db.execute("UPDATE chain_exit_notices SET status='attempted-unknown' WHERE chat=? AND signature=? AND status='queued'",(who['chat'],signature))
    # No replay after this durable reservation, including Stop/crash/unknown HTTP.
    sender,photo_sender=senders
    status='unknown'
    if manually_blocked(chain.store,who):status='blocked'
    elif not cancelled():
        try:status='accepted' if (photo_sender(text,photo) if photo is not None and photo_sender is not None else sender(text)) is True else 'unknown'
        except Exception:pass
    with chain.store.connection() as db:
        db.execute("UPDATE chain_exit_notices SET status=? WHERE chat=? AND signature=? AND status='attempted-unknown'",(status,who['chat'],signature))
        db.execute('DELETE FROM chain_exit_payloads WHERE chat=? AND signature=?',(who['chat'],signature))
    return status
