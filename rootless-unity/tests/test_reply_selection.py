"""1.2.3 list eligibility and diagnostic regression tests. Synthetic only."""
import unittest
from unittest.mock import MagicMock
import dialog_browser as b
import assistant_inbox as inbox
import assistant_error_notify as notify
from test_dialog_browser import raw_open, TARGET, WHO
from test_inbox_profiles import Base, nav, snap, msg
from conversation_engine import QUESTIONS


class ReplySchema(unittest.TestCase):
    def test_reply_filter_is_mandatory_evidence_when_requested(self):
        v=raw_open()
        with self.assertRaises(ValueError):b.validate(v,'open',allowed=[TARGET],needs_reply_only=True)
        v['navigation'].update(reply_filter_applied=True,reply_needed_verified=True)
        self.assertEqual(b.validate(v,'open',allowed=[TARGET],needs_reply_only=True)['state'],'opened')
        with self.assertRaises(ValueError):b.validate(v,'open',allowed=[TARGET])

    def test_exhaustion_has_filter_but_no_reply_verification(self):
        v=raw_open();v['navigation'].update(exhausted=True,selection_verified=False,chat_verified=False,
            private_identity=None,selection_checkpoint='exhausted',reply_filter_applied=True,
            waiting_rows_skipped=1,handled_rows_skipped=1)
        self.assertEqual(b.validate(v,'open',allowed=[TARGET],needs_reply_only=True)['state'],'exhausted')
        v['navigation']['reply_needed_verified']=True
        with self.assertRaises(ValueError):b.validate(v,'open',allowed=[TARGET],needs_reply_only=True)

    def test_reply_options_and_skip_counts_are_strict(self):
        for value in (1,None,'true'):
            with self.assertRaises(ValueError):b.build('open',allowed=[TARGET],needs_reply_only=value)
        for op in ('back','return','list'):
            with self.assertRaises(ValueError):b.build(op,expected=WHO if op=='back' else None,needs_reply_only=True)
        for field,value in [('waiting_rows_skipped',True),('handled_rows_skipped',-1),('waiting_rows_skipped',3)]:
            v=raw_open();v['navigation'].update(reply_filter_applied=True,reply_needed_verified=True);v['navigation'][field]=value
            with self.assertRaises(ValueError):b.validate(v,'open',allowed=[TARGET],needs_reply_only=True)

    def test_seen_ids_are_private_strict_bounded_positive_identifiers(self):
        target=dict(TARGET,seen_ids=['1002'])
        self.assertEqual(b.targets([target]),[target])
        for value in (None,['0'],['-1'],['1002','1002'],[{}],[1],['1']*21):
            with self.assertRaises(ValueError):b.targets([dict(TARGET,seen_ids=value)])
        v=raw_open();v['navigation'].update(reply_filter_applied=True,reply_needed_verified=True)
        result=b.validate(v,'open',allowed=[target],needs_reply_only=True)
        self.assertNotIn('1002',str(result['diagnostic']))

    def test_last_headers_are_checked_and_rechecked_before_open_without_bodies(self):
        source=b.build('open',allowed=[TARGET],needs_reply_only=True)
        for method in ('get_LastMessage','get_SenderId','get_ChatId','get_IsMine'):
            self.assertIn(method,source)
        for needle in ('if(unread===0&&!header.incoming)', 'if(alreadyHandled', "fail('selection-last-message-changed')"):
            self.assertLess(source.index(needle),source.index('call(s.openCell,current,args)'))
        for forbidden in ('get_Text','get_Body','get_Name','OnSend'):
            self.assertNotIn(forbidden,source)
        self.assertNotIn('sort(',source)  # No invented message chronology.


class ReplyFlow(Base):
    def test_waiting_own_and_handled_incoming_are_skipped_without_read_or_send(self):
        self.journal()
        exhausted=nav('exhausted',unread=False)
        exhausted['diagnostic'].update(waiting_rows_skipped=1,handled_rows_skipped=1)
        out=self.walk([nav('exhausted'),exhausted,nav('search-ready')],[])
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual((out['waiting_rows_skipped'],out['handled_rows_skipped']),(1,1))
        self.assertEqual(out['dialogs_opened'],0)
        self.reader.assert_not_called();self.assertFalse(self.sent)
        self.assertEqual(out['isolated_dialogs'],0)
        self.assertTrue(all(c.kwargs['needs_reply_only'] for c in self.nav.call_args_list if c.args[0]=='open'))

    def test_new_read_incoming_is_answered_not_ignored_and_seen_ids_are_forwarded(self):
        self.journal();chain=self.chain();chain.consume(snap())
        hello=msg(1002,'Давай знакомиться');question=msg(1003,QUESTIONS[0],True)
        out=self.walk([nav('exhausted'),nav('opened',WHO,unread=False),nav('returned',WHO),nav('search-ready')],
                      [snap(hello),snap(hello),snap(hello,question)],chain=chain)
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['submission_calls'],1)
        self.assertEqual(out['outgoing_observed'],1)
        self.assertEqual(self.sent,[QUESTIONS[0]])
        calls=[c for c in self.nav.call_args_list if c.args[0]=='open']
        self.assertEqual(calls[1].kwargs['allowed'][0]['seen_ids'],['1001'])

    def test_unread_incoming_is_answered_and_filter_required(self):
        self.journal();hello=msg(1002,'Здравствуйте!');q=msg(1003,QUESTIONS[0],True)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[snap(hello),snap(hello),snap(hello,q)])
        self.assertEqual(out['submission_calls'],1);self.assertEqual(self.sent,[QUESTIONS[0]])
        self.assertTrue(self.nav.call_args_list[0].kwargs['needs_reply_only'])

    def test_unverified_filter_stops_before_read_or_send(self):
        self.journal();bad=nav('opened',WHO);bad['diagnostic']['reply_filter_applied']=False
        out=self.walk([bad],[])
        self.assertEqual(out['reason'],'reply-selection-not-verified')
        self.reader.assert_not_called();self.assertFalse(self.sent)

    def test_manual_outgoing_review_has_safe_exact_cause(self):
        self.journal();chain=self.chain();chain.consume(snap())
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                      [snap(msg(1002,'Входящее'),msg(1003,'Ручной ответ',True))],chain=chain)
        self.assertEqual(out['review_causes'],{'unjournalled-outgoing':1})
        self.assertEqual(chain.review_reason(WHO),'unjournalled-outgoing')
        self.assertFalse(self.sent)

    def test_history_change_cause_is_persistent_without_storing_body(self):
        self.journal();chain=self.chain();chain.consume(snap())
        altered=snap();altered['messages'][0]['text']='PRIVATE MODIFIED'
        self.assertEqual(chain.consume(altered),('manual-review',None))
        self.assertEqual(chain.review_reason(WHO),'history-edited')
        # Later missing history must not overwrite the original verified cause.
        with chain.store.connection() as db:
            self.assertNotIn('PRIVATE',str(db.execute('SELECT * FROM chain_review_reasons').fetchall()))
        chain.mark_review(WHO)
        self.assertEqual(chain.review_reason(WHO),'history-edited')

    def test_existing_reviews_are_not_reset_by_selection_migration(self):
        self.journal();chain=self.chain();chain.mark_review(WHO)
        self.assertEqual(chain.review_reason(WHO),'review-cause-unavailable')
        out=self.walk([],[],chain=chain)
        self.assertEqual(out['status'],'inbox-empty')
        self.nav.assert_not_called()
        self.assertEqual(inbox.inbox_targets(self.chain()),([],[]))


class ReviewAlerts(unittest.TestCase):
    def test_notification_cause_is_allowlisted_no_private_text(self):
        sender=MagicMock(return_value=True)
        result=notify.notify_isolated(dict(isolated_reasons={'manual-review':1},
            review_causes={'unjournalled-outgoing':1,'PRIVATE':1}),loader=lambda:('token','chat'),sender=sender)
        self.assertEqual(result,'accepted')
        self.assertIn('unjournalled-outgoing',sender.call_args.args[2])
        self.assertNotIn('PRIVATE',sender.call_args.args[2])
