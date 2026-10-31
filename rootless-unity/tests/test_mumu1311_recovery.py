"""Regression contracts for 1.3.10 reports; synthetic data, no live accounts."""
import copy
import unittest
from unittest.mock import MagicMock
import assistant_pass
import assistant_error_notify as alerts
import search_city
from test_assistant import cycle


class Recovery(unittest.TestCase):
    def test_actual_wait_only_before_authorization_and_while_identity_verified(self):
        s=assistant_pass.build('Привет')
        start=s.index("if(state.waitSignature===signature")
        end=s.index("state.waitSignature=signature",start)
        part=s[start:end]
        for guard in ("reason==='chat-not-actual'","n.phase==='check-chat'",'n.chat_verified&&n.chat_identity_verified',
                      '!n.send_attempted&&!n.send_handler_returned','cohortPending===null&&cohortApproved===null',
                      'n.profile_ready_waits<4',"else fail('history-not-ready')"):
            self.assertIn(guard,part)
        self.assertIn('state.nextActionAt=Date.now()+1000',s[end:])
        self.assertIn("!user.equals(target(state.targetUser))",s)
        self.assertIn("save('chatController',current)",s)

    def test_strict_counter_and_no_cached_history_authorization(self):
        v=cycle();n=v['navigation'];n.update(cycle_timeout_ms=90000,
            profile_read_budget_retries=0,profile_ready_waits=1,greeting_frame_splits=1,submit_frame_retries=0)
        before=copy.deepcopy(v);self.assertIs(assistant_pass.validate(v),v);self.assertEqual(v,before)
        for key,bad in [('profile_ready_waits',True),('profile_ready_waits',-1),('profile_ready_waits',5),
                        ('chat_identity_verified',False),('chat_verified',False),('samples',1),('model_actual',False)]:
            x=copy.deepcopy(v);x['navigation'][key]=bad
            with self.subTest(key=key,bad=bad),self.assertRaises(ValueError):assistant_pass.validate(x)

    def test_post_apply_retry_is_read_only_and_all_budgets_still_bounded(self):
        s=search_city.build('Pskov')
        self.assertIn("n.phase==='wait-return'&&n.apply_completed&&n.city_select_completed&&n.city_form_verified",s)
        self.assertIn("e==='frame-budget'&&!cityFrameMutated",s)
        self.assertIn('n.city_read_budget_retries<4',s)
        self.assertIn('const deadline=Date.now()+100;',s)
        self.assertIn('n.managed_calls>=6000',s)
        self.assertIn('r.navigation.frames>=900',s)
        self.assertIn('},30000);',s)
        self.assertEqual(s.count('cityTransition(s.apply,current)'),1)
        self.assertIn("r.navigation.phase==='wait-return'&&Date.now()<(navState.cityReturnNext||0)",s)


class TerminalAlerts(unittest.TestCase):
    def report(self, profile):
        return dict(status='stopped',reason='initial-pass-stopped',initial_run=dict(
            status='stopped',reason='profiles-not-finished',
            inbox=dict(status='inbox-completed',reason='visible-exhausted',
                ai_key_failures=['groq-key-pool-exhausted','openrouter-key-pool-exhausted','PRIVATE'],
                last_chat_diagnostics=dict(failure_point='groq-key-pool-exhausted')),
            profiles=profile))

    def test_completed_ai_failures_not_mixed_into_city_stop(self):
        r=self.report(dict(status='profiles-stopped',reason='city-not-verified',last_error='frame-budget'))
        reasons=alerts.reasons(r)
        self.assertIn('city-not-verified',reasons);self.assertIn('frame-budget',reasons)
        self.assertNotIn('groq-key-pool-exhausted',reasons)
        self.assertEqual(alerts.ai_warnings(r),['groq-key-pool-exhausted','openrouter-key-pool-exhausted'])
        sender=MagicMock(return_value=True)
        self.assertEqual(alerts.notify(r,loader=lambda:('token','chat'),sender=sender),'accepted')
        text=sender.call_args.args[2];cause,warning=text.split('Предупреждения ИИ (отдельно): ')
        self.assertNotIn('key-pool-exhausted',cause);self.assertIn('openrouter-key-pool-exhausted',warning)
        self.assertNotIn('PRIVATE',text);sender.assert_called_once()

    def test_actual_chat_failure_not_hidden_by_previous_ai_problem(self):
        r=self.report(dict(status='profiles-stopped',reason='profile-check-stopped',last_error='history-not-ready'))
        self.assertIn('history-not-ready',alerts.reasons(r))
        self.assertNotIn('groq-key-pool-exhausted',alerts.reasons(r))

    def test_actual_ai_stop_still_shows_ai_reason(self):
        r=dict(status='stopped',reason='inbox-pass-stopped',last_pass=dict(status='inbox-stopped',
            reason='chat-groq-key-pool-exhausted'))
        self.assertIn('groq-key-pool-exhausted',alerts.reasons(r))

    def test_previous_completed_initial_pass_does_not_pollute_later_stop(self):
        r=dict(status='stopped',reason='profile-pass-stopped',initial_run=dict(status='completed',
            reason='none',profiles=dict(reason='city-not-verified',last_error='frame-budget')),
            last_profile_run=dict(status='stopped',reason='profiles-not-finished',
                profiles=dict(status='profiles-stopped',reason='profile-check-stopped',last_error='history-not-ready')))
        self.assertNotIn('city-not-verified',alerts.reasons(r))
        self.assertIn('history-not-ready',alerts.reasons(r))
