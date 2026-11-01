"""v1.3.108 (M76yfk): «пофикси ошибки и сделай нормальную рабочую сборку».

The dropmefiles M76yfk reports (monitors 693/694, and the same signature on
688-691) all stop the port identically right after ONE successful send:

    host_failure   = 'validation-failed'
    validation_reason = 'Invalid journal targets'
    post_send_checks  = 1          (the 1.3.104 merge happened)
    submission_attempted/returned  (the send itself was fine)
    last_navigation  = a HEALTHY previous Back

Mechanical root, reproduced here: dialog_browser.targets() raises
ValueError('Invalid journal targets') for more than MAX_TARGETS (1000)
entries, and the 1.3.104 post-send verification merge prepended its retry
target into a live group UNCONDITIONALLY. Whenever the sending chat was NOT
a member of the first non-empty group - an adopted chat outside the current
chunk, a journal split across attention/unread/read_round groups, a paged
page_groups() rebuild without the combined dedup - that group could hold a
FULL 1000-entry chunk, grew to 1001 journal targets, and the next open's
with_seen_ids() died inside its kwargs preparation: the whole pass stopped
with the healthy previous Back still in the report, on every port whose
journal crossed the transport bound.

The merge now respects the bound: a group with room keeps the single merged
scan (the 1.3.104 one-open semantics); a FULL chunk keeps its own open and
the verification target rides its own one-target group in front of it. The
dead-port ValueError is structurally impossible again, and the previously
uncovered merge path (no test ever pinned post_send_checks > 0) is pinned
end to end. The 1.3.106 'inbox-prepare' checkpoint also joins the closed
CHECKPOINTS set so the diagnostic projection stops silently dropping it.

Synthetic only; no device, database or worker process is touched.
"""
import json
import unittest

import dialog_browser
import assistant_inbox as inbox
import assistant_failure
from pathlib import Path
from unittest.mock import MagicMock

from test_inbox_profiles import Base, WHO, OTHER, msg, nav, snap, verify
from conversation_engine import QUESTIONS


def source_of(module):
    return Path(module.__file__).read_text(encoding='utf-8')


def filler(count, start=1000):
    """Decimal peers that sort BEFORE WHO's peer, so WHO lands in the tail."""
    return [dict(account='100', peer=str(start + i), chat=str(start + i))
            for i in range(count)]


class TransportBound(unittest.TestCase):
    """The closed transport bound itself: 1000 rides, 1001 is a named error."""

    def test_exactly_the_bound_is_accepted(self):
        values = filler(1000)
        self.assertEqual(len(dialog_browser.targets(values)), 1000)

    def test_one_past_the_bound_is_the_reported_error(self):
        values = filler(1001)
        with self.assertRaises(ValueError) as raised:
            dialog_browser.targets(values)
        self.assertEqual(str(raised.exception), 'Invalid journal targets')

    def test_with_seen_ids_keeps_the_same_bound(self):
        chain = MagicMock()
        chain.store.read_connection.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []
        with self.assertRaises(ValueError) as raised:
            inbox.with_seen_ids(chain, filler(1001))
        self.assertEqual(str(raised.exception), 'Invalid journal targets')


class MergeRespectsTheTransportBound(Base):
    """The 1.3.104 merge can never again push a group past the bound.

    The reproduction shape: unread holds 1001 targets (1000 filler peers that
    sort before WHO, plus WHO), so the group list is
    [unread-chunk(1000), unread-tail(WHO), read-chunk(1000), read-tail(WHO)].
    The first chunk scans exhausted, WHO opens from the tail group and sends,
    WHO is removed from every group - and the first NON-EMPTY group is then
    the FULL read chunk. The old unconditional prepend made that chunk 1001
    journal targets and the next open died as 'Invalid journal targets'
    exactly like monitors 688-694; the bounded merge rides its own group.
    """

    def saturate(self):
        # 1000 guided peers sorting before WHO: unread = 1001 targets, so the
        # unread group chunks into [1000 filler, WHO-tail] and read_round
        # duplicates the same split.
        self.chain()  # creates the chain tables (guided_bindings included)
        with self.store.connection() as db:
            db.executemany(
                'INSERT INTO guided_bindings(account,peer,chat,greeting_hash) VALUES(?,?,?,?)',
                [(w['account'], w['peer'], w['chat'], 'h') for w in filler(1000)])

    def test_saturated_journal_survives_its_own_send(self):
        self.saturate()
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('exhausted'), nav('opened', WHO), nav('returned', WHO),
                         verify(waiting=1), nav('exhausted'), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)], quick_send_exit=True)
        # The pass COMPLETES instead of dying after its first successful send.
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertNotEqual(out.get('host_failure'), 'validation-failed')
        self.assertNotEqual(out.get('validation_reason'), 'Invalid journal targets')
        self.assertEqual(out['submission_calls'], 1)
        self.assertEqual(out['post_send_checks'], 1)
        # The one-open merged scan proof: the verification target list that
        # reached the native transport carries exactly one retry entry.
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertEqual([c.args[0] for c in self.nav.call_args_list],
                         ['open', 'open', 'back', 'open', 'open', 'return'])
        verification = opens[2].kwargs['allowed']
        self.assertEqual(len(verification), 1)
        self.assertEqual(verification[0]['account'], WHO['account'])
        self.assertEqual(verification[0]['peer'], WHO['peer'])
        self.assertTrue(verification[0]['retry'])
        # Every uploaded list respected the closed transport bound.
        for call_args in opens:
            self.assertLessEqual(len(call_args.kwargs['allowed']),
                                 dialog_browser.MAX_TARGETS)
        self.assertEqual(out['post_send_list_verified'], 1)

    def test_the_full_chunk_keeps_room_for_nothing(self):
        # Source pin: the merge is bounded by the transport bound, a full
        # chunk is never prepended into, and the verification target rides
        # its own group in front of it.
        source = source_of(inbox)
        self.assertIn('MAX_TARGETS as TRANSPORT_TARGETS', source)
        self.assertIn('if len(groups[live][0]) + len(verification) <= TRANSPORT_TARGETS:',
                      source)
        self.assertIn('groups.insert(live, (verification, groups[live][1], groups[live][2]))',
                      source)
        # The unbounded 1.3.104 form is gone.
        self.assertNotIn('groups[live][0][:0] = row_targets([dict(account=', source)


class MergeKeepsTheSingleScanWhenThereIsRoom(Base):
    """The common case is unchanged: the verification target merges into the
    live group's next open - ONE merged scan, no extra navigation."""

    def test_roomy_group_still_gets_one_merged_open(self):
        self.journal()
        self.chain()
        with self.store.connection() as db:
            db.execute('INSERT INTO guided_bindings(account,peer,chat,greeting_hash) VALUES(?,?,?,?)',
                       (OTHER['account'], OTHER['peer'], OTHER['chat'], 'h'))
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO),
                         verify(waiting=1), nav('exhausted'), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)], quick_send_exit=True)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['post_send_checks'], 1)
        self.assertEqual(out['post_send_list_verified'], 1)
        # The 1.3.104 one-open doctrine: after the Back the very next open
        # carries the merged list - the retry target FIRST, then the live
        # rows - in a single native scan.
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertEqual(len(opens), 3)
        merged = opens[1].kwargs['allowed']
        self.assertEqual(len(merged), 2)
        self.assertEqual((merged[0]['account'], merged[0]['peer']),
                         (WHO['account'], WHO['peer']))
        self.assertTrue(merged[0]['retry'])
        self.assertEqual((merged[1]['account'], merged[1]['peer']),
                         (OTHER['account'], OTHER['peer']))
        self.assertEqual([c.args[0] for c in self.nav.call_args_list],
                         ['open', 'back', 'open', 'open', 'return'])
        self.assertEqual(self.reader.call_count, 2)


class PrepareCheckpointIsVisibleAgain(unittest.TestCase):
    """v1.3.106 named the pre-open checkpoint but never whitelisted it, so
    the diagnostic projection silently dropped host_checkpoint from every
    validation-failed report (the M76yfk monitors had to be reconstructed by
    hand). The closed set now carries it."""

    def test_closed_checkpoint_set_contains_inbox_prepare(self):
        self.assertIn('inbox-prepare', assistant_failure.CHECKPOINTS)

    def test_projection_keeps_the_prepare_checkpoint(self):
        from assistant_error_notify import diagnostic_json
        report = dict(status='stopped', reason='initial-pass-stopped',
                      initial_run=dict(status='stopped', reason='inbox-not-finished',
                                       inbox=dict(status='inbox-stopped',
                                                  reason='navigation-check-stopped',
                                                  host_failure='validation-failed',
                                                  host_checkpoint='inbox-prepare',
                                                  validation_reason='Invalid journal targets')))
        cleaned = json.loads(diagnostic_json(report))['diagnostic']['initial_run']['inbox']
        self.assertEqual(cleaned['host_checkpoint'], 'inbox-prepare')
        self.assertEqual(cleaned['validation_reason'], 'Invalid journal targets')

    def test_walk_records_the_prepare_checkpoint_before_the_open(self):
        source = source_of(inbox)
        prepare = source.index("host_checkpoint = 'inbox-prepare'")
        # The preparation checkpoint precedes THIS iteration's own
        # 'inbox-open' (the second occurrence in the file: the first guards
        # the phase before the preparation block).
        self.assertIn("host_checkpoint = 'inbox-open'", source[prepare:])


if __name__ == '__main__':
    unittest.main()
