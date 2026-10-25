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
MAX_READ_RECOVERIES = 3


def report(limit):
    return dict(tool_version=VERSION, mode='new-profiles-pass', status='profiles-stopped',
                reason='not-started', profile_limit=limit, profiles_checked=0, qualified_profiles=0, scan_limit=MAX_SCANNED,
                search_cycles=0, search_cycle_limit=MAX_SEARCH_CYCLES,
                skipped_friends=0, skipped_existing_chat=0, skipped_unready_chat=0, skipped_input_disabled=0,
                read_recovery_limit=MAX_READ_RECOVERIES, consecutive_read_recoveries=0, recovery_events=[], greetings_offered=0,
                greetings_sent=0, send_attempts=0, send_attempts_unknown=False, handlers_returned=0, outgoing_observed=None,
                greetings_declined=0, city_changes=0, search_budget_rotations=0, last_profile_diagnostics=None,
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
    from contextlib import nullcontext
    from assistant_lock import operation_lock
    shared=getattr(store,'mumu_shared_claims',False)
    path=store.path.parent
    if shared and store.device_port!=5563:path=path/'devices'/str(store.device_port)
    with operation_lock(path/'worker.lock') if shared else nullcontext():
        with store.connection() as db:
            for table in ('profile_visits', 'city_rotation_used', 'search_session'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    db.execute(f'DELETE FROM {table}')
            if getattr(store,'mumu_shared_claims',False):
                db.execute('DELETE FROM mumu_city_claims WHERE device=?',(str(store.device_port),))
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
    if getattr(store,'mumu_shared_claims',False):
        from mumu_cities import change
        value,cities=change(store,cities,lambda allowed,seen:city_next(settings.adb,settings.folder,allowed,seen,stopped.is_set))
    else:
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
            'settings_checkpoint', 'city_transition_overruns', 'city_read_budget_retries',
            'city_queries_started', 'city_query_text_returns', 'city_query_returns', 'city_candidates_skipped', 'city_result_waits')}
        if n['stage'] != 'navigation-ready':
            diagnostics['last_error'] = n['error']
    if n['stage'] != 'navigation-ready':
        raise StateError('city-no-alternative' if n['error'] == 'city-no-alternative' else 'city-not-verified')
    history.record(cities, value)
    return n['city_selected_name']


def walk(settings, stopped, approve, progress, store, *, cycle, city_next=None, config=None,
         limit=5, fresh_session=False, between_profiles=None, recovery_notifier=None):
    from assistant_config import load
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError('Invalid profile limit')
    out = report(limit)
    out.update(flags(approve))
    from run_preparation import checkpoint
    with checkpoint('profiles-config'):
        config = load() if config is None else config
    session = Session(store)
    out['current_city'] = session.get('city')
    cycle_pending = False
    host_checkpoint = 'profile-start'
    try:
        from assistant_pause import boundary
        def new_city(text):
            nonlocal host_checkpoint
            host_checkpoint = 'city-navigation'
            boundary(stopped)
            if stopped.is_set():
                raise StateError('cancelled')
            progress(text)
            city = change_city(settings, stopped, store, config.cities, city_next=city_next, diagnostics=out)
            out['city_changes'] += 1
            out.update(current_city=city, online_verified=True)
            host_checkpoint = 'city-journal'
            session.set('city', city)
            session.set('city_changed_at', datetime.now(timezone.utc).isoformat(timespec='seconds'))

        shared_city_ok=True
        if getattr(store,'mumu_shared_claims',False):
            from mumu_cities import owns
            shared_city_ok=owns(store,out['current_city'])
        if fresh_session or out['current_city'] is None or not shared_city_ok:
            new_city('Поиск • выбираю город и «Только онлайн»')
        while out['qualified_profiles'] < limit:
            boundary(stopped)
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
            host_checkpoint = 'profile-cycle'
            out['last_profile_diagnostics'] = None
            value = cycle(settings.adb, settings.folder, greeting, ask, stopped.is_set, store=store)
            n = value['navigation']
            # Closed public diagnostics: no identity, message body or native pointers.
            out['last_profile_diagnostics'] = {key: n[key] for key in (
                'stage', 'error', 'phase', 'frames', 'managed_calls', 'metadata_checkpoint',
                'selection_check', 'read_checkpoint', 'wait_reason', 'search_verified',
                'open_attempted', 'open_completed', 'chat_open_attempted', 'chat_open_completed',
                'send_attempted', 'send_handler_returned', 'return_verified',
                'profile_read_budget_retries', 'greeting_frame_splits', 'profile_ready_waits',
                'profile_read_skipped', 'profile_read_skip_reason', 'profile_input_enabled', 'chat_back_attempted', 'chat_back_completed',
                'chat_return_verified', 'chat_identity_verified', 'chat_return_route') if key in n}
            cycle_pending = False
            if n['send_attempted']:
                out['send_attempts'] += 1
                out['greetings_sent'] = None
            if n['send_handler_returned']:
                out['handlers_returned'] += 1
            host_checkpoint = 'profile-journal'
            session.set('checked_at', datetime.now(timezone.utc).isoformat(timespec='seconds'))
            host_checkpoint = 'profile-verify'
            if offered:
                out['greetings_offered'] += 1
            # A crowded/previously visited search may exhaust its read budget.
            # Recover ONLY before any profile/chat/send action or approval. The
            # new-city probe independently verifies search before changing it;
            # a failure there stops. Never retry a failed native/send operation.
            scan_budget = (n['error'] == 'call-limit' and n['stage'] == 'navigation-stopped'
                and n.get('cleanup_failed') is False and n.get('phase') == 'search'
                and n.get('search_verified') is True and n.get('open_attempted') is False
                and n.get('open_completed') is False
                and n.get('chat_open_attempted') is False and n.get('chat_open_completed') is False
                and n.get('send_attempted') is False and n.get('send_handler_returned') is False
                and not offered)
            if scan_budget:
                out['search_budget_rotations'] += 1
                new_city('Поиск • лимит чтения исчерпан до открытия анкеты, проверяю поиск и меняю город')
                continue
            if n['error'] == 'selection-unavailable' and not n['open_attempted']:
                if out['search_cycles'] >= MAX_SEARCH_CYCLES:
                    raise StateError('search-cycle-limit')
                new_city('Поиск • анкеты закончились, меняю город')
                continue
            out['profiles_checked'] += 1
            if n['send_attempted'] and not n['send_handler_returned']:
                raise StateError('send-outcome-unknown')
            if not n.get('profile_read_skipped'):
                out['consecutive_read_recoveries'] = 0
            if n['send_handler_returned']:
                pass
            elif value.get('declined'):
                out['greetings_declined'] += 1
                out.update(reason='greeting-not-approved')
                raise StateError('greeting-not-approved')
            elif n['stage'] != 'navigation-ready':
                out['last_error'] = n['error'] if isinstance(n['error'], str) else 'unknown'
                raise StateError('profile-check-stopped')
            elif n.get('profile_read_skipped') is True:
                # Native validation and durable record_visit completed before
                # cycle returns. No host Back, reauthorization or send replay.
                from assistant_profile_read import SKIP_REASONS
                if (n.get('profile_read_skip_reason') not in SKIP_REASONS or offered or n.get('error') != 'none' or
                    n.get('return_verified') is not True or n.get('chat_return_verified') is not True or
                    n.get('chat_back_completed') is not True or n.get('chat_identity_verified') is not True or
                    n.get('send_attempted') is not False or n.get('send_handler_returned') is not False or
                    n.get('cleanup_failed') is not False):
                    raise StateError('return-not-verified')
                if n['profile_read_skip_reason'] == 'input-disabled':
                    if n.get('profile_input_enabled') is not False:
                        raise StateError('return-not-verified')
                    out['skipped_input_disabled'] += 1
                    out['consecutive_read_recoveries'] = 0
                    progress('Анкета пропущена: ввод недоступен. Возврат проверен. Продолжаю поиск.')
                    continue
                out['skipped_unready_chat'] += 1
                out['consecutive_read_recoveries'] += 1
                event = dict(sequence=out['skipped_unready_chat'], reason=n['profile_read_skip_reason'],
                    status='recovered', action='verified-back-and-skip', return_verified=True,
                    send_attempted=False, diagnostic=dict(out['last_profile_diagnostics']),
                    continue_work=out['consecutive_read_recoveries'] < MAX_READ_RECOVERIES, notification='not-needed')
                out['recovery_events'].append(event)
                out['recovery_events'] = out['recovery_events'][-20:]
                progress('Анкета пропущена: история не готова. Возврат проверен.' + (' Продолжаю поиск.' if event['continue_work'] else ' Достигнут лимит восстановлений.'))
                if getattr(settings, 'errors_enabled', False):
                    from assistant_error_notify import notify_recovery
                    try:
                        result = (notify_recovery if recovery_notifier is None else recovery_notifier)(event)
                        event['notification'] = result if result in ('accepted','unknown','not-configured','not-needed') else 'unknown'
                    except Exception:
                        event['notification'] = 'unknown'
                if out['consecutive_read_recoveries'] >= MAX_READ_RECOVERIES:
                    raise StateError('profile-recovery-limit')
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
        from assistant_failure import category,evidence
        out.update(host_failure=category(error),host_checkpoint=host_checkpoint)
        failure=evidence(error)
        if failure:out['last_preparation_failure']=failure
        if cycle_pending and not (getattr(error,'_dvk_profile_not_executed',False) is True and not offered):
            out.update(send_attempts_unknown=True, greetings_sent=None)
        known = {'profile-recovery-limit', 'between-profile-inbox-stopped', 'cancelled', 'send-outcome-unknown', 'greeting-not-approved', 'profile-check-stopped',
                 'return-not-verified', 'legacy-reservation-present', 'city-no-alternative', 'city-not-verified', 'city-pool-exhausted', 'city-reservation-unresolved', 'search-cycle-limit', 'profile-scan-limit'}
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
            import os
            extra={}
            observer=None
            if os.environ.get('DVK_MUMU_MULTI')=='1':
                from assistant_setup_retry import SetupRetry
                observer=SetupRetry(settings,stopped,progress)
                extra['preexecution_retry']=observer
            value=capture(executable, folder, cancelled, inspector=lambda port, token, cancel, expected:
                           native_cycle(port, token, cancel, text, store, ask),**extra)
            if observer is not None:observer.completed()
            return value
    return walk(settings, stopped, approve, progress, Store() if store is None else store,
                cycle=cycle, city_next=city_next, config=config, limit=limit,
                fresh_session=fresh_session, between_profiles=between_profiles)
