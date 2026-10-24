"""Closed native message failures: quarantine, verified back, no send replay."""
import json,unittest
import assistant_inbox as inbox
from assistant_error_notify import diagnostic_json
from one_chat_device import ReadStopped
from one_chat_probe import ERRORS as READ_ERRORS
import test_inbox_profiles as fixture
from test_inbox_profiles import WHO,OTHER,nav,msg,snap

CODES={'nonpositive-message-id':'message-id','nonpositive-message-sender-id':'message-sender-id',
       'nonpositive-message-chat-id':'message-chat-id'}
def failure(code='nonpositive-message-id',**changes):
    value=dict(error=code,stage='navigation-stopped',metadata_checkpoint='ready',read_checkpoint='last-message',
               wait_reason='none',frames=7,managed_calls=598,identity_checkpoint='recheck',
               scalar_checkpoint=CODES[code],scalar_state='negative',message_slot=0,
               message_kind='not-read',message_direction='not-read')
    value.update(changes)
    return ReadStopped(code,dict(value,private_text='PRIVATE BODY'))

class Projection(unittest.TestCase):
    def test_all_fixed_reader_codes_survive_but_arbitrary_text_does_not(self):
        for code in READ_ERRORS:
            out=json.loads(diagnostic_json(dict(last_read_failure=dict(error=code,private_text='PRIVATE'))))
            self.assertEqual(out['diagnostic']['last_read_failure']['error'],code)
            self.assertNotIn('PRIVATE',json.dumps(out))
        out=json.loads(diagnostic_json(dict(last_read_failure=dict(error='PRIVATE BODY'))))
        self.assertEqual(out['diagnostic']['last_read_failure']['error'],'unrecognized-diagnostic-code')
    def test_safe_scalar_evidence_survives_without_identity_values(self):
        e=failure();out=json.loads(diagnostic_json(dict(last_read_failure=e.diagnostic)))['diagnostic']['last_read_failure']
        for k in ('identity_checkpoint','scalar_checkpoint','scalar_state','message_slot','message_direction'):
            self.assertEqual(out[k],e.diagnostic[k])
        self.assertNotIn('PRIVATE',json.dumps(out))
    def test_no_unsafe_evidence_authorizes_skip(self):
        for changes in (dict(identity_checkpoint='saved-binding'),dict(scalar_checkpoint='chat-id'),
                        dict(scalar_state='positive'),dict(read_checkpoint='identity'),
                        dict(metadata_checkpoint='base'),dict(message_slot=128),dict(message_slot=True),
                        dict(error='unrecognized-diagnostic-code')):
            with self.subTest(changes=changes):
                e=failure(**changes)
                self.assertIsNone(inbox.isolation_reason(dict(reason='bound-chat-read-failed',diagnostics=dict(last_read_failure=e.diagnostic))))

class ReadIsolation(fixture.Base):
    def test_quarantine_and_next_chat_without_retry(self):
        for code in CODES:
            with self.subTest(code=code):
                # Independent fixture database for each code.
                case=fixture.Base();case.setUp();self.addCleanup(case.doCleanups)
                case.journal();case.journal(OTHER)
                h=msg(1002,'Привет',who=OTHER);q=msg(1003,'Как дела?)',True,who=OTHER)
                out=case.walk([nav('opened',WHO),nav('returned',WHO),nav('opened',OTHER),nav('returned',OTHER),nav('search-ready')],
                              [failure(code),snap(h,who=OTHER),snap(h,who=OTHER),snap(h,q,who=OTHER)])
                self.assertEqual(out['status'],'inbox-completed')
                self.assertEqual(out['isolated_reasons'],{code:1})
                self.assertEqual(case.sent,['Как дела?)'])
                self.assertEqual(case.reader.call_count,4)
                self.assertNotIn(WHO['peer'],[v['peer'] for v in sum(inbox.inbox_targets(case.chain()),[])])
    def test_unknown_send_kept_and_not_replayed(self):
        self.journal();h=msg(1002,'Привет')
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                      [snap(h),snap(h),failure()])
        self.assertEqual(out['status'],'inbox-completed')
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'handler-returned-unconfirmed')
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.walk([],[])['status'],'inbox-empty')
        self.assertEqual(len(self.sent),1)
    def test_changed_back_never_continues(self):
        self.journal()
        out=self.walk([nav('opened',WHO),nav('returned',OTHER)],[failure()])
        self.assertEqual(out['status'],'inbox-stopped');self.assertFalse(self.sent)
