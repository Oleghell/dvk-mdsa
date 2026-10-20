"""One automatic city change after visible exhaustion; never a messaging loop."""
import secrets

import assistant_preview as preview
import search_city
from assistant_config import load


class History:
    def __init__(self, store):
        self.store = store

    def used(self, cities):
        allowed = {search_city.normalize_city(city): city for city in search_city.check_cities(cities)}
        with self.store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS city_rotation_used(city TEXT PRIMARY KEY)')
            rows = db.execute('SELECT city FROM city_rotation_used').fetchall()
        if len(rows) > 10000:
            raise ValueError('City history is too large')
        return [allowed[row[0]] for row in rows if row[0] in allowed]

    def record(self, cities, value):
        # Consume only a strictly checked successful city result.
        search_city.validate_next(value, cities)
        navigation = value['navigation']
        allowed = {search_city.normalize_city(city): city for city in search_city.check_cities(cities)}
        selected = search_city.normalize_city(navigation['city_selected_name'])
        previous = navigation['city_previous_name']
        if (navigation['stage'] != 'navigation-ready' or navigation['city_verified'] is not True
                or navigation['online_verified'] is not True or selected not in allowed
                or type(navigation['city_round_reset']) is not bool):
            raise ValueError('Unverified city outcome')
        names = [selected]
        if previous is not None:
            previous = search_city.normalize_city(previous)
            if previous not in allowed or previous == selected:
                raise ValueError('Invalid previous city')
            names.append(previous)
        with self.store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS city_rotation_used(city TEXT PRIMARY KEY)')
            if navigation['city_round_reset']:
                db.execute('DELETE FROM city_rotation_used')
            for name in names:
                db.execute('INSERT OR IGNORE INTO city_rotation_used(city) VALUES(?)', (name,))


def after_exhaustion(executable, folder, result, store, cancelled, progress):
    if (result['status'] != 'preview-exhausted' or result['reason'] != 'visible-exhausted'
            or result['profile_may_remain_open'] or result['chats_opened'] != 0 or result['messages_sent'] != 0):
        return result
    change = dict(status='stopped', reason='not-started', selected_city=None, online_verified=False)
    result['city_change'] = change
    if cancelled():
        change.update(status='cancelled', reason='cancelled')
        return result
    try:
        cities = search_city.check_cities(load().cities)
        history = History(store)
        used = history.used(cities)
        secrets.SystemRandom().shuffle(cities)
        progress('Новых видимых анкет нет. Выбираю другой случайный город и включаю «Только онлайн».')
        if cancelled():
            change.update(status='cancelled', reason='cancelled')
            return result
        value = search_city._capture_next(executable, folder, cities, used, cancelled)
        search_city.validate_next(value, cities)
        n = value['navigation']
        if n['stage'] != 'navigation-ready':
            change['reason'] = 'no-alternative' if n['error'] == 'city-no-alternative' else 'city-not-verified'
            return result
        history.record(cities, value)
        change.update(status='changed', reason='verified', selected_city=n['city_selected_name'], online_verified=True)
    except Exception:
        # No retry or second city when applying/transport/history has an unknown outcome.
        change.update(status='cancelled' if cancelled() else 'unknown',
                      reason='cancelled' if cancelled() else 'city-not-verified')
    return result


def run(executable, folder, cancelled=lambda: False, progress=lambda text: None, *, store=None):
    return preview.run(executable, folder, cancelled, progress, store=store,
                       after_preview=lambda result, journal: after_exhaustion(
                           executable, folder, result, journal, cancelled, progress))


def status_text(result):
    text = preview.status_text(result)
    change = result.get('city_change')
    if change is None:
        return text
    if change['status'] == 'changed':
        return (f"Новых видимых анкет не осталось. Проверено: {result['checked']}/5. "
                f"Выбран следующий город: {change['selected_city']}. «Только онлайн» включён. "
                'Чаты не открывались, сообщения не отправлялись. Для просмотра нового города нажми кнопку ещё раз.')
    if change['reason'] == 'no-alternative':
        return text + ' В списке нет другого города. Добавь ещё один город в config/cities.json.'
    return text + ' Смена города не подтверждена. Повтора нет; проверь экран и настройки вручную.'