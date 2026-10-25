"""Supplied message-invalid shape: local quarantine, no send validation bypass."""
import json
from contextlib import nullcontext
from unittest.mock import MagicMock
import unittest
import assistant_inbox as inbox
import assistant_run
from assistant_history_wait import verified_message_invalid
from assistant_error_notify import diagnostic_json,KNOWN
from one_chat_device import ReadStopped
from test_inbox_profiles import Base,WHO,OTHER,GREETING,nav,msg,snap


def failure(**changes):
    data=dict(stage='navigation-stopped',metadata_checkpoint='ready',
        read_checkpoint='last-message',wait_reason='none',frames=5,managed_calls=407,
        message_kind='text',message_direction='own',scalar_checkpoint='chat-id',
        scalar_state='positive',message_slot=5,identity_checkpoint='recheck')
    data.update(changes)
    return ReadStopped('message-invalid',data)


class InvalidMessage(Base):
    def test_exact_report_quarantines_chat_and_continues_next(self):
        self.journal();self.journal(OTHER)
        h=msg(1002,'Привет',who=OTHER);q=msg(1003,'Как дела?)',True,who=OTHER)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('opened',OTHER),
            nav('returned',OTHER),nav('search-ready')],
            [failure(),snap(h,who=OTHER),snap(h,who=OTHER),snap(h,q,who=OTHER)])
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['isolated_reasons'],{'message-invalid':1})
        self.assertEqual(self.sent,['Как дела?)'])
        self.assertEqual(self.reader.call_count,4)
        self.assertEqual(self.nav.call_args_list[1].kwargs['expected'],WHO)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs WHERE peer=?',(WHO['peer'],)).fetchone()[0],'manual-review')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_actions WHERE chat=?',(WHO['chat'],)).fetchone()[0],0)
        self.assertNotIn(WHO['peer'],[v['peer'] for v in sum(inbox.inbox_targets(self.chain()),[])])
    def test_unknown_send_never_repeated_or_marked_confirmed(self):
        self.journal();h=msg(1002,'Привет')
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                      [snap(h),snap(h),failure()])
        self.assertEqual(out['status'],'inbox-completed')
        with self.store.connection() as db:
            before=db.execute('SELECT * FROM chain_actions').fetchall()
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'handler-returned-unconfirmed')
        self.assertEqual(self.walk([],[])['status'],'inbox-empty')
        self.assertEqual(len(self.sent),1)
        with self.store.connection() as db:self.assertEqual(before,db.execute('SELECT * FROM chain_actions').fetchall())
    def test_wrong_back_or_unknown_back_stops_without_next_action(self):
        for returned in (nav('returned',OTHER),RuntimeError('PRIVATE')):
            case=Base();case.setUp();self.addCleanup(case.doCleanups);case.journal()
            out=case.walk([nav('opened',WHO),returned],[failure()])
            self.assertEqual(out['status'],'inbox-stopped');self.assertEqual(out['isolated_dialogs'],0)
            self.assertEqual(case.nav.call_count,2);self.assertFalse(case.sent)
    def test_initial_pass_still_runs_profiles(self):
        self.journal();profiles=MagicMock(return_value=dict(status='profiles-completed'))
        out=assistant_run.start(self.settings,self.stop,self.approve,
            inbox=lambda *a:self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[failure()]),
            profiles=profiles,lock=nullcontext,write=lambda _: 'last-run.json')
        self.assertEqual(out['status'],'completed');profiles.assert_called_once()
    def test_cancellation_never_navigates_back(self):
        self.journal()
        def read(*args):self.stop.set();raise failure()
        navigator=MagicMock(side_effect=[nav('opened',WHO)])
        sender=MagicMock()
        out=inbox.walk(self.settings,self.stop,self.approve,lambda _:None,self.chain(),
            navigator=navigator,reader=read,sender=sender,greetings=(GREETING,),pause=lambda _:False)
        self.assertEqual(out['status'],'inbox-cancelled');self.assertEqual(navigator.call_count,1)
        sender.assert_not_called()


class Classification(unittest.TestCase):
    def test_missing_or_identity_evidence_cannot_authorize_local_skip(self):
        good=dict(error='message-invalid',**failure().diagnostic)
        self.assertTrue(verified_message_invalid(good))
        changes=[dict(error='identity-changed'),dict(error='PRIVATE'),dict(stage='navigation-ready'),
            dict(metadata_checkpoint='base'),dict(read_checkpoint='identity'),dict(identity_checkpoint='saved-binding'),
            dict(scalar_checkpoint='account-id'),dict(scalar_checkpoint='peer-id'),dict(scalar_state='negative'),
            dict(wait_reason='history-loading'),dict(message_kind='not-read'),dict(message_direction='not-read'),
            dict(message_slot=-1),dict(message_slot=128),dict(message_slot=True)]
        for change in changes:
            with self.subTest(change=change):self.assertFalse(verified_message_invalid(dict(good,**change)))
        for key in good:
            broken=dict(good);del broken[key]
            if key not in ('frames','managed_calls'):
                with self.subTest(missing=key):self.assertFalse(verified_message_invalid(broken))
        # A stale diagnostic attached to an unrelated host failure must NOT skip.
        for reason in ('binding-or-history-check-stopped','snapshot-validation-failed','unrecognized-diagnostic-code'):
            self.assertIsNone(inbox.isolation_reason(dict(reason=reason,diagnostics=dict(last_read_failure=good))))
        self.assertIsNone(inbox.isolation_reason(dict(reason='message-invalid',diagnostics={})))
    def test_known_prefixed_reasons_already_survive_sanitizer(self):
        for code in ('message-invalid','bound-chat-read-failed','binding-or-history-check-stopped'):
            value=json.loads(diagnostic_json(dict(reason='chat-'+code,last_chat_diagnostics=dict(failure_point=code))))['diagnostic']
            self.assertEqual(value['reason'],'chat-'+code)
            self.assertEqual(value['last_chat_diagnostics']['failure_point'],code)
        raw=diagnostic_json(dict(reason='PRIVATE',last_chat_diagnostics=dict(failure_point='PRIVATE',body='PRIVATE',key='PRIVATE')))
        self.assertNotIn(b'PRIVATE',raw)
