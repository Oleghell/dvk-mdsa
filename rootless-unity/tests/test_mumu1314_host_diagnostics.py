"""No exception strings, SQL or paths may enter cloud diagnostics."""
import json,sqlite3,unittest
from unittest.mock import patch
from assistant_store import StateError
from assistant_failure import category,CODES
import assistant_error_notify as notify
from test_inbox_profiles import Base,WHO,nav,msg,snap

class HostCategories(unittest.TestCase):
    def test_sqlite_codes_not_message_matching(self):
        for code,name in [(sqlite3.SQLITE_BUSY,'journal-busy'),(sqlite3.SQLITE_LOCKED,'journal-locked'),
            (sqlite3.SQLITE_READONLY,'journal-readonly'),(sqlite3.SQLITE_FULL,'journal-storage-full'),
            (sqlite3.SQLITE_CORRUPT,'journal-corrupt')]:
            error=sqlite3.OperationalError('PRIVATE SQL KEY PATH');error.sqlite_errorcode=code
            self.assertEqual(category(error),name)
        self.assertEqual(category(sqlite3.OperationalError('database is locked PRIVATE')),'journal-error')
    def test_contract_state_transport_and_unknown_failures_closed(self):
        for error,expected in [(KeyError('PRIVATE'),'internal-contract-error'),
            (StateError('PRIVATE'),'state-check-failed'),(TimeoutError('PRIVATE'),'device-timeout'),
            (ValueError('PRIVATE'),'validation-failed'),(RuntimeError('PRIVATE'),'internal-error')]:
            self.assertEqual(category(error),expected);self.assertIn(category(error),CODES)
    def test_native_profile_codes_and_chat_prefix_no_longer_silently_lost(self):
        for code in ('selection-limit','selection-unavailable','history-invalid','input-disabled','send-already-attempted',
            'chat-check-stopped','navigation-check-stopped','chat-groq-draft-unavailable'):
            out=json.loads(notify.diagnostic_json(dict(status='stopped',last_pass=dict(reason=code,error=code))))
            self.assertEqual(out['diagnostic']['last_pass']['reason'],code)
            self.assertEqual(out['diagnostic']['last_pass']['error'],code)
    def test_unknown_failure_explicitly_redacted_not_silently_dropped(self):
        out=notify.diagnostic_json(dict(status='stopped',reason='PRIVATE',host_failure='journal-busy',host_checkpoint='profile-journal'))
        value=json.loads(out)['diagnostic'];self.assertEqual(value['reason'],'unrecognized-diagnostic-code')
        self.assertEqual(value['host_failure'],'journal-busy');self.assertEqual(value['host_checkpoint'],'profile-journal')
        self.assertNotIn(b'PRIVATE',out)

class InboxHostEvidence(Base):
    def test_host_contract_failure_before_read_is_categorized_without_resend(self):
        self.journal()
        with patch('assistant_legacy_recovery.reserve_probe',side_effect=KeyError('PRIVATE')):
            out=self.walk([nav('opened',WHO)],[snap(msg(1002,'Привет'))])
        self.assertEqual(out['status'],'inbox-stopped');self.assertEqual(out['host_failure'],'internal-contract-error')
        self.assertFalse(self.sent);self.assertNotIn('PRIVATE',json.dumps(out))

class ProfileHostEvidence(Base):
    def test_journal_failure_after_native_result_is_reported_not_replayed(self):
        import assistant_profiles as profiles
        from test_inbox_profiles import Config,cycle_result
        profiles.Session(self.store).set('city','Псков')
        error=sqlite3.OperationalError('PRIVATE SQL PATH');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        native=cycle_result(send_attempted=False,send_handler_returned=False)
        from unittest.mock import MagicMock
        cycle=MagicMock(return_value=native)
        with patch.object(profiles.Session,'set',side_effect=error):
            out=profiles.walk(self.settings,self.stop,self.approve,lambda _:None,self.store,cycle=cycle,config=Config(),limit=1)
        self.assertEqual(out['status'],'profiles-stopped');self.assertEqual(out['host_failure'],'journal-busy')
        self.assertEqual(out['host_checkpoint'],'profile-journal');self.assertEqual(cycle.call_count,1)
        data=notify.diagnostic_json(out);self.assertIn(b'journal-busy',data);self.assertNotIn(b'PRIVATE',data)
