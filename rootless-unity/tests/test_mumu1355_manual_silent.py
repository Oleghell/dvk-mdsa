"""/num excludes open-dialog work silently, preserving all unknown outcomes."""
import threading,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import test_inbox_profiles as fixture
from assistant_inbox import inbox_targets
from assistant_exit_notify import notify_exit
from mumu_store import SharedStore
from mumu_peer_policy import manual_block,without_manual_blocks,manually_blocked
from test_guided_chain import WHO,GREETING

class ManualSilence(unittest.TestCase):
    setUp=fixture.Base.setUp
    journal=fixture.Base.journal
    chain=fixture.Base.chain
    sender=fixture.Base.sender
    walk=fixture.Base.walk
    def shared(self):
        self.store=SharedStore(self.store.path,Path(self.tmp.name)/'old',device_port=5557)
        self.other=SharedStore(self.store.path,Path(self.tmp.name)/'old',device_port=5563)
        self.journal()
    def block(self):return manual_block(WHO['peer'],self.store.path)
    def test_manual_queue_exclusion_on_all_ports_accounts_and_installs(self):
        self.shared();self.journal(fixture.OTHER);chain=self.chain()
        self.assertTrue(self.block())
        self.assertEqual(inbox_targets(chain),( [],[dict(fixture.OTHER,chat='-1')] ))
        self.other.reserve(dict(attempt=1,account='101',peer='202',chat='-1',variant=0),'Synthetic',approved=True)
        from assistant_inbox import InboxChain
        InboxChain(self.other)
        with self.other.connection() as db:
            db.execute("INSERT INTO guided_bindings VALUES('101','200','400','hash')")
        from assistant_inbox import InboxChain
        self.assertNotIn('200',[x['peer'] for group in inbox_targets(InboxChain(self.other)) for x in group])
        self.assertFalse(manually_blocked(self.store,fixture.OTHER))
        a=SharedStore(self.store.path,device_port=5567,installation_id='a'*32)
        self.assertTrue(manually_blocked(a,dict(account='999',peer='200',chat='900')))
    def test_repeated_passes_do_not_open_read_send_or_notify(self):
        self.shared();self.block();notify=MagicMock();photo=MagicMock()
        for _ in range(3):
            out=self.walk([],[],exit_notifier=notify,exit_photo=photo)
            self.assertEqual(out['status'],'inbox-empty');self.assertEqual(out['dialogs_opened'],0)
            self.nav.assert_not_called();self.reader.assert_not_called()
        notify.assert_not_called();photo.assert_not_called();self.assertFalse(self.sent)
    def test_command_during_open_only_verified_back_no_read_no_notice(self):
        self.shared();notify=MagicMock();photo=MagicMock();opened=[]
        def nav(operation,*args,**kwargs):
            opened.append(operation)
            if operation=='open':self.block();return fixture.nav('opened',WHO)
            if operation=='back':return fixture.nav('returned',WHO)
            return fixture.nav('search-ready')
        import assistant_inbox as inbox
        reader=MagicMock();sender=MagicMock();chain=self.chain()
        out=inbox.walk(self.settings,self.stop,self.approve,lambda _:None,chain,navigator=nav,
                       reader=reader,sender=sender,exit_notifier=notify,exit_photo=photo)
        self.assertEqual(out['status'],'inbox-completed');self.assertEqual(opened,['open','back','return'])
        reader.assert_not_called();sender.assert_not_called();notify.assert_not_called();photo.assert_not_called()
        self.assertEqual(inbox_targets(chain),([],[]))
    def test_command_during_read_no_draft_no_screenshot_or_telegram(self):
        self.shared();chain=self.chain();notify=MagicMock();photo=MagicMock()
        def read(*args,**kwargs):self.block();return fixture.snap(fixture.msg(1002,'Привет'))
        with patch.object(chain,'proposal',side_effect=AssertionError('No draft for /num')):
            import assistant_inbox as inbox
            route=iter([fixture.nav('opened',WHO),fixture.nav('returned',WHO),fixture.nav('search-ready')])
            sender=MagicMock()
            out=inbox.walk(self.settings,self.stop,self.approve,lambda _:None,chain,navigator=lambda *a,**k:next(route),
                           reader=read,sender=sender,exit_notifier=notify,exit_photo=photo,pause=lambda _:False)
        self.assertEqual(out['status'],'inbox-completed');notify.assert_not_called();photo.assert_not_called();sender.assert_not_called()
        self.assertEqual(inbox_targets(chain),([],[]))
    def test_exit_notice_suppressed_before_journal_credentials_or_photo(self):
        self.shared();chain=self.chain();self.block();sender=MagicMock();photo_sender=MagicMock()
        for reason in ('peer-contact-blocked','send-outcome-unknown','manual-review'):
            out=notify_exit(chain,WHO,dict(reason=reason),sender=sender,photo=b'not-a-png',photo_sender=photo_sender)
            self.assertEqual(out['notification'],'manual-block-suppressed')
        sender.assert_not_called();photo_sender.assert_not_called()
        with self.store.read_connection() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='chain_exit_notices'").fetchone())
    def test_command_also_silences_existing_contact_ban_without_overwriting_it(self):
        self.shared();chain=self.chain()
        with self.other.connection() as db:self.other.record_peer_outcome(db,WHO,'contact-received')
        self.assertFalse(manually_blocked(self.store,WHO));self.assertFalse(self.block())
        self.assertTrue(manually_blocked(self.store,WHO));self.assertEqual(inbox_targets(chain),([],[]))
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT reason FROM mumu_peer_blocks WHERE peer=?',('200',)).fetchone(),('contact-received',))
    def test_unknown_send_journals_are_not_reset_by_silence(self):
        self.shared();chain=self.chain()
        with self.store.connection() as db:
            db.execute("INSERT INTO chain_actions VALUES('300','question','1002','hash','reserved-unknown')")
            before=db.execute('SELECT * FROM manual_actions').fetchall()
        self.block();self.assertEqual(inbox_targets(chain),([],[]))
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT * FROM manual_actions').fetchall(),before)
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchall(),[('reserved-unknown',)])
    def test_nonmanual_contact_and_refusal_policy_unchanged(self):
        self.shared();chain=self.chain()
        with self.other.connection() as db:self.other.record_peer_outcome(db,WHO,'contact-refused')
        self.assertFalse(manually_blocked(self.store,WHO));self.assertEqual(without_manual_blocks(self.store,[WHO]),[WHO])
        self.assertTrue(any(x['peer']=='200' for group in inbox_targets(chain) for x in group))
    def test_notice_rechecks_manual_deny_before_network_send(self):
        self.shared();chain=self.chain();sender=MagicMock()
        with patch('mumu_peer_policy.manually_blocked',side_effect=[False,True]):
            out=notify_exit(chain,WHO,dict(reason='peer-contact-blocked'),sender=sender)
        self.assertEqual(out['notification'],'manual-block-suppressed');sender.assert_not_called()

if __name__=='__main__':unittest.main()
