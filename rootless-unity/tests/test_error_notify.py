import json
import unittest
from unittest.mock import MagicMock
import assistant_error_notify as n

class ErrorAlerts(unittest.TestCase):
    def test_sends_only_authored_reason_codes_not_messages_or_ids(self):
        report=dict(status='stopped',reason='inbox-pass-stopped',last_pass=dict(
            reason='chat-groq-rate-limit',last_chat_diagnostics=dict(failure_point='groq-rate-limit'),
            PRIVATE='secret',last_navigation=dict(error='PRIVATE')))
        sender=MagicMock(return_value=True)
        self.assertEqual(n.notify(report,loader=lambda:('token','chat'),sender=sender),'accepted')
        sender.assert_called_once()
        text=sender.call_args.args[2]
        self.assertIn('groq-rate-limit',text);self.assertNotIn('PRIVATE',text);self.assertNotIn('secret',text)

    def test_unknown_telegram_delivery_is_not_retried(self):
        sender=MagicMock(side_effect=RuntimeError('token PRIVATE'))
        self.assertEqual(n.notify(dict(status='stopped'),loader=lambda:('token','chat'),sender=sender),'unknown')
        self.assertEqual(sender.call_count,1)

    def test_unconfigured_cancelled_and_waiting_do_not_send(self):
        loader=MagicMock(side_effect=RuntimeError('PRIVATE'));sender=MagicMock()
        self.assertEqual(n.notify(dict(status='stopped'),loader=loader,sender=sender),'not-configured')
        for status in ('cancelled','waiting'):
            self.assertEqual(n.notify(dict(status=status),loader=loader,sender=sender),'not-needed')
        self.assertEqual(loader.call_count,1);sender.assert_not_called()

    def test_isolated_alert_is_bounded_and_contains_only_safe_codes(self):
        sender=MagicMock(return_value=True)
        report=dict(isolated_reasons={'send-outcome-unknown':1, 'PRIVATE':1})
        self.assertEqual(n.notify_isolated(report, loader=lambda:('token','chat'), sender=sender), 'accepted')
        text=sender.call_args.args[2]
        self.assertIn('send-outcome-unknown', text)
        self.assertNotIn('PRIVATE', text)
        self.assertEqual(sender.call_count, 1)

    def test_isolated_alert_no_retry_or_repeated_alert_without_new_isolation(self):
        sender=MagicMock(side_effect=RuntimeError('PRIVATE'))
        self.assertEqual(n.notify_isolated(dict(isolated_reasons={'manual-review':1}),
                         loader=lambda:('token','chat'), sender=sender), 'unknown')
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(n.notify_isolated(dict(isolated_reasons={}),
                         loader=lambda:('token','chat'), sender=sender), 'not-needed')
        self.assertEqual(sender.call_count, 1)
