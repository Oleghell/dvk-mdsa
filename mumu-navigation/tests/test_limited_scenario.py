import unittest
from unittest.mock import patch
from limited_scenario import (
    CITIES, REQUESTED_GREETINGS, LimitedPolicy, choose_city,
    choose_requested_greeting, TYPING_WORDS_PER_MINUTE, SECONDS_PER_CHARACTER,
)

class LimitedScenarioTests(unittest.TestCase):
    def test_exactly_thirty_unique_cities(self):
        self.assertEqual(len(CITIES),30);self.assertEqual(len(set(CITIES)),30)
        self.assertEqual(CITIES[0],'Нальчик');self.assertEqual(CITIES[-1],'Каменск-Уральский')
        self.assertIn('Королёв',CITIES);self.assertIn('Петропавловск-Камчатский',CITIES)

    def test_exactly_thirty_unique_greetings(self):
        self.assertEqual(len(REQUESTED_GREETINGS),30)
        self.assertEqual(len(set(REQUESTED_GREETINGS)),30)
        self.assertEqual(REQUESTED_GREETINGS[0],'Привет 🙂')
        self.assertEqual(REQUESTED_GREETINGS[-1],'Здравствуй 💐')
        self.assertIn('Привет, красавица 💫',REQUESTED_GREETINGS)

    def test_five_is_fixed_not_background_restart(self):
        p=LimitedPolicy()
        self.assertEqual(p.max_visited_profiles,5)
        self.assertFalse(p.automatic_restart);self.assertTrue(p.stop_after_limit)
        for n in [0,1,4,6,True,'5']:
            with self.subTest(n=n),self.assertRaises(ValueError):LimitedPolicy(n)

    def test_gui_defaults_new_run_to_five_without_changing_active_run(self):
        from pathlib import Path
        import ast
        source=(Path(__file__).resolve().parents[1]/'mumu_bridge.py').read_text()
        tree=ast.parse(source)
        start=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='start_test')
        ask=next(n for n in ast.walk(start) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='askinteger')
        kw={k.arg:k.value for k in ask.keywords}
        self.assertEqual(kw['initialvalue'].id,'DEFAULT_NEW_PROFILE_LIMIT')
        self.assertEqual(kw['maxvalue'].value,5)
        self.assertIn("if info['state']=='active':",ast.get_source_segment(source,start))
        self.assertNotIn('выберите 4',ast.get_source_segment(source,start))

    def test_cannot_disable_stopping(self):
        for kw in [{'automatic_restart':True},{'stop_after_limit':False},
                   {'automatic_restart':0},{'stop_after_limit':1}]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):LimitedPolicy(**kw)

    def test_strictly_less_than_fifty_friends(self):
        p=LimitedPolicy()
        for n in [0,1,49]:self.assertTrue(p.friends_eligible(n))
        for n in [50,51,-1,None,True,'49',49.0,'не видно']:
            with self.subTest(n=n):self.assertFalse(p.friends_eligible(n))

    def test_stop_on_fifth_visit_including_skips(self):
        p=LimitedPolicy()
        for n in range(5):self.assertTrue(p.can_open_next(n,active=True,previous_visit_returned=True,uncertain=False))
        for n in [5,6,-1,True,None,'4']:
            with self.subTest(n=n):self.assertFalse(p.can_open_next(n,active=True,previous_visit_returned=True,uncertain=False))

    def test_unknown_or_unfinished_or_inactive_blocks_next(self):
        p=LimitedPolicy()
        for active,returned,uncertain in [(False,True,False),(True,False,False),(True,True,True),('yes',True,False)]:
            self.assertFalse(p.can_open_next(0,active=active,previous_visit_returned=returned,uncertain=uncertain))

    def test_city_change_excludes_current_and_tried(self):
        with patch('limited_scenario.secrets.choice',side_effect=lambda xs:xs[0]) as pick:
            result=choose_city(current=CITIES[0],excluded=CITIES[1:4])
            self.assertEqual(result,CITIES[4])
            self.assertNotIn(CITIES[0],pick.call_args.args[0])
            for city in CITIES[1:4]:self.assertNotIn(city,pick.call_args.args[0])

    def test_exhausted_cities_stop_not_cycle_forever(self):
        with patch('limited_scenario.secrets.choice') as pick:
            with self.assertRaises(ValueError):choose_city(excluded=CITIES)
            pick.assert_not_called()

    def test_greeting_only_from_supplied_list(self):
        with patch('limited_scenario.secrets.choice',side_effect=lambda xs:xs[-1]) as pick:
            self.assertEqual(choose_requested_greeting(),'Здравствуй 💐')
            pick.assert_called_once_with(REQUESTED_GREETINGS)

    def test_typing_pace_is_explicit_five_character_word_convention(self):
        self.assertEqual(TYPING_WORDS_PER_MINUTE,35)
        self.assertAlmostEqual(SECONDS_PER_CHARACTER,60/175)

if __name__=='__main__':unittest.main()
