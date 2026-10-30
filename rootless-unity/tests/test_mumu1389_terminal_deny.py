"""v1.3.89 regressions: finished chats stop riding the idle reopen walk.

Reported symptom: «когда все чаты прочитаны и обработаны оно повторно почему
заходит в них на секунду и выходит по очереди, пофикси это чтобы чекало новые
анкеты а не в холостую проходило по чатам с которыми уже проведена работа».

Root cause (the part 1.3.88 could not see): the native needs-reply filter
answers "handled" only from THIS round's journal targets. A FINISHED chat
(contact received -> done, refusal accepted -> declined, operator quarantine
-> manual-review) is deliberately not a target, so alreadyHandled() answered
false for it - and adoption mode, reset at every pass start, admitted ANY
non-hidden row. Every finished chat whose last message is the peer's (a
refusal, a delivered contact) was opened for a second, left read-only by a
verified Back, counted as processed work, and reopened the SAME way on the
next pass: a sequential idle walk through dozens of finished rows between
profile batches. Terminal peers now ride every open as deny-with-evidence
rows (their consumed message ids), so the scan skips them in every mode until
a GENUINELY new message changes the row's last message.
"""
from pathlib import Path
import tempfile
import threading
import unittest

import assistant_inbox as inbox
from conversation_engine import QUESTIONS
from mumu_store import SharedStore
from test_inbox_profiles import Base, WHO, msg, nav, snap


OTHER = dict(account='100', peer='201', chat='301')
THIRD = dict(account='100', peer='202', chat='302')


def shared(base, port=5559):
    return SharedStore(base.store.path, Path(base.tmp.name) / 'old', device_port=port)


class TerminalDenySources(unittest.TestCase):
    """The deny candidate set: sources, stages and scopes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SharedStore(Path(self.tmp.name) / 'assistant.sqlite3',
                                 Path(self.tmp.name) / 'old', device_port=5559)
        self.chainobj = inbox.InboxChain(self.store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)

    def chain(self):
        return self.chainobj

    def track(self, who, stage, ids=()):
        with self.store.connection() as db:
            db.execute("INSERT OR REPLACE INTO manual_actions(account,peer,initial_chat,text_hash,confirmed,status)"
                       " VALUES(?,?,?,'h',1,'handler-returned-unconfirmed')",
                       (who['account'], who['peer'], who['chat']))
            db.execute("INSERT OR REPLACE INTO chain_dialogs VALUES(?,?,?,?,?,'salt')",
                       (who['account'], who['peer'], who['chat'], '1', stage))
            for value in ids:
                db.execute("INSERT OR REPLACE INTO chain_seen VALUES(?,?,?)", (who['chat'], value, 'f'))

    def test_terminal_stages_are_deny_candidates_active_stages_are_not(self):
        self.track(WHO, 'declined', ('5',))
        self.track(OTHER, 'wait-mood', ('7',))
        self.track(THIRD, 'manual-review')
        deny = inbox.terminal_deny(self.chain())
        self.assertIn(dict(account='100', peer='200', chat='300'), deny)
        self.assertIn(dict(account='100', peer='202', chat='302'), deny)
        self.assertNotIn(dict(account='100', peer='201', chat='301'), deny)

    def test_done_stage_is_a_deny_candidate(self):
        self.track(WHO, 'done', ('5', '6'))
        self.assertIn(dict(account='100', peer='200', chat='300'), inbox.terminal_deny(self.chain()))

    def test_manually_blocked_terminal_peer_is_left_to_the_hidden_set(self):
        self.track(WHO, 'declined', ('5',))
        with self.store.connection() as db:
            db.execute("INSERT INTO mumu_peer_blocks VALUES('200','manual-block','telegram','','',CURRENT_TIMESTAMP)")
        self.assertEqual(inbox.terminal_deny(self.chain()), ())

    def test_plain_store_has_no_deny(self):
        from assistant_store import Store
        from assistant_inbox import InboxChain
        plain = Store(Path(self.tmp.name) / 'plain.sqlite3', Path(self.tmp.name) / 'old2')
        self.assertEqual(inbox.terminal_deny(InboxChain(plain)), ())
        self.assertEqual(inbox.deny_with_seen(InboxChain(plain), inbox.terminal_deny(InboxChain(plain))), ())

    def test_deny_candidates_are_capped(self):
        for index in range(inbox.MAX_DENY_TARGETS + 25):
            who = dict(account='100', peer=str(1000 + index), chat=str(2000 + index))
            with self.store.connection() as db:
                db.execute("INSERT OR REPLACE INTO manual_actions(account,peer,initial_chat,text_hash,confirmed,status)"
                           " VALUES(?,?,?,'h',1,'handler-returned-unconfirmed')",
                           (who['account'], who['peer'], who['chat']))
                db.execute("INSERT OR REPLACE INTO chain_dialogs VALUES(?,?,?,?,?,'salt')",
                           (who['account'], who['peer'], who['chat'], '1', 'declined'))
        self.assertEqual(len(inbox.terminal_deny(self.chain())), inbox.MAX_DENY_TARGETS)


class DenyEvidence(unittest.TestCase):
    """The consumed-id evidence: receipts, reporting, ordering and the cap."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SharedStore(Path(self.tmp.name) / 'assistant.sqlite3',
                                 Path(self.tmp.name) / 'old', device_port=5559)
        self.chainobj = inbox.InboxChain(self.store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)
        from assistant_reply_audit import DDL as receipt_ddl
        from assistant_skip_audit import DDL as skip_ddl
        self.store.ensure_tables(receipt_ddl, skip_ddl)

    def chain(self):
        return self.chainobj

    def track(self, who, stage='declined'):
        with self.store.connection() as db:
            db.execute("INSERT OR REPLACE INTO manual_actions(account,peer,initial_chat,text_hash,confirmed,status)"
                       " VALUES(?,?,?,'h',1,'handler-returned-unconfirmed')",
                       (who['account'], who['peer'], who['chat']))
            db.execute("INSERT OR REPLACE INTO chain_dialogs VALUES(?,?,?,?,?,'salt')",
                       (who['account'], who['peer'], who['chat'], '1', stage))

    def test_consumed_ids_ride_newest_first_and_pending_receipts_do_not_reopen(self):
        # The journal-target arm deliberately drops a consumed id with a PENDING
        # reply receipt (to re-observe an unobserved outgoing). For a FINISHED
        # chat that exclusion was the idle walk: the receipt can no longer be
        # resolved by reopening, so the deny evidence includes it unconditionally.
        self.track(WHO)
        with self.store.connection() as db:
            for value in ('5', '9', '12'):
                db.execute("INSERT INTO chain_seen VALUES(?,?,?)", (WHO['chat'], value, 'f'))
            db.execute("INSERT INTO chain_reply_receipts VALUES(?,?,?,'pending',NULL)",
                       (WHO['chat'], '9', 'f'))
        entries = inbox.deny_with_seen(self.chain(), inbox.terminal_deny(self.chain()))
        self.assertEqual(entries, (dict(account='100', peer='200', chat='300',
                                        seen_ids=['12', '9', '5']),))

    def test_reported_inputs_join_the_evidence(self):
        self.track(WHO)
        with self.store.connection() as db:
            db.execute("INSERT INTO chain_seen VALUES(?,?,?)", (WHO['chat'], '4', 'f'))
            db.execute("INSERT INTO inbox_reported_inputs VALUES(?,?,?)", (WHO['chat'], '8', 'g'))
        entries = inbox.deny_with_seen(self.chain(), inbox.terminal_deny(self.chain()))
        self.assertEqual(entries[0]['seen_ids'], ['8', '4'])

    def test_evidence_is_capped_at_128_newest_ids_without_error(self):
        self.track(WHO)
        with self.store.connection() as db:
            for value in range(1, 131):
                db.execute("INSERT INTO chain_seen VALUES(?,?,?)", (WHO['chat'], str(value), 'f'))
        entries = inbox.deny_with_seen(self.chain(), inbox.terminal_deny(self.chain()))
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(entries[0]['seen_ids']), 128)
        self.assertEqual(entries[0]['seen_ids'][0], '130')  # newest first
        self.assertEqual(entries[0]['seen_ids'][-1], '3')

    def test_finished_chat_without_consumed_ids_yields_no_entry(self):
        # No evidence, no deny: the row keeps its previous (bounded) behavior
        # instead of uploading an empty seen_ids list that skips nothing.
        self.track(THIRD, 'manual-review')
        self.assertEqual(inbox.deny_with_seen(self.chain(), inbox.terminal_deny(self.chain())), ())

    def test_with_seen_ids_merges_deny_after_real_targets_without_duplicates(self):
        self.track(WHO, 'declined')
        self.track(OTHER, 'wait-mood')
        with self.store.connection() as db:
            db.execute("INSERT INTO chain_seen VALUES(?,?,?)", (WHO['chat'], '5', 'f'))
            db.execute("INSERT INTO chain_seen VALUES(?,?,?)", (OTHER['chat'], '7', 'f'))
        deny = inbox.deny_with_seen(self.chain(), inbox.terminal_deny(self.chain()))
        merged = inbox.with_seen_ids(self.chain(), [dict(OTHER)], deny=deny)
        peers = [(x['account'], x['peer']) for x in merged]
        self.assertEqual(peers, [('100', '201'), ('100', '200')])
        by_peer = {x['peer']: x for x in merged}
        self.assertEqual(by_peer['200']['seen_ids'], ['5'])
        # A deny peer that IS a real target this round keeps exactly one entry.
        again = inbox.with_seen_ids(self.chain(), [dict(WHO), dict(OTHER)], deny=deny)
        self.assertEqual([x['peer'] for x in again], ['200', '201'])


class WalkTerminalDeny(Base):
    """Walk level: finished rows ride every open and are not walked again."""

    def setUp(self):
        super().setUp()
        self.store = shared(self)
        self.chainobj = self.chain()

    def finished(self, who, stage='declined', ids=('5',)):
        self.journal(who)
        with self.store.connection() as db:
            db.execute("INSERT OR REPLACE INTO chain_dialogs VALUES(?,?,?,?,?,'salt')",
                       (who['account'], who['peer'], who['chat'], '1', stage))
            for value in ids:
                db.execute("INSERT OR REPLACE INTO chain_seen VALUES(?,?,?)", (who['chat'], value, 'f'))

    def test_finished_row_rides_every_open_and_is_never_walked(self):
        # One live chat is answered; the finished (declined) chat with its
        # consumed last message rides the open call as deny evidence instead of
        # being opened for a second and left by a verified Back.
        self.finished(OTHER)
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['dialogs_opened'], 1)
        self.assertEqual(out['terminal_rows_deny'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertEqual(len(opens), 1)
        allowed = opens[0].kwargs['allowed']
        by_peer = {x['peer']: x for x in allowed}
        self.assertIn('200', by_peer)  # the live target itself
        self.assertEqual(by_peer['201']['seen_ids'], ['5'])  # the finished row's evidence
        self.assertTrue(opens[0].kwargs['adopt_untracked'])

    def test_new_message_in_finished_chat_still_opens_read_only_once(self):
        # A GENUINELY new message changes the row's last message id: the native
        # scan may still open it (adoption mode), the host leaves it read-only,
        # and the deny evidence for that peer is dropped from later opens of the
        # SAME pass - the old anti-cycle semantics, now for finished rows too.
        self.finished(OTHER)
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', OTHER), nav('returned', OTHER),
                         nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['dialogs_opened'], 2)
        self.assertEqual(out['dialogs_processed'], 2)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertEqual(len(opens), 2)
        self.assertIn(dict(account='100', peer='201', chat='301', seen_ids=['5']),
                      opens[0].kwargs['allowed'])
        self.assertNotIn('201', {x['peer'] for x in opens[1].kwargs['allowed']})

    def test_only_finished_rows_left_still_means_no_walk(self):
        # The exact reported end state: every tracked chat is finished, nothing
        # is pending - the pass is empty, no row is opened at all, and the
        # monitor moves straight to the profile search (v1.3.88 gate).
        self.finished(WHO)
        self.finished(OTHER, 'done', ('6',))
        out = self.walk([], [])
        self.assertEqual(out['status'], 'inbox-empty')
        self.nav.assert_not_called()
        self.reader.assert_not_called()

    def test_plain_store_walk_unchanged_without_deny(self):
        # The single-port engine keeps its exact previous behavior.
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['terminal_rows_deny'], 0)
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertEqual({x['peer'] for x in opens[0].kwargs['allowed']}, {'200'})


if __name__ == '__main__':
    unittest.main()
