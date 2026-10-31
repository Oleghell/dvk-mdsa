"""Reports LAZ5VEvy (v1.3.96, dropmefiles): three contracts in one release.

1. «пофикси эти ошибки» - port 5563 died at startup-failed on
   journal-initialization / CloudDatabaseError cloud-database-unavailable
   (connect) and stayed dead until a manual restart: the refusal outlasted
   the whole worker ladder AND both controller requeues, and the manual
   «Перезапустить порт» path had NO requeue at all. The requeue loop is now
   the shared run_with_startup_requeue wrapper (run_many + the GUI restart),
   with a wider budget (worker rungs to 120 s, three controller requeues).

2. «ты открываешь только входящие диалоги с новыми сообщениями, а не
   непрочитанными» (v1.3.96) -> v1.3.103 «нужно чтобы открывало новый
   входящий не прочитанный»: the native row admission is the genuinely NEW
   INCOMING last message WITH an unread badge; a badge-less row is a read
   row and stays closed, and the only badge-less open is the host-marked
   retry recheck of owed work (deferral ladder due, or a pending receipt).

3. «после быстрой проверки отправки сообщения сразу выходишь из чата» - the
   inbox walk performs exactly ONE verification read after a send and leaves
   the chat; her fast reply (in the check read or after the exit) keeps its
   unanswered state and the NEXT pass re-opens the row.

Synthetic only; no device, database or worker process is touched."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import dialog_browser
import dialog_models
import mumu_controller
import assistant_inbox as inbox
from assistant_store import Store
from assistant_settings import Settings
from mumu_common import atomic, device_directory
from mumu_pause import PortControl
from test_inbox_profiles import Base, WHO, msg, snap, nav
from test_mumu1377_vycruyxne_fixes import report_5577, write_report
from conversation_engine import QUESTIONS


class QuickExitAfterSend(Base):
    """«быстрая проверка отправки → сразу выхожу из чата» at the walk level."""

    def test_exactly_one_verification_read_after_the_send(self):
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['submission_calls'], 1)
        self.assertTrue(out['last_chat_diagnostics']['post_send_checked'])
        # Entry read + pre-send freshness read + the ONE post-send check.
        self.assertEqual(self.reader.call_count, 3)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        self.assertEqual(out['outcomes'], {'chain-waiting:wait-mood': 1})

    def test_fast_peer_reply_in_the_check_read_is_left_for_the_next_pass(self):
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        # She read our question and answered IMMEDIATELY - her reply is already
        # inside the one post-send check read. The visit still leaves after
        # that single check: her message keeps its pending answer receipt and
        # the draft the proposal reserved is resumed by the next pass.
        fast = msg(1004, 'Согласна!')
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question, fast)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['submission_calls'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        self.assertEqual(self.reader.call_count, 3)
        self.assertEqual(out['outcomes'], {'chain-waiting:incoming-answer-pending': 1})
        # The pending-answer cooldown defers the chat; the pass itself goes on.
        self.assertEqual(out['history_deferred'], 1)
        with self.store.read_connection() as db:
            receipts = db.execute("SELECT message,status FROM chain_reply_receipts").fetchall()
        self.assertIn(('1004', 'pending'), receipts)
        # The closed loop: her pending receipt is excluded from the uploaded
        # consumed ids, so the row's next-pass admission (last message is her
        # NEW incoming) still re-opens the chat and the reserved draft is
        # resumed there - the reply is never missed, only left for later.
        uploaded = inbox.with_seen_ids(self.chain(), [dict(WHO)])
        self.assertNotIn('1004', uploaded[0]['seen_ids'])

    def test_unobserved_outgoing_leaves_the_pass_running(self):
        self.journal()
        hello = msg(1002, 'Привет')
        # The send returned but the outgoing never rendered into the check
        # read: the walk leaves after the ONE check (no three polls) and the
        # PASS keeps going - the chat defers with her pending answer receipt
        # instead of stopping the whole port.
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['submission_calls'], 1)
        self.assertEqual(self.reader.call_count, 3)
        self.assertEqual(out['outcomes'], {'chain-waiting:incoming-answer-pending': 1})
        self.assertEqual(out['history_deferred'], 1)

    def test_monitor_mode_keeps_its_full_observation_flow(self):
        # until_waiting=False (the one-chat monitor) is untouched: an
        # unobserved outgoing still burns its three polls there.
        import assistant_guided_chain as guided
        self.journal()
        before = snap(msg(1002, 'Привет'))
        chain = self.chain()
        approve = MagicMock(return_value=True)
        sent = []
        def sender(snapshot, text):
            sent.append(text)
            return dict(attempted=True, handler_returned=True)
        reads = MagicMock(side_effect=[before for _ in range(20)])
        out = guided.walk(chain, WHO, self.stop, approve, reads, sender,
                          approved=True, greetings=('Привет 🙂',), pause=lambda _: False,
                          until_waiting=False, max_polls=8)
        self.assertEqual(out['reason'], 'outgoing-not-observed')
        self.assertEqual(len(sent), 1)
        self.assertGreaterEqual(reads.call_count, 4)


class NewMessageAdmission(unittest.TestCase):
    """«нужно чтобы открывало новый входящий не прочитанный» (v1.3.103): the
    unread badge IS an admission signal for the reply filter, on both engines;
    the only badge-less open is the host-marked retry recheck."""

    TARGET = dict(account='1', peer='2', chat='3')

    def test_browser_admission_is_the_new_incoming_message_only(self):
        s = dialog_browser.build('open', allowed=[dict(self.TARGET, seen_ids=['9'])],
                                 needs_reply_only=True)
        # The waiting skip no longer consults the badge at all.
        self.assertIn("if(!header.incoming){n.waiting_rows_skipped++;return false;}", s)
        # v1.3.103: the badge gate - one rule for both filters, with the retry
        # recheck as the ONLY badge-less exception.
        self.assertIn("if(unread===0&&!retryRow(model.who)){n.read_rows_skipped++;return false;}", s)
        self.assertIn("if(unread===0)n.retry_rows_opened++;", s)
        self.assertNotIn("unreadOnly&&!needsReplyOnly", s)
        # Order: badge gate BEFORE the header read - a badge-less row never
        # even reaches the incoming/handled checks.
        self.assertLess(s.index('if(unread===0&&!retryRow'),
                        s.index("if(!header.incoming)"))
        self.assertLess(s.index("if(!header.incoming)"),
                        s.index('call(s.openCell,current,args)'))
        # The retry helper is the badge-less exception's only source.
        self.assertIn("x.retry===true);", s)

    def test_models_admission_is_the_same_rule(self):
        s = dialog_models.build(allowed=[dict(self.TARGET, seen_ids=['9'])],
                                needs_reply_only=True, recent_limit=50, reverse=True, start=0)
        self.assertIn("if(!header.incoming){n.waiting_rows_skipped++;return false;}", s)
        self.assertIn("if(unread===0&&!retryRow(model.who)){n.read_rows_skipped++;return false;}", s)
        self.assertIn("if(needsReplyOnly&&unread===0)n.retry_rows_opened++;", s)
        self.assertNotIn("unreadOnly&&!needsReplyOnly", s)

    def test_badged_row_with_our_last_message_is_valid_waiting_evidence(self):
        # The 846 shape: unread evidence present, the row skipped as waiting
        # (our message last) - the validator must accept exactly this.
        from test_dialog_browser import raw_open, TARGET
        value = raw_open()
        value['navigation'].update(reply_filter_applied=True, reply_needed_verified=True,
                                   waiting_rows_skipped=1, read_rows_skipped=0)
        result = dialog_browser.validate(value, 'open', allowed=[TARGET], needs_reply_only=True)
        self.assertEqual(result['state'], 'opened')

    def test_badge_less_row_is_a_read_skip_under_the_reply_filter(self):
        # v1.3.103: a badge-less row is skipped by the gate BEFORE the header
        # checks - read_rows_skipped is legitimate reply-filter evidence now.
        from test_dialog_browser import raw_open, TARGET
        value = raw_open()
        value['navigation'].update(reply_filter_applied=True, reply_needed_verified=True,
                                   waiting_rows_skipped=0, read_rows_skipped=2)
        result = dialog_browser.validate(value, 'open', allowed=[TARGET], needs_reply_only=True)
        self.assertEqual(result['state'], 'opened')
        self.assertEqual(result['diagnostic']['read_rows_skipped'], 2)

    def test_badge_less_row_without_any_filter_is_still_rejected(self):
        # A plain open (no unread and no reply filter) never reports read skips.
        from test_dialog_browser import raw_open, TARGET
        value = raw_open()
        value['navigation'].update(read_rows_skipped=1)
        with self.assertRaises(ValueError):
            dialog_browser.validate(value, 'open', allowed=[TARGET])

    def test_retry_open_needs_the_host_marked_retry_target(self):
        # A badge-less open is legitimate ONLY through a retry target the host
        # uploaded; the native may never invent one.
        from test_dialog_browser import raw_open, TARGET
        value = raw_open()
        value['navigation'].update(reply_filter_applied=True, reply_needed_verified=True,
                                   retry_rows_opened=1)
        with self.assertRaises(ValueError):
            dialog_browser.validate(value, 'open', allowed=[TARGET], needs_reply_only=True)
        result = dialog_browser.validate(value, 'open', allowed=[dict(TARGET, retry=True)],
                                         needs_reply_only=True)
        self.assertEqual(result['state'], 'opened')
        self.assertEqual(result['diagnostic']['retry_rows_opened'], 1)
        # And never without the reply filter itself (the read-check tool never
        # reports retry evidence).
        with self.assertRaises(ValueError):
            dialog_browser.validate(value, 'open', allowed=[dict(TARGET, retry=True)],
                                    unread_only=True)

    def test_combined_flags_report_the_unread_evidence_without_gating(self):
        # unread_only + needs_reply_only (the inbox 'unread' group): both
        # filters agree - the badge gates, the reply checks stay.
        source = dialog_browser.build('open', allowed=[self.TARGET],
                                      unread_only=True, needs_reply_only=True)
        self.assertIn("if(unread===0&&!retryRow(model.who)){n.read_rows_skipped++;return false;}", source)

    def test_read_check_tool_keeps_its_own_badge_admission(self):
        # unread_only ALONE (the 0.4.6 user-confirmed read-check tool) still
        # opens by the badge and skips read rows - now through the very same
        # shared gate string.
        source = dialog_browser.build('open', allowed=[self.TARGET], unread_only=True)
        self.assertIn("if(unread===0&&!retryRow(model.who)){n.read_rows_skipped++;return false;}", source)


class StartupRequeueWrapper(unittest.TestCase):
    """The LAZ5VEvy port-5563 shape: the shared requeue wrapper covers the
    manual single-port restart and keeps the bounded, Stop-aware contract."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        env = patch.dict(os.environ, LOCALAPPDATA=folder.name)
        env.start()
        self.addCleanup(folder.cleanup)
        self.addCleanup(env.stop)
        delays = patch.object(mumu_controller, 'STARTUP_REQUEUE_DELAYS', (0.0, 0.0, 0.0))
        delays.start()
        self.addCleanup(delays.stop)
        self.stopped = threading.Event()

    def run_wrapper(self, worker, control=None, on_requeue=None):
        messages = []
        value = mumu_controller.run_with_startup_requeue(
            5563, Settings(), 'inbox', False, self.stopped,
            lambda n, text: messages.append((n, text)),
            worker=worker, control=control, on_requeue=on_requeue,
            jitter=lambda: 1.0)
        return value, messages

    def test_transient_connect_death_is_retried_until_success(self):
        state = {'failed': 0}

        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            if state['failed'] < 2:
                state['failed'] += 1
                write_report(n, report_5577(port=n))
                return 'Этап: journal-initialization. Тип: CloudDatabaseError. См. last-startup.json.'
            return 'ok'
        value, messages = self.run_wrapper(worker)
        self.assertEqual(value, 'ok')
        self.assertEqual(state['failed'], 2)
        self.assertTrue(any('Автоповтор запуска (попытка 2 из 4)' in text
                            and 'общая база была занята' in text for _, text in messages), messages)

    def test_budget_is_bounded_and_the_real_failure_survives(self):
        calls = []

        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            calls.append(n)
            write_report(n, report_5577(port=n))
            return 'Этап: journal-initialization. Тип: CloudDatabaseError. См. last-startup.json.'
        value, messages = self.run_wrapper(worker)
        self.assertEqual(calls, [5563] * (mumu_controller.STARTUP_REQUEUE_LIMIT + 1))
        self.assertTrue(value.startswith('Этап: journal-initialization'))

    def test_non_requeueable_death_keeps_one_attempt(self):
        calls = []

        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            calls.append(n)
            write_report(n, report_5577(port=n, code='cloud-database-permission'))
            return 'ошибка прав'
        value, messages = self.run_wrapper(worker)
        self.assertEqual(calls, [5563])
        self.assertEqual(value, 'ошибка прав')
        self.assertFalse(any('Автоповтор' in text for _, text in messages), messages)

    def test_stop_during_the_cooldown_keeps_the_failure_text(self):
        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            write_report(n, report_5577(port=n))
            self.stopped.set()
            return 'Этап: journal-initialization. Тип: CloudDatabaseError. См. last-startup.json.'
        value, messages = self.run_wrapper(worker)
        self.assertTrue(value.startswith('Этап: journal-initialization'))
        self.assertFalse(any('Автоповтор' in text for _, text in messages), messages)

    def test_each_requeued_attempt_gets_the_fresh_control(self):
        controls = []

        def worker(n, settings, mode, fresh, stopped, progress, *, control=None):
            controls.append(control)
            write_report(n, report_5577(port=n))
            return 'ошибка'
        first = PortControl()
        holder = {'control': first}

        def on_requeue():
            holder['control'] = PortControl()
            return holder['control']
        self.run_wrapper(worker, control=first, on_requeue=on_requeue)
        self.assertIs(controls[0], first)
        self.assertIsNot(controls[1], first)
        self.assertIsNot(controls[2], first)
        self.assertIsNot(controls[3], first)
        self.assertIs(holder['control'], controls[3])

    def test_manual_restart_button_rides_the_same_wrapper(self):
        source = (Path(__file__).resolve().parents[1] / 'assistant_app.py').read_text(encoding='utf-8')
        self.assertIn("run_with_startup_requeue(n, current_run['settings'], current_run['mode'], False, stopped", source)
        self.assertIn("control=port_controls[n], on_requeue=fresh_control", source)

    def test_run_many_delegates_to_the_shared_wrapper(self):
        source = (Path(mumu_controller.__file__)).read_text(encoding='utf-8')
        self.assertIn('value = run_with_startup_requeue(', source)


class StartupLadderBudgets(unittest.TestCase):
    """The widened worker ladder and controller budget for LAZ5VEvy."""

    def test_worker_ladder_rides_out_a_multi_minute_refusal(self):
        import mumu_worker
        self.assertEqual(mumu_worker.JOURNAL_START_RETRY_DELAYS,
                         (3.0, 7.0, 15.0, 30.0, 60.0, 120.0))

    def test_controller_budget_is_three_requeues_over_wider_delays(self):
        self.assertEqual(mumu_controller.STARTUP_REQUEUE_LIMIT, 3)
        self.assertEqual(mumu_controller.STARTUP_REQUEUE_DELAYS, (20.0, 45.0, 90.0))


if __name__ == '__main__':
    unittest.main()
