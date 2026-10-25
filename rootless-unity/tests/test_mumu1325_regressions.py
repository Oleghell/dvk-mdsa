"""New reports: available app choice, read budgets, durable cross-port peer IDs."""
from contextlib import closing
import json,sqlite3,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import MagicMock
import assistant_contact_clarify as clarify
import assistant_contact_intent as intent
import assistant_history_wait as history
from assistant_error_notify import diagnostic_json
from one_chat_device import ReadStopped
from mumu_store import SharedStore,SharedPeerClaimed
from test_guided_chain import snapshot,WHO
import test_mumu1323_alternatives_statistics as alternatives
from test_inbox_profiles import Base,nav,snap,msg
from test_mumu_multi import pending

class Choices(alternatives.Alternatives):
    def test_supplied_available_choices_do_not_decline_or_call_ai(self):
        for phrase,text in [('Ватсапп',clarify.WHATSAPP_TEXT),('Ватсап',clarify.WHATSAPP_TEXT),
            ('У меня их нет. Тока макс',clarify.MAX_TEXT),('Тока MAX',clarify.MAX_TEXT),
            ('Ватсап лучше телеграм у меня не работает',clarify.WHATSAPP_TEXT),
            ('Ватсапп лучше, телеграм у меня не работает',clarify.WHATSAPP_TEXT)]:
            with self.subTest(phrase=phrase):
                c,store,h=self.chain();sample=snapshot(*h,(phrase,False))
                stage,a=c.proposal(sample)
                self.assertEqual((stage,a),('pending-clarify',dict(kind='clarify',text=text)))
                self.assertEqual(c.proposal(sample),(stage,a));c.responder.assert_not_called()
                c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
                h.extend([(phrase,False),(text,True)])
                self.assertEqual(c.proposal(snapshot(*h)),('wait-contact',None))
                self.assertEqual(c.proposal(snapshot(*h,('Мой номер +79991234567',False))),('done',None))
    def test_explicit_privacy_and_stay_still_win_over_app_choice(self):
        for rows in [('Ватсапп','Номер не дам'),('Тока макс','Мне удобнее здесь'),
                     ('Телеграм у меня не работает','Ватсап тоже не работает')]:
            c,store,h=self.chain()
            self.assertEqual(c.proposal(snapshot(*h,*[(v,False) for v in rows])),('declined',None))
            c.responder.assert_not_called()
    def test_new_aliases_do_not_turn_person_question_or_quote_into_choice(self):
        for phrase in ('> Ватсапп\nНе хочу переходить','Ватсапп не работает','У меня нет MAX',
                       'Тока Макс сказал привет','Ватсап лучше?'):
            self.assertIsNone(intent.available_alternative([dict(text=phrase)]))
            self.assertFalse(intent.max_selected([dict(text=phrase)]))


def budget(**changes):
    value=dict(stage='navigation-stopped',metadata_checkpoint='ready',read_checkpoint='identity',
        wait_reason='none',frames=6,managed_calls=510,scalar_checkpoint='peer-id',message_slot=5,
        identity_checkpoint='initial-ids',message_direction='not-own',message_kind='text',scalar_state='not-read')
    value.update(changes);return ReadStopped('frame-budget',value)

class InitialReadBudget(Base):
    def test_report_shape_retries_only_read_and_then_answers(self):
        self.journal();hello=msg(1002,'Привет');q=msg(1003,'Как дела?)',True)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
            [budget(),snap(hello),snap(hello),snap(hello,q)])
        self.assertEqual(out['status'],'inbox-completed');self.assertEqual(self.sent,['Как дела?)'])
        self.assertEqual(out['last_chat_diagnostics']['read_retries'],1)
        self.assertEqual(self.nav.call_count,3)
    def test_persistent_budget_defers_via_verified_back_without_send(self):
        self.journal()
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[budget() for _ in range(4)])
        self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['history_deferred'],1)
        self.assertFalse(self.sent);self.assertEqual(self.reader.call_count,4)
    def test_identity_failure_and_missing_evidence_not_classified_as_budget(self):
        good=dict(error='frame-budget',**budget().diagnostic)
        self.assertTrue(history.verified_read_budget(good))
        for changes in (dict(error='identity-not-bound'),dict(error='identity-changed'),dict(scalar_state='zero'),
            dict(scalar_state='negative'),dict(identity_checkpoint='saved-binding'),dict(metadata_checkpoint='base')):
            self.assertFalse(history.verified_read_budget(dict(good,**changes)))

class GlobalPeer(unittest.TestCase):
    def test_every_old_namespace_is_imported_with_unknowns_untouched(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'db';legacy=Path(t)/'old'
            for port in (5563,5557,5559,5561,5565):
                s=SharedStore(path,legacy,device_port=port)
                s.reserve(pending(peer=str(port+100),account=str(port+200)),'Hi',approved=True)
            with closing(sqlite3.connect(path,isolation_level=None)) as db:
                db.execute('DELETE FROM mumu_peer_claims')
                old={row[0]:db.execute('SELECT * FROM '+row[0]).fetchall() for row in db.execute("SELECT name FROM sqlite_master WHERE name='manual_actions' OR name GLOB 'm[0-9][0-9][0-9][0-9]__manual_actions'").fetchall()}
            fresh=SharedStore(path,legacy,device_port=5559)
            for port in (5563,5557,5559,5561,5565):
                person=pending(peer=str(port+100),account='999')
                self.assertTrue(fresh.peer_claimed(person))
                with self.assertRaises(SharedPeerClaimed):fresh.reserve(person,'Hello',approved=True)
            with closing(sqlite3.connect(path,isolation_level=None)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM mumu_peer_claims').fetchone()[0],5)
                for table,rows in old.items():self.assertEqual(db.execute('SELECT * FROM '+table).fetchall(),rows)
    def test_atomic_cross_account_claim_existing_contract(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'db';legacy=Path(t)/'old'
            stores=[SharedStore(path,legacy,device_port=p) for p in (5557,5563)]
            barrier=threading.Barrier(2);results=[]
            def claim(s,account):
                barrier.wait()
                try:s.reserve(pending(account=account),'Hi',approved=True);results.append('won')
                except SharedPeerClaimed:results.append('blocked')
            ts=[threading.Thread(target=claim,args=(s,str(i+100))) for i,s in enumerate(stores)]
            for th in ts:th.start()
            for th in ts:th.join(10);self.assertFalse(th.is_alive())
            self.assertEqual(sorted(results),['blocked','won'])

class Diagnostics(unittest.TestCase):
    def test_native_no_send_diagnostic_survives_but_secrets_do_not(self):
        source=dict(last_chat_diagnostics=dict(last_send_failure='submission-snapshot-changed',
            submission_attempted=False,submission_returned=False,body='PRIVATE',key='PRIVATE'))
        raw=diagnostic_json(source);self.assertNotIn(b'PRIVATE',raw)
        d=json.loads(raw)['diagnostic']['last_chat_diagnostics']
        self.assertEqual(d['last_send_failure'],'submission-snapshot-changed')
        self.assertIs(d['submission_attempted'],False);self.assertIs(d['submission_returned'],False)


class RecoveryEvidence(unittest.TestCase):
    def test_current_city_and_initial_identity_budget_can_recover_not_stale_completed(self):
        from mumu_recovery import recoverable
        city=dict(stage='navigation-stopped',error='frame-budget',city_select_attempted=True,city_select_completed=True,
                  apply_attempted=False,apply_completed=False)
        profiles=dict(status='profiles-stopped',reason='city-not-verified',host_failure='state-check-failed',
                      host_checkpoint='city-navigation',last_city_navigation=city)
        report=dict(status='stopped',reason='profile-pass-stopped',last_profile_run=dict(status='stopped',profiles=profiles))
        self.assertTrue(recoverable(report))
        city['error']='identity-changed';self.assertFalse(recoverable(report))
        city['error']='frame-budget'
        profiles['host_checkpoint']='profile-verify';profiles['reason']='profile-check-stopped'
        self.assertFalse(recoverable(report)) # old city evidence must not hide another host fault
        profiles['status']='profiles-completed';self.assertFalse(recoverable(report))
    def test_profile_same_pinned_card_observation_is_bounded_and_never_reopens(self):
        import assistant_pass
        source=assistant_pass.build('Привет')
        start=source.index("   if(n.phase==='check-chat'){")
        branch=source[start:source.index("if(k!=='chat')fail('unexpected-screen');",start)]
        for guard in ("current.equals(target(state.card))",'verifyProfile(current)',
                      'n.chat_open_completed&&n.chat_verified', 'cohortPending===null&&cohortApproved===null',
                      '(state.chatTransitionWaits||0)<3'):
            self.assertIn(guard,branch)
        for action in ('call(s.startChat','call(s.chatBack','call(s.send'):
            self.assertNotIn(action,branch)
