"""Report 138: pre-tap read failure is not a failed profile return."""
import json
from unittest.mock import MagicMock,patch,call
from assistant_contact_photo import capture_profile,ProfilePhotoNotStarted,ProfileReturnUnverified
from assistant_store import StateError
from assistant_guided_chain import GuidedChain
from mumu_store import SharedStore
from assistant_error_notify import diagnostic_json
from test_extensions126 import png
from test_inbox_profiles import Base,WHO,msg,snap,nav
from test_mumu139_unavailable import timeout


class PhotoRecovery(Base):
    def test_failed_pre_tap_identity_read_has_no_ui_action_or_screenshot(self):
        dev=MagicMock();reader=MagicMock(side_effect=timeout())
        with self.assertRaises(ProfilePhotoNotStarted) as caught:
            capture_profile('adb','folder',WHO,device_factory=lambda *a:dev,chat_reader=reader)
        dev.run.assert_not_called();dev.screen.assert_not_called();dev.pause.assert_not_called()
        detail=caught.exception.diagnostic
        self.assertFalse(detail['action_attempted'])
        self.assertEqual(detail['photo_checkpoint'],'before-profile-open')
        self.assertEqual(detail['last_read_failure']['error'],'transition-timeout')
        self.assertNotEqual(str(caught.exception),'profile-return-not-verified')

    def test_after_tap_unknown_return_still_stops_and_never_blind_backs(self):
        dev=MagicMock();dev.screen.return_value=png()
        with self.assertRaises(ProfileReturnUnverified) as caught:
            capture_profile('adb','folder',WHO,device_factory=lambda *a:dev,
                chat_reader=MagicMock(side_effect=[snap(),timeout(),timeout()]),
                profile_reader=MagicMock(side_effect=StateError('profile-not-verified')))
        self.assertNotIn(call(['shell','input','keyevent','4']),dev.run.call_args_list)
        self.assertTrue(caught.exception.diagnostic['action_attempted'])
        self.assertEqual(str(caught.exception),'profile-return-not-verified')

    def saved(self):
        self.store=SharedStore(self.path if hasattr(self,'path') else self.store.path,
                              self.store.legacy,device_port=5563)
        self.journal(WHO,WHO['chat'])
        chain=self.chain();chain.media_required=True
        chain.bind(snap(),('Привет 🙂',),approved=True)
        candidate=dict(snap(msg(1002,'Мой номер +79001234567')),peer_name='Тест')
        self.assertEqual(chain.proposal(candidate),('done',None))
        return chain,candidate

    def test_saved_contact_photo_failure_is_local_only_after_same_chat_back(self):
        chain,candidate=self.saved()
        photo=MagicMock(side_effect=ProfilePhotoNotStarted(timeout()))
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                      [candidate],chain=chain,contact_photo=photo)
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['history_deferred'],1)
        self.assertEqual(out['contact_delivery_pending'],1)
        self.assertFalse(self.sent);self.notifier.assert_not_called()
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone()[0],'pending')
            self.assertEqual(db.execute('SELECT reason FROM mumu_peer_blocks').fetchone()[0],'contact-received')
        self.assertEqual(out['last_chat_diagnostics']['photo_failure']['photo_checkpoint'],'before-profile-open')

    def test_pending_saved_receipt_can_resume_without_proposal_ai_or_new_message(self):
        chain,candidate=self.saved()
        chain.responder=MagicMock(side_effect=AssertionError('No AI'))
        with patch.object(chain,'proposal',side_effect=AssertionError('Receipt only')):
            out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                [candidate],chain=chain,contact_photo=MagicMock(return_value=png()))
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['contacts_forwarded'],1)
        self.assertTrue(out['last_chat_diagnostics']['saved_receipt_only'])
        self.assertFalse(self.sent);self.approve.assert_not_called();chain.responder.assert_not_called()
        self.assertEqual(self.notifier.call_count,1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone()[0],'accepted')
            self.assertEqual(db.execute('SELECT reason FROM mumu_peer_blocks').fetchone()[0],'contact-received')

    def test_failed_same_chat_back_is_not_a_local_photo_skip(self):
        chain,candidate=self.saved()
        other=dict(WHO,peer='201',chat='301')
        out=self.walk([nav('opened',WHO),nav('returned',other)], [candidate],chain=chain,
                      contact_photo=MagicMock(side_effect=ProfilePhotoNotStarted(timeout())))
        self.assertEqual(out['status'],'inbox-stopped');self.assertFalse(self.sent)
        self.assertEqual(self.nav.call_count,2)

    def test_photo_json_separates_current_failure_from_historical_read_timeout(self):
        error=ProfilePhotoNotStarted(timeout())
        value=dict(last_chat_diagnostics=dict(photo_failure=dict(error.diagnostic,private_text='PRIVATE'),
            host_checkpoint='chat-contact-photo',saved_receipt_only=True))
        encoded=diagnostic_json(value);safe=json.loads(encoded)['diagnostic']['last_chat_diagnostics']
        self.assertEqual(safe['photo_failure']['photo_checkpoint'],'before-profile-open')
        self.assertFalse(safe['photo_failure']['action_attempted'])
        self.assertEqual(safe['host_checkpoint'],'chat-contact-photo')
        self.assertNotIn(b'PRIVATE',encoded)

    def test_saved_pending_photo_is_not_hidden_by_seen_incoming(self):
        from assistant_inbox import with_seen_ids
        chain,candidate=self.saved()
        self.assertEqual(with_seen_ids(chain,[WHO])[0]['seen_ids'],[])
        with self.store.connection() as db:
            before=list(db.execute('SELECT * FROM chain_actions'))
            db.execute("UPDATE chain_contact_outbox SET status='accepted'")
        self.assertTrue(with_seen_ids(chain,[WHO])[0]['seen_ids'])
        with self.store.connection() as db:
            self.assertEqual(before,list(db.execute('SELECT * FROM chain_actions')))

    def test_unknown_receipt_is_not_reopened_for_photo(self):
        from assistant_inbox import with_seen_ids
        chain,candidate=self.saved()
        with self.store.connection() as db:
            db.execute("UPDATE chain_contact_outbox SET status='unknown'")
        self.assertTrue(with_seen_ids(chain,[WHO])[0]['seen_ids'])
