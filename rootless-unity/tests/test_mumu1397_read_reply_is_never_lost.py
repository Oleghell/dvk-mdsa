"""v1.3.97: «я написал сообщение, его быстро прочитали и ответили - но чат уже
прочитан». Her fast reply that lands READ (badge-less) is never lost work.

The durable record is the pending-reply ledger (chain_reply_receipts) plus the
1.3.96 id-based row admission: her genuinely new incoming message re-opens the
row regardless of read state, and the receipt keeps it re-openable until it is
answered. This file pins the full chain end to end:

1. her reply arriving AFTER the quick exit (never seen by any bot read, no
   badge) is excluded from the uploaded consumed ids - so the native reply
   filter re-admits the row - and the NEXT pass answers it;
2. her reply INSIDE the one post-send check read still defers with
   'incoming-answer-pending' and stays re-admittable (the 1.3.96 contract,
   re-verified under the owed projection);
3. the operator's manual message followed by her reply («я написал сообщение,
   его прочитали и ответили») is answered by the next pass;
4. the owed projection: a receipt shadowed by OUR side's later word in the
   verified history (the bot's confirmed outgoing or the operator's manual
   answer) is not live work - the visit leaves with the clean waiting stage,
   no false «ответ ещё не подтверждён», no inert deferral cooldown; the ledger
   row itself stays pending until the audit resolves it;
5. the anti-goal: an ours-last waiting row with nothing new does NO work - no
   submission, no deferral, no receipt churn («не открывать абсолютно все
   неотвеченные чаты»).

Synthetic only; no device, database or worker process is touched."""
import unittest
from unittest.mock import MagicMock

import assistant_guided_chain as guided
import assistant_inbox as inbox
import assistant_reply_audit as audit
from assistant_inbox import InboxChain
from conversation_engine import CONTACT_TEXT, QUESTIONS
from pathlib import Path
import tempfile
import threading

from test_inbox_profiles import Base, GREETING, WHO, msg, nav, snap


class ReadReplyNeverLost(Base):
    """Her badge-less READ reply becomes work on the next pass, both timings."""

    def test_her_reply_after_the_exit_is_answered_next_pass(self):
        # THE reported shape: the bot sends its message, performs the ONE
        # post-send check read and exits; she reads and answers quickly - her
        # reply lands AFTER the exit. Nothing read it (the harness has no
        # badge model at all, which IS the badge-less/read case), so no bot
        # pathway can mark it consumed: the upload keeps excluding it and the
        # next pass opens the row and answers.
        self.journal()
        hello, question = msg(1002, 'Привет'), msg(1003, QUESTIONS[0], True)
        first = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                          [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(first['status'], 'inbox-completed')
        self.assertEqual(first['outcomes'], {'chain-waiting:wait-mood': 1})
        self.assertEqual(first['history_deferred'], 0)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        # Her reply arrives after the exit. The consumed-id upload must NOT
        # contain it (no bot read ever saw it) - exactly the evidence the
        # native needs-reply filter checks, so the row is re-admitted.
        mood = msg(1004, 'Согласна, давай')
        uploaded = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        self.assertNotIn(mood['id'], uploaded[0]['seen_ids'])
        # The next pass answers her.
        second = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                           [snap(hello, question, mood), snap(hello, question, mood),
                            snap(hello, question, mood, msg(1005, CONTACT_TEXT, True))])
        self.assertEqual(second['status'], 'inbox-completed')
        self.assertEqual(second['submission_calls'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])
        self.assertEqual(second['outcomes'], {'chain-waiting:wait-contact': 1})
        # The receipt for her reply exists and resolved to answered.
        with self.store.read_connection() as db:
            rows = dict(db.execute("SELECT message,status FROM chain_reply_receipts"))
        self.assertEqual(rows.get(mood['id']), 'answered')

    def test_her_reply_in_the_check_read_still_defers(self):
        # The 1.3.96 contract re-verified under the owed projection: her reply
        # INSIDE the one post-send check read (it follows our outgoing, so it
        # is owed) leaves the visit with 'incoming-answer-pending' - one send,
        # the cooldown defers the chat, her id stays out of the upload and the
        # receipt stays pending for the next pass.
        self.journal()
        hello, question = msg(1002, 'Привет'), msg(1003, QUESTIONS[0], True)
        fast = msg(1004, 'Согласна!')
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question, fast)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['outcomes'], {'chain-waiting:incoming-answer-pending': 1})
        self.assertEqual(out['history_deferred'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        with self.store.read_connection() as db:
            rows = dict(db.execute("SELECT message,status FROM chain_reply_receipts"))
        self.assertEqual(rows.get(fast['id']), 'pending')
        uploaded = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        self.assertNotIn(fast['id'], uploaded[0]['seen_ids'])

    def test_operator_manual_message_then_her_reply_is_answered(self):
        # «я написал сообщение, его быстро прочитали и ответили»: the OPERATOR
        # wrote manually (an outgoing outside the journal), she read it and
        # answered. Her reply is the genuinely new incoming last message - the
        # next pass answers it; the operator's own message never confuses the
        # chain into double-answering or skipping.
        self.journal()
        hello, question = msg(1002, 'Привет'), msg(1003, QUESTIONS[0], True)
        manual = msg(1004, 'Это мой ручной ответ', True)
        self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                  [snap(hello), snap(hello), snap(hello, question)])
        reply = msg(1005, 'Спасибо, и я так подумала')
        uploaded = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        self.assertNotIn(reply['id'], uploaded[0]['seen_ids'])
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello, question, manual, reply),
                         snap(hello, question, manual, reply),
                         snap(hello, question, manual, reply, msg(1006, CONTACT_TEXT, True))])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['submission_calls'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])

    def test_waiting_row_with_no_new_message_does_no_work(self):
        # The anti-goal: «не стоит открывать абсолютно все неотвеченные чаты».
        # An ours-last row with nothing new is a WAITING row - the native's
        # new-message admission skips it (pinned since 1.3.96), and the host
        # side invents no work either: no submission, no deferral, no receipt.
        self.journal()
        hello, question = msg(1002, 'Привет'), msg(1003, QUESTIONS[0], True)
        self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                  [snap(hello), snap(hello), snap(hello, question)])
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['submission_calls'], 0)
        self.assertEqual(out['history_deferred'], 0)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        with self.store.read_connection() as db:
            pending = db.execute(
                "SELECT COUNT(*) FROM chain_reply_receipts WHERE status='pending'").fetchone()[0]
        self.assertEqual(pending, 0)

    def test_manually_shadowed_receipt_leaves_clean_without_defer(self):
        # Her fast reply landed AFTER the quick exit (nobody read it yet) and
        # the operator answered her manually before the next pass. The next
        # visit sees our side's word AFTER her message: the operator_leads
        # rule already refuses to double-answer, and the owed projection is
        # empty - the visit leaves with the clean waiting stage, no
        # «ответ ещё не подтверждён» defer cooldown, and the ledger row itself
        # stays pending (the record is never dropped, only its work signal is
        # precise). Her NEXT genuinely new message is still admitted as work.
        self.journal()
        hello, question = msg(1002, 'Привет'), msg(1003, QUESTIONS[0], True)
        self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                  [snap(hello), snap(hello), snap(hello, question)])
        fast, manual = msg(1004, 'Согласна!'), msg(1005, 'Ответил руками', True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello, question, fast, manual)])
        self.assertEqual(out['outcomes'], {'chain-waiting:wait-mood': 1})
        self.assertEqual(out['history_deferred'], 0)
        self.assertEqual(out['submission_calls'], 0)
        self.assertEqual(out['isolated_dialogs'], 0)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        with self.store.read_connection() as db:
            rows = dict(db.execute("SELECT message,status FROM chain_reply_receipts"))
        self.assertEqual(rows.get(fast['id']), 'pending')
        # And her next message after the operator's word is still new work:
        # the row re-admits (her reply is the new last message, never consumed)
        # and the following pass answers it.
        later = msg(1006, 'А я ещё подумала и вот пишу')
        uploaded = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        self.assertNotIn(later['id'], uploaded[0]['seen_ids'])
        second = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                           [snap(hello, question, fast, manual, later),
                            snap(hello, question, fast, manual, later),
                            snap(hello, question, fast, manual, later,
                                 msg(1007, CONTACT_TEXT, True))])
        self.assertEqual(second['submission_calls'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])


class OwedProjection(unittest.TestCase):
    """The evidence-based projection of the durable pending ledger."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from assistant_store import Store
        self.store = Store(Path(self.tmp.name) / 'assistant.sqlite3', Path(self.tmp.name) / 'old')
        self.stop = threading.Event()
        self.chain = InboxChain(self.store, choose=lambda: 0,
                                seal=lambda v: v, unseal=lambda v: v)
        # A tracked dialog bound to the real chat id (the journal reserves at
        # the technical '-1' until the first bind, exactly like the walk does).
        self.chain.bind(dict(identity=dict(WHO), messages=[msg(1001, GREETING, True)]),
                        (GREETING,), approved=True)

    def _receipts(self):
        with self.store.read_connection() as db:
            return dict(db.execute("SELECT message,status FROM chain_reply_receipts"))

    def test_her_last_message_is_owed(self):
        audit.observe(self.chain, snap(msg(1002, 'Привет')))
        self.assertEqual(list(self._receipts()), ['1002'])
        self.assertEqual(audit.owed(self.chain, WHO, snap(msg(1002, 'Привет'))), ['1002'])

    def test_shadowed_by_our_own_word_is_not_owed(self):
        audit.observe(self.chain, snap(msg(1002, 'Привет')))
        shadowed = snap(msg(1002, 'Привет'), msg(1003, 'любой наш ответ', True))
        self.assertEqual(audit.owed(self.chain, WHO, shadowed), [])
        # The ledger row is untouched - only the work signal is precise.
        self.assertEqual(self._receipts(), {'1002': 'pending'})

    def test_absent_snapshot_and_absent_message_stay_owed(self):
        audit.observe(self.chain, snap(msg(1002, 'Привет')))
        self.assertEqual(audit.owed(self.chain, WHO, None), ['1002'])
        self.assertEqual(audit.owed(self.chain, WHO, {}), ['1002'])
        self.assertEqual(audit.owed(self.chain, WHO, snap(msg(1009, 'другое'))), ['1002'])

    def test_only_the_unshadowed_receipt_stays_owed(self):
        audit.observe(self.chain, snap(msg(1002, 'Привет'), msg(1003, 'вопрос?', True),
                                        msg(1004, 'ответ'), msg(1005, 'спасибо', True),
                                        msg(1006, 'ещё сообщение')))
        # 1002 shadowed by 1003 (ours); 1004 shadowed by 1005 (ours);
        # 1006 is her last word - the only owed receipt.
        self.assertEqual(audit.owed(self.chain, WHO,
                                    snap(msg(1002, 'Привет'), msg(1003, 'вопрос?', True),
                                         msg(1004, 'ответ'), msg(1005, 'спасибо', True),
                                         msg(1006, 'ещё сообщение'))), ['1006'])

    def test_source_pins(self):
        source = Path(guided.__file__).read_text(encoding='utf-8')
        self.assertIn('remaining=owed(chain,who,before)', source)
        self.assertNotIn('remaining=pending(chain,who)', source)
        inbox_source = Path(inbox.__file__).read_text(encoding='utf-8')
        self.assertIn('unanswered=owed_replies(chain,who,private_snapshot[0] if private_snapshot else None)',
                      inbox_source)
        audit_source = Path(audit.__file__).read_text(encoding='utf-8')
        self.assertIn('def owed(chain,who,snapshot=None):', audit_source)


if __name__ == '__main__':
    unittest.main()
