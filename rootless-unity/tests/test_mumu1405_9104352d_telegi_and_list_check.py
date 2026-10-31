"""Reports S5GK7 + 9104352d port 5571 (v1.3.104): three contracts.

1. «Телеги нет, стёрла. Мах или вотсап» - the whole телег-stem joins the TG
   family, a bare app list is a platform choice in EITHER order, and the
   deny gates still win, so the chain stays open and asks the app question.
2. «заходит в новый непрочитанный чат и резко выходит» - the entry shapes
   (not-ready with zero identity evidence, observer-stopped mid-read) get
   up to two read-only retries of the SAME bound chat.
3. «резко после этого делай шаг назад и проверяй уже в личке на отправку» -
   no in-chat post-send history read; the row-level verification rides the
   next scan and reports its counters.

Synthetic only; no device, database or worker process is touched."""
import unittest
from test_inbox_profiles import Base, WHO, OTHER, msg, snap, nav, verify

MSG = 'Телеги нет, стёрла. Мах или вотсап'


class TelegiFamily(unittest.TestCase):
    def test_reported_message_is_a_platform_choice(self):
        import assistant_contact_intent as intent
        import assistant_contact_clarify as clarify
        import assistant_contact_policy as policy
        m = [{'text': MSG, 'sender': 'peer'}]
        self.assertEqual(intent.available_alternative(m), 'whatsapp')
        self.assertTrue(clarify.chosen(m))
        self.assertTrue(intent.max_selected(m))

    def test_mirrored_order_and_absence_forms_are_choices(self):
        import assistant_contact_intent as intent
        import assistant_contact_clarify as clarify
        for text in ('Телегу удалила. Вотсап или мах', 'Телегу снесла, есть макс',
                     'Вотсап или телега'):
            m = [{'text': text, 'sender': 'peer'}]
            self.assertTrue(clarify.chosen(m) or intent.max_selected(m), text)

    def test_deny_gates_still_win(self):
        import assistant_contact_intent as intent
        import assistant_contact_clarify as clarify
        for text in ('Макс не работает', 'телеги нет и ватсапа нет, нигде нет',
                     'мне макс не нравится, давай тут'):
            m = [{'text': text, 'sender': 'peer'}]
            self.assertFalse(intent.max_selected(m), text)
            self.assertFalse(clarify.chosen(m), text)

    def test_policy_keeps_the_chain_open(self):
        import tempfile
        from pathlib import Path
        from assistant_store import Store
        from assistant_inbox import InboxChain
        import assistant_contact_policy as policy
        tmp = tempfile.mkdtemp()
        store = Store(Path(tmp) / 'a.sqlite3', Path(tmp) / 'old')
        policy.enable(store)
        chain = InboxChain(store)
        m = [{'text': MSG, 'sender': 'peer'}]
        with store.read_connection() as db:
            self.assertFalse(policy.should_close(db, None, 'wait-contact', m, requested=True))
            self.assertFalse(policy.should_close(db, None, 'pending-clarify', m, requested=True))


class EntryReadPatience(unittest.TestCase):
    def test_not_ready_zero_evidence_is_retryable(self):
        from one_chat_device import verified_entry_retry, ReadStopped
        failure = dict(error='not-ready', stage='navigation-stopped',
                       metadata_checkpoint='ready', read_checkpoint='not-checked',
                       wait_reason='not-checked', identity_checkpoint='not-checked',
                       message_kind='not-read', message_direction='not-read',
                       message_slot=-1, scalar_checkpoint='not-read',
                       scalar_state='not-read', frames=0, managed_calls=0)
        self.assertTrue(verified_entry_retry(ReadStopped('not-ready', failure)))

    def test_observer_stopped_is_retryable(self):
        from one_chat_device import verified_entry_retry, ReadStopped
        failure = dict(error='observer-stopped', read_checkpoint='last-message',
                       identity_checkpoint='recheck', frames=2, managed_calls=158)
        self.assertTrue(verified_entry_retry(ReadStopped('observer-stopped', failure)))

    def test_identity_failures_stay_fatal(self):
        from one_chat_device import verified_entry_retry, ReadStopped
        for code in ('identity-changed', 'identity-not-bound', 'signature-mismatch'):
            self.assertFalse(verified_entry_retry(ReadStopped(code)))

    def test_in_chat_read_with_evidence_is_not_an_entry_shape(self):
        from one_chat_device import verified_entry_retry, ReadStopped
        failure = dict(error='not-ready', read_checkpoint='sample',
                       wait_reason='none', identity_checkpoint='recheck',
                       scalar_state='positive', frames=4, managed_calls=90)
        self.assertFalse(verified_entry_retry(ReadStopped('not-ready', failure)))


class ImmediateBackAndListCheck(Base):
    def test_send_leaves_without_the_third_history_read(self):
        from conversation_engine import QUESTIONS
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)],
                        quick_send_exit=True)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['outcomes'], {'chain-waiting:outgoing-not-observed': 1})
        self.assertEqual(self.reader.call_count, 2)
        self.assertEqual([c.args[0] for c in self.nav.call_args_list], ['open', 'back', 'return'])

    def test_merged_row_target_rides_the_next_scan(self):
        # The queue: a submission without observation marks the chat for the
        # row glance; with no live group left in a single-chat pass the
        # confirmation stays with the ladder (checks == 0), and with a live
        # group the retry target rides its next open (pinned by the repinned
        # multi-chat cases in test_inbox_profiles / test_mumu1396).
        from conversation_engine import QUESTIONS
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)],
                        quick_send_exit=True)
        self.assertEqual(out['post_send_checks'], 0)
        self.assertEqual(out['post_send_reopened'], 0)

    def test_legacy_default_keeps_the_v1_3_103_semantics(self):
        from conversation_engine import QUESTIONS
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['outcomes'], {'chain-waiting:wait-mood': 1})
        self.assertEqual(self.reader.call_count, 3)
