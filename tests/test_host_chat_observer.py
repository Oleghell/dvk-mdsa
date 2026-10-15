import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from host_chat_observer import Observer

def incoming(text='TEST_A',uncertain=False):
    return {'direction':'incoming_candidate','text':text,'words':[{'text':text,'confidence':99 if not uncertain else 20,'uncertain':uncertain}]}
class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'state.sqlite3');self.obs=Observer(self.path)
    def tearDown(self):self.tmp.cleanup()
    def test_first_is_baseline_not_reply(self):
        r=self.obs.observe('ctx','frame1',[incoming()]);self.assertEqual(r['status'],'baseline_only');self.assertEqual(r['review_candidates'],[])
    def test_same_frame_suppressed(self):
        self.obs.observe('ctx','f',[incoming()]);self.assertEqual(self.obs.observe('ctx','f',[incoming()])['status'],'unchanged_visible_region')
    def test_unseen_is_only_review_candidate(self):
        self.obs.observe('ctx','f1',[incoming()]);r=self.obs.observe('ctx','f2',[incoming(),incoming('TEST_B')])
        self.assertEqual(len(r['review_candidates']),1);self.assertFalse(r['freshness_verified']);self.assertFalse(r['identity_verified'])
        self.assertFalse(r['automatic_reply_enabled']);self.assertEqual(r['messages_sent'],0)
    def test_same_text_different_frame_suppressed(self):
        self.obs.observe('ctx','f1',[incoming()]);self.assertEqual(self.obs.observe('ctx','f2',[incoming()])['review_candidates'],[])
    def test_new_context_baseline(self):
        self.obs.observe('ctx1','f1',[incoming()]);self.assertEqual(self.obs.observe('ctx2','f2',[incoming('TEST_B')])['status'],'baseline_only')
    def test_return_to_context_not_replied_again(self):
        self.obs.observe('ctx1','f1',[incoming()]);self.obs.observe('ctx2','f2',[incoming()]);self.assertEqual(self.obs.observe('ctx1','f3',[incoming()])['review_candidates'],[])
    def test_unreadable_header_blocks(self):self.assertEqual(self.obs.observe('ctx','f',[incoming()],False)['status'],'blocked_unreadable_context')
    def test_uncertain_incoming_does_not_poison_baseline(self):
        self.assertEqual(self.obs.observe('ctx','f1',[incoming(uncertain=True)])['status'],'blocked_uncertain_incoming_ocr')
        self.assertEqual(self.obs.observe('ctx','f2',[incoming()])['status'],'baseline_only')
    def test_empty_incoming_blocks(self):self.assertEqual(self.obs.observe('ctx','f',[incoming('')])['status'],'blocked_uncertain_incoming_ocr')
    def test_uncertain_outgoing_not_used_as_incoming(self):
        item=incoming(uncertain=True);item['direction']='outgoing_candidate'
        self.assertEqual(self.obs.observe('ctx','f',[item,incoming()])['status'],'baseline_only')
    def test_state_persists(self):
        self.obs.observe('ctx','f',[incoming()]);self.assertEqual(Observer(self.path).observe('ctx','f',[incoming()])['status'],'unchanged_visible_region')
    def test_duplicate_candidates_deduplicated(self):
        self.obs.observe('ctx','f1',[]);r=self.obs.observe('ctx','f2',[incoming(),incoming()]);self.assertEqual(len(r['review_candidates']),1)
    def test_context_capacity_fail_closed(self):
        with patch('host_chat_observer.MAX_CONTEXTS',1):
            self.obs.observe('ctx1','f',[]);self.assertEqual(self.obs.observe('ctx2','f',[])['status'],'blocked_state_capacity')
    def test_content_capacity_fail_closed(self):
        self.obs.observe('ctx','f',[incoming()])
        with patch('host_chat_observer.MAX_SEEN_PER_CONTEXT',1):
            self.assertEqual(self.obs.observe('ctx','f2',[incoming('TEST_B')])['status'],'blocked_state_capacity')
    def test_no_plaintext_in_state(self):
        self.obs.observe('ctx','f',[incoming('PRIVATE_SYNTHETIC_MARKER')]);self.assertNotIn(b'PRIVATE_SYNTHETIC_MARKER',Path(self.path).read_bytes())

if __name__=='__main__':unittest.main()
