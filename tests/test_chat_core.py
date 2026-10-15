import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from chat_core import InputError, decode, process
ROOT = Path(__file__).resolve().parents[1]

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads((ROOT/'examples/synthetic-chat.json').read_text(encoding='utf-8'))
    def test_multiline(self):
        self.assertEqual(process(self.doc)['message_candidates'][0]['text'], 'Это синтетический пример переноса')
    def test_separate_bubbles(self):
        self.assertEqual(len(process(self.doc)['message_candidates']), 2)
    def test_same_sender_not_merged(self):
        self.doc['bubbles'][1]['direction'] = 'outgoing_candidate'
        self.assertEqual(len(process(self.doc)['message_candidates']), 2)
    def test_service_exclusion_traceable(self):
        result = process(self.doc)
        self.assertEqual(result['excluded_service_source_indices'], [2])
        self.assertEqual(result['raw_lines'][2]['text'], '18:19')
    def test_outside_preserved(self):
        self.assertEqual(process(self.doc)['unassigned_source_indices'], [4])
    def test_no_bubbles_no_guess(self):
        self.doc['bubbles'] = []
        self.assertEqual(process(self.doc)['message_candidates'], [])
    def test_overlapping_ambiguous(self):
        self.doc['bubbles'].append({'id': 'overlap', 'bounds': [0, 0, 800, 600]})
        result = process(self.doc)
        self.assertTrue({0, 1, 3}.issubset(result['unassigned_source_indices']))
        self.assertTrue(all(not ({0, 1, 3} & set(c['source_indices'])) for c in result['message_candidates']))
    def test_crossing_not_assigned(self):
        self.doc['lines'][0]['bounds'] = [370, 50, 290, 30]
        self.assertIn(0, process(self.doc)['unassigned_source_indices'])
    def test_no_autocorrect(self):
        self.doc['lines'][0]['text'] = 'туг'
        self.assertTrue(process(self.doc)['message_candidates'][0]['text'].startswith('туг '))
    def test_time_message_preserved(self):
        self.doc['lines'][0]['text'] = '17:30'
        self.assertTrue(process(self.doc)['message_candidates'][0]['text'].startswith('17:30 '))
    def test_emoji_preserved(self):
        self.doc['lines'][0]['text'] = '🌷 OK ✓'
        self.assertTrue(process(self.doc)['message_candidates'][0]['text'].startswith('🌷 OK ✓ '))
    def test_identical_bubbles_not_deduplicated(self):
        self.doc['lines'][3]['text'] = 'Это синтетический пример переноса'
        self.assertEqual(len(process(self.doc)['message_candidates']), 2)
    def test_empty(self):
        self.doc['bubbles'] = []; self.doc['lines'] = []
        self.assertEqual(process(self.doc)['message_candidates'], [])
    def test_input_not_mutated(self):
        before = copy.deepcopy(self.doc); process(self.doc)
        self.assertEqual(self.doc, before)
    def test_order(self):
        self.doc['lines'][0], self.doc['lines'][1] = self.doc['lines'][1], self.doc['lines'][0]
        self.assertEqual(process(self.doc)['message_candidates'][0]['text'], 'Это синтетический пример переноса')
    def test_unknown_direction_stays_unknown(self):
        del self.doc['bubbles'][0]['direction']
        self.assertEqual(process(self.doc)['message_candidates'][0]['direction'], 'unknown')
    def test_duplicate_ids(self):
        self.doc['bubbles'][1]['id'] = 'a'
        with self.assertRaises(InputError): process(self.doc)
    def test_bad_rectangles(self):
        for box in [[-1, 0, 1, 1], [0, 0, 0, 2], [799, 0, 2, 2], [float('nan'), 0, 1, 1], [True, 0, 1, 1]]:
            with self.subTest(box=box):
                self.doc['lines'][0]['bounds'] = box
                with self.assertRaises(InputError): process(self.doc)
    def test_invalid_schema(self):
        self.doc['schema_version'] = 2
        with self.assertRaises(InputError): process(self.doc)
    def test_invalid_role(self):
        self.doc['lines'][0]['role'] = 'execute'
        with self.assertRaises(InputError): process(self.doc)
    def test_invalid_direction(self):
        self.doc['bubbles'][0]['direction'] = 'send'
        with self.assertRaises(InputError): process(self.doc)
    def test_utf8_bom(self):
        self.assertEqual(decode(b'\xef\xbb\xbf'+json.dumps(self.doc).encode()), self.doc)
    def test_invalid_json(self):
        for text in [b'{', b'\xff', b'{"x":NaN}']:
            with self.assertRaises(InputError): decode(text)
    def test_safety_flags(self):
        result = process(self.doc)
        for key in ['new_messages_detected', 'automatic_reply_enabled', 'directions_verified', 'bubble_boundaries_verified']:
            self.assertFalse(result[key])
        self.assertEqual(result['messages_sent'], 0)
    def test_cli(self):
        run = subprocess.run([sys.executable, str(ROOT/'chat_core.py')], input=json.dumps(self.doc).encode(), capture_output=True)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(json.loads(run.stdout), process(self.doc))
    def test_cli_safe_error(self):
        secret = 'EXAMPLE_NOT_A_REAL_SECRET'
        run = subprocess.run([sys.executable, str(ROOT/'chat_core.py')], input=secret.encode(), capture_output=True)
        self.assertEqual(run.returncode, 2)
        self.assertNotIn(secret.encode(), run.stderr+run.stdout)

if __name__ == '__main__': unittest.main()
