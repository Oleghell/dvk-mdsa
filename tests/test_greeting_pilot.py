import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from greeting_pilot import ChatEvidence, PreparedDraft, Ledger, GREETINGS, StopPilot, run_pilot

class FakeAdapter:
    authorized_five_profile_send = True
    def __init__(self):
        self.ids = ['test-'+str(i) for i in range(12)]
        self.online = False
        self.events = []
        self.evidence_changes = {}
        self.prepared_changes = {}
        self.send_result = True
    def open_search_from_home(self): self.events.append('search')
    def open_search_settings(self): self.events.append('settings')
    def online_only_state(self): return self.online
    def set_online_only(self): self.events.append('enable_online'); self.online = True
    def confirm_search_settings(self): self.events.append('confirm')
    def visible_profile_ids(self): return self.ids
    def open_profile(self, p): self.current = p; self.events.append(('profile', p))
    def open_message_dialog(self): self.events.append('dialog')
    def inspect_chat(self):
        return replace(ChatEvidence(self.current, True, True, True, False, True), **self.evidence_changes)
    def prepare_greeting_if_still_empty(self, p, t):
        self.events.append(('draft', p, t))
        return replace(PreparedDraft(p, t, True, True, True, True), **self.prepared_changes)
    def send_once_and_verify(self, p, t): self.events.append(('send', p, t)); return self.send_result
    def return_to_grid_preserving_draft(self): self.events.append('back_preserving_draft')

class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'pilot.sqlite'
        self.ledger = Ledger(self.path)
        self.a = FakeAdapter()
    def tearDown(self): self.ledger.close(); self.temp.cleanup()
    def sends(self): return [e for e in self.a.events if isinstance(e, tuple) and e[0]=='send']
    def test_five_profiles_not_unbounded(self):
        result = run_pilot(self.a, self.ledger)
        self.assertEqual(result['visited'], 5); self.assertEqual(result['sent_verified'], 5)
        self.assertEqual(len(self.sends()), 5)
        self.assertEqual(self.a.events[:4], ['search','settings','enable_online','confirm'])
    def test_ten_distinct_variants(self): self.assertEqual(len(GREETINGS), 10); self.assertEqual(len(set(GREETINGS)), 10)
    def test_existing_drafts_messages_unknown_identity_or_history_skip(self):
        for change in ({'draft_empty':False}, {'has_messages':True}, {'history_loaded':False},
                       {'identity_verified':False}, {'explicit_empty_conversation':False}, {'profile_id':'wrong'}):
            with self.subTest(change=change):
                local = Ledger(Path(self.temp.name)/('case'+str(len(list(Path(self.temp.name).iterdir())))+'.sqlite'))
                a=FakeAdapter(); a.evidence_changes=change
                try:
                    r=run_pilot(a,local)
                    self.assertEqual(r['visited'],5); self.assertEqual(r['skipped'],5)
                    self.assertFalse(any(isinstance(e,tuple) and e[0] in ('send','draft') for e in a.events))
                finally: local.close()
    def test_no_retry_after_unknown_send_even_after_restart(self):
        self.a.send_result = None
        with self.assertRaises(StopPilot): run_pilot(self.a,self.ledger)
        self.assertEqual(len(self.sends()),1)
        other=Ledger(self.path)
        try:
            with self.assertRaises(StopPilot): run_pilot(FakeAdapter(),other)
        finally: other.close()
        self.assertEqual(len(self.sends()),1)
    def test_restart_cannot_reset_budget(self):
        run_pilot(self.a,self.ledger)
        other=Ledger(self.path)
        try: self.assertEqual(run_pilot(FakeAdapter(),other)['status'],'limit_reached')
        finally: other.close()
    def test_duplicate_profiles_not_sent_twice(self):
        self.a.ids=['same']*5
        self.assertEqual(run_pilot(self.a,self.ledger)['sent_verified'],1)
    def test_unknown_online_state_stops(self):
        self.a.online=None
        with self.assertRaises(StopPilot): run_pilot(self.a,self.ledger)
        self.assertFalse(self.sends())
    def test_already_online_not_toggled_off(self):
        self.a.online=True; run_pilot(self.a,self.ledger)
        self.assertNotIn('enable_online',self.a.events)
    def test_wrong_prepared_recipient_no_send(self):
        self.a.prepared_changes={'profile_id':'wrong'}
        with self.assertRaises(StopPilot): run_pilot(self.a,self.ledger)
        self.assertFalse(self.sends())
    def test_wrong_prepared_text_no_send(self):
        self.a.prepared_changes={'text':'unexpected'}
        with self.assertRaises(StopPilot): run_pilot(self.a,self.ledger)
        self.assertFalse(self.sends())
    def test_unverified_send_button_no_send(self):
        self.a.prepared_changes={'send_control_verified':False}
        with self.assertRaises(StopPilot): run_pilot(self.a,self.ledger)
        self.assertFalse(self.sends())
    def test_history_changed_after_draft_no_send(self):
        self.a.prepared_changes={'history_still_empty':False}
        with self.assertRaises(StopPilot): run_pilot(self.a,self.ledger)
        self.assertFalse(self.sends())
    def test_no_live_adapter_fails_closed(self):
        with self.assertRaises(StopPilot): run_pilot(object(), self.ledger)
    def test_interrupted_send_reservation_blocks_claim(self):
        key,_=self.ledger.claim('recipient')
        self.ledger.transition(key,'visited','attempted')
        with self.assertRaises(StopPilot): self.ledger.claim('another')
    def test_claim_is_atomic_between_connections(self):
        other=Ledger(self.path)
        try:
            for i in range(5): (self.ledger if i%2 else other).claim(str(i))
            with self.assertRaises(StopPilot): other.claim('six')
        finally: other.close()
    def test_ledger_does_not_store_recipient_text(self):
        self.ledger.claim('private-recipient-id')
        self.assertNotIn(b'private-recipient-id',self.path.read_bytes())

if __name__=='__main__': unittest.main()
