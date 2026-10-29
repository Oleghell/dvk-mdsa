"""No stale reopen, drain before search, explicit contact before AI. Synthetic only."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import test_assistant_monitor as mf
from test_inbox_profiles import Base,WHO,msg,snap,nav
from test_inbox_reactivity import ContactFlow
import assistant_reply_audit as audit
import assistant_history_wait as wait
import assistant_skip_audit as skips
import assistant_inbox as inbox
from assistant_chain import fingerprint
from shared_contact import self_shared,voluntary_batch
from mumu_store import SharedStore
from groq_reply import GroqError


class ReportedInputs(Base):
    def initial_skip(self,notice=True):
        self.journal();chain=self.chain()
        chain.responder=MagicMock(side_effect=GroqError('groq-rate-limit'))
        sample=snap(msg(1002,'Привет'))
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[sample],chain=chain,
            exit_notifier=MagicMock(return_value=True) if notice else None)
        self.assertEqual(out['status'],'inbox-completed');self.assertFalse(self.sent)
        return chain,sample,out

    def test_reported_is_not_answered_but_blocks_same_input_before_open(self):
        chain,sample,out=self.initial_skip()
        self.assertEqual(audit.pending(chain,WHO),['1002'])
        self.assertIn('1002',inbox.with_seen_ids(chain,[WHO])[0]['seen_ids'])
        self.assertEqual(wait.eligible(self.store,[WHO],[])[2],0) # New input has no leftover timer.
        result=self.walk([nav('exhausted'),nav('search-ready')],[],chain=chain)
        self.reader.assert_not_called();self.assertEqual(chain.responder.call_count,1)
        self.assertEqual(result['dialogs_opened'],0)
        self.assertIn('1002',self.nav.call_args_list[0].kwargs['allowed'][0]['seen_ids'])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT message FROM inbox_reported_inputs').fetchall(),[('1002',)])
            self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'awaiting-approval')

    def test_new_peer_message_can_be_answered_without_wait(self):
        chain,sample,_=self.initial_skip()
        chain.responder.side_effect=None;chain.responder.return_value=dict(decision='reply',text='Как настроение?')
        fresh=snap(msg(1002,'Привет'),msg(1003,'Как ты?'))
        after=copy.deepcopy(fresh);after['messages'].append(msg(1004,'Как настроение?',True))
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[fresh,fresh,after],chain=chain)
        self.assertEqual(out['submission_calls'],1);self.assertEqual(self.sent,['Как настроение?'])
        self.assertEqual(audit.pending(chain,WHO),[])
        ids=self.nav.call_args_list[0].kwargs['allowed'][0]['seen_ids']
        self.assertIn('1002',ids);self.assertNotIn('1003',ids)

    def test_disabled_telegram_does_not_create_reported_mark(self):
        chain,_,_=self.initial_skip(notice=False)
        self.assertNotIn('1002',inbox.with_seen_ids(chain,[WHO])[0]['seen_ids'])
        self.assertEqual(audit.pending(chain,WHO),['1002'])

    def test_mismatched_fingerprint_never_suppresses_pending_input(self):
        chain,_,_=self.initial_skip()
        with self.store.connection() as db:db.execute("UPDATE inbox_reported_inputs SET fingerprint='wrong'")
        self.assertNotIn('1002',inbox.with_seen_ids(chain,[WHO])[0]['seen_ids'])

    def test_table_is_separate_for_each_phone(self):
        with tempfile.TemporaryDirectory() as tmp:
            stores=[SharedStore(Path(tmp)/'shared.sqlite3',Path(tmp)/'old',device_port=p) for p in (5563,5557)]
            for i,store in enumerate(stores):
                with store.connection() as db:
                    skips.initialize(db);db.execute('INSERT INTO inbox_reported_inputs VALUES(?,?,?)',('300','1002','salt'+str(i)))
            for i,store in enumerate(stores):
                with store.connection() as db:self.assertEqual(db.execute('SELECT fingerprint FROM inbox_reported_inputs').fetchall(),[('salt'+str(i),)])


class Contacts(ContactFlow):
    def test_whatsapp_permission_phone_is_success_not_ai_failure(self):
        chain,messages=self.waiting();chain.responder=MagicMock(side_effect=AssertionError('AI must not run'))
        sample=dict(snap(*messages,msg(1006,'На ватсап можно 89991234567')),peer_name='Тест')
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[sample],chain=chain)
        self.assertEqual(out['contacts_detected'],1);self.assertEqual(out['contacts_forwarded'],1)
        self.assertEqual(out['submission_calls'],0);chain.responder.assert_not_called()
        self.assertEqual(self.notifier.call_args.args[0]['contacts'],['+79991234567'])

    def test_contact_before_old_broken_ai_draft_restore(self):
        chain,messages=self.waiting();chain.responder=MagicMock(side_effect=GroqError('groq-rate-limit'))
        first=snap(*messages,msg(1006,'Нормально'))
        with self.assertRaises(GroqError):chain.proposal(first)
        sample=dict(snap(*messages,msg(1006,'Нормально'),msg(1007,'На ватсап можно 89991234567')),peer_name='Тест')
        chain.responder.reset_mock()
        with patch('assistant_ai_drafts.restore',side_effect=AssertionError('Old draft must not block contact')):
            out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[sample],chain=chain)
        self.assertEqual(out['contacts_detected'],1);self.assertEqual(out['contacts_forwarded'],1)
        chain.responder.assert_not_called();self.assertFalse(self.sent)

    def test_saved_contact_notification_is_success_even_if_transport_disabled(self):
        chain,messages=self.waiting();notice=MagicMock(return_value=True)
        sample=dict(snap(*messages,msg(1006,'На ватсап можно 89991234567')),peer_name='Тест')
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[sample],chain=chain,notifier=None,exit_notifier=notice)
        self.assertEqual(out['contacts_detected'],1);self.assertEqual(out['contacts_forwarded'],0)
        self.assertIn('Успех: Контакт получен.',notice.call_args.args[0]);self.assertNotIn('Пропущено:',notice.call_args.args[0])
        self.assertEqual(out['contact_delivery_pending'],1)

for name in dir(ContactFlow):
    if name.startswith('test_') and name not in Contacts.__dict__:setattr(Contacts,name,None)


class ContactSafety(unittest.TestCase):
    def test_explicit_invitation_in_new_packet(self):
        text='На ватсап можно 89991234567'
        self.assertTrue(voluntary_batch([msg(1002,text)]))
        self.assertEqual(self_shared(text,requested=True),['+79991234567'])
        self.assertEqual(self_shared(text,requested=False),[])

    def test_questions_third_party_and_negatives_still_rejected(self):
        for text in ('На ватсап можно 89991234567?', 'На ватсап можно номер подруги 89991234567',
                     'Не пиши мне, на ватсап можно 89991234567','На ватсап нельзя 89991234567',
                     '> На ватсап можно 89991234567','На ватсап можно код 89991234567'):
            self.assertEqual(self_shared(text,requested=True),[],text)


class Drain(mf.Monitor):
    def test_more_than_two_productive_passes_before_search_even_after_deadline(self):
        events=[]
        def incoming(*a,**kw):
            events.append('inbox');return mf.inbox_result(dialogs_processed=1,new_incoming_messages=1) if events.count('inbox')<=5 else mf.inbox_result()
        def profiles(*a,**kw):
            events.append('search');self.stop.set();return dict(status='completed',report_name='last-run.json')
        self.inbox.side_effect=incoming
        wait=MagicMock(side_effect=AssertionError('No idle delay'))
        out=self.run_monitor(continuous=True,clock=lambda:10000,repeat=profiles,wait=wait)
        self.assertEqual(events,['inbox']*6+['search']);wait.assert_not_called()
        self.assertEqual(out['immediate_rechecks'],5)

for name in dir(mf.Monitor):
    if name.startswith('test_') and name not in Drain.__dict__:setattr(Drain,name,None)
