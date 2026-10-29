"""v1.3.84 operator-led dialog adoption; synthetic only, no device or sends.

Covers the structure probe (own verified messages + native-verified latest peer
message), the durable operator_bindings/rejects journals, the third eligibility
source in inbox_targets/InboxChain, and the adopt-mode native contracts.
"""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import assistant_inbox as inbox
import dialog_browser as browser
from assistant_inbox import InboxChain, inbox_targets, with_seen_ids
from assistant_operator_adoption import adopt, probe, record_reject, reject_targets, tracked
from assistant_settings import Settings
from assistant_store import Store
from conversation_engine import QUESTIONS
from test_assistant_dialogs import nav_result as plain_nav
from test_guided_chain import GREETING, stable_snapshots

WHO = dict(account='100', peer='200', chat='300')
OTHER = dict(account='100', peer='201', chat='301')


def nav(state, who=None, unread=True):
    value = plain_nav(state, who)
    value['diagnostic'].update(reply_filter_applied=state in ('opened', 'exhausted'),
                               reply_needed_verified=state == 'opened', waiting_rows_skipped=0, handled_rows_skipped=0)
    if unread:
        value['diagnostic'].update(unread_filter_applied=state in ('opened', 'exhausted'),
                                   unread_verified=state == 'opened')
    return value


def msg(i, text, own=False, who=WHO):
    return dict(id=str(i), sender=who['account'] if own else who['peer'], text=text)


def raw(*messages, who=WHO, latest=None):
    return dict(identity=dict(who), messages=list(messages), latest_message_id=latest)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'assistant.sqlite3', Path(self.tmp.name) / 'old')
        self.stop = threading.Event()
        self.settings = Settings()
        self.approve = MagicMock(return_value=True)
        self.sent = []

    def chain(self):
        return InboxChain(self.store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)

    def sender(self, adb, folder, snapshot, cancelled, *, text):
        self.sent.append(text)
        return dict(attempted=True, handler_returned=True)

    def journal(self, who=WHO):
        action = self.store.reserve(dict(attempt=1, account=who['account'], peer=who['peer'],
                                         chat='-1', variant=0), GREETING, approved=True)
        self.store.finish(action, dict(send_attempted=True, send_handler_returned=True))

    def walk(self, navigations, reads, **kwargs):
        self.nav = MagicMock(side_effect=navigations)
        self.reader = MagicMock(side_effect=stable_snapshots(reads))
        return inbox.walk(self.settings, self.stop, self.approve, lambda _: None,
                          kwargs.pop('chain', None) or self.chain(), navigator=self.nav,
                          reader=self.reader, sender=kwargs.pop('sender', self.sender),
                          greetings=(GREETING,), pause=lambda _: False, **kwargs)


class Structure(Base):
    def test_own_led_dialog_with_peer_latest_is_adopted_wait_reply(self):
        chain = self.chain()
        adopted, reason = adopt(chain, raw(msg(11, 'Привет, я Игорь', True),
                                           msg(12, 'Привет'), latest='12'))
        self.assertEqual((adopted, reason), (True, 'adopted'))
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT greeting,stage FROM chain_dialogs').fetchall(),
                             [('11', 'wait-reply')])
            # Everything except the native-verified latest peer message is seen;
            # the latest is the one new incoming reply the chain answers.
            self.assertEqual(db.execute('SELECT message FROM chain_seen').fetchall(), [('11',)])
            self.assertEqual(db.execute('SELECT account,peer,chat FROM operator_bindings').fetchall(),
                             [('100', '200', '300')])

    def test_stranger_chat_without_own_messages_is_rejected(self):
        chain = self.chain()
        self.assertEqual(adopt(chain, raw(msg(21, 'Привет'), latest='21')),
                         (False, 'no-own-messages'))

    def test_own_latest_and_unverified_latest_are_rejected(self):
        chain = self.chain()
        self.assertEqual(adopt(chain, raw(msg(31, 'Написал сам', True), latest='31')),
                         (False, 'latest-not-peer'))
        self.assertEqual(adopt(chain, raw(msg(31, 'Написал сам', True), msg(32, 'Ответ'),
                                          latest=None)),
                         (False, 'latest-unverified'))

    def test_existing_journals_chains_and_reviews_are_never_reset(self):
        chain = self.chain()
        self.journal()
        self.assertEqual(adopt(chain, raw(msg(11, 'Своё', True), msg(12, 'Ответ'), latest='12')),
                         (False, 'journal-exists'))
        other = Store(Path(self.tmp.name) / 'second.sqlite3', Path(self.tmp.name) / 'old2')
        chain2 = InboxChain(other, choose=lambda: 0)
        with other.connection() as db:
            db.execute("INSERT INTO chain_actions VALUES('300','question',NULL,'hash','reserved-unknown')")
        self.assertEqual(adopt(chain2, raw(msg(11, 'Своё', True), msg(12, 'Ответ'), latest='12')),
                         (False, 'persisted-state-protected'))
        with other.connection() as db:
            db.execute('DELETE FROM chain_actions')
            db.execute("INSERT INTO chain_review_reasons VALUES('300','history-missing')")
        self.assertEqual(adopt(chain2, raw(msg(11, 'Своё', True), msg(12, 'Ответ'), latest='12')),
                         (False, 'persisted-state-protected'))


class ProbeAndRejects(Base):
    def test_probe_read_failure_is_benign_and_records_nothing(self):
        chain = self.chain()

        def broken(who):
            raise RuntimeError('PRIVATE transport noise')
        self.assertEqual(probe(chain, OTHER, broken, lambda: False), 'read-failed')
        self.assertEqual(reject_targets(self.store), [])
        self.assertFalse(tracked(self.store, OTHER))

    def test_rejected_probe_records_skip_marker_until_last_message_changes(self):
        chain = self.chain()
        stranger = raw(msg(21, 'Привет', who=OTHER), who=OTHER, latest='21')
        self.assertEqual(probe(chain, OTHER, lambda who: stranger, lambda: False), 'rejected')
        self.assertEqual(reject_targets(self.store),
                         [dict(account='100', peer='201', chat='301', seen_ids=['21'])])
        # A NEW peer message changes the row's last message and reopens it.
        record_reject(self.store, OTHER, '22', 'no-own-messages')
        self.assertEqual(reject_targets(self.store),
                         [dict(account='100', peer='201', chat='301', seen_ids=['22'])])

    def test_with_seen_ids_merges_reject_markers_without_ambiguity(self):
        chain = self.chain()
        record_reject(self.store, OTHER, '21', 'no-own-messages')
        merged = with_seen_ids(chain, [dict(account='100', peer='200', chat='300')])
        self.assertIn(dict(account='100', peer='200', chat='300', seen_ids=[]), merged)
        self.assertIn(dict(account='100', peer='201', chat='301', seen_ids=['21']), merged)
        # A peer that later becomes tracked never duplicates its reject marker.
        self.journal(OTHER)
        merged = with_seen_ids(chain, [dict(account='100', peer='201', chat='-1')])
        self.assertEqual([x for x in merged if x['peer'] == '201'],
                         [dict(account='100', peer='201', chat='-1', seen_ids=[])])


class Eligibility(Base):
    def test_operator_bindings_are_a_third_target_source(self):
        chain = self.chain()
        self.assertEqual(inbox_targets(chain), ([], []))
        own = msg(11, 'Своё сообщение оператора', True)
        adopted, _ = adopt(chain, raw(own, msg(12, 'Ответ'), latest='12'))
        self.assertTrue(adopted)
        attention, unread = inbox_targets(chain)
        self.assertEqual(unread, [dict(account='100', peer='200', chat='300')])
        from assistant_chain import text_hash
        self.assertEqual(chain.authorized(WHO), text_hash('Своё сообщение оператора'))
        # The anchor must stay present in the verified history on re-bind.
        chain.bind(raw(own, msg(12, 'Ответ'), latest='12'), (), approved=True)
        with self.assertRaises(Exception):
            chain.bind(raw(msg(12, 'Ответ'), latest='12'), (), approved=True)

    def test_journal_wins_over_stale_operator_rows(self):
        chain = self.chain()
        self.journal()
        with self.store.connection() as db:
            db.execute("INSERT INTO operator_bindings VALUES('100','200','300','hash')")
        attention, unread = inbox_targets(chain)
        self.assertEqual(attention + unread, [dict(account='100', peer='200', chat='-1')])


class NativeContracts(unittest.TestCase):
    TARGET = dict(account='100', peer='200', chat='-1')

    def source(self, **kwargs):
        return browser.build('open', allowed=[self.TARGET], needs_reply_only=True, **kwargs)

    def test_adopt_mode_permits_untracked_rows_and_strict_mode_does_not(self):
        source = self.source(adopt_untracked=True)
        self.assertIn('adoptUntracked=true', source)
        self.assertIn('permitted=who=>adoptUntracked||allowedTargets.some', source)
        self.assertIn('adoptUntracked=false', self.source())
        for bad in (1, 'true', None):
            with self.assertRaises(ValueError):
                browser.build('open', allowed=[self.TARGET], adopt_untracked=bad)
        with self.assertRaises(ValueError):
            browser.build('back', expected=WHO, adopt_untracked=True)

    def test_untracked_private_binding_only_validates_in_adopt_mode(self):
        from test_dialog_browser import raw_open
        result = browser.validate(raw_open(), 'open', allowed=[], adopt_untracked=True)
        self.assertEqual(result['state'], 'opened')
        self.assertEqual(result['identity'], WHO)
        with self.assertRaises(ValueError):
            browser.validate(raw_open(), 'open', allowed=[])
        with self.assertRaises(ValueError):
            browser.validate(raw_open(), 'open', allowed=[], adopt_untracked=1)


if __name__ == '__main__':
    unittest.main()
