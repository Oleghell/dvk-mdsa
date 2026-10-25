"""Report 136: read budget after a positive initial ID, not identity proof."""
import unittest
import assistant_history_wait as history
from one_chat_device import ReadStopped, safe_read_failure
import test_inbox_profiles as fixtures
from test_inbox_profiles import WHO, OTHER, nav, msg, snap


def failure(**changes):
    value=dict(stage='navigation-stopped', metadata_checkpoint='ready',
        read_checkpoint='identity', wait_reason='none', frames=4, managed_calls=254,
        scalar_checkpoint='chat-id', identity_checkpoint='initial-ids', scalar_state='positive',
        message_direction='not-own', message_slot=0, message_kind='text')
    value.update(changes)
    return ReadStopped('frame-budget', value)


class Classification(unittest.TestCase):
    def test_exact_report_and_each_initial_id_are_read_only_retry_candidates(self):
        for scalar in ('account-id','peer-id','chat-id'):
            with self.subTest(scalar=scalar):
                self.assertTrue(history.verified_read_budget(safe_read_failure(failure(scalar_checkpoint=scalar))))

    def test_no_identity_mismatch_or_bad_scalar_can_be_retried(self):
        good=safe_read_failure(failure())
        for changes in (dict(error='identity-changed'), dict(error='identity-not-bound'),
            dict(error='message-invalid'), dict(stage='navigation-ready'), dict(metadata_checkpoint='base'),
            dict(scalar_state='zero'), dict(scalar_state='negative'), dict(scalar_state='invalid'),
            dict(scalar_checkpoint='message-id'), dict(read_checkpoint='last-message'),
            dict(identity_checkpoint='saved-binding'), dict(wait_reason='history-loading'),
            dict(message_slot=True),dict(message_slot=128)):
            with self.subTest(changes=changes):
                self.assertFalse(history.verified_read_budget(dict(good,**changes)))


class Inbox(fixtures.Base):
    def test_transient_report_restarts_bound_read_before_any_reply(self):
        self.journal();h=msg(1002,'Привет');q=msg(1003,'Как дела?)',True)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
            [failure(),snap(h),snap(h),snap(h,q)])
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['last_chat_diagnostics']['read_retries'],1)
        self.assertEqual(self.sent,['Как дела?)'])
        self.assertEqual(self.nav.call_count,3)
        for call in self.reader.call_args_list:
            self.assertEqual(call.args[3],WHO)

    def test_persistent_report_defers_then_continues_other_chat_without_send(self):
        self.journal();self.journal(OTHER)
        h=msg(1002,'Привет',who=OTHER);q=msg(1003,'Как дела?)',True,who=OTHER)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('opened',OTHER),
            nav('returned',OTHER),nav('search-ready')],
            [*[failure() for _ in range(history.BUDGET_READ_ATTEMPTS)],snap(h,who=OTHER),
             snap(h,who=OTHER),snap(h,q,who=OTHER)])
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['history_deferred'],1)
        self.assertEqual(self.sent,['Как дела?)'])
        self.assertEqual(self.reader.call_count,history.BUDGET_READ_ATTEMPTS+3)
        self.assertEqual(self.nav.call_args_list[1].kwargs['expected'],WHO)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_actions WHERE chat=?',(WHO['chat'],)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT peer FROM inbox_history_deferrals').fetchall(),[(WHO['peer'],)])

    def test_wrong_or_unknown_back_stops_before_next_chat(self):
        for back in (nav('returned',OTHER),RuntimeError('PRIVATE')):
            case=fixtures.Base();case.setUp();self.addCleanup(case.doCleanups);case.journal()
            out=case.walk([nav('opened',WHO),back],[failure() for _ in range(history.BUDGET_READ_ATTEMPTS)])
            self.assertEqual(out['status'],'inbox-stopped')
            self.assertEqual(case.nav.call_count,2)
            self.assertFalse(case.sent)

    def test_identity_mismatch_after_interrupted_read_never_sends_or_retries(self):
        self.journal()
        out=self.walk([nav('opened',WHO)],[failure(),ReadStopped('identity-changed')])
        self.assertEqual(out['status'],'inbox-stopped')
        self.assertEqual(self.reader.call_count,2)
        self.assertEqual(self.nav.call_count,1)
        self.assertFalse(self.sent)

    def test_post_send_read_budget_does_not_resubmit_existing_action(self):
        self.journal();h=msg(1002,'Привет')
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
            [snap(h),snap(h),*[failure() for _ in range(history.BUDGET_READ_ATTEMPTS)]])
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['history_deferred'],1)
        self.assertEqual(len(self.sent),1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('handler-returned-unconfirmed',)])
            before=db.execute('SELECT * FROM chain_actions').fetchall()
        self.assertEqual(self.walk([],[])['status'],'inbox-empty')
        self.assertEqual(len(self.sent),1)
        with self.store.connection() as db:
            self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())
