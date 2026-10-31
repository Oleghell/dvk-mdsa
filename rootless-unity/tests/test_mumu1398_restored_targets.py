"""v1.3.98: «почему при запуске оно заходит в прочитанные чаты когда этого не
должно быть как я описывал ранее?»

The reported startup shape, reproduced end to end: a TRACKED chat that this
round's target lists no longer carry is still OPENED by the native
needs-reply filter (its last message is the peer's and the row carries live
incoming work), and the walk's stray branch used to leave it read-only with
NO marker, NO cooldown and NO chain visit - so every later pass reset
adoption and re-entered the SAME read state, twice per pass, at EVERY
startup, with zero submissions. The 1.3.90 comment named the false
assumption itself («Active (non-terminal) strays never get one: a cooldown
or reply window must re-admit them unchanged»): a tracked stray is not
always under a deliberate exclusion, and one that is not is live work the
filter just proved.

This file pins the restored-target contract:

1. the reported carousel - a targetless tracked chat with her new message is
   opened ONCE, answered (the receipt resolves), and the next pass opens
   nothing: ours-last keeps the row a waiting row («в то же состояние не
   захожу, только в новое»);
2. a DELIBERATE exclusion (an active history cooldown) still leaves the row
   read-only - the 1.3.88 semantics the branch was built for;
3. a TERMINAL stray still records its durable marker and never re-opens -
   the 1.3.90 contract;
4. the operator adoption probe is untouched: an untracked her-last chat is
   probed once, rejected with a marker, and skipped afterwards.

The navigator here implements the exact admission semantics of
dialog_browser.py's scan() (permitted/needs-reply-only/alreadyHandled over
the uploaded target list), so the re-open behavior is DRIVEN by the walk's
own upload, not scripted. Synthetic only; no device, database or worker.
"""
import copy
import unittest
from unittest.mock import patch

import assistant_inbox as inbox
import assistant_history_wait as wait
import assistant_reply_audit as audit
from conversation_engine import QUESTIONS
from test_assistant_dialogs import diag
from test_inbox_profiles import OTHER, Base, GREETING, WHO, msg


def nav_result(state, who=None, **diagnostic):
    value = dict(state=state, identity=dict(who) if who else None, diagnostic=diag())
    value['diagnostic'].update(reply_filter_applied=True,
                               reply_needed_verified=state == 'opened',
                               unread_filter_applied=True,
                               unread_verified=state == 'opened',
                               **diagnostic)
    return value


class App:
    """The simulated dialog list: one row per chat with its full history."""

    def __init__(self, *whos):
        self.rows = {who['peer']: dict(who=who, history=[msg(1001, GREETING, True)]) for who in whos}
        self._next = 5000

    def receive(self, who, text):
        row = self.rows[who['peer']]
        self._next += 1
        row['history'].append(msg(self._next, text, False, who))

    def send(self, who, text):
        row = self.rows[who['peer']]
        self._next += 1
        row['history'].append(msg(self._next, text, True, who))

    def last(self, who):
        message = self.rows[who['peer']]['history'][-1]
        return message['id'], message['sender'] == who['account']

    def snapshot(self, who, read_name=False):
        row = self.rows[who['peer']]
        value = dict(identity=dict(who), messages=copy.deepcopy(row['history']),
                     latest_message_id=row['history'][-1]['id'])
        if read_name:
            value['peer_name'] = 'Тест'
        return value


class NativeNav:
    """dialog_browser.py's scan() admission over the simulated rows."""

    def __init__(self, app, log):
        self.app, self.log = app, log

    def __call__(self, operation, adb, folder, cancelled, **kwargs):
        if operation != 'open':
            if operation == 'back':
                return nav_result('returned', kwargs['expected'])
            return nav_result('search-ready')
        allowed = kwargs['allowed']
        hidden = kwargs.get('hidden') or ()
        adopt = kwargs.get('adopt_untracked')
        hidden_set = {x['account'] + ':' + x['peer'] for x in hidden}
        hidden_set |= {'*:' + x['peer'] for x in hidden if x['account'] == '*'}
        waiting = handled = 0
        for who in (row['who'] for row in self.app.rows.values()):
            if who['account'] + ':' + who['peer'] in hidden_set or '*:' + who['peer'] in hidden_set:
                continue
            if not (adopt or any(x['account'] == who['account'] and x['peer'] == who['peer']
                                 and (int(x['chat']) <= 0 or x['chat'] == who['chat']) for x in allowed)):
                continue
            last_id, ours = self.app.last(who)
            if ours:
                waiting += 1
                continue
            if any(x['account'] == who['account'] and x['peer'] == who['peer']
                   and (int(x['chat']) <= 0 or x['chat'] == who['chat'])
                   and last_id in (x.get('seen_ids') or []) for x in allowed):
                handled += 1
                continue
            self.log.append(who['peer'])
            return nav_result('opened', who, selected_message=last_id,
                              waiting_rows_skipped=waiting, handled_rows_skipped=handled,
                              rows_scanned=len(self.app.rows))
        return nav_result('exhausted', None, waiting_rows_skipped=waiting,
                          handled_rows_skipped=handled, rows_scanned=len(self.app.rows))


class RestoredTargets(Base):

    def drive(self, app, chain=None, targetless=True):
        """One inbox pass driven by the real admission over the simulated rows."""
        opened = []
        chain = chain or self.chain()

        def reader(adb, folder, cancelled, expected, **kw):
            return app.snapshot(expected, read_name=kw.get('read_name', False))

        def sender(adb, folder, snapshot, cancelled, *, text):
            self.sent.append((snapshot['identity']['peer'], text))
            app.send(snapshot['identity'], text)
            return dict(attempted=True, handler_returned=True)

        targets = (lambda c: ([], [dict(OTHER)])) if targetless else inbox.inbox_targets
        with patch.object(inbox, 'inbox_targets', targets):
            out = inbox.walk(self.settings, self.stop, self.approve, lambda _: None, chain,
                             navigator=NativeNav(app, opened), reader=reader, sender=sender,
                             notifier=self.notifier, greetings=(GREETING,), pause=lambda _: False)
        return out, opened

    def test_targetless_tracked_chat_is_answered_once_never_reentered(self):
        # THE reported startup carousel: WHO is tracked, her new message is
        # live work, but this round's target lists drop WHO entirely (the
        # same state the operator's own adopted dialogs fall into when their
        # target entry goes missing). The native filter still proves the row
        # needs a reply: the pass must ANSWER her once - not open her read
        # chat twice with zero work - and the next pass must open nothing.
        self.journal()
        self.journal(OTHER)
        app = App(WHO, OTHER)
        app.receive(WHO, 'Привет')
        first, opened = self.drive(app)
        self.assertEqual(first['status'], 'inbox-completed')
        self.assertEqual(opened, [WHO['peer']])
        self.assertEqual(first['restored_target_rows'], 1)
        self.assertEqual(self.sent, [(WHO['peer'], QUESTIONS[0])])
        self.assertEqual(audit.pending(self.chain(), WHO), [])
        with self.store.read_connection() as db:
            stage = db.execute('SELECT stage FROM chain_dialogs WHERE peer=?', (WHO['peer'],)).fetchone()[0]
        self.assertEqual(stage, 'wait-mood')
        # The next startup pass - the target list STILL drops WHO - opens
        # nothing: ours-last keeps the row a waiting row the admission skips.
        self.sent.clear()
        second, opened2 = self.drive(app)
        self.assertEqual(second['status'], 'inbox-completed')
        self.assertEqual(opened2, [])
        self.assertEqual(second['dialogs_opened'], 0)
        self.assertEqual(self.sent, [])

    def test_active_cooldown_stray_stays_read_only(self):
        # The 1.3.88 semantics the stray branch exists for: a chat under an
        # ACTIVE history cooldown is deliberately out of this round - the
        # native may open it, but the walk leaves it read-only (the second
        # entry is the designed adoption switch-off revisit) and the cooldown
        # ladder re-admits it to finish the owed answer later.
        self.journal()
        self.journal(OTHER)
        app = App(WHO, OTHER)
        app.receive(WHO, 'Привет')
        wait.initialize(self.store)
        wait.defer(self.store, WHO)
        first, opened = self.drive(app)
        self.assertEqual(first['status'], 'inbox-completed')
        self.assertLessEqual(opened.count(WHO['peer']), 2)
        self.assertLessEqual(opened.count(WHO['peer']), 2)
        self.assertEqual(first['restored_target_rows'], 0)
        self.assertEqual(self.sent, [])

    def test_terminal_stray_keeps_marker_and_read_only_leave(self):
        # The 1.3.90 contract under the new branch: a TERMINAL chat without
        # consumed-id evidence or an automatic-outcome marker (a contact kept
        # with delivery disabled, a review quarantine before consume) is still
        # opened once by adoption, left read-only, and its durable marker
        # stops every later re-entry until a genuinely NEW message arrives.
        self.journal()
        self.journal(OTHER)
        app = App(WHO, OTHER)
        app.receive(WHO, 'Мой ватсап 89991234567')
        self.store.ensure_tables(
            'CREATE TABLE IF NOT EXISTS chain_dialogs(account TEXT,peer TEXT,chat TEXT UNIQUE,'
            'greeting TEXT,stage TEXT,salt TEXT,PRIMARY KEY(account,peer))')
        with self.store.connection() as db:
            db.execute("INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)",
                       (WHO['account'], WHO['peer'], WHO['chat'], '1001', 'done', 'salt'))
        first, opened = self.drive(app)
        self.assertEqual(first['status'], 'inbox-completed')
        self.assertEqual(opened, [WHO['peer']])
        self.assertEqual(first['terminal_row_markers'], 1)
        self.assertEqual(first['restored_target_rows'], 0)
        self.assertEqual(self.sent, [])
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT reason FROM operator_rejects WHERE peer=?',
                                        (WHO['peer'],)).fetchone()[0], 'terminal-state')
        second, opened2 = self.drive(app)
        self.assertEqual(opened2, [])
        self.assertEqual(second['dialogs_opened'], 0)

    def test_untracked_operator_chat_probe_is_unchanged(self):
        # The adoption probe (v1.3.84) is untouched by the restored-target
        # branch: an UNTRACKED her-last chat the operator never answered is
        # probed once, rejected with a durable marker, and never re-opened
        # until its last message changes.
        self.journal(OTHER)
        app = App(OTHER)
        app.rows[WHO['peer']] = dict(who=WHO, history=[msg(4102, 'Она написала сама', False, WHO)])
        first, opened = self.drive(app)
        self.assertEqual(first['status'], 'inbox-completed')
        self.assertEqual(opened, [WHO['peer']])
        self.assertEqual(first['operator_probed'], 1)
        self.assertEqual(first['operator_rejected'], 1)
        self.assertEqual(first['restored_target_rows'], 0)
        self.assertEqual(self.sent, [])
        second, opened2 = self.drive(app)
        self.assertEqual(opened2, [])
        self.assertEqual(second['dialogs_opened'], 0)


if __name__ == '__main__':
    unittest.main()
