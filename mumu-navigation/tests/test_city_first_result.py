"""Explicit user-ordered city selection; synthetic text only."""
import unittest
from city_search import CityRow, resolve_first_city_result

class FirstCityResultTests(unittest.TestCase):
    def decide(self, rows, **kw):
        args=dict(city='Нижнекамск', query='Нижнекамск', results_ready=True)
        args.update(kw)
        return resolve_first_city_result(rows=rows, **args)

    def test_selects_first(self):
        self.assertEqual(self.decide([CityRow('Нижнекамск', 'Татарстан · Россия')]).index, 0)

    def test_duplicate_labels_still_select_first(self):
        row=CityRow('Нижнекамск', 'Татарстан · Россия')
        self.assertEqual(self.decide([row,row]).index, 0)

    def test_preserves_display_order_without_region_reranking(self):
        rows=[CityRow('Первый результат', 'Первый регион'), CityRow('Нижнекамск', 'Татарстан · Россия')]
        self.assertEqual(self.decide(rows).index, 0)

    def test_lower_clipped_rows_do_not_change_first(self):
        self.assertEqual(self.decide([CityRow('Нижнекамск','Татарстан · Россия'), CityRow('СНТ…','…',False)]).index, 0)

    def test_no_results(self):
        self.assertFalse(self.decide([]).selectable)

    def test_query_mismatch(self):
        self.assertFalse(self.decide([CityRow('Нижнекамск','Россия')],query='Нальчик').selectable)

    def test_loading_and_unknown_readiness(self):
        for value in (False,None,1,'true'):
            self.assertFalse(self.decide([CityRow('Нижнекамск','Россия')],results_ready=value).selectable)

    def test_unlisted_city(self):
        self.assertFalse(self.decide([CityRow('Москва','Россия')],city='Москва',query='Москва').selectable)

    def test_bad_or_clipped_first_row(self):
        for row in ({},CityRow('','Россия'),CityRow('Нижне…','Россия'),CityRow('Нижнекамск','Россия',False)):
            self.assertFalse(self.decide([row]).selectable)

    def test_unsupported_rows(self):
        for rows in (None,'rows',[CityRow('Нижнекамск','Россия')]*201):
            self.assertFalse(self.decide(rows).selectable)

if __name__ == '__main__':
    unittest.main()
