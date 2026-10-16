"""Text-only synthetic city-result observations; no real profiles or device I/O."""
import unittest
from city_search import CityRow, resolve_city

CITY='Нальчик'
REGION='Кабардино-Балкарская Республика'
SUBTITLE=REGION+' · Россия'

class CitySearchTests(unittest.TestCase):
    def decide(self,rows,**kwargs):
        args=dict(city=CITY,region=REGION,query=CITY,results_ready=True,labels_complete=True)
        args.update(kwargs)
        return resolve_city(rows=rows,**args)

    def test_one_exact_result_is_selected_even_at_index_zero(self):
        d=self.decide([CityRow(CITY,SUBTITLE)])
        self.assertTrue(d.selectable);self.assertEqual(d.index,0)
        self.assertEqual(d.reason,'unique_exact_match')

    def test_two_identical_name_region_results_are_ambiguous(self):
        # Distinct visible rows cannot be assumed to be the same location ID.
        d=self.decide([CityRow(CITY,SUBTITLE),CityRow(CITY,SUBTITLE),
                       CityRow(CITY,'Московская область · Россия')])
        self.assertFalse(d.selectable);self.assertEqual(d.reason,'ambiguous_exact_matches')

    def test_moscow_region_result_not_a_match(self):
        d=self.decide([CityRow(CITY,'Московская область · Россия')])
        self.assertFalse(d.selectable)

    def test_matching_substring_is_not_the_city_name(self):
        for text in ['Учебного хозяйства Нальчикского сельскохозяйственного института',
                     'Нальчикский район','Нальчик-2']:
            with self.subTest(text=text):self.assertFalse(self.decide([CityRow(text,SUBTITLE)]).selectable)

    def test_district_in_subtitle_not_an_exact_region(self):
        d=self.decide([CityRow(CITY,'Черкесский район · '+SUBTITLE)])
        self.assertFalse(d.selectable)

    def test_correct_result_must_not_be_assumed_first(self):
        d=self.decide([CityRow(CITY,'Московская область · Россия'),CityRow(CITY,SUBTITLE)])
        self.assertEqual(d.index,1)

    def test_no_result_stops_selection(self):
        self.assertFalse(self.decide([]).selectable)

    def test_wrong_query_never_selects_stale_result(self):
        d=self.decide([CityRow(CITY,SUBTITLE)],query='Таганрог')
        self.assertEqual(d.reason,'query_mismatch');self.assertFalse(d.selectable)

    def test_loading_incomplete_or_unknown_flags_never_select(self):
        for kw in [dict(results_ready=False),dict(results_ready=1),dict(results_ready=None),
                   dict(labels_complete=False),dict(labels_complete='true')]:
            with self.subTest(kw=kw):self.assertFalse(self.decide([CityRow(CITY,SUBTITLE)],**kw).selectable)

    def test_missing_or_clipped_target_is_not_guessed(self):
        for kw in [dict(region=None),dict(region=''),dict(region='Кабардино…'),
                   dict(city=None),dict(query='Наль...')]:
            with self.subTest(kw=kw):self.assertFalse(self.decide([CityRow(CITY,SUBTITLE)],**kw).selectable)

    def test_clipped_row_could_hide_a_duplicate_and_blocks_snapshot(self):
        for row in [CityRow(CITY,'Черкесский район · Кабардино-Балкарская Респ…'),
                    CityRow('Учебного хозяйства…',SUBTITLE),
                    CityRow(CITY,SUBTITLE,labels_complete=False),CityRow('',SUBTITLE)]:
            with self.subTest(row=row):
                self.assertFalse(self.decide([CityRow(CITY,SUBTITLE),row]).selectable)

    def test_wrong_country_not_selected(self):
        for country in ['Украина','Россия / другая страна','']:
            with self.subTest(country=country):
                self.assertFalse(self.decide([CityRow(CITY,REGION+' · '+country)]).selectable)

    def test_unlisted_city_not_accepted(self):
        d=self.decide([CityRow('Волжский','Волгоградская область · Россия')],
                      city='Волжский',region='Волгоградская область',query='Волжский')
        self.assertEqual(d.reason,'city_not_allowlisted')

    def test_unicode_whitespace_and_case_not_fuzzy_substrings(self):
        d=self.decide([CityRow('  НАЛЬЧИК ', 'Кабардино-Балкарская\u00a0Республика · РОССИЯ')])
        self.assertTrue(d.selectable)

    def test_unsupported_input_never_selects(self):
        for rows in [None,'Нальчик',[{}],[CityRow(CITY,SUBTITLE)]*201]:
            with self.subTest(kind=type(rows).__name__):self.assertFalse(self.decide(rows).selectable)

if __name__=='__main__':unittest.main()
