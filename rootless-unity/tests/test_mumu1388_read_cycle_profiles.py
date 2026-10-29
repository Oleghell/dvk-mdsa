"""v1.3.88 regressions: the read-all-answered reopen cycle. Synthetic only.

Reported symptom: «когда все чаты прочитаны то не отвеченный просто заходит в
чат постоянно и выходит, и так по кругу, пофикси чтобы дальше искало анкеты как
это должно быть по алгоритму если все чаты прочитаны и отвечены».

Two coupled defects, both fixed here:
(1) The monitor counted ANY pass with dialogs_processed>0 as productive work -
    including a pass that only OPENED the unanswerable row and left it by
    verified Back - so continuous full mode rechecked the inbox forever and
    never reached the profile search.
(2) The adoption filter (adopt_untracked, reset on every pass) kept opening
    rows the host had deliberately excluded this round (an active history
    cooldown, a manual /num block or silence, a run-scoped reply exclusion):
    open -> Back -> next pass -> the same row again. Those peers are now
    uploaded to the native scan as a deny-only hidden set that permitted()
    checks BEFORE the adoption arm; the set is recomputed per open call, so an
    expired cooldown stops hiding the peer immediately.
"""
from contextlib import nullcontext
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

import assistant_monitor as monitor
import dialog_browser as browser
import dialog_models as models
import assistant_inbox as inbox
from assistant_settings import Settings
from conversation_engine import QUESTIONS
from mumu_store import SharedStore
from test_assistant_monitor import inbox_result, list_result
from test_inbox_profiles import Base, WHO, msg, nav, snap
from test_dialog_browser import raw_open, TARGET


OTHER = dict(account='100', peer='201', chat='301')


def shared(base, port=5559):
    return SharedStore(base.store.path, Path(base.tmp.name) / 'old', device_port=port)


class SearchAfterReadCycle(unittest.TestCase):
    """Monitor level: an open/leave-only pass moves on to the profile search."""

    def setUp(self):
        self.stop = threading.Event()
        self.initial = MagicMock(return_value=dict(status='completed', report_name='last-run.json'))

    def run_cycle(self, incoming, *, wait=None):
        events = []

        def inbox_pass(*a, **k):
            events.append('inbox')
            return incoming()

        def profiles(*a, **k):
            events.append('profiles')
            self.stop.set()
            return dict(status='completed', report_name='last-run.json')

        navf = MagicMock(side_effect=lambda op, *a, **kw:
                         list_result() if op == 'list' else dict(list_result(), state='search-ready'))
        out = monitor.run(Settings(), self.stop, lambda _: True, mode='full',
                          inbox=MagicMock(side_effect=inbox_pass), initial=self.initial,
                          navigator=navf, lock=nullcontext, write=lambda _: 'last-monitor.json',
                          wait=wait or MagicMock(side_effect=AssertionError(
                              'An open/leave-only pass must not idle-spin')),
                          repeat=profiles, continuous=True, clock=lambda: 0)
        return out, events

    def test_open_leave_only_pass_starts_profiles_not_rechecks(self):
        # All chats are read and answered; one unanswerable chat is opened and
        # left every pass. dialogs_processed>0 with no reply work is NOT
        # productive: the monitor goes straight to the profile batch («дальше
        # ищет анкеты») instead of cycling open->back on the same dialog.
        out, events = self.run_cycle(lambda: inbox_result(dialogs_processed=1))
        self.assertEqual(events, ['inbox', 'profiles'])
        self.assertEqual(out['immediate_rechecks'], 0)
        self.assertEqual(out['early_profile_batches'], 1)
        self.assertEqual(out['profile_batches_completed'], 1)

    def test_productive_pass_still_drains_once_before_profiles(self):
        # The drain contract itself is unchanged: a pass that submitted a
        # reply gets exactly one fresh recheck before the profile batch.
        calls = [0]

        def incoming():
            calls[0] += 1
            return inbox_result(dialogs_processed=1, submission_calls=1, handler_returns=1) \
                if calls[0] == 1 else inbox_result()

        out, events = self.run_cycle(incoming, wait=MagicMock(side_effect=AssertionError(
            'A productive pass must not idle either')))
        self.assertEqual(events, ['inbox', 'inbox', 'profiles'])
        self.assertEqual(out['immediate_rechecks'], 1)

    def test_new_incoming_read_still_drains_before_profiles(self):
        # Reading a genuinely NEW incoming message (a contact arrival, an
        # unread burst) is productive even when nothing was sent this pass.
        calls = [0]

        def incoming():
            calls[0] += 1
            return inbox_result(dialogs_processed=1, new_incoming_messages=1) \
                if calls[0] == 1 else inbox_result()

        out, events = self.run_cycle(incoming)
        self.assertEqual(events, ['inbox', 'inbox', 'profiles'])
        self.assertEqual(out['immediate_rechecks'], 1)


class HiddenRows(Base):
    """Walk level: deliberately excluded rows never reach the native scan."""

    def setUp(self):
        super().setUp()
        self.store = shared(self)

    def defer(self, who):
        import assistant_history_wait as history_wait
        history_wait.initialize(self.store)
        with self.store.connection() as db:
            db.execute('INSERT INTO inbox_history_deferrals VALUES(?,?,?,?)',
                       (who['account'], who['peer'], who['chat'], 1e12))

    def walk_eligible(self):
        # One eligible tracked chat (answered in this pass) keeps the pass
        # running; the walk returns after its verified return to search.
        # The cooled/blocked row is hidden from the scan, so exactly ONE row
        # is ever opened: open -> back -> return.
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        return self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                         [snap(hello), snap(hello), snap(hello, question)])

    def test_cooled_tracked_row_is_hidden_from_every_open(self):
        # The 1.3.86 latch stopped the SECOND in-pass revisit; the row was
        # still opened once per pass because adoption mode reset every pass.
        # Now the cooled peer is uploaded as hidden and never opened at all.
        self.journal(OTHER)
        self.defer(OTHER)
        out = self.walk_eligible()
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['dialogs_opened'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        self.assertEqual(len(opens), 1)  # the cooled row is never even opened
        for call in opens:
            self.assertIn(dict(account='100', peer='201'), call.kwargs['hidden'])
        self.assertTrue(all(c.kwargs['adopt_untracked'] for c in opens))

    def test_expired_cooldown_stops_hiding_the_peer(self):
        # The hidden set is host data recomputed per open: after the cooldown
        # expires the peer is uploaded no more and becomes a normal target.
        import assistant_history_wait as history_wait
        history_wait.initialize(self.store)
        with self.store.connection() as db:
            db.execute('INSERT INTO inbox_history_deferrals VALUES(?,?,?,?)',
                       (OTHER['account'], OTHER['peer'], OTHER['chat'], 0))
        self.assertEqual(inbox.hidden_peers(self.chain()), ())

    def test_manually_blocked_row_is_hidden_from_every_open(self):
        # /num may commit while the worker runs - AFTER the greeting was
        # already journaled. The blocked peer's row must not be opened by
        # adoption mode on every later pass either.
        self.journal(OTHER)  # greeted before the manual deny arrived
        with self.store.connection() as db:
            db.execute("INSERT INTO mumu_peer_blocks VALUES('201','manual-block','telegram','','',CURRENT_TIMESTAMP)")
            db.execute("INSERT INTO mumu_manual_silences VALUES('201')")
        out = self.walk_eligible()
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['dialogs_opened'], 1)
        opens = [c for c in self.nav.call_args_list if c.args[0] == 'open']
        for call in opens:
            self.assertIn(dict(account='*', peer='201'), call.kwargs['hidden'])

    def test_only_unanswerable_chat_left_means_an_empty_pass(self):
        # The exact reported end state: everything is read and answered except
        # ONE deferred chat. Its cooldown hides it from the scan, the pass is
        # empty, no row is opened at all - and the monitor (above) moves on to
        # the profile search instead of cycling.
        self.journal()
        self.defer(WHO)
        out = self.walk([], [])
        self.assertEqual(out['status'], 'inbox-empty')
        self.nav.assert_not_called()
        self.reader.assert_not_called()


class HiddenSet(unittest.TestCase):
    """The deny-only hidden set source tables and their scopes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SharedStore(Path(self.tmp.name) / 'assistant.sqlite3',
                                 Path(self.tmp.name) / 'old', device_port=5559)
        import assistant_history_wait as history_wait
        from assistant_reply_window import tables as reply_tables
        history_wait.initialize(self.store)
        with self.store.connection() as db:
            reply_tables(db)
        self.now = 1000.0

    def chain(self):
        return inbox.InboxChain(self.store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)

    def hidden(self, clock=None):
        return inbox.hidden_peers(self.chain(), clock=clock or (lambda: self.now))

    def test_active_cooldown_hides_and_expiry_releases(self):
        with self.store.connection() as db:
            db.execute("INSERT INTO inbox_history_deferrals VALUES('100','200','300',?)", (self.now + 60,))
            db.execute("INSERT INTO inbox_history_deferrals VALUES('100','201','301',?)", (self.now - 10,))
        now = self.hidden()
        self.assertIn(dict(account='100', peer='200'), now)
        self.assertNotIn(dict(account='100', peer='201'), now)
        later = inbox.hidden_peers(self.chain(), clock=lambda: self.now + 61)
        self.assertNotIn(dict(account='100', peer='200'), later)

    def test_run_scoped_reply_exclusion_hides(self):
        with self.store.connection() as db:
            db.execute("INSERT INTO inbox_reply_exclusions VALUES('100','202','new-start-excluded')")
        self.assertIn(dict(account='100', peer='202'), self.hidden())

    def test_manual_block_and_silence_hide_under_every_account(self):
        with self.store.connection() as db:
            db.execute("INSERT INTO mumu_peer_blocks VALUES('300','manual-block','telegram','','',CURRENT_TIMESTAMP)")
            db.execute("INSERT INTO mumu_manual_silences VALUES('301')")
        got = self.hidden()
        self.assertIn(dict(account='*', peer='300'), got)
        self.assertIn(dict(account='*', peer='301'), got)

    def test_automatic_outcomes_are_not_hidden(self):
        # contact-received/contact-refused keep their own 1.3.86 skip markers
        # and the operator-led exemption; they must stay visible to the scan.
        with self.store.connection() as db:
            db.execute("INSERT INTO mumu_peer_blocks VALUES('302','contact-received','5563','100','302',CURRENT_TIMESTAMP)")
        self.assertEqual(tuple(p for p in self.hidden() if p['peer'] == '302'), ())

    def test_plain_store_never_hides(self):
        from assistant_store import Store
        from assistant_inbox import InboxChain
        plain = Store(Path(self.tmp.name) / 'plain.sqlite3', Path(self.tmp.name) / 'old2')
        self.assertEqual(inbox.hidden_peers(InboxChain(plain)), ())


class NativeContracts(unittest.TestCase):
    """The hidden-peer native contract: build, upload, validation."""

    def test_hidden_set_is_compiled_and_guard_permits_before_adoption(self):
        source = browser.build('open', allowed=[TARGET], needs_reply_only=True, adopt_untracked=True,
                               hidden=[dict(account='100', peer='200'), dict(account='*', peer='999')])
        self.assertIn('hiddenPeers=new Set(["100:200", "*:999"])', source)
        self.assertIn('permitted=who=>!hiddenPeer(who)&&(adoptUntracked||allowedTargets.some', source)
        self.assertIn("hiddenPeers.has(who.account+':'+who.peer)||hiddenPeers.has('*:'+who.peer)", source)
        empty = browser.build('open', allowed=[TARGET], needs_reply_only=True)
        self.assertIn('hiddenPeers=new Set([])', empty)

    def test_prepared_source_swaps_the_uploaded_hidden_set(self):
        prepared = browser.prepared_source(browser.build('open', needs_reply_only=True))
        self.assertIn('hiddenPeers=navigationHidden', prepared)
        self.assertIn('function prepareNavigationHidden(values)', prepared)
        navigation = browser.PreparedNavigation(
            browser.build('open', needs_reply_only=True), [TARGET], lambda v: v,
            hidden=[dict(account='100', peer='200')])
        self.assertEqual(navigation.hidden, [dict(account='100', peer='200')])
        bare = browser.PreparedNavigation(browser.build('open', needs_reply_only=True), [TARGET], lambda v: v)
        self.assertEqual(bare.hidden, [])

    def test_hidden_inputs_are_strict_bounded_literals(self):
        self.assertEqual(browser.hidden_peers([dict(account='100', peer='200'), dict(account='*', peer='7')]),
                         [dict(account='100', peer='200'), dict(account='*', peer='7')])
        for bad in ([dict(account='0', peer='200')], [dict(account='100', peer='0')],
                    [dict(account='100', peer='200', chat='1')],
                    [dict(account='100', peer='200'), dict(account='100', peer='200')],
                    'x', [dict(account='-1', peer='200')], [dict(account='*', peer='*')]):
            with self.assertRaises(ValueError):
                browser.hidden_peers(bad)
        for bad in (1, 'true', None, {'a': 1}):
            with self.assertRaises(ValueError):
                browser.build('open', allowed=[TARGET], hidden=bad)
        with self.assertRaises(ValueError):
            browser.build('back', expected=WHO, hidden=[dict(account='100', peer='200')])

    def test_opened_hidden_peer_is_rejected_exact_and_wildcard(self):
        result = browser.validate(raw_open(), 'open', allowed=[TARGET], adopt_untracked=True,
                                  hidden=[dict(account='101', peer='200')])
        self.assertEqual(result['state'], 'opened')  # a different account is unaffected
        for hidden in ([dict(account='100', peer='200')], [dict(account='*', peer='200')]):
            with self.assertRaises(ValueError):
                browser.validate(raw_open(), 'open', allowed=[TARGET], adopt_untracked=True, hidden=hidden)

    def test_model_navigator_plumbs_the_hidden_set(self):
        source = models.build(allowed=(), needs_reply_only=True, adopt_untracked=True)
        self.assertIn('hiddenPeers=new Set([])', source)
        prepared = browser.prepared_source(source)
        self.assertIn('hiddenPeers=navigationHidden', prepared)
        for bad in (1, 'x', [dict(account='100')]):
            with self.assertRaises(ValueError):
                models.build(hidden=bad)
        # Non-open operations simply never carry a hidden set.
        with patch_object_models_capture():
            models.perform('return', 'adb', 'folder', hidden=[dict(account='100', peer='200')])


def patch_object_models_capture():
    from unittest.mock import patch
    return patch('one_chat_device.capture', MagicMock(return_value=(MagicMock(), None)))


if __name__ == '__main__':
    unittest.main()
