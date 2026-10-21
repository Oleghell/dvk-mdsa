"""«Старт», step 1: unread chats that already belong to the message chain.

Only chats with OUR greeting are eligible: an explicit guided binding or a
greeting recorded in the send journal. Each outgoing message needs its own
confirmation; unknown sends and notifications are never retried. Message
bodies stay in RAM; the report holds counters only.
"""
from assistant_chain import Chain, TERMINAL
from assistant_guided_chain import GuidedChain, walk as walk_chat
from assistant_store import StateError
from dialog_browser import targets
from one_chat_probe import identity
from version import VERSION

LIMIT = 10
PAUSE_OUTCOMES = {'message-not-approved', 'manual-review', 'telegram-disabled',
                  'telegram-outcome-unknown', 'contact-payload-blocked'}
CONTINUE = {'chain-waiting', 'chain-completed', 'chain-needs-review', 'chain-paused'}


class InboxChain(GuidedChain):
    """Guided chain that also accepts peers greeted through «Новые анкеты»."""

    def _guided(self, who):
        with self.store.connection() as db:
            return db.execute('SELECT 1 FROM guided_bindings WHERE account=? AND peer=?',
                              (who['account'], who['peer'])).fetchone() is not None

    def authorized(self, who):
        who = identity(who)
        if self._guided(who):
            return super().authorized(who)
        try:
            return Chain.authorized(self, who)
        except StateError:
            raise StateError('guided-binding-not-authorized') from None

    def bind(self, snapshot, greetings, *, approved=False):
        if approved is not True:
            raise StateError('guided-consent-required')
        who = identity(snapshot['identity'])
        if self._guided(who):
            return super().bind(snapshot, greetings, approved=True)
        try:
            Chain.authorized(self, who)
        except StateError:
            # Not in the send journal: only the guided fresh-greeting binding.
            return super().bind(snapshot, greetings, approved=True)
        # The journal already proves our greeting went to an empty chat; the
        # base chain anchors that exact greeting (hash) on first consumption.


def inbox_targets(chain):
    """Return (attention, unread) target lists. Terminal chats are excluded."""
    with chain.store.connection() as db:
        rows = db.execute('''
          WITH sources(account,peer,chat) AS (
            SELECT account,peer,chat FROM guided_bindings
            UNION ALL
            SELECT m.account,m.peer,m.initial_chat FROM manual_actions m
            WHERE m.status!='not-invoked' AND NOT EXISTS (
              SELECT 1 FROM guided_bindings g WHERE g.account=m.account AND g.peer=m.peer))
          SELECT s.account,s.peer,COALESCE(c.chat,s.chat),c.stage,
            EXISTS(SELECT 1 FROM chain_contact_outbox o WHERE o.chat=c.chat AND o.status='pending'),
            EXISTS(SELECT 1 FROM chain_actions a WHERE a.chat=c.chat
                   AND a.status IN ('awaiting-approval','handler-returned-unconfirmed'))
          FROM sources s LEFT JOIN chain_dialogs c ON c.account=s.account AND c.peer=s.peer
          ORDER BY s.account,s.peer''').fetchall()
    attention, unread = [], []
    for account, peer, chat, stage, outbox, pending in rows:
        item = dict(account=account, peer=peer, chat=chat)
        if stage == 'done' and outbox:
            attention.append(item)  # contact received, Telegram not yet sent
        elif stage in TERMINAL:
            continue
        elif pending or (stage or '').startswith('pending-'):
            attention.append(item)  # unconfirmed draft or unobserved outgoing
        else:
            unread.append(item)
    return targets(attention), targets(unread)


def report():
    return dict(tool_version=VERSION, mode='inbox-chain-pass', status='inbox-stopped',
                reason='not-started', dialog_limit=LIMIT, dialogs_opened=0,
                dialogs_processed=0, read_rows_skipped=0, confirmations=0,
                submission_calls=0, handler_returns=0, outgoing_observed=0, contacts_forwarded=0,
                outcomes={}, per_message_confirmation=True, automatic_send=False,
                return_verified=False, dialogs_verified=False, delivery_confirmed=False,
                all_dialogs_covered=False, ui_may_remain_open=False,
                personal_data_exported=False, chat_content_exported=False,
                device_scope='MuMu-4-only', last_navigation=None)


def walk(settings, stopped, approve, progress, chain, *, navigator, reader, sender,
         notifier=None, greetings=(), pause=None, entry='search', return_to='search'):
    from assistant_navigation_check import safe_diagnostic
    if entry not in ('search', 'dialogs') or return_to not in ('search', 'dialogs'):
        raise ValueError('Invalid inbox screen')
    out = report()
    attention, unread = inbox_targets(chain)
    if not attention and not unread:
        out.update(status='inbox-empty', reason='no-chain-dialogs')
        return out

    def call(operation, **kwargs):
        if stopped.is_set():
            raise StateError('cancelled')
        out['ui_may_remain_open'] = True
        value = navigator(operation, settings.adb, settings.folder, stopped.is_set, **kwargs)
        if not isinstance(value, dict) or set(value) != {'state', 'identity', 'diagnostic'}:
            raise ValueError('Invalid navigation result')
        n = out['last_navigation'] = safe_diagnostic(value['diagnostic'])
        if value['state'] == 'stopped':
            raise StateError('navigation-stopped')
        if n['stage'] != 'navigation-ready' or n['error'] != 'none' or not n['destination_verified']:
            raise ValueError('Unverified navigation')
        if value['state'] not in {'open': {'opened', 'exhausted'}, 'back': {'returned'},
                                  'return': {'search-ready'}}[operation]:
            raise ValueError('Unexpected navigation state')
        if operation == 'open' and kwargs['unread_only']:
            if not n['unread_filter_applied'] or n['unread_verified'] != (value['state'] == 'opened'):
                raise StateError('unread-selection-not-verified')
            out['read_rows_skipped'] += n['read_rows_skipped']
        who = identity(value['identity']) if value['identity'] is not None else None
        if (value['state'] in ('opened', 'returned')) != (who is not None):
            raise ValueError('Invalid navigation binding')
        if operation == 'open' and who is not None and not any(
                x['account'] == who['account'] and x['peer'] == who['peer'] and
                (int(x['chat']) <= 0 or x['chat'] == who['chat']) for x in kwargs['allowed']):
            raise StateError('untracked-dialog')
        if operation == 'back' and who != kwargs['expected']:
            raise StateError('changed-dialog')
        return value

    def count(outcome):
        out['outcomes'][outcome] = out['outcomes'].get(outcome, 0) + 1

    phase = 'navigation'
    try:
        reason = 'visible-pass-limit'
        groups = [(attention, False), (unread, True)]
        while out['dialogs_opened'] < LIMIT and groups:
            allowed, unread_only = groups[0]
            if not allowed:
                groups.pop(0)
                continue
            phase = 'navigation'
            progress(f'Ответы: открываю чат {out["dialogs_opened"] + 1}. '
                     'Каждое сообщение — только после твоего подтверждения.')
            selected = call('open', allowed=allowed, entry=entry, unread_only=unread_only)
            entry = 'dialogs'
            if selected['state'] == 'exhausted':
                groups.pop(0)
                continue
            who = identity(selected['identity'])
            out['dialogs_opened'] += 1
            phase = 'chat'
            result = walk_chat(
                chain, who, stopped, approve,
                lambda expected: reader(settings.adb, settings.folder, stopped.is_set, expected),
                lambda snapshot, text: sender(settings.adb, settings.folder, snapshot,
                                              stopped.is_set, text=text),
                approved=True, greetings=greetings, notifier=notifier, progress=progress,
                pause=pause, max_polls=8, until_waiting=True,
                contact_reader=lambda expected: reader(settings.adb, settings.folder,
                                                       stopped.is_set, expected, read_name=True))
            for key in ('confirmations', 'submission_calls', 'handler_returns'):
                out[key] += result[key]
            out['outgoing_observed'] += result['outgoing_observed_this_run']
            out['contacts_forwarded'] += result['notifications']['accepted']
            if result['telegram_used']:
                out['personal_data_exported'] = True
            count(result['reason'] if result['status'] != 'chain-waiting' else result['status'] + ':' + result['reason'])
            if result['status'] == 'chain-cancelled' or stopped.is_set():
                raise StateError('cancelled')
            if result['status'] not in CONTINUE:
                # Unknown send, unobserved outgoing or a changed chat: never
                # continue blindly. The chat is left open for a manual check.
                out.update(status='inbox-stopped', reason='chat-' + result['reason'])
                return out
            phase = 'navigation'
            call('back', expected=who)
            out['dialogs_processed'] += 1
            for group in groups:
                group[0][:] = [x for x in group[0] if (x['account'], x['peer']) != (who['account'], who['peer'])]
            if result['reason'] in PAUSE_OUTCOMES:
                reason = 'needs-review'
                break  # No further approval prompts in this pass after No/timeout.
        else:
            reason = 'visible-exhausted' if not groups else 'visible-pass-limit'
        phase = 'navigation'
        if return_to == 'search':
            call('return')
        out.update(status='inbox-completed', reason=reason, return_verified=return_to == 'search',
                   dialogs_verified=return_to == 'dialogs',
                   ui_may_remain_open=False)
    except Exception as error:
        n = out['last_navigation']
        out.update(status='inbox-cancelled' if stopped.is_set() else 'inbox-stopped',
                   reason='cancelled' if stopped.is_set() else
                   str(error) if isinstance(error, StateError) and str(error) in
                   {'unread-selection-not-verified', 'untracked-dialog', 'changed-dialog',
                    'navigation-stopped'} else
                   n['error'] if n and n['error'] != 'none' else phase + '-check-stopped')
    return out


def run(settings, stopped, approve, progress=lambda _: None, *, store=None, navigator=None,
        reader=None, sender=None, notifier=None, greetings=None, pause=None,
        entry='search', return_to='search'):
    """Caller must hold the shared device lock."""
    from assistant_config import load
    from assistant_store import Store
    from dialog_browser import perform
    from one_chat_device import capture
    from one_chat_send_device import submit
    import telegram_notify
    if stopped.is_set():
        return dict(report(), status='inbox-cancelled', reason='cancelled')
    if notifier is None and settings.contacts_enabled:
        token, chat_id = telegram_notify.load()
        notifier = lambda payload: telegram_notify.send_contact(token, chat_id, payload)
    chain = InboxChain(Store() if store is None else store)
    return walk(settings, stopped, approve, progress, chain,
                navigator=perform if navigator is None else navigator,
                reader=capture if reader is None else reader,
                sender=submit if sender is None else sender,
                notifier=notifier, pause=pause, entry=entry, return_to=return_to,
                greetings=load().greetings if greetings is None else greetings)
