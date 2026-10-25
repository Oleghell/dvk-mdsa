"""Report 137: late message header read at sample, without send replay."""
import unittest
from unittest.mock import MagicMock
import assistant_history_wait as history
from one_chat_device import ReadStopped, safe_read_failure
import test_inbox_profiles as fixtures
from test_inbox_profiles import WHO, OTHER, nav, msg, snap


def failure(code='frame-budget', **changes):
    value=dict(stage='navigation-stopped',metadata_checkpoint='ready',
        read_checkpoint='sample',wait_reason='none',frames=5,managed_calls=424,
        identity_checkpoint='recheck',message_kind='text',message_direction='not-own',
        scalar_state='positive',message_slot=1,scalar_checkpoint='message-chat-id')
    value.update(changes)
    return ReadStopped(code,value)


class Classification(unittest.TestCase):
    def test_exact_report_and_final_header_scalar_states(self):
        for code in ('frame-budget','transition-timeout'):
            for scalar in ('message-id','message-sender-id','message-chat-id'):
                for state in ('positive','not-read'):
                    self.assertTrue(history.verified_read_budget(safe_read_failure(
                        failure(code,scalar_checkpoint=scalar,scalar_state=state))))

    def test_json_keeps_retry_count_without_raw_failure_details(self):
        import json
        from assistant_error_notify import diagnostic_json
        value=dict(last_chat_diagnostics=dict(read_retries=3,
            last_read_failure=dict(safe_read_failure(failure()),private_text='PRIVATE_SECRET')))
        encoded=diagnostic_json(value)
        safe=json.loads(encoded)['diagnostic']['last_chat_diagnostics']
        self.assertEqual(safe['read_retries'],3)
        self.assertEqual(safe['last_read_failure']['scalar_checkpoint'],'message-chat-id')
        self.assertNotIn(b'PRIVATE',encoded)
        for invalid in (True,-1,1.5,'PRIVATE_SECRET'):
            value['last_chat_diagnostics']['read_retries']=invalid
            self.assertNotIn('read_retries',json.loads(diagnostic_json(value))['diagnostic']['last_chat_diagnostics'])

    def test_unverified_errors_stages_and_invalid_header_slots_still_stop(self):
        good=safe_read_failure(failure())
        for changes in (dict(error='identity-changed'),dict(error='identity-not-bound'),
            dict(error='message-invalid'),dict(error='nonpositive-message-chat-id'),
            dict(stage='navigation-ready'),dict(metadata_checkpoint='base'),
            dict(identity_checkpoint='initial-ids'),dict(identity_checkpoint='saved-binding'),
            dict(scalar_state='zero'),dict(scalar_state='negative'),
            dict(message_slot=-1),dict(message_slot=True),dict(message_slot=128),
            dict(read_checkpoint='complete'),dict(wait_reason='history-loading')):
            with self.subTest(changes=changes):
                self.assertFalse(history.verified_read_budget(dict(good,**changes)))


class Inbox(fixtures.Base):
    def test_exact_report_retries_same_identity_before_one_reply(self):
        self.journal();h=msg(1002,'Привет');q=msg(1003,'Как дела?)',True)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                      [failure(),snap(h),snap(h),snap(h,q)])
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['last_chat_diagnostics']['read_retries'],1)
        self.assertEqual(self.sent,['Как дела?)'])
        for call in self.reader.call_args_list:self.assertEqual(call.args[3],WHO)

    def test_persistent_sample_defers_after_verified_back_and_processes_other_peer(self):
        self.journal();self.journal(OTHER)
        h=msg(1002,'Привет',who=OTHER);q=msg(1003,'Как дела?)',True,who=OTHER)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('opened',OTHER),
                       nav('returned',OTHER),nav('search-ready')],
            [*[failure() for _ in range(history.BUDGET_READ_ATTEMPTS)],
             snap(h,who=OTHER),snap(h,who=OTHER),snap(h,q,who=OTHER)])
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['history_deferred'],1)
        self.assertEqual(self.sent,['Как дела?)'])
        self.assertEqual(self.reader.call_count,history.BUDGET_READ_ATTEMPTS+3)
        self.assertEqual(self.nav.call_args_list[1].kwargs['expected'],WHO)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_actions WHERE chat=?',(WHO['chat'],)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT peer FROM inbox_history_deferrals').fetchall(),[(WHO['peer'],)])

    def test_reported_transition_timeout_keeps_two_attempt_bound(self):
        self.journal()
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                      [failure('transition-timeout',read_checkpoint='last-message',scalar_checkpoint='chat-id')]*2)
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['history_deferred'],1)
        self.assertEqual(self.reader.call_count,2)
        self.assertFalse(self.sent)

    def test_wrong_or_unknown_back_stops_without_opening_next_peer(self):
        for back in (nav('returned',OTHER),RuntimeError('PRIVATE')):
            case=fixtures.Base();case.setUp();self.addCleanup(case.doCleanups);case.journal()
            out=case.walk([nav('opened',WHO),back],[failure()]*history.BUDGET_READ_ATTEMPTS)
            self.assertEqual(out['status'],'inbox-stopped')
            self.assertEqual(case.nav.call_count,2)
            self.assertFalse(case.sent)

    def test_changed_identity_after_sample_failure_never_authorizes_send(self):
        self.journal()
        out=self.walk([nav('opened',WHO)],[failure(),ReadStopped('identity-changed')])
        self.assertEqual(out['status'],'inbox-stopped')
        self.assertEqual(self.reader.call_count,2)
        self.assertFalse(self.sent)

    def test_post_send_sample_failure_keeps_journal_and_never_resubmits(self):
        self.journal();h=msg(1002,'Привет')
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                      [snap(h),snap(h),*[failure() for _ in range(history.BUDGET_READ_ATTEMPTS)]])
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['history_deferred'],1)
        self.assertEqual(len(self.sent),1)
        with self.store.connection() as db:
            before=db.execute('SELECT * FROM chain_actions').fetchall()
            self.assertEqual(before[0][-1],'handler-returned-unconfirmed')
        self.assertEqual(self.walk([],[])['status'],'inbox-empty')
        self.assertEqual(len(self.sent),1)
        with self.store.connection() as db:
            self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())
