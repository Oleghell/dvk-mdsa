"""v1.3.103: «когда идет проверка диалога то открывается каждый неотвеченный
диалог, когда нужно чтобы открывало новый входящий не прочитанный».

The dialog check opens a row ONLY when it carries a NEW INCOMING UNREAD
message. The 1.3.96 badge-less new-incoming admission opened every merely
unanswered row - deferred chats after their cooldown, strays, operator-read
dialogs - which the user watched as an endless walk over «неотвеченные»
dialogs. The unread badge is now an admission signal for the reply filter on
BOTH native engines (the cell browser and the cached-models browser), and
the only badge-less open left is the host-scheduled retry recheck of owed
work: a deferral-ladder step that expired, or a pending reply receipt - the
promised «проверю позже» made real instead of the reported queue that never
rechecked. Nothing owed is dropped: the retry target lifts exactly the
reported-input suppression on its owed message, a skip marker never merges
into it, and every other badge-less row stays closed whatever its last
message is.

Synthetic only; no device, database or worker process is touched.
"""
import unittest
from pathlib import Path
import tempfile
import threading

import dialog_browser
import dialog_models
import assistant_inbox as inbox
import assistant_history_wait as history_wait
from assistant_store import Store
from assistant_settings import Settings
from unittest.mock import MagicMock
from conversation_engine import QUESTIONS

from test_inbox_profiles import Base, WHO, OTHER, msg, nav, snap


GATE = "if(unread===0&&!retryRow(model.who)){n.read_rows_skipped++;return false;}"


class NativeGate(unittest.TestCase):
    """The badge gate itself, pinned on the composed scan source."""

    TARGET = dict(account='1', peer='2', chat='3')

    def test_browser_gate_precedes_the_header_checks(self):
        s = dialog_browser.build('open', allowed=[dict(self.TARGET, seen_ids=['9'])],
                                 needs_reply_only=True)
        self.assertIn(GATE, s)
        self.assertIn("const retryRow=who=>allowedTargets.some(x=>x.account===who.account&&x.peer===who.peer&&", s)
        self.assertIn("x.retry===true);", s)
        self.assertIn("if(unread===0)n.retry_rows_opened++;", s)
        # The 1.3.96 form (badge evidence only, no admission) is gone.
        self.assertNotIn("unreadOnly&&!needsReplyOnly", s)
        # A badge-less row never reaches the incoming/handled checks.
        self.assertLess(s.index('if(unread===0&&!retryRow'), s.index("if(!header.incoming)"))

    def test_models_engine_carries_the_same_gate(self):
        s = dialog_models.build(allowed=[dict(self.TARGET, seen_ids=['9'])],
                                needs_reply_only=True, recent_limit=50, reverse=True, start=0)
        self.assertIn(GATE, s)
        self.assertIn("if(needsReplyOnly&&unread===0)n.retry_rows_opened++;", s)
        self.assertNotIn("unreadOnly&&!needsReplyOnly", s)

    def test_bootstrap_accepts_the_retry_target_shapes(self):
        source = dialog_browser.TARGET_BOOTSTRAP
        self.assertIn("keys!=='account,chat,peer,retry'&&keys!=='account,chat,peer,retry,seen_ids'", source)
        self.assertIn("x.retry!==true)throw new Error('invalid-target');", source)
        self.assertIn("if(Object.prototype.hasOwnProperty.call(x,'retry'))value.retry=true;", source)

    def test_read_check_tool_shares_the_gate_string(self):
        # unread_only alone (the 0.4.6 read-check tool) opens by the badge
        # through the very same shared gate - one rule, no divergence.
        source = dialog_browser.build('open', allowed=[self.TARGET], unread_only=True)
        self.assertIn(GATE, source)


class RetryTargets(unittest.TestCase):
    """The retry flag rides the private target transport, strictly."""

    TARGET = dict(account='1', peer='2', chat='3')

    def test_targets_accept_and_preserve_the_flag(self):
        for value in (dict(self.TARGET, retry=True),
                      dict(self.TARGET, seen_ids=['9'], retry=True)):
            self.assertEqual(dialog_browser.targets([value]), [value])

    def test_targets_reject_non_true_retry_values(self):
        for retry in (False, 1, 'yes', None):
            with self.assertRaises(ValueError):
                dialog_browser.targets([dict(self.TARGET, retry=retry)])


class LedgerRetryPeers(Base):
    """Exactly the two ledger sources may open badge-less."""

    def chain(self):
        return inbox.InboxChain(self.store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)

    def test_expired_deferral_ladder_row_is_retry_due(self):
        history_wait.initialize(self.store)
        with self.store.connection() as db:
            db.execute('INSERT INTO inbox_history_deferrals VALUES(?,?,?,?,?)',
                       (WHO['account'], WHO['peer'], WHO['chat'], 0.0, 1))
        self.assertEqual(inbox.ledger_retry_peers(self.chain()), {(WHO['account'], WHO['peer'])})

    def test_active_cooldown_is_not_retry_due(self):
        history_wait.initialize(self.store)
        history_wait.defer(self.store, WHO, clock=lambda: 1000.0)
        self.assertEqual(inbox.ledger_retry_peers(self.chain(), clock=lambda: 1001.0), set())

    def test_pending_receipt_is_retry_due(self):
        from assistant_reply_audit import DDL as receipt_ddl
        chain = self.chain()
        self.store.ensure_tables(receipt_ddl)
        with self.store.connection() as db:
            db.execute("INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)",
                       (WHO['account'], WHO['peer'], WHO['chat'], '1001', 'wait-reply', 's'))
            db.execute("INSERT INTO chain_reply_receipts VALUES(?,?,?,'pending',NULL)",
                       (WHO['chat'], '1002', 'f1'))
        self.assertEqual(inbox.ledger_retry_peers(chain), {(WHO['account'], WHO['peer'])})

    def test_answered_receipt_is_not_retry_due(self):
        from assistant_reply_audit import DDL as receipt_ddl
        chain = self.chain()
        self.store.ensure_tables(receipt_ddl)
        with self.store.connection() as db:
            db.execute("INSERT INTO chain_dialogs VALUES(?,?,?,?,?,?)",
                       (WHO['account'], WHO['peer'], WHO['chat'], '1001', 'wait-reply', 's'))
            db.execute("INSERT INTO chain_reply_receipts VALUES(?,?,?,'answered','1003')",
                       (WHO['chat'], '1002', 'f1'))
        self.assertEqual(inbox.ledger_retry_peers(chain), set())

    def test_clean_chat_is_not_retry_due(self):
        self.assertEqual(inbox.ledger_retry_peers(self.chain()), set())

    def test_mark_retry_targets_attaches_only_matching_peers(self):
        items = [dict(WHO), dict(OTHER)]
        inbox.mark_retry_targets(items, {(WHO['account'], WHO['peer'])})
        self.assertEqual(items, [dict(WHO, retry=True), dict(OTHER)])


class SeenIdsSuppression(Base):
    """The retry target lifts exactly the reported-input suppression."""

    def setUp(self):
        super().setUp()
        from assistant_reply_audit import DDL as receipt_ddl
        from assistant_skip_audit import DDL as skip_ddl
        self.chain()  # ensures the chain tables (chain_seen included)
        self.store.ensure_tables(receipt_ddl, skip_ddl)
        with self.store.connection() as db:
            # A consumed own greeting (no receipt) and her reported message
            # with a pending receipt: the classic deferred-answer shape.
            db.execute("INSERT INTO chain_seen VALUES(?,?,?)", (WHO['chat'], '1001', 'own'))
            db.execute("INSERT INTO chain_reply_receipts VALUES(?,?,?,'pending',NULL)",
                       (WHO['chat'], '1002', 'f1'))
            db.execute("INSERT INTO inbox_reported_inputs VALUES(?,?,?)",
                       (WHO['chat'], '1002', 'f1'))

    def chain(self):
        return inbox.InboxChain(self.store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)

    def test_reported_input_stays_suppressed_without_the_retry_flag(self):
        uploaded = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        # The 1.3.89 suppression: a reported+receipted message is handled.
        self.assertEqual(uploaded[0]['seen_ids'], ['1001', '1002'])

    def test_retry_target_lifts_only_the_reported_suppression(self):
        uploaded = inbox.with_seen_ids(self.chain(), [dict(WHO, retry=True)])
        # The owed message re-admits; the consumed own greeting stays handled.
        self.assertEqual(uploaded[0]['seen_ids'], ['1001'])
        self.assertTrue(uploaded[0]['retry'])

    def test_skip_marker_never_merges_into_a_retry_target(self):
        from assistant_operator_adoption import record_reject
        record_reject(self.store, WHO, '1002', 'workless-state')
        plain = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        self.assertIn('1002', plain[0]['seen_ids'])
        retry = inbox.with_seen_ids(self.chain(), [dict(WHO, retry=True)])
        self.assertEqual(retry[0]['seen_ids'], ['1001'])
        self.assertTrue(retry[0]['retry'])


class WalkRetryPlumbing(Base):
    """The walk marks ladder-due chats and reports the badge-less recheck."""

    def chain(self):
        return inbox.InboxChain(self.store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)

    def ladder_due(self):
        history_wait.initialize(self.store)
        with self.store.connection() as db:
            db.execute('INSERT INTO inbox_history_deferrals VALUES(?,?,?,?,?)',
                       (WHO['account'], WHO['peer'], WHO['chat'], 0.0, 1))

    def first_open_allowed(self):
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertTrue(opens)
        return opens[0].kwargs['allowed']

    def test_ladder_due_chat_opens_with_the_retry_flag_and_reports_it(self):
        self.journal()
        self.ladder_due()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        opened = nav('opened', WHO)
        # The synthetic navigator models the badge-less retry recheck: the
        # row opened without a badge, exactly what the retry flag permits.
        opened['diagnostic']['retry_rows_opened'] = 1
        out = self.walk([opened, nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['read_retry_targets'], 1)
        self.assertEqual(out['retry_rows_opened'], 1)
        allowed = self.first_open_allowed()
        self.assertTrue(any(x.get('retry') is True for x in allowed), allowed)

    def test_clean_chat_keeps_the_badge_only_admission(self):
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['read_retry_targets'], 0)
        self.assertEqual(out['retry_rows_opened'], 0)
        allowed = self.first_open_allowed()
        self.assertFalse(any(x.get('retry') is True for x in allowed), allowed)

    def test_read_rows_skipped_is_reply_filter_evidence_now(self):
        self.journal()
        first = nav('exhausted')
        first['diagnostic'].update(read_rows_skipped=2, waiting_rows_skipped=0)
        second = nav('exhausted')
        second['diagnostic'].update(read_rows_skipped=1, waiting_rows_skipped=0)
        out = self.walk([first, second, nav('search-ready')], [])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['read_rows_skipped'], 3)
        self.assertEqual(out['dialogs_opened'], 0)


if __name__ == '__main__':
    unittest.main()
