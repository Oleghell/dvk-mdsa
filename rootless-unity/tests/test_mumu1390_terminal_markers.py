"""v1.3.90 regressions: a finished chat is never re-entered in the SAME state.

Reported symptom: «но я ведь вижу что на этой версии оно все равно заходит в
чат даже которому час и несколько раз проверен, улучши этот фикс».

Root cause (the part 1.3.89 could not see): the deny-with-evidence upload only
carried CONSUMED message ids. A finished chat without them - a contact kept
with delivery disabled, a review quarantine before consume, or any genuinely
new post-terminal message the engine deliberately left read-only - had NO
entry in the uploaded target list, so the native needs-reply filter answered
alreadyHandled() false for it and adoption mode reopened the row on EVERY
later pass that had live work: open for a second, verified Back, nothing
recorded, next pass the same row again. The fix reports the selected row's
last message id from the native open (selected_message) and records it as a
durable terminal-state skip marker on every deliberate read-only leave, so
the row is skipped in every mode until a GENUINELY new message changes its
last message - «не захожу в то же состояние, только в новое».
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

import assistant_inbox as inbox
import dialog_browser as browser
import dialog_models as models
from assistant_navigation_check import safe_diagnostic
from conversation_engine import QUESTIONS
from mumu_store import SharedStore
from test_assistant_dialogs import nav_result as plain_nav
from test_inbox_profiles import Base, WHO, msg, snap
from test_dialog_browser import raw_open, TARGET


OTHER = dict(account='100', peer='201', chat='301')
THIRD = dict(account='100', peer='202', chat='302')


def shared(base, port=5559):
    return SharedStore(base.store.path, Path(base.tmp.name) / 'old', device_port=port)


def nav(state, who=None, unread=True, selected=None):
    value = plain_nav(state, who)
    value['diagnostic'].update(reply_filter_applied=state in ('opened', 'exhausted'),
                               reply_needed_verified=state == 'opened', waiting_rows_skipped=0, handled_rows_skipped=0)
    if unread:
        value['diagnostic'].update(unread_filter_applied=state in ('opened', 'exhausted'),
                                   unread_verified=state == 'opened')
    if selected is not None:
        value['diagnostic']['selected_message'] = selected
    return value


class NativeSelectionContract(unittest.TestCase):
    """The selected row's last message id rides the open diagnostic."""

    def test_browser_source_initializes_and_reports_selected_message(self):
        source = browser.build('open', allowed=[TARGET], needs_reply_only=True, adopt_untracked=True)
        self.assertIn('selected_message:null', source)
        self.assertIn('if(needsReplyOnly)n.selected_message=header.id;', source)

    def test_models_source_reports_selected_message(self):
        source = models.build(allowed=(), needs_reply_only=True, adopt_untracked=True)
        self.assertIn('if(needsReplyOnly)n.selected_message=header.id;', source)

    def test_validate_passes_the_selected_message_through(self):
        value = raw_open()
        value['navigation'].update(reply_filter_applied=True, reply_needed_verified=True,
                                   selected_message='42')
        result = browser.validate(value, 'open', allowed=[TARGET], needs_reply_only=True, adopt_untracked=True)
        self.assertEqual(result['state'], 'opened')
        self.assertEqual(result['diagnostic']['selected_message'], '42')

    def test_validate_rejects_malformed_selected_message(self):
        base = lambda: dict(raw_open())
        # A selected id without a verified reply-needed selection.
        v = base(); v['navigation']['selected_message'] = '42'
        with self.assertRaises(ValueError):
            browser.validate(v, 'open', allowed=[TARGET], needs_reply_only=True, adopt_untracked=True)
        # Non-digit, leading zero, overlong and non-string forms.
        for bad in ('042', 'abc', '4' * 20, 42, -1, '', '4.2'):
            v = base(); v['navigation'].update(reply_filter_applied=True, reply_needed_verified=True,
                                               selected_message=bad)
            with self.assertRaises(ValueError):
                browser.validate(v, 'open', allowed=[TARGET], needs_reply_only=True, adopt_untracked=True)
        # A selected id on an operation without the reply filter.
        v = base(); v['navigation'].update(reply_filter_applied=False, reply_needed_verified=False,
                                           selected_message='42')
        with self.assertRaises(ValueError):
            browser.validate(v, 'open', allowed=[TARGET], adopt_untracked=True)

    def test_safe_diagnostic_validates_the_optional_field(self):
        def diagnostic(**extra):
            value = plain_nav('opened', WHO)['diagnostic']
            value.update(reply_filter_applied=True, reply_needed_verified=True)
            value.update(extra)
            return value
        self.assertIsNone(safe_diagnostic(diagnostic(selected_message=None)).get('selected_message'))
        self.assertEqual(safe_diagnostic(diagnostic(selected_message='42'))['selected_message'], '42')
        for bad in ('042', 'x', 42, '4' * 20):
            with self.assertRaises(ValueError):
                safe_diagnostic(diagnostic(selected_message=bad))
        # Without a verified selection the id is never valid.
        value = plain_nav('opened', WHO)['diagnostic']
        value.update(reply_filter_applied=True, reply_needed_verified=False, selected_message='42')
        with self.assertRaises(ValueError):
            safe_diagnostic(value)


class TerminalMarkerHelpers(unittest.TestCase):
    """terminal_marker: terminal stages only, positive ids only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SharedStore(Path(self.tmp.name) / 'assistant.sqlite3',
                                 Path(self.tmp.name) / 'old', device_port=5559)
        self.chainobj = inbox.InboxChain(self.store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)

    def chain(self):
        return self.chainobj

    def stage(self, who, stage):
        with self.store.connection() as db:
            db.execute("INSERT OR REPLACE INTO manual_actions(account,peer,initial_chat,text_hash,confirmed,status)"
                       " VALUES(?,?,?,'h',1,'handler-returned-unconfirmed')",
                       (who['account'], who['peer'], who['chat']))
            db.execute("INSERT OR REPLACE INTO chain_dialogs VALUES(?,?,?,?,?,'salt')",
                       (who['account'], who['peer'], who['chat'], '1', stage))

    def test_terminal_stage_records_the_marker(self):
        for stage in ('done', 'declined', 'manual-review'):
            self.stage(WHO, stage)
            self.assertTrue(inbox.terminal_marker(self.chain(), WHO, '42'))
            with self.store.read_connection() as db:
                self.assertEqual(db.execute('SELECT last_message,reason FROM operator_rejects').fetchall(),
                                 [('42', 'terminal-state')])
            with self.store.connection() as db:
                db.execute('DELETE FROM operator_rejects')

    def test_active_stage_and_missing_chain_never_record(self):
        self.stage(WHO, 'wait-mood')
        self.assertFalse(inbox.terminal_marker(self.chain(), WHO, '42'))
        self.assertFalse(inbox.terminal_marker(self.chain(), OTHER, '42'))
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM operator_rejects').fetchone()[0], 0)

    def test_bad_ids_never_record(self):
        self.stage(WHO, 'declined')
        for bad in (None, '', 42, dict()):
            self.assertFalse(inbox.terminal_marker(self.chain(), WHO, bad))
        self.assertEqual(inbox.snapshot_marker(self.chain(), WHO, None), False)
        self.assertEqual(inbox.snapshot_marker(self.chain(), WHO, dict(messages=[])), False)
        self.assertTrue(inbox.snapshot_marker(self.chain(), WHO, snap(msg(1002, 'до свидания'))))
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT last_message,reason FROM operator_rejects').fetchall(),
                             [('1002', 'terminal-state')])


class WalkStrayTerminalMarker(Base):
    """Walk level: the deliberate read-only leave records the row marker."""

    def setUp(self):
        super().setUp()
        self.store = shared(self)
        self.chainobj = self.chain()

    def finished(self, who, stage='declined'):
        self.journal(who)
        with self.store.connection() as db:
            db.execute("INSERT OR REPLACE INTO chain_dialogs VALUES(?,?,?,?,?,'salt')",
                       (who['account'], who['peer'], who['chat'], '1', stage))

    def rejects(self):
        with self.store.read_connection() as db:
            return db.execute('SELECT account,peer,chat,last_message,reason FROM operator_rejects').fetchall()

    def test_stray_terminal_row_records_marker_and_rides_later_uploads(self):
        # The exact reported shape: a finished chat WITHOUT consumed-id
        # evidence rides a live pass. Before 1.3.90 the row was opened, left
        # by verified Back and nothing was recorded - the same row reopened on
        # every later pass. Now the native-reported row id becomes a durable
        # skip marker that rides every later upload.
        self.finished(OTHER)
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', OTHER, selected='42'), nav('returned', OTHER),
                         nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['terminal_row_markers'], 1)
        self.assertEqual(out['dialogs_processed'], 2)
        self.assertEqual(self.rejects(), [('100', '201', '301', '42', 'terminal-state')])
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        # The marker rides the SAME pass's later uploads as skip evidence.
        self.assertIn(dict(account='100', peer='201', chat='301', seen_ids=['42']),
                      opens[1].kwargs['allowed'])

    def test_second_pass_uploads_the_marker_so_the_row_is_skipped(self):
        # The «час и несколько раз проверен» contract: a LATER pass with live
        # work uploads the marker as the row's seen_ids, so the native
        # needs-reply filter (alreadyHandled) answers handled for the SAME
        # last message and the finished row is never re-entered.
        self.finished(OTHER)
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        first = self.walk([nav('opened', OTHER, selected='42'), nav('returned', OTHER),
                           nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                          [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(first['terminal_row_markers'], 1)
        # A fresh live chat keeps the second pass running; OTHER is terminal
        # and carries its marker - the uploaded target list proves the native
        # would skip the row (id 42 already handled).
        self.journal(THIRD)
        hello3 = msg(1004, 'Привет', who=THIRD)
        question3 = msg(1005, QUESTIONS[0], True, THIRD)
        # THIRD is answered; WHO's answered row is a native waiting-skip
        # (its last message is our own question), so the scan exhausts.
        second = self.walk([nav('opened', THIRD), nav('returned', THIRD),
                            nav('exhausted', unread=False), nav('search-ready')],
                           [snap(hello3, who=THIRD), snap(hello3, who=THIRD),
                            snap(hello3, question3, who=THIRD)])
        self.assertEqual(second['status'], 'inbox-completed')
        self.assertEqual(second['terminal_row_markers'], 0)
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertIn(dict(account='100', peer='201', chat='301', seen_ids=['42']),
                      opens[0].kwargs['allowed'])
        self.assertEqual(second['submission_calls'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0], QUESTIONS[0]])

    def test_genuinely_new_message_refreshes_the_marker(self):
        # «только в новое»: a genuinely new message changes the row's last id,
        # the native selects the row once more, and the marker is REPLACED by
        # the new id so later passes again skip the row.
        self.finished(OTHER)
        with self.store.connection() as db:
            db.execute("INSERT OR REPLACE INTO operator_rejects VALUES(?,?,?,?,?)",
                       ('100', '201', '301', '5', 'terminal-state'))
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', OTHER, selected='9'), nav('returned', OTHER),
                         nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['terminal_row_markers'], 1)
        self.assertEqual(self.rejects(), [('100', '201', '301', '9', 'terminal-state')])
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertIn(dict(account='100', peer='201', chat='301', seen_ids=['9']),
                      opens[1].kwargs['allowed'])
        self.assertNotIn(dict(account='100', peer='201', chat='301', seen_ids=['5']),
                         opens[1].kwargs['allowed'])

    def test_active_stray_is_never_marked(self):
        # A mid-pass revisit of an ACTIVE chat (pruned from the groups after
        # processing) must never record a marker: its cooldown or reply window
        # has to re-admit the row unchanged on a later pass.
        self.journal(OTHER)
        self.journal()
        hello_other = msg(1002, 'Привет', who=OTHER)
        question_other = msg(1003, QUESTIONS[0], True, OTHER)
        hello = msg(1004, 'Привет')
        question = msg(1005, QUESTIONS[0], True)
        out = self.walk([nav('opened', OTHER, selected='7'), nav('returned', OTHER),
                         nav('opened', OTHER, selected='7'), nav('returned', OTHER),
                         nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello_other, who=OTHER), snap(hello_other, who=OTHER),
                         snap(hello_other, question_other, who=OTHER),
                         snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertTrue(out.get('adoption_disabled_reopen'))
        self.assertEqual(out['terminal_row_markers'], 0)
        self.assertEqual(self.rejects(), [])

    def test_isolated_chat_records_marker_from_the_read_snapshot(self):
        # A chat quarantined into manual-review just after its read: the
        # snapshot the host already has becomes the marker - no extra open,
        # no later re-entry into the same state.
        self.journal()
        hello = msg(1002, 'Привет')
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello)],
                        sender=MagicMock(side_effect=RuntimeError('PRIVATE')))
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['isolated_dialogs'], 1)
        self.assertEqual(out['terminal_row_markers'], 1)
        self.assertEqual(self.rejects(), [('100', '200', '300', '1002', 'terminal-state')])
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs WHERE peer=?',
                                        (WHO['peer'],)).fetchall(), [('manual-review',)])

    def test_missing_native_id_records_nothing(self):
        # An older native payload without selected_message degrades to the
        # bounded 1.3.89 behavior instead of failing the pass.
        self.finished(OTHER)
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', OTHER), nav('returned', OTHER),
                         nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['terminal_row_markers'], 0)
        self.assertEqual(self.rejects(), [])


class ReviewTargetGuard(unittest.TestCase):
    """A review target's deliberately empty seen_ids is never poisoned."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SharedStore(Path(self.tmp.name) / 'assistant.sqlite3',
                                 Path(self.tmp.name) / 'old', device_port=5559)
        self.chainobj = inbox.InboxChain(self.store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)

    def chain(self):
        return self.chainobj

    def review_target(self):
        # A manual-review chat with an ambiguous contact batch: exactly the
        # contact_candidates() shape that forces empty seen_ids so the row
        # MUST open for the review probe.
        with self.store.connection() as db:
            db.execute("INSERT OR REPLACE INTO manual_actions(account,peer,initial_chat,text_hash,confirmed,status)"
                       " VALUES(?,?,?,'h',1,'handler-returned-unconfirmed')",
                       (WHO['account'], WHO['peer'], WHO['chat']))
            db.execute("INSERT OR REPLACE INTO chain_dialogs VALUES(?,?,?,?,?,'salt')",
                       (WHO['account'], WHO['peer'], WHO['chat'], '1', 'manual-review'))
            db.execute("INSERT OR REPLACE INTO chain_review_reasons VALUES(?,'contact-batch-ambiguous')",
                       (WHO['chat'],))
            db.execute("INSERT OR REPLACE INTO chain_actions VALUES(?,?,?,?,'outgoing-observed')",
                       (WHO['chat'], 'contact', 'trigger', 'hash'))
            db.execute("INSERT OR REPLACE INTO operator_rejects VALUES(?,?,?,?,?)",
                       (WHO['account'], WHO['peer'], WHO['chat'], '42', 'terminal-state'))

    def test_marker_never_merges_into_a_review_entry(self):
        self.review_target()
        merged = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['seen_ids'], [])
        # The same marker still skips the row once the review is no longer a
        # target: a non-review round keeps the plain merge.
        with self.store.connection() as db:
            db.execute('DELETE FROM chain_review_reasons')
        plain = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        self.assertEqual(plain[0]['seen_ids'], ['42'])

    def test_standalone_marker_entry_still_skips_a_non_target_row(self):
        self.review_target()
        # A finished chat that is NOT a round target rides as its own entry.
        merged = inbox.with_seen_ids(self.chain(), [dict(OTHER)])
        by_peer = {(x['account'], x['peer']): x for x in merged}
        self.assertEqual(by_peer[('100', '200')]['seen_ids'], ['42'])


if __name__ == '__main__':
    unittest.main()
