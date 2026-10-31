"""v1.3.106: «если новая анкета подходит по параметрам то при открытии диалога
пусть сразу без проверки отправляет сообщение», «с первым приветствием тоже
что-то срочно делай ибо все равно в холостую там сидит», «отчеты в телеграм
бота перестает присылать будто где-то копиться в буфере» and the dropmefiles
eEP7SW stop (host_failure 'validation-failed' at host_checkpoint 'inbox-open'
while last_navigation kept the PREVIOUS verified Back).

Three doctrines, pinned here:

1. THE LIGHT SUBMIT FRAME: the ACKed submit-greeting tick carries only the
   controller pin, the three saved pins, the integer helper and the field
   box - the third full CONTEXT re-verification is gone because the SEND
   block re-verifies identity and screen LIVE at the send instant. The frame
   budget that used to blow exactly at the send call (the mechanical root of
   «в холостую сидит» and «14 анкет / 0 сообщений») now has ~45% fewer managed
   calls to fit.
2. THE UNKILLABLE TELEGRAM QUEUE: the delivery thread survives every job
   (BaseException included), a dead thread is restarted by the next enqueue
   under a restart lock, and the queue depth plus delivered/failed/restart
   counters ride backlog() into the pass report and the monitor summary.
3. THE PINPOINTED PRE-OPEN FAILURE: the open's kwargs preparation runs under
   its own 'inbox-prepare' checkpoint with the authored validation code
   recorded as validation_reason, and the prepared target list is defensively
   deduplicated so one duplicated (account, peer) can never again stop the
   whole pass as ValueError('Ambiguous target') with a stale Back diagnostic.
"""
import threading
import time
import unittest

import assistant_pass
import assistant_profile_read
import assistant_notification_queue as queue_module
import assistant_inbox
import assistant_monitor as monitor_module
from pathlib import Path


def source_of(module):
    return Path(module.__file__).read_text(encoding='utf-8')


class LightSubmitFrame(unittest.TestCase):
    def test_submit_context_is_light_and_complete(self):
        """The submit frame defines exactly what SEND consumes - nothing more."""
        context = assistant_profile_read.SUBMIT_CONTEXT
        self.assertIn("target(state.chatController)", context)
        self.assertIn('target(state.chatModelPin)', context)
        self.assertIn('target(state.chatUserPin)', context)
        self.assertIn('target(state.chatCMPin)', context)
        self.assertIn('const integer=', context)
        self.assertIn('s.loadedClass', context)
        # The heavy re-verification arms are NOT in the submit context.
        self.assertNotIn('call(s.opponent,chat)', context)
        self.assertNotIn('target(state.targetUser)', context)
        self.assertNotIn('n.samples!==2', context)
        self.assertNotIn('bool(s.presenting,current)', context)

    def test_composed_source_uses_the_light_context_only_in_submit(self):
        s = assistant_pass.build('Привет')
        c = s.index("if(n.phase==='submit-greeting')")
        submit = s[c:]
        # The duplicated full re-verification never follows the ACK gate.
        self.assertEqual(submit.count('!call(s.opponent,chat).equals(user)'), 0)
        # The pins, the ACK binding and the live SEND gate are all present.
        for guard in ('target(state.chatController)', 's.cohortManager',
                      '!call(s.chatUser,current).equals(user)', '!call(s.messages,chat).equals(cm)',
                      'integer(s.count,cm)!==0', '!call(s.last,chat).isNull()',
                      'batchSent.add(batchCandidateKey);n.send_attempted=true'):
            self.assertIn(guard, submit)

    def test_prepare_greeting_keeps_the_full_gate_with_input_skip(self):
        s = assistant_pass.build('Привет')
        b = s.index("if(n.phase==='prepare-greeting')")
        c = s.index("if(n.phase==='submit-greeting')")
        prepare = s[b:c]
        self.assertIn('!call(s.opponent,chat).equals(user)', prepare)
        self.assertIn('n.profile_input_enabled', prepare)
        self.assertIn("const reason='input-disabled'", prepare)


class UnkillableQueue(unittest.TestCase):
    def run_jobs(self, dispatcher, seconds=0.6):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            dispatcher.drain()
            time.sleep(0.02)

    def test_base_exception_does_not_kill_the_worker(self):
        stopped = threading.Event()
        with queue_module.running(stopped) as dispatcher:
            class Crash:
                class store:
                    path = 'crash'
                def _notify(self, who, notifier, cancelled):
                    raise KeyboardInterrupt('control-flow signal')
            dispatcher.enqueue(Crash(), dict(account='1', peer='2', chat='3'),
                               lambda payload: True, lambda: False)
            self.run_jobs(dispatcher)
            backlog = dispatcher.backlog()
            self.assertFalse(backlog['dead'])
            self.assertGreaterEqual(backlog['failed'], 1)

    def test_dead_worker_is_restarted_and_counted(self):
        stopped = threading.Event()
        with queue_module.running(stopped) as dispatcher:
            # Emulate the silent v1.3.106 defect: a thread that already died.
            finished = threading.Thread(target=lambda: None)
            finished.start(); finished.join()
            dispatcher.thread = finished
            self.assertTrue(dispatcher.backlog()['dead'])
            class Ok:
                class store:
                    path = 'ok'
                def _notify(self, who, notifier, cancelled):
                    return 'accepted'
            status = dispatcher.enqueue(Ok(), dict(account='1', peer='2', chat='3'),
                                        lambda payload: True, lambda: False)
            self.assertEqual(status, 'queued')
            self.run_jobs(dispatcher)
            backlog = dispatcher.backlog()
            self.assertEqual(backlog['restarts'], 1)
            self.assertEqual(backlog['delivered'], 1)
            self.assertFalse(backlog['dead'])

    def test_blocked_and_decided_outcomes_are_not_failures(self):
        stopped = threading.Event()
        with queue_module.running(stopped) as dispatcher:
            class Blocked:
                class store:
                    path = 'blocked'
                def _notify(self, who, notifier, cancelled):
                    return 'blocked'
            dispatcher.enqueue(Blocked(), dict(account='1', peer='2', chat='3'),
                               lambda payload: True, lambda: False)
            self.run_jobs(dispatcher)
            backlog = dispatcher.backlog()
            self.assertEqual(backlog['failed'], 0)
            self.assertEqual(backlog['delivered'], 0)

    def test_depth_is_tracked_while_jobs_wait(self):
        stopped = threading.Event()
        with queue_module.running(stopped) as dispatcher:
            class Slow:
                class store:
                    path = 'slow'
                def _notify(self, who, notifier, cancelled):
                    time.sleep(0.3)
                    return 'accepted'
            dispatcher.enqueue(Slow(), dict(account='1', peer='2', chat='3'),
                               lambda payload: True, lambda: False)
            time.sleep(0.05)
            dispatcher.enqueue(Slow(), dict(account='4', peer='5', chat='6'),
                               lambda payload: True, lambda: False)
            time.sleep(0.05)
            backlog = dispatcher.backlog()
            self.assertGreaterEqual(backlog['deepest'], 1)
            self.run_jobs(dispatcher, seconds=1.0)
            self.assertEqual(dispatcher.backlog()['delivered'], 2)


class PinpointedPreOpenFailure(unittest.TestCase):
    def test_preparation_codes_are_closed_and_cover_the_reported_shape(self):
        codes = assistant_inbox.PREPARATION_VALIDATION_CODES
        self.assertIn('Ambiguous target', codes)
        self.assertIn('Invalid observed IDs', codes)
        self.assertIn('Invalid navigation binding', codes)
        for code in codes:
            self.assertIsInstance(code, str)
            self.assertTrue(code)

    def test_walk_names_the_prepare_checkpoint_before_the_open(self):
        source = source_of(assistant_inbox)
        self.assertIn("host_checkpoint = 'inbox-prepare'", source)
        prepare = source.index("host_checkpoint = 'inbox-prepare'")
        following = source[prepare:]
        # The preparation result feeds the open, and the checkpoint moves on
        # to 'inbox-open' only after both kwargs succeeded.
        self.assertLess(following.index('prepared_allowed = with_seen_ids'),
                        following.index("host_checkpoint = 'inbox-open'"))
        self.assertLess(following.index('prepared_hidden = hidden_peers'),
                        following.index("host_checkpoint = 'inbox-open'"))
        self.assertIn('allowed=prepared_allowed', following)
        self.assertIn('hidden=prepared_hidden', following)

    def test_validation_reason_is_recorded_from_the_closed_set(self):
        source = source_of(assistant_inbox)
        self.assertIn('PREPARATION_VALIDATION_CODES', source)
        self.assertIn("out['validation_reason'] = str(error)", source)

    def test_with_seen_ids_deduplicates_before_final_validation(self):
        source = source_of(assistant_inbox)
        self.assertIn('deduplicated.setdefault((entry[\'account\'],entry[\'peer\']),entry)',
                      source)
        self.assertIn('return targets(list(deduplicated.values()))', source)

    def test_diagnostic_json_projects_the_queue_health(self):
        from assistant_error_notify import diagnostic_json
        import json
        report = dict(status='stopped', reason='inbox-pass-stopped',
                      tg_queue=dict(queued=3, delivered=2, failed=1, depth=3,
                                    deepest=5, restarts=1, dead=True),
                      validation_reason='Ambiguous target')
        cleaned = json.loads(diagnostic_json(report))['diagnostic']
        self.assertEqual(cleaned['tg_queue'], dict(tg_queued=3, tg_delivered=2,
                                                   tg_failed=1, tg_depth=3,
                                                   tg_deepest=5, tg_restarts=1,
                                                   tg_dead=True))
        self.assertEqual(cleaned['validation_reason'], 'Ambiguous target')

    def test_monitor_summary_shows_the_queue_backlog(self):
        result = monitor_module.report('full')
        result.update(status='waiting')
        result['last_pass'] = dict(tg_queue=dict(queued=4, restarts=2, dead=True))
        text = monitor_module.summary(result)
        self.assertIn('в очереди TG 4', text)
        self.assertIn('очередь TG перезапущена 2 раз', text)
        self.assertIn('очередь TG не работает', text)


class GreetingStillBoundToDurableAuthorization(unittest.TestCase):
    def test_submit_frame_keeps_the_ack_binding_and_latch_order(self):
        """The light frame must not weaken the authorization contract."""
        s = assistant_pass.build('Привет')
        c = s.index("if(n.phase==='submit-greeting')")
        submit = s[c:]
        self.assertIn("if(cohortApproved!==reservationKey)fail('identity-changed');", submit)
        # Guards still precede the latch inside SEND.
        latch = submit.index('batchSent.add(batchCandidateKey);n.send_attempted=true')
        for guard in ("if(deadline<Date.now())fail('frame-budget')",
                      "if(state.stop!==null)fail(state.stop)",
                      'if(fixedCancellationRequested)fail(\'cancelled\')'):
            self.assertLess(submit.index(guard), latch)


if __name__ == '__main__':
    unittest.main()
