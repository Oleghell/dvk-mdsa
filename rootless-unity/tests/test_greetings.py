import json,unittest
from unittest.mock import patch
import greetings as g
import chat_send_probe as p

class GreetingsTests(unittest.TestCase):
    def test_exact_catalog_shape(self):
        self.assertEqual(len(g.GREETINGS),30);self.assertEqual(len(set(g.GREETINGS)),30)
        self.assertEqual(g.GREETINGS[0],'Привет 🙂');self.assertEqual(g.GREETINGS[-1],'Здравствуй 💐')
        self.assertTrue(all(s and s==s.strip() and '\n' not in s for s in g.GREETINGS))
    def test_uniform_fresh_choice_uses_catalog_size(self):
        with patch.object(g.secrets,'randbelow',side_effect=[0,29,0]) as choose:
            self.assertEqual([g.choose_index() for _ in range(3)],[0,29,0])
            self.assertEqual(choose.call_count,3);choose.assert_called_with(30)
    def test_all_variants_are_fixed_literals_in_the_actual_script(self):
        for index,text in enumerate(g.GREETINGS):
            source=p.build(index)
            self.assertIn('Memory.allocUtf8String('+json.dumps(text)+')',source)
            self.assertIn('greeting_variant:'+str(index),source)
            self.assertIn('greetingAttempted=true',source)
    def test_invalid_variant_never_becomes_script_text(self):
        for index in (-1,30,True,None,'PRIVATE'):
            with self.assertRaises(ValueError):p.build(index)
    def test_each_transport_build_draws_again(self):
        with patch.object(p,'choose_index',side_effect=[1,29]) as choose:
            first=p.build_random();second=p.build_random()
            self.assertIn('greeting_variant:1',first);self.assertIn('greeting_variant:29',second)
            self.assertEqual(choose.call_count,2)
