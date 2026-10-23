"""City counts are not capped; validation and greeting bounds remain intact."""
import json
from pathlib import Path
import tempfile
import unittest
from assistant_config import entries, ConfigError
from search_city import check_cities, build_next

class CityListSize(unittest.TestCase):
    def test_large_lists_load_and_validate(self):
        for count in (101,281,1000):
            cities = ['Город '+str(i) for i in range(count)]
            with tempfile.TemporaryDirectory() as folder:
                Path(folder,'cities.json').write_text(json.dumps({'cities':cities},ensure_ascii=False),encoding='utf-8')
                loaded=entries(folder,'cities',80)
                self.assertEqual(list(loaded),cities)
                self.assertEqual(check_cities(loaded),cities)
                self.assertIn('const cityCandidates=',build_next(loaded))

    def test_empty_duplicate_invalid_lists_still_rejected(self):
        for cities in ([],['Москва','Москва'],[' Москва'],['']):
            with tempfile.TemporaryDirectory() as folder:
                Path(folder,'cities.json').write_text(json.dumps({'cities':cities}),encoding='utf-8')
                with self.assertRaises(ConfigError):entries(folder,'cities',80)
            with self.assertRaises(ConfigError):check_cities(cities)

    def test_greeting_limit_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'greetings.json').write_text(json.dumps({'greetings':['Hello '+str(i) for i in range(101)]}),encoding='utf-8')
            with self.assertRaises(ConfigError):entries(folder,'greetings',256)
