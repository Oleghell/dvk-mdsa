"""«Старт», step 2: new profiles, friends < 50, greeting after run or per-message permission.

Each profile cycle is the existing native one-profile cycle (assistant_pass):
it opens one new visible profile, reads the friend count, opens the chat only
when friends < 50, re-checks that the history is empty and asks for an explicit
permission for ONE greeting. When the visible list is exhausted, the city is
changed to another configured city and «Только онлайн» is re-verified.
"""
from datetime import datetime, timezone
import secrets

from assistant_store import StateError
from version import VERSION
from assistant_authorization import flags

MAX_LIMIT = 20
MAX_SEARCH_CYCLES = 200
MAX_SCANNED = 200


def report(limit):
    return dict(tool_version=VERSION, mode='new-profiles-pass', status='profiles-stopped',
                reason='not-started', profile_limit=limit, profiles_checked=0, qualified_profiles=0, scan_limit=MAX_SCANNED,
                search_cycles=0, search_cycle_limit=MAX_SEARCH_CYCLES,
                skipped_friends=0, skipped_existing_chat=0, greetings_offered=0,
                greetings_sent=0, send_attempts=0, send_attempts_unknown=False, handlers_returned=0, outgoing_observed=None,
                greetings_declined=0, city_changes=0,
                current_city=None, online_verified=False, per_message_confirmation=True,
                automatic_send=False, delivery_confirmed=False, return_verified=False,
                personal_data_exported=False, device_scope='MuMu-4-only', last_error=None, last_city_navigation=None)


class Session:
    """Current search city and the time of the last check (TZ §3, §10)."""

    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS search_session(key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    def get(self, key):
        with self.store.connection() as db:
            row = db.execute('SELECT value FROM search_session WHERE key=?', (key,)).fetchone()
        return None if row is None else row[0]

    def set(self, key, value):
        with self.store.connection() as db:
            db.execute('INSERT INTO search_session VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (key, value))


def clear_history(store):
    """Forget viewed profiles and city rotation. Send journals are kept on purpose:
    they are the protection against a second greeting to the same person."""
    with store.connection() as db:
        for table in ('profile_visits', 'city_rotation_used', 'search_session'):
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                db.execute(f'DELETE FROM {table}')
    return True


def change_city(settings, stopped, store, cities, *, city_next=None, diagnostics=None):
    """Return the verified city name or raise StateError; never retries."""
    import search_city
    from assistant_rotation import History
    city_next = search_city._capture_next if city_next is None else city_next
    cities = search_city.check_cities(list(cities))
    history = History(store)
    used = history.used(cities)
    secrets.SystemRandom().shuffle(cities)
    value = city_next(settings.adb, settings.folder, cities, used, stopped.is_set)
    search_city.validate_next(value, cities)
    n = value['navigation']
    if diagnostics is not None:
        diagnostics['last_city_navigation'] = {key: n[key] for key in (
            'stage', 'error', 'phase', 'city_checkpoint', 'city_prepare',
            'city_visible_rows', 'city_total_rows', 'city_scan_samples',
            'city_matches', 'city_select_attempted', 'city_select_completed', 'city_verified',
            'open_attempted', 'open_completed', 'city_open_attempted', 'city_open_completed',
            'city_query_attempted', 'city_query_text_completed', 'city_query_completed', 'apply_attempted', 'apply_completed',
            'settings_checkpoint', 'city_transition_overruns', 'city_read_budget_retries')}
        if n['stage'] != 'navigation-ready':
            diagnostics['last_error'] = n['error']
    if n['stage'] != 'navigation-ready':
        raise StateError('city-no-alternative' if n['error'] == 'city-no-alternative' else 'city-not-verified')
    history.record(cities, value)
    return n['city_selected_name']


def walk(settings, stopped, approve, progress, store, *, cycle, city_next=None, config=None,
         limit=5, fresh_session=False, between_profiles=None):
    from assistant_config import load
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError('Invalid profile limit')
    out = report(limit)
    out.update(flags(approve))
    config = load() if config is None else config
    session = Session(store)
    out['current_city'] = session.get('city')
    cycle_pending = False
    try:
        def new_city(text):
            if stopped.is_set():
                raise StateError('cancelled')
            progress(text)
            city = change_city(settings, stopped, store, config.cities, city_next=city_next, diagnostics=out)
            out['city_changes'] += 1
            out.update(current_city=city, online_verified=True)
            session.set('city', city)
            session.set('city_changed_at', datetime.now(timezone.utc).isoformat(timespec='seconds'))

        if fresh_session or out['current_city'] is None:
            new_city('Поиск • выбираю город и «Только онлайн»')
        while out['qualified_profiles'] < limit:
            if stopped.is_set():
                raise StateError('cancelled')
            # Only between complete native cycles, on verified search; never
            # interrupt a chat/send handler or release the shared device lock.
            if between_profiles is not None:
                between_profiles()
            if out['profiles_checked'] >= MAX_SCANNED:
                raise StateError('profile-scan-limit')
            if stopped.is_set():
                raise StateError('cancelled')
            if out['search_cycles'] >= MAX_SEARCH_CYCLES:
                raise StateError('search-cycle-limit')
            greeting = config.greeting()
            progress(f'Анкеты • подходящих {out["qualified_profiles"]}/{limit} • просмотрено {out["profiles_checked"]}')
            offered = []

            def ask(pending, text, cancelled):
                offered.append(True)
                return approve('greeting', text, cancelled)

            cycle_pending = True
            out['search_cycles'] += 1
            value = cycle(settings.adb, settings.folder, greeting, ask, stopped.is_set, store=store)
            n = value['navigation']
            cycle_pending = False
            if n['send_attempted']:
                out['send_attempts'] += 1
                out['greetings_sent'] = None
            if n['send_handler_returned']:
                out['handlers_returned'] += 1
            session.set('checked_at', datetime.now(timezone.utc).isoformat(timespec='seconds'))
            if offered:
                out['greetings_offered'] += 1
            if n['error'] == 'selection-unavailable' and not n['open_attempted']:
                if out['search_cycles'] >= MAX_SEARCH_CYCLES:
                    raise StateError('search-cycle-limit')
                new_city('Поиск • анкеты закончились, меняю город')
                continue
            out['profiles_checked'] += 1
            if n['send_attempted'] and not n['send_handler_returned']:
                raise StateError('send-outcome-unknown')
            if n['send_handler_returned']:
                pass
            elif value.get('declined'):
                out['greetings_declined'] += 1
                out.update(reason='greeting-not-approved')
                raise StateError('greeting-not-approved')
            elif n['stage'] != 'navigation-ready':
                out['last_error'] = n['error'] if isinstance(n['error'], str) else 'unknown'
                raise StateError('profile-check-stopped')
            elif not n['friends_eligible']:
                out['skipped_friends'] += 1
            else:
                out['skipped_existing_chat'] += 1
            if not n['return_verified']:
                raise StateError('return-not-verified')
            if n['send_handler_returned']:
                out['qualified_profiles'] += 1
        out.update(status='profiles-completed', reason='profile-limit', return_verified=True)
    except Exception as error:
        if cycle_pending:
            out.update(send_attempts_unknown=True, greetings_sent=None)
        known = {'between-profile-inbox-stopped', 'cancelled', 'send-outcome-unknown', 'greeting-not-approved', 'profile-check-stopped',
                 'return-not-verified', 'legacy-reservation-present', 'city-no-alternative', 'city-not-verified', 'search-cycle-limit', 'profile-scan-limit'}
        reason = 'cancelled' if stopped.is_set() else (
            str(error) if isinstance(error, StateError) and str(error) in known else 'device-or-journal-check-stopped')
        status = ('profiles-cancelled' if reason == 'cancelled' else
                  'profiles-paused' if reason == 'greeting-not-approved' else 'profiles-stopped')
        out.update(status=status, reason=reason)
    return out


def run(settings, stopped, approve, progress=lambda _: None, *, store=None, cycle=None,
        city_next=None, config=None, limit=5, fresh_session=False, between_profiles=None):
    """Caller must hold the shared device lock (assistant_pass.run re-enters it)."""
    from assistant_store import Store
    if stopped.is_set():
        return dict(report(limit), status='profiles-cancelled', reason='cancelled')
    if cycle is None:
        from assistant_pass import inspect as native_cycle
        from assistant_config import check_text
        from one_chat_device import capture
        from pathlib import Path

        def cycle(executable, folder, text, ask, cancelled, *, store):
            folder = Path(folder).resolve(strict=True)
            for name in ('.dvk-ten-profile-pass.lock', '.dvk-one-greeting.lock'):
                if (folder / name).exists():
                    raise StateError('legacy-reservation-present')
            text = check_text(text)
            return capture(executable, folder, cancelled, inspector=lambda port, token, cancel, expected:
                           native_cycle(port, token, cancel, text, store, ask))
    return walk(settings, stopped, approve, progress, Store() if store is None else store,
                cycle=cycle, city_next=city_next, config=config, limit=limit,
                fresh_session=fresh_session, between_profiles=between_profiles)
