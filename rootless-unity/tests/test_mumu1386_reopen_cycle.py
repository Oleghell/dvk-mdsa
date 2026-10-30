"""v1.3.86 regressions: the pass-start open→back reopen cycle and operator-led
dialogs stranded by automatic shared peer blocks. Synthetic only, no device,
no real sends, no network.

Two reported symptoms, one pass each:
(1) «MuMu ADB 5559 (3) · ПК 9104352d / Собеседник: «Привет» / Пропущено: В
общей базе отмечен полученный контакт…» — the operator himself started and
leads that dialog; an automatic cross-port outcome must not stop the chain.
(2) «при старте… открывается диалог, потом закрывает и открывает и закрывает
по кругу» — the adoption filter kept reopening rows the host had deliberately
left without an answer; the pass cycled open→back on the same dialog.
"""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

import assistant_inbox as inbox
import assistant_guided_chain as guided
from assistant_settings import Settings
from assistant_store import Store
from conversation_engine import QUESTIONS
from mumu_peer_policy import ensure_communication_allowed, PeerCommunicationBlocked
from mumu_store import SharedStore
from test_assistant_dialogs import nav_result as plain_nav
from test_guided_chain import GREETING, snapshot, stable_snapshots
from test_inbox_profiles import Base, msg, nav, snap

WHO = dict(account='100', peer='200', chat='300')
OTHER = dict(account='100', peer='201', chat='301')


def shared(base, port=5559):
    return SharedStore(base.store.path, Path(base.tmp.name) / 'old', device_port=port)


class OperatorBlock(Base):
    """v1.3.86: automatic shared outcomes never strand an operator-led dialog."""

    def setUp(self):
        super().setUp()
        self.store = shared(self)

    def block(self, reason, who=OTHER):
        other = SharedStore(self.store.path, Path(self.tmp.name) / 'old', device_port=5563)
        with other.connection() as db:
            other.record_peer_outcome(db, who, reason)

    def bind_operator(self, who=OTHER):
        from assistant_operator_adoption import ensure_tables
        ensure_tables(self.store)
        with self.store.connection() as db:
            db.execute('INSERT INTO operator_bindings VALUES(?,?,?,?)',
                       (who['account'], who['peer'], who['chat'], 'anchor-hash'))

    def test_automatic_outcomes_do_not_block_an_operator_led_dialog(self):
        self.bind_operator()
        for reason in ('contact-received', 'contact-refused'):
            self.block(reason)
            ensure_communication_allowed(self.store, OTHER)

    def test_manual_num_order_still_blocks_even_an_operator_led_dialog(self):
        self.bind_operator()
        self.block('manual-block')
        with self.assertRaises(PeerCommunicationBlocked):
            ensure_communication_allowed(self.store, OTHER)

    def test_foreign_identities_and_missing_bindings_still_block(self):
        self.block('contact-received')
        # No binding at all.
        with self.assertRaises(PeerCommunicationBlocked):
            ensure_communication_allowed(self.store, OTHER)
        # A binding for a DIFFERENT peer never exempts the blocked one.
        self.bind_operator(dict(account='100', peer='202', chat='302'))
        with self.assertRaises(PeerCommunicationBlocked):
            ensure_communication_allowed(self.store, OTHER)
        # The operator's own binding exempts exactly his (account, peer).
        self.bind_operator()
        ensure_communication_allowed(self.store, OTHER)
        # The same blocked peer under another account stays blocked.
        with self.assertRaises(PeerCommunicationBlocked):
            ensure_communication_allowed(self.store, dict(account='101', peer=OTHER['peer'], chat=OTHER['chat']))

    def test_blocked_peer_dialog_led_by_operator_is_adopted_and_answered(self):
        # The exact report shape: the operator started this dialog himself, the
        # peer is globally marked contact-received, the peer writes «Привет».
        # Adoption binds the chat, the block no longer stops the chain and the
        # standard question is sent in the SAME cycle; no «Пропущено» skip.
        self.block('contact-received')
        self.journal()  # another tracked target keeps the pass running
        own = msg(1001, 'Привет, я Игорь, давай пообщаемся', True, OTHER)
        peer = msg(1002, 'Привет', False, OTHER)
        question = msg(1003, QUESTIONS[0], True, OTHER)
        reads = [dict(identity=dict(OTHER), messages=[own, peer], latest_message_id='1002'),
                 dict(identity=dict(OTHER), messages=[own, peer]),
                 dict(identity=dict(OTHER), messages=[own, peer]),
                 dict(identity=dict(OTHER), messages=[own, peer, question])]
        # Shared-store mode merges the round into ONE 'recent' group: the pass
        # is open → back → one exhausted scan → return.
        out = self.walk([nav('opened', OTHER), nav('returned', OTHER), nav('exhausted'),
                         nav('search-ready')], reads)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['operator_adopted'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        self.assertNotIn('chain-waiting:peer-contact-blocked', out['outcomes'])
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs WHERE peer=?',
                                        (OTHER['peer'],)).fetchall(), [('wait-mood',)])

    def test_blocked_journal_chat_records_a_row_skip_marker(self):
        # A bot-started (journal) chat with a blocked peer keeps its one-shot
        # skip notice, but its newest message is recorded as the row's skip
        # marker so the native needs-reply filter stops reopening the row and
        # the host stops rereading its full history on every later pass.
        self.journal()
        self.block('contact-received', who=WHO)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(msg(1002, 'Привет'))])
        self.assertEqual(out['outcomes'], {'chain-waiting:peer-contact-blocked': 1})
        self.assertEqual(out['blocked_observed'], 1)
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT last_message,reason FROM operator_rejects').fetchall(),
                             [('1002', 'peer-contact-blocked')])
        merged = inbox.with_seen_ids(self.chain(), [dict(account='100', peer='200', chat='300')])
        self.assertTrue(merged and merged[0]['seen_ids'] == ['1002'])


class ReopenCycle(Base):
    """v1.3.86: a revisit of an already-handled row ends adoption, not the pass."""

    def defer(self, who):
        import assistant_history_wait as history_wait
        history_wait.initialize(self.store)
        with self.store.connection() as db:
            # v1.3.94: the deferral table grew a consecutive-miss counter.
            db.execute('INSERT INTO inbox_history_deferrals VALUES(?,?,?,?,?)',
                       (who['account'], who['peer'], who['chat'], 1e12, 0))

    def test_reopened_row_switches_remaining_opens_to_strict_targets(self):
        # The adopt filter opens a tracked-but-cooled chat (deliberately
        # excluded this round), the host leaves read-only; the scan comes back
        # to the SAME row. Before the fix that cycled open→back forever; now
        # the second visit switches the remaining opens to strict journal
        # targets and the pass completes normally.
        self.journal(OTHER)
        self.defer(OTHER)
        self.journal()  # the eligible target
        navigations = [nav('opened', OTHER), nav('returned', OTHER),
                       nav('opened', OTHER), nav('returned', OTHER),
                       nav('exhausted'), nav('exhausted'), nav('search-ready')]
        out = self.walk(navigations, [])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertTrue(out.get('adoption_disabled_reopen'))
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertEqual([c.kwargs['adopt_untracked'] for c in opens], [True, True, False, False])
        # The cooled chat is never read, drafted or answered; only its row is
        # opened and left by verified Back.
        self.reader.assert_not_called()
        self.assertEqual(self.sent, [])
        self.assertEqual(out['dialogs_processed'], 2)

    def test_first_visit_of_an_excluded_row_keeps_adoption_for_later_rows(self):
        # A single visit of an excluded row is not a cycle: adoption stays on
        # so a genuinely new operator dialog later in the same pass is still
        # adopted (the v1.3.84 contract is preserved).
        self.journal(OTHER)
        self.defer(OTHER)
        running = dict(account='100', peer='203', chat='303')
        self.journal(running)  # keeps the pass running while OTHER is excluded
        adopted = dict(account='100', peer='202', chat='302')
        own = msg(1001, 'Я сам начал этот диалог', True, adopted)
        peer = msg(1002, 'Привет', False, adopted)
        question = msg(1003, QUESTIONS[0], True, adopted)
        reads = [dict(identity=dict(adopted), messages=[own, peer], latest_message_id='1002'),
                 dict(identity=dict(adopted), messages=[own, peer]),
                 dict(identity=dict(adopted), messages=[own, peer]),
                 dict(identity=dict(adopted), messages=[own, peer, question])]
        out = self.walk([nav('opened', OTHER), nav('returned', OTHER),
                         nav('opened', adopted), nav('returned', adopted),
                         nav('exhausted'), nav('exhausted'), nav('search-ready')], reads)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertFalse(out.get('adoption_disabled_reopen'))
        self.assertEqual(out['operator_adopted'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertEqual([c.kwargs['adopt_untracked'] for c in opens], [True, True, True, True])

    def test_blocked_skip_marker_is_a_noop_without_verified_history(self):
        chain = self.chain()
        self.assertFalse(inbox.blocked_skip_marker(chain, WHO, dict(identity=dict(WHO), messages=[])))
        self.assertFalse(inbox.blocked_skip_marker(chain, WHO, None))
        self.assertFalse(inbox.blocked_skip_marker(
            chain, WHO, dict(identity=dict(WHO), messages=[dict(id=17, sender='200', text='x')])))
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM operator_rejects').fetchone()[0], 0)


class OperatorLeadsGuardedChain(unittest.TestCase):
    """guided.walk level: an operator binding overrides the automatic block."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.db'
        self.old = Path(self.tmp.name) / 'old'
        self.store = SharedStore(self.path, self.old, device_port=5559)
        self.stop = threading.Event()
        from test_guided_chain import WHO as GUIDED_WHO
        self.who = GUIDED_WHO
        self.chain = guided.GuidedChain(self.store, choose=lambda: 0, seal=lambda b: b, unseal=lambda b: b)
        self.chain.bind(snapshot(), (GREETING,), approved=True)

    def block(self, reason):
        other = SharedStore(self.path, self.old, device_port=5563)
        with other.connection() as db:
            other.record_peer_outcome(db, self.who, reason)

    def bind_operator(self):
        from assistant_operator_adoption import ensure_tables
        ensure_tables(self.store)
        with self.store.connection() as db:
            db.execute('INSERT INTO operator_bindings VALUES(?,?,?,?)',
                       (self.who['account'], self.who['peer'], self.who['chat'], 'anchor-hash'))

    def walk(self, sender):
        approve = MagicMock(return_value=True)
        # bind read and approval re-read see the same history; only the
        # post-send read observes the sent question.
        reads = [snapshot(('Привет', False)), snapshot(('Привет', False)),
                 snapshot(('Привет', False), (QUESTIONS[0], True))]
        return guided.walk(self.chain, self.who, self.stop, approve,
                           MagicMock(side_effect=stable_snapshots(reads)),
                           sender, approved=True, greetings=(GREETING,), pause=lambda _: False,
                           until_waiting=True, max_polls=8)

    def test_operator_bound_chat_answers_despite_contact_received_block(self):
        self.bind_operator()
        self.block('contact-received')
        sent = []

        def sender(before, text):
            sent.append(text)
            return dict(attempted=True, handler_returned=True)

        out = self.walk(sender)
        self.assertEqual(out['status'], 'chain-waiting')
        self.assertNotEqual(out['reason'], 'peer-contact-blocked')
        self.assertEqual(sent, [QUESTIONS[0]])

    def test_without_binding_the_block_still_stops_the_reply(self):
        self.block('contact-received')
        sender = MagicMock(side_effect=AssertionError('A blocked journal peer must never be messaged'))
        out = self.walk(sender)
        self.assertEqual(out['reason'], 'peer-contact-blocked')
        sender.assert_not_called()


if __name__ == '__main__':
    unittest.main()
