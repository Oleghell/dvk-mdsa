"""Reports 480-483 (v1.3.71, dropmefiles WHm3) plus the user's three standing
complaints; all fixed in one pass.

1. All three monitor reports stopped at startup-result-validation-failed with
   'Inconsistent avatar counts' ON the fixed 1.3.71: the cooperative scan
   counts `cells`/`rows` once per unique observation (scanCellCounted /
   scanRowCounted), but a frame-budget thrown mid-cell is retried through
   scan_yields up to EIGHT times, and every skip/avatar counter re-incremented
   on each re-inspection of the same cell. One noninteractive avatar could
   legally reach cells+8 and still stop the pass. Every per-cell and per-row
   counter now increments only on the first look.

2. «Пропущено: Цепочка закрыта без нового ответа» repeated in Telegram for
   every new peer photo: the exit-notice signature included the unread batch,
   so a CLOSED chain re-notified per batch. Terminal closures ('declined',
   'done') are now reported once per chat and reason.

3. Recovery walked in circles doing nothing: the assistant opens chats ON TOP
   of a profile card, so a verified Back lands on the PROFILE screen, which no
   fixed operation could close - the user had to press Esc once or twice. The
   list/back navigation now performs that bounded Esc press through the same
   verified OnCloseRequested handler, and supervision is bounded
   (MAX_RECOVERY_ROUNDS) instead of spinning forever.

4. A port with an error status can now be resumed manually: the window gains a
   «Перезапустить порт» button that restarts only that port's worker process.

Synthetic only; no device, database or credentials."""
from pathlib import Path
import threading
import unittest
from unittest.mock import MagicMock, call

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chat_batch
import assistant_preview
import dialog_browser as browser
import mumu_recovery
from assistant_exit_notify import notify_exit, REASONS
from assistant_monitor import REPORT
from assistant_settings import Settings
from test_inbox_profiles import Base, WHO
from test_guided_chain import GREETING


class OncePerCellCounters(unittest.TestCase):
    """Fix 1: every per-cell/per-row counter is guarded like `cells` itself."""

    def sources(self):
        yield chat_batch.FUNCTION
        yield assistant_preview.build()

    def test_every_per_cell_counter_is_first_look_guarded(self):
        guarded = ('cell_unready', 'entry_missing', 'promoted', 'user_missing',
                   'self_user', 'avatar_missing', 'avatar_unready')
        for source in self.sources():
            for counter in guarded:
                self.assertIn('if(scanFirst)n.selection_counts.%s++' % counter, source)
            self.assertIn('const scanFirst=!state.scanCellCounted', source)
            self.assertIn('if(scanFirst){n.selection_counts.cells++;', source)

    def test_avatar_counters_inside_attached_are_repeat_look_guarded(self):
        for source in self.sources():
            self.assertIn('if(!needsInteraction&&!state.scanRepeatLook)n.selection_counts.avatar_hidden++', source)
            self.assertIn('if(!state.scanRepeatLook)n.selection_counts.avatar_noninteractive++;', source)
            self.assertIn('state.scanRepeatLook=!scanFirst;', source)
            self.assertIn('scanRepeatLook:false', source)

    def test_row_counters_are_first_look_guarded(self):
        for source in self.sources():
            self.assertIn('const scanRowFirst=!state.scanRowCounted', source)
            self.assertIn('if(scanRowFirst)n.selection_counts.row_unready++', source)
            self.assertIn('if(scanRowFirst)n.selection_counts.binding_missing++', source)

    def test_yields_and_retries_keep_the_validator_arithmetic_exact(self):
        # The retried-observation arithmetic (port 470 report shape) still
        # validates, and the JS guards keep avatar counters at exactly one
        # observation per unique cell, so the WHm3 cells+8 case can no longer
        # be produced at all.
        from uikit_profile_navigation import validate
        from test_profile_navigation import ready_profile
        value = ready_profile()
        n = value['navigation']
        n['selection_counts'].update(cells=1, avatar_noninteractive=3, rows=1, passes=1)
        n['selection_retries'] = 2
        validate(value)
        # Any observation beyond the retry allowance is still rejected: the
        # validator strictness is unchanged, only the counter source is fixed.
        value['navigation']['selection_counts']['avatar_noninteractive'] = 4
        with self.assertRaises(ValueError):
            validate(value)


class TerminalNoticeOnce(Base):
    """Fix 2: a closed chain is reported once, not per unread batch."""

    def declined(self, chain, messages):
        return notify_exit(chain, WHO, dict(reason='declined', _exit_messages=messages),
                           sender=lambda text: True)

    def test_declined_notifies_once_across_new_peer_photos(self):
        self.journal()
        chain = self.chain()
        first = self.declined(chain, ['Ни где'])
        second = self.declined(chain, ['[нет текста]'])
        third = self.declined(chain, [])
        self.assertEqual(first['notification'], 'accepted')
        self.assertEqual(second['notification'], 'already-attempted')
        self.assertEqual(third['notification'], 'already-attempted')

    def test_done_has_its_own_text_and_notifies_once(self):
        self.journal()
        chain = self.chain()
        sent = []
        first = notify_exit(chain, WHO, dict(reason='done', _exit_messages=['привет']),
                            sender=sent.append)
        second = notify_exit(chain, WHO, dict(reason='done', _exit_messages=['фото']),
                             sender=sent.append)
        self.assertEqual(first['reason'], 'done')
        self.assertIn(REASONS['done'], sent[0])
        self.assertEqual(len(sent), 1)
        self.assertEqual(second['notification'], 'already-attempted')

    def test_non_terminal_reasons_still_report_distinct_batches(self):
        self.journal()
        chain = self.chain()
        first = notify_exit(chain, WHO, dict(reason='incoming-answer-pending', _exit_messages=['одно']),
                            sender=lambda text: True)
        second = notify_exit(chain, WHO, dict(reason='incoming-answer-pending', _exit_messages=['другое']),
                             sender=lambda text: True)
        self.assertEqual(first['notification'], 'accepted')
        self.assertEqual(second['notification'], 'accepted')


class BoundedProfileRecovery(unittest.TestCase):
    """Fix 3: the bounded Esc press in navigation plus bounded supervision."""

    def stopped_report(self):
        return dict(status='stopped', reason='inbox-pass-stopped',
                    last_pass=dict(status='inbox-stopped', reason='navigation-check-stopped',
                                   host_failure='internal-error',
                                   last_navigation_failure=dict(stage='forward-open', error='startup-forward-open-failed',
                                                                error_type='TestError', adb_check='test-forward-open',
                                                                adb_reason='device-not-found')))

    def test_profile_close_is_bounded_and_verified_in_the_fixed_navigation(self):
        from one_chat_probe import identity
        expected = identity(dict(account=WHO['account'], peer=WHO['peer'], chat=WHO['chat']))
        for source in (browser.build('list', entry='either'), browser.build('back', expected=expected)):
            self.assertIn("if(k==='profile'&&!n.profile_closed){n.profile_closed=true;n.action_attempted=true;call(s.closeProfile,current);n.action_completed=true;return;}", source)
            self.assertIn("if(k==='search'&&n.profile_closed&&operation!=='return'){n.action_attempted=true;switchTab(s.messageTab);", source)
        # The Esc press is operation-guarded at runtime: the entry branch
        # requires operation==='list', so 'open'/'return' fail closed with
        # wrong-screen on a profile, exactly as before.
        for op in ('open', 'return'):
            source = browser.build(op)
            self.assertIn("if(operation==='list'&&k==='profile')", source)
            self.assertIn("if(k==='profile'&&!n.profile_closed){", source)

    def test_validator_accepts_and_bounds_profile_recovery_evidence(self):
        from test_dialog_browser import raw_open
        value = raw_open()
        n = value['navigation']
        n.update(chat_verified=False, private_identity=None, selection_verified=False,
                 rows_scanned=0, scan_batches=0, selection_checkpoint='not-checked',
                 root_top_kind='dialogs', controller_path=['dialogs'])
        n['profile_closed'] = True
        out = browser.validate(value, 'list')
        self.assertEqual(out['state'], 'dialogs-ready')
        # Without the action ladder the evidence is rejected.
        broken = raw_open()
        broken['navigation'].update(chat_verified=False, private_identity=None,
                                    selection_verified=False, rows_scanned=0, scan_batches=0,
                                    selection_checkpoint='not-checked', root_top_kind='dialogs',
                                    controller_path=['dialogs'], profile_closed=True,
                                    action_attempted=False, action_completed=False)
        with self.assertRaises(ValueError):
            browser.validate(broken, 'list')
        # 'open' never carries profile-close evidence.
        opening = raw_open()
        opening['navigation']['profile_closed'] = True
        with self.assertRaises(ValueError):
            browser.validate(opening, 'open', allowed=[dict(WHO, chat='-1')])

    def test_supervision_is_bounded_instead_of_spinning_forever(self):
        self.assertEqual(mumu_recovery.MAX_RECOVERY_ROUNDS, 8)
        monitor = MagicMock(side_effect=[self.stopped_report()])
        repair = MagicMock(return_value=False)
        waits = []
        out = mumu_recovery.run(Settings(errors_enabled=False), threading.Event(), None,
                                monitor=monitor, repair=repair, wait=lambda seconds: waits.append(seconds) or False,
                                json_alert=MagicMock(), write=lambda value: REPORT)
        self.assertEqual(out['status'], 'stopped')
        self.assertEqual(out['reason'], 'recovery-unfinished')
        self.assertEqual(out['recovery_failure']['recovery_rounds'], 8)
        self.assertEqual(repair.call_count, 8)
        # Bounded exponential backoff per failed round.
        self.assertEqual(waits, [2, 4, 8, 16, 30, 30, 30])

    def test_transport_failure_has_its_own_generous_bound(self):
        self.assertEqual(mumu_recovery.MAX_TRANSPORT_FAILURES, 30)
        monitor = MagicMock(side_effect=[self.stopped_report()])
        repair = MagicMock(side_effect=ConnectionError('no link'))
        waits = []
        out = mumu_recovery.run(Settings(errors_enabled=False), threading.Event(), None,
                                monitor=monitor, repair=repair, wait=lambda seconds: waits.append(seconds) or False,
                                json_alert=MagicMock(), write=lambda value: REPORT)
        # The emulator may be restarting: connection trouble keeps waiting far
        # longer than screen rounds, but never forever.
        self.assertEqual(out['status'], 'stopped')
        self.assertEqual(out['reason'], 'recovery-unfinished')
        self.assertEqual(out['recovery_failure']['host_failure'], 'native-transport-error')
        self.assertEqual(repair.call_count, 30)
        self.assertEqual(len(waits), 29)

    def test_successful_repair_still_resumes_the_pass(self):
        monitor = MagicMock(side_effect=[self.stopped_report(), dict(status='cancelled')])
        repair = MagicMock(return_value=True)
        states = []
        out = mumu_recovery.run(Settings(errors_enabled=False), threading.Event(), None,
                                monitor=monitor, repair=repair, wait=lambda seconds: False,
                                json_alert=MagicMock(), write=lambda value: states.append(value) or REPORT)
        self.assertEqual(out['status'], 'cancelled')
        self.assertEqual(monitor.call_count, 2)
        self.assertEqual(states[0]['status'], 'recovering')
        repair.assert_called_once()


class ManualPortResume(unittest.TestCase):
    """Fix 4: the window restarts one stopped port without touching others."""

    def test_restart_button_is_declared_and_gated_on_a_finished_port(self):
        source = (Path(__file__).resolve().parents[1] / 'assistant_app.py').read_text(encoding='utf-8')
        self.assertIn("text='Перезапустить порт'", source)
        self.assertIn("state=='finished'", source)
        # The restart reuses the captured run settings and mode, never fresh;
        # since v1.3.96 it rides the same bounded startup requeue wrapper as
        # the staggered multi-port start (a transient journal-connect refusal
        # no longer leaves a manually restarted port dead).
        self.assertIn("run_with_startup_requeue(n, current_run['settings'], current_run['mode'], False, stopped", source)
        # Restarted ports keep the run busy until they finish.
        self.assertIn("main_done[0] and not restarts", source)

    def test_controller_runs_one_port_with_the_same_contract(self):
        from mumu_controller import run_one
        from mumu_pause import PortControl
        import io
        import json as json_module
        events = []

        class FakeProcess:
            def __init__(self):
                self.stdin = io.BytesIO()
                payload = ''.join(json_module.dumps(event) + '\n' for event in (
                    dict(kind='progress', value='работаю'),
                    dict(kind='control', value='paused'),
                    dict(kind='control', value='resumed'),
                    dict(kind='result', value='готово')))
                self.stdout = io.BytesIO(payload.encode('utf-8'))
                self.stderr = None
            def poll(self): return 0
            def wait(self, timeout=None): return 0
            def kill(self): pass
            def terminate(self): pass

        class PopenFactory:
            def __init__(self): self.opened = []
            def __call__(self, command, **options):
                self.opened.append(command)
                return FakeProcess()

        control = PortControl()
        factory = PopenFactory()
        out = run_one(5571, Settings(), 'full', False, threading.Event(),
                      lambda n, text: events.append((n, text)),
                      popen=factory, control=control)
        self.assertEqual(out, 'готово')
        self.assertIn('--mumu-worker', ' '.join(factory.opened[0]))
        self.assertIn((5571, 'работаю'), events)
        self.assertEqual(control.state(), 'finished')


if __name__ == '__main__':
    unittest.main()
