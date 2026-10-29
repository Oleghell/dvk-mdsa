"""Reports v1.3.82: «Старт» skipped every dialog and wrote new profiles first.

One «Новые анкеты» run wrote 'new-start-excluded' rows for every tracked
dialog of the port into the shared journal, and NOTHING ever removed them:
later «Старт»/«Только ответы» worker starts cleared only the legacy age
reasons, eligible_groups() silently filtered every dialog out of every inbox
pass, the inbox returned empty and the run went straight to writing new
profiles - the user watched «сначала не проходится по диалогам и не
отвечает, а сразу идет писать новым» after ONE new-profiles press. The
exclusion is now scoped to the new-profiles RUN itself: a reply-capable
worker start (full/inbox) ends the stale scope in the same startup
transaction that re-enables the policy, and only a worker that itself starts
new-only re-establishes the exclusions. Synthetic only; no device, database
service or credentials.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import assistant_inbox as inbox
import assistant_reply_window as window
from assistant_store import Store
from mumu_store import SharedStore
from test_inbox_profiles import Base, nav, msg, snap, WHO, QUESTIONS


class Scope(Base):
    """The reported symptom and its exact recovery path."""

    def test_full_start_restores_the_dialog_pass_after_new_profiles_run(self):
        self.journal()
        window.enable(self.store, new_only=True)  # the «Новые анкеты» run
        stale = self.walk([], [])
        self.assertEqual(stale['status'], 'inbox-empty')  # the reported bug
        self.nav.assert_not_called()  # the dialogs were never even opened
        window.enable(self.store)  # the next «Старт» worker start
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(self.sent, [QUESTIONS[0]])  # the reply goes first again

    def test_inbox_targets_are_restored_by_a_full_start(self):
        self.journal()
        window.enable(self.store, new_only=True)
        attention, unread = inbox.inbox_targets(self.chain())
        self.assertEqual(len(attention) + len(unread), 0)
        window.enable(self.store)
        attention, unread = inbox.inbox_targets(self.chain())
        self.assertEqual(len(attention) + len(unread), 1)

    def test_new_profiles_run_keeps_its_exclusions_across_store_reopen(self):
        # Within the new-profiles run the exclusion stays durable: a crash of
        # that run never silently turns the stored scope reply-capable, and
        # the skip reason keeps explaining itself on the notify path.
        self.journal()
        window.enable(self.store, new_only=True)
        reopened = Store(self.store.path, self.store.legacy)
        self.assertEqual(window.reason(reopened, WHO), 'new-start-excluded')
        chain = inbox.InboxChain(reopened, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)
        attention, unread = inbox.inbox_targets(chain)
        self.assertEqual(len(attention) + len(unread), 0)

    def test_new_only_run_reestablishes_its_own_scope(self):
        self.journal()
        window.enable(self.store)  # a full start ended the previous scope
        self.assertIsNone(window.reason(self.store, WHO))
        window.enable(self.store, new_only=True)  # a fresh new-profiles run
        self.assertEqual(window.reason(self.store, WHO), 'new-start-excluded')

    def test_peer_greeted_during_the_new_run_stays_eligible(self):
        # The mode promise is intact: replies stay allowed to NEW interlocutors
        # - the snapshot insert only captures dialogs that existed at enable().
        self.journal()
        window.enable(self.store, new_only=True)
        newcomer = dict(WHO, peer='222', chat='333')
        self.journal(newcomer)  # greeted during the run itself
        self.assertIsNone(window.reason(self.store, newcomer))
        self.assertEqual(window.reason(self.store, WHO), 'new-start-excluded')


class PortScope(unittest.TestCase):
    """The clear is as port-scoped as the insert: neighbours keep their run."""

    def test_full_start_of_one_port_never_ends_another_ports_new_start(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'db'; old = Path(temp) / 'old'
            mine = SharedStore(path, old, device_port=5563)
            other = SharedStore(path, old, device_port=5557)
            for store, peer in ((mine, '200'), (other, '201')):
                store.reserve(dict(account='100', peer=peer, chat='-1', attempt=1, variant=0),
                              'Привет', approved=True)
            window.enable(mine, new_only=True)  # my port runs «Новые анкеты»
            window.enable(other)  # the neighbour runs «Старт» at the same time
            self.assertEqual(window.reason(mine, dict(account='100', peer='200')), 'new-start-excluded')
            self.assertIsNone(window.reason(other, dict(account='100', peer='201')))
            with mine.read_connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM inbox_reply_exclusions').fetchone()[0], 1)
            with other.read_connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM inbox_reply_exclusions').fetchone()[0], 0)
            # The shared claims registry is untouched by the scope bookkeeping.
            with mine.connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM mumu_greeting_claims').fetchone()[0], 2)


class WorkerWiring(unittest.TestCase):
    """open_shared_journal maps the worker mode onto the new scope contract."""

    def startup(self, new_only):
        stopped = MagicMock(); stopped.is_set.return_value = False
        with patch('assistant_store.Store', side_effect=['JOURNAL']), \
             patch('assistant_reply_window.enable') as enable, \
             patch('assistant_contact_policy.enable') as contact:
            import mumu_worker
            journal = mumu_worker.open_shared_journal(new_only, stopped, lambda _: None,
                                                      pause=lambda _: None)
        return journal, enable, contact

    def test_full_and_inbox_starts_call_the_reply_capable_enable(self):
        # spec['mode'] in ('full','inbox') both pass new_only=False into
        # open_shared_journal, so the clear runs on every «Старт» and every
        # «Только ответы» worker start.
        journal, enable, contact = self.startup(False)
        self.assertEqual(journal, 'JOURNAL')
        enable.assert_called_with('JOURNAL', new_only=False)
        contact.assert_called_with('JOURNAL')

    def test_new_mode_start_keeps_the_new_only_enable(self):
        journal, enable, contact = self.startup(True)
        self.assertEqual(journal, 'JOURNAL')
        enable.assert_called_with('JOURNAL', new_only=True)

    def test_worker_source_wires_the_mode_flag(self):
        import mumu_worker
        source = Path(mumu_worker.__file__).read_text(encoding='utf-8')
        self.assertIn("journal=open_shared_journal(spec['mode']=='new',stopped,progress)", source)
