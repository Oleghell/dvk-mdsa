"""Reports aPYyN7weMm (v1.3.78) - three user-visible defect classes:

1. Missed WhatsApp contacts. «89116863602 вотсап», «8999614 7273 Ватсапп или
   Макс» and «Давай вотапп 89523991160» were all reported as
   «Цепочка закрыта без нового ответа: отказ, ограничение контактного
   сценария или лимит уточнений»: the phone number was detected, but the
   ownership remainder kept an unrecognized WhatsApp spelling (вотсап,
   вотапп), the «или» conjunction joining two messenger names or the «давай»
   consent filler, so the peer's own number looked unattributed and the chain
   closed instead of saving the contact.

2. Worker deaths on latency-only read interruptions (monitors 516/517).
   516: frame-budget expired before the read checkpoint itself began
   (read_checkpoint not-checked) - classified as bound-chat-read-failed, the
   whole pass and worker stopped. 517: the wall-clock history read budget
   expired BETWEEN clean reads (no last_read_failure at all; AI proposal and
   submit had consumed the cycle) - the deferral gate demanded a verified
   failure shape that cannot exist in that state and stopped the worker at
   its very first inbox pass.

3. «Заходит в чат и выходит без приветствия». The claimed-peer pre-check was
   a live pooled registry read per profile; under multi-port pooler
   saturation its transient window exhausted into a verified no-send skip
   exactly when the chat was already open (tests in test_mumu1369/1374/1376).

Plus the latency work itself: an adaptive per-chat history read budget
(12-48s) instead of a fixed 12s, and bounded idle-poll jitter so a worker
fleet stops resynchronizing against the shared pooler (schedule tests live
in test_runtime_latency). Synthetic only; no device, database or network.
"""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import assistant_guided_chain as guided
import assistant_history_wait as wait
import assistant_inbox as inbox
import shared_contact
from assistant_chain import step
from assistant_contact_clarify import chosen
from assistant_guided_chain import GuidedChain
from assistant_store import Store
from cloud_database import TRANSIENT_CODES  # noqa: F401  (import order parity with sibling suites)
from conversation_engine import CONTACT_TEXT, QUESTIONS
from one_chat_device import ReadStopped, safe_read_failure
from test_assistant_chain import GREETING, msg, snap
from test_inbox_profiles import OTHER, WHO, Base, nav
from test_1210_context_loading import Clock  # noqa: F401  (timing harness parity)
import test_guided_chain as guide


def freeze_516(**changes):
    """Exact monitor-516 evidence: the emptiest possible read interruption."""
    value = dict(stage='navigation-stopped', metadata_checkpoint='ready', read_checkpoint='not-checked',
                 identity_checkpoint='not-checked', scalar_checkpoint='not-read', scalar_state='not-read',
                 wait_reason='not-checked', frames=1, managed_calls=28, message_kind='not-read',
                 message_direction='not-read', message_slot=-1)
    value.update(changes)
    return ReadStopped('frame-budget', value)


class WhatsAppFamily(unittest.TestCase):
    MISSED = [
        ('89116863602 вотсап', ['+79116863602']),
        ('8999614 7273 Ватсапп или Макс', ['+79996147273']),
        ('Давай вотапп 89523991160', ['+79523991160']),
    ]

    def test_the_three_reported_messages_now_save_the_phone(self):
        for text, want in self.MISSED:
            with self.subTest(text=text):
                self.assertEqual(shared_contact.self_shared(text, requested=True), want)

    def test_spelling_family_positions_and_endings(self):
        for text, want in (('вотсап 89116863602', ['+79116863602']),
                           ('мой вотсап 89523991160', ['+79523991160']),
                           ('вассап 89116863602', ['+79116863602']),
                           ('воцап: 89116863602', ['+79116863602']),
                           ('давай 89116863602', ['+79116863602']),
                           ('Ватсапп или Макс, вот 89996147273', ['+79996147273'])):
            with self.subTest(text=text):
                self.assertEqual(shared_contact.self_shared(text, requested=True), want)

    def test_negatives_questions_and_third_party_stay_rejected(self):
        for text in ('нет у меня ватсапа, есть макс: 89646974728',
                     'у меня нет ватсапа', 'вотапп не работает',
                     'номер заказа 791234567890', 'номер моей подруги 791234567890',
                     '791234567890?', '"791234567890"', 'не пересылай 791234567890',
                     'код 791234567890', 'Давай встретимся, а номер потом'):
            with self.subTest(text=text):
                self.assertEqual(shared_contact.self_shared(text, requested=True), [], text)

    def test_non_requested_stage_stays_conservative(self):
        for text, _ in self.MISSED:
            with self.subTest(text=text):
                self.assertEqual(shared_contact.self_shared(text, requested=False), [])

    def test_terse_lists_with_new_spellings_still_choose_via_clarification(self):
        for text in ('Макс вотсап', 'вотапп или макс', 'вотсап или макс', 'Макс ватцап'):
            with self.subTest(text=text):
                self.assertTrue(chosen([dict(text=text)]), text)


class MissedContactsEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from assistant_contact_policy import enable
        self.path = Path(self.temp.name) / 'assistant.sqlite3'
        self.store = Store(self.path, Path(self.temp.name) / 'old')
        action = self.store.reserve(dict(attempt=1, account='100', peer='200', chat='-1', variant=0),
                                     GREETING, approved=True)
        self.store.finish(action, dict(send_attempted=True, send_handler_returned=True))
        seal = lambda data: bytes(b ^ 77 for b in data)
        self.chain = GuidedChain(self.store, choose=lambda: 0, seal=seal, unseal=seal)
        self.chain.bind(snap(), (GREETING,), approved=True)
        enable(self.store)
        self.sent = []

    def send(self, before, text):
        self.sent.append(text)
        return dict(attempted=True, handler_returned=True)

    def reach_wait_contact(self):
        reply = msg(1002, 'Привет!')
        step(self.chain, snap(reply), self.send)
        question = msg(1003, QUESTIONS[0], True)
        step(self.chain, snap(reply, question), self.send)
        mood = msg(1004, 'Отлично!')
        step(self.chain, snap(reply, question, mood), self.send)
        contact = msg(1005, CONTACT_TEXT, True)
        self.assertEqual(step(self.chain, snap(reply, question, mood, contact), self.send),
                         'wait-contact')
        return [reply, question, mood, contact]

    def prepare(self):
        self.history = self.reach_wait_contact()
        return len(self.sent)

    def deliver(self, text):
        self.history.append(msg(1006, text))
        snapshot = snap(*self.history)
        snapshot['peer_name'] = 'ИмяДляТеста'
        return step(self.chain, snapshot, self.send)

    def feed(self, text):
        self.prepare()
        return self.deliver(text)

    def saved_payload(self):
        with self.store.connection() as db:
            row = db.execute("SELECT payload FROM chain_contact_outbox WHERE chat='300'").fetchone()
        return bytes(b ^ 77 for b in row[0]).decode('utf-8', 'replace') if row else None

    def test_reported_messages_close_the_chain_as_saved_contacts(self):
        for text, number in (('89116863602 вотсап', '+79116863602'),
                             ('8999614 7273 Ватсапп или Макс', '+79996147273'),
                             ('Давай вотапп 89523991160', '+79523991160')):
            with self.subTest(text=text):
                case = MissedContactsEndToEnd('test_reported_messages_close_the_chain_as_saved_contacts')
                case.setUp()
                case.addCleanup(case.temp.cleanup)
                seeded = case.prepare()
                self.assertEqual(case.deliver(text), 'done')
                self.assertIn(number, case.saved_payload())
                self.assertEqual(len(case.sent), seeded)  # saved contact, no outgoing reply

    def test_a_negated_presence_still_never_saves_or_sends(self):
        seeded = self.prepare()
        outcome = self.deliver('нет у меня ватсапа, есть макс: 89646974728')
        self.assertNotEqual(outcome, 'done')
        self.assertIsNone(self.saved_payload())
        # MAX was chosen, so exactly one MAX clarification goes out - never a
        # saved contact and never an AI reply to the unattributed number.
        from assistant_contact_clarify import MAX_TEXT
        self.assertEqual(outcome, 'await-outgoing')
        self.assertEqual(self.sent[seeded:], [MAX_TEXT])


class PreCheckpointFreeze(unittest.TestCase):
    def test_monitor_516_shape_is_a_verified_budget_interruption(self):
        self.assertTrue(wait.verified_read_budget(safe_read_failure(freeze_516())))

    def test_walk_retries_the_freeze_then_defers_without_dying(self):
        store = Store(Path(tempfile.mkdtemp()) / 'assistant.sqlite3')
        chain = GuidedChain(store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)
        stop = threading.Event()
        reader = MagicMock(side_effect=lambda who: (_ for _ in ()).throw(freeze_516()))
        sent = []
        out = guided.walk(chain, WHO, stop, lambda *a: True, reader,
                          lambda before, text: sent.append(text) or dict(attempted=True, handler_returned=True),
                          approved=True, pause=lambda _: False)
        self.assertEqual(reader.call_count, wait.BUDGET_READ_ATTEMPTS)
        self.assertEqual(out['reason'], 'history-read-budget-timeout')
        self.assertEqual(out['status'], 'chain-waiting')
        self.assertFalse(sent)

    def test_identity_error_still_escalates_immediately(self):
        store = Store(Path(tempfile.mkdtemp()) / 'assistant.sqlite3')
        chain = GuidedChain(store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)
        stop = threading.Event()
        reader = MagicMock(side_effect=[freeze_516(), ReadStopped('identity-changed')])
        out = guided.walk(chain, WHO, stop, lambda *a: True, reader,
                          lambda before, text: dict(attempted=True, handler_returned=True),
                          approved=True, pause=lambda _: False)
        self.assertEqual(out['reason'], 'bound-chat-read-failed')
        self.assertEqual(reader.call_count, 2)


class DeadlineBetweenReads(Base):
    """Monitor 517: the budget expired between clean reads - no failure shape."""

    def deferred(self, **diagnostic):
        out = guided.report()
        out.update(status='chain-waiting', reason='history-read-budget-timeout')
        out['diagnostics'].update(history_budget_exhausted=True)
        out['diagnostics'].update(diagnostic)
        return out

    def test_missing_failure_evidence_defers_instead_of_stopping_the_worker(self):
        self.journal()
        self.journal(OTHER)
        chain = self.chain()
        normal = guided.report()
        normal.update(status='chain-waiting', reason='wait-reply')
        with patch.object(inbox, 'walk_chat', side_effect=[self.deferred(), normal]):
            out = self.walk([nav('opened', WHO), nav('returned', WHO),
                             nav('opened', OTHER), nav('returned', OTHER), nav('search-ready')],
                            [], chain=chain, clock=lambda: 100.)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['history_deferred'], 1)
        self.assertEqual(out['dialogs_processed'], 2)
        # The peer-local cooldown is recorded exactly like a verified deferral.
        attention, unread, skipped = wait.eligible(self.store, [WHO, OTHER], [], clock=lambda: 100.)
        self.assertEqual(skipped, 1)

    def test_present_but_unverified_failure_shape_still_stops(self):
        self.journal()
        chain = self.chain()
        bad = self.deferred(last_read_failure=dict(error='identity-changed'))
        with patch.object(inbox, 'walk_chat', return_value=bad):
            out = self.walk([nav('opened', WHO)], [], chain=chain)
        self.assertEqual(out['status'], 'inbox-stopped')
        self.assertEqual(out['reason'], 'chat-bound-chat-read-failed')

    def test_budget_not_exhausted_still_stops(self):
        self.journal()
        chain = self.chain()
        bad = self.deferred()
        bad['diagnostics']['history_budget_exhausted'] = False
        with patch.object(inbox, 'walk_chat', return_value=bad):
            out = self.walk([nav('opened', WHO)], [], chain=chain)
        self.assertEqual(out['status'], 'inbox-stopped')


class AdaptiveReadBudget(unittest.TestCase):
    def test_constants_pin_the_adaptation_window(self):
        self.assertEqual(inbox.HISTORY_READ_BUDGET_INITIAL, 20.0)
        self.assertEqual(inbox.HISTORY_READ_BUDGET_MAX, 48.0)
        source = (Path(__file__).resolve().parents[1] / 'assistant_inbox.py').read_text(encoding='utf-8')
        self.assertIn('chain.history_read_budget=HISTORY_READ_BUDGET_INITIAL', source)

    def test_budget_rises_immediately_for_slow_reads(self):
        # Monitor 517 measured ~10.8s per read call under 12-port load; the
        # ladder needs room for ~3 attempts of that.
        self.assertEqual(inbox.adapted_read_budget(20.0, dict(read_calls=4, read_ms=43.0)), 32.25)
        self.assertEqual(inbox.adapted_read_budget(20.0, dict(read_calls=2, read_ms=30.0)), 45.0)
        self.assertEqual(inbox.adapted_read_budget(20.0, dict(read_calls=1, read_ms=20.0)), 48.0)

    def test_budget_never_drops_below_the_floor_and_relaxes_slowly(self):
        self.assertEqual(inbox.adapted_read_budget(48.0, dict(read_calls=2, read_ms=2.0)), 43.2)
        self.assertEqual(inbox.adapted_read_budget(43.2, dict(read_calls=2, read_ms=2.0)), 38.88)
        self.assertEqual(inbox.adapted_read_budget(20.0, dict(read_calls=2, read_ms=2.0)), 20.0)

    def test_missing_or_invalid_timings_keep_the_current_budget(self):
        for diagnostics in (dict(), dict(read_calls=0, read_ms=0.0),
                            dict(read_calls='2', read_ms=4.0), dict(read_calls=2, read_ms=-4.0)):
            with self.subTest(diagnostics=diagnostics):
                self.assertEqual(inbox.adapted_read_budget(33.0, diagnostics), 33.0)

    def test_inbox_walk_adapts_the_live_budget_from_chat_timings(self):
        case = Base()
        case.setUp()
        case.addCleanup(case.tmp.cleanup)
        case.journal()
        case.journal(OTHER)
        chain = case.chain()
        chain.history_read_budget = inbox.HISTORY_READ_BUDGET_INITIAL
        slow = guided.report(); slow.update(status='chain-waiting', reason='wait-reply',
                                            diagnostics=dict(guided.report()['diagnostics'],
                                                            read_calls=2, read_ms=30.0))
        fast = guided.report(); fast.update(status='chain-waiting', reason='wait-reply')
        fast['diagnostics'].update(read_calls=2, read_ms=2.0)
        with patch.object(inbox, 'walk_chat', side_effect=[slow, fast]):
            out = case.walk([nav('opened', WHO), nav('returned', WHO),
                             nav('opened', OTHER), nav('returned', OTHER), nav('search-ready')],
                            [], chain=chain)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['history_read_budget'], 40.5)  # 45.0 then relaxed to 45.0*0.9
        self.assertEqual(chain.history_read_budget, 40.5)


if __name__ == '__main__':
    unittest.main()
