"""v1.3.100 («одна анкета — один просмотр», user report: «все также проходится
в холостую по новым анкетам, измени эту методику чтобы корректно работало а не
набивало просмотры анкет, такого быть не должно»).

Two methodology holes are closed and pinned here:

(1) VISITS were phone-local. The shared mumu_profile_visits table existed in
    every database since the multi-port schema but nothing ever wrote or read
    it, so a profile merely OPENED (not greeted, not claimed, not terminally
    done) was invisible to every other port: each of the 12 ports re-opened
    the same feed entry - one more view on the same girl per port - and a
    released no-send claim (1.3.81/1.3.99) returned the peer straight back
    into that re-open carousel. record_visit now commits the shared window
    row in the SAME transaction as the own-port verdict, and the pass-start
    snapshot feeds it to every port's native batchSeen pre-filter with the
    same 24-hour window as greeting claims («можно через сутки»). One anketa
    costs at most one view per day across the whole fleet; a visit is pure
    view protection and never a greeting ban (blocked()/reserve() never
    consult it).

(2) The failure bound was CONSECUTIVE only. Every clean qualification
    verdict (friends>=50, existing chat) reset consecutive_read_recoveries,
    so a saturated host could legally interleave [fail, verdict, fail,
    verdict...] and grind through up to MAX_SCANNED opened ankety in ONE pass
    with zero greetings - the reported idle walking. The pass now carries a
    TOTAL failed-open budget (MAX_FAILED_OPENS, pinned equal to
    MAX_READ_RECOVERIES) that interleaved clean cycles never reset.

Synthetic SQLite only; no device, cloud, worker process or native script."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import assistant_profiles as profiles
from assistant_store import Store
from mumu_store import SharedStore
from test_assistant import pending
from test_inbox_profiles import Config, cycle_result
from test_mumu1311_autorecovery import skipped

FRESH = datetime.now(timezone.utc).replace(microsecond=0)


def stamp_at(moment):
    return moment.strftime('%Y-%m-%d %H:%M:%S')


def visit_navigation(**extra):
    value = dict(profile_verified=True, friends_count=10, history_status='empty')
    value.update(extra)
    return value


class SharedVisitRegistry(unittest.TestCase):
    """The shared visit window: one row per opened anketa, 24 hours, no bans."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'db'
        self.old = Path(self.temp.name) / 'legacy'
        self.a = self.store(5557)
        self.b = self.store(5559)

    def store(self, port):
        return SharedStore(self.path, self.old, device_port=port)

    def shared_rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT peer,checked_at FROM mumu_profile_visits ORDER BY peer').fetchall()

    def test_record_visit_commits_the_shared_row_and_the_own_verdict_together(self):
        self.a.record_visit('300', visit_navigation())
        self.assertIn('300', self.a.visited_peers())
        self.assertIn('300', self.b.visited_peers())
        rows = self.shared_rows()
        self.assertEqual([row[0] for row in rows], ['300'])
        # The window stamp is the claim-format UTC text inside 24 hours.
        from mumu_greetings import claim_cutoff
        self.assertGreaterEqual(rows[0][1], claim_cutoff())
        # The own-port namespaced verdict row is exactly the engine's write.
        with closing(sqlite3.connect(self.path)) as db:
            own = db.execute('SELECT peer,friends_count,history_status FROM m5557__profile_visits').fetchall()
        self.assertEqual(own, [('300', 10, 'empty')])
        self.assertFalse(self.b.peer_claimed(pending(peer='300')))

    def test_unverified_profile_writes_neither_row(self):
        # A selected row alone is not proof of a view: no shared window, no
        # own verdict, nothing in any port's snapshot.
        self.a.record_visit('301', visit_navigation(profile_verified=False,
                                                    friends_count=None, history_status='unknown'))
        self.assertNotIn('301', self.a.visited_peers())
        self.assertNotIn('301', self.b.visited_peers())
        self.assertEqual(self.shared_rows(), [])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM m5557__profile_visits').fetchone()[0], 0)

    def test_expired_shared_visit_leaves_the_snapshot_but_keeps_the_audit_row(self):
        stale = stamp_at(FRESH - timedelta(hours=25))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO mumu_profile_visits(peer,checked_at) VALUES(?,?)', ('302', stale))
        self.assertNotIn('302', self.b.visited_peers())
        # «можно через сутки»: tomorrow's anketa may open her again; the row
        # itself stays as audit, exactly like an expired greeting claim.
        self.assertEqual([row[0] for row in self.shared_rows()], ['302'])

    def test_a_revisit_refreshes_the_window_stamp(self):
        stale = stamp_at(FRESH - timedelta(hours=25))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO mumu_profile_visits(peer,checked_at) VALUES(?,?)', ('303', stale))
        self.assertNotIn('303', self.b.visited_peers())
        self.b.record_visit('303', visit_navigation())
        self.assertIn('303', self.b.visited_peers())
        self.assertIn('303', self.a.visited_peers())
        refreshed = dict(self.shared_rows())['303']
        self.assertGreater(refreshed, stale)

    def test_a_shared_visit_never_blocks_a_greeting_authorization(self):
        # Pure view protection: only claims/blocks/journals deny greetings.
        self.a.record_visit('304', visit_navigation())
        for store in (self.a, self.b):
            self.assertFalse(store.peer_claimed(pending(peer='304')))
            self.assertFalse(store.peer_terminal(pending(peer='304')))
        self.assertIsNotNone(self.b.reserve(pending(peer='304'), 'Hi', approved=True))

    def test_snapshot_degrades_shared_visits_freshest_first(self):
        store = self.store(5557)
        store.VISITED_SNAPSHOT_LIMIT = 6
        own = [str(6000000000 + i) for i in range(5)]
        with closing(sqlite3.connect(self.path)) as db, db:
            for peer in own:
                db.execute('INSERT OR IGNORE INTO m5557__profile_visits(peer,friends_count,history_status,checked_at) '
                           "VALUES(?,10,'read',?)", (peer, stamp_at(FRESH)))
            # Older first, freshest last: only the newest shared visit fits.
            for offset, peer in enumerate(('7000000000', '7000000001', '7000000002')):
                db.execute('INSERT INTO mumu_profile_visits(peer,checked_at) VALUES(?,?)',
                           (peer, stamp_at(FRESH - timedelta(minutes=60 - offset))))
        visited = set(store.visited_peers())
        # Own journals always upload COMPLETE.
        self.assertTrue(all(peer in visited for peer in own))
        # Shared visits take the one remaining slot freshest-first.
        self.assertIn('7000000002', visited)
        self.assertNotIn('7000000000', visited)
        self.assertNotIn('7000000001', visited)
        self.assertEqual(len(visited), 6)

    def test_snapshot_sources_carry_the_same_window_as_greeting_claims(self):
        sources = SharedStore.shared_visited_sources(None, 'CUTOFF_STAMP')
        self.assertEqual(len(sources), 3)
        claims_sql, claims_params = sources[0]
        visits_sql, visits_params = sources[1]
        blocks_sql, blocks_params = sources[2]
        self.assertEqual(claims_params, ('CUTOFF_STAMP',))
        self.assertEqual(visits_params, ('CUTOFF_STAMP',))
        self.assertEqual(blocks_params, ())
        self.assertIn('created_at>=?', claims_sql)
        self.assertIn('checked_at>=?', visits_sql)
        self.assertIn('ORDER BY checked_at DESC', visits_sql)
        self.assertNotIn('checked_at>=?', blocks_sql)
        self.assertIn('ORDER BY created_at DESC', blocks_sql)


class CloudTranslation(unittest.TestCase):
    """The shared visit upsert must survive the PostgreSQL translation."""

    def test_revisit_replace_translates_to_on_conflict_update(self):
        from cloud_sql import schema_info, translate
        info = schema_info(
            'CREATE TABLE IF NOT EXISTS mumu_profile_visits(\n'
            '  peer TEXT PRIMARY KEY, checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        sql, returning = translate(
            'INSERT OR REPLACE INTO mumu_profile_visits(peer,checked_at) VALUES(?,?)',
            {'mumu_profile_visits': info})
        self.assertIsNone(returning)
        self.assertEqual(sql,
            'INSERT INTO mumu_profile_visits(peer,checked_at) VALUES(%s,%s)'
            ' ON CONFLICT ("peer") DO UPDATE SET "checked_at"=EXCLUDED."checked_at"')

    def test_the_window_stamp_uses_the_claim_format_on_both_storages(self):
        from mumu_greetings import claim_cutoff, claim_stamp
        cutoff, stamp = claim_cutoff(), claim_stamp()
        self.assertRegex(cutoff, r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
        self.assertRegex(stamp, r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
        self.assertLess(cutoff, stamp)


class FailedOpenBudget(unittest.TestCase):
    """The pass-wide TOTAL of opened-without-send ankety (never reset)."""

    def go(self, values, *, limit=2, errors=False):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 's.sqlite3', Path(folder) / 'legacy')
            profiles.Session(store).set('city', 'Псков')
            calls = []

            def next_cycle(*args, **kwargs):
                calls.append(1)
                return values[len(calls) - 1]

            settings = SimpleNamespace(adb='fake', folder=folder, errors_enabled=errors)
            out = profiles.walk(settings, threading.Event(), MagicMock(return_value=True),
                                lambda _: None, store, cycle=next_cycle, config=Config(),
                                limit=limit)
            return out, len(calls)

    def test_the_total_budget_is_pinned_to_the_recovery_constant(self):
        self.assertEqual(profiles.MAX_FAILED_OPENS, 3)
        self.assertEqual(profiles.MAX_FAILED_OPENS, profiles.MAX_READ_RECOVERIES)
        empty = profiles.report(5)
        self.assertEqual((empty['failed_opens'], empty['failed_open_limit']), (0, profiles.MAX_FAILED_OPENS))
        self.assertEqual(empty['read_recovery_limit'], profiles.MAX_READ_RECOVERIES)

    def test_verdict_only_passes_never_touch_the_budget(self):
        # Qualification verdicts (existing chat, friends>=50) are productive
        # opens with durable per-port records - they are not failures.
        out, calls = self.go([cycle_result(), cycle_result(),
                              cycle_result(send_attempted=True, send_handler_returned=True)], limit=1)
        self.assertEqual((out['status'], calls), ('profiles-completed', 3))
        self.assertEqual(out['failed_opens'], 0)
        self.assertEqual(out['skipped_existing_chat'], 2)

    def test_interleaved_verdicts_never_reset_the_total_budget(self):
        # The exact reported shape: every clean verdict used to reset the only
        # (consecutive) bound, so the pass walked ankety «в холостую» forever.
        # Three opened-without-send ankety now stop it - bounded, no carousel.
        values = [skipped(), cycle_result()] * 3
        out, calls = self.go(values)
        self.assertEqual((out['status'], out['reason']), ('profiles-stopped', 'profile-recovery-limit'))
        self.assertEqual(calls, 5)
        self.assertEqual(out['skipped_unready_chat'], 3)
        self.assertEqual(out['failed_opens'], profiles.MAX_FAILED_OPENS)
        self.assertEqual(out['consecutive_read_recoveries'], 1)
        self.assertFalse(out['recovery_events'][-1]['continue_work'])
        self.assertTrue(all(event['return_verified'] for event in out['recovery_events']))

    def test_two_failures_still_leave_room_for_a_clean_pass(self):
        out, calls = self.go([skipped(), skipped(), cycle_result(send_attempted=True,
                                                                 send_handler_returned=True)], limit=1)
        self.assertEqual((out['status'], calls), ('profiles-completed', 3))
        self.assertEqual(out['failed_opens'], 2)
        self.assertEqual(out['qualified_profiles'], 1)

    def test_a_greeting_does_not_refill_the_budget(self):
        # Even a successful greeting between failures never resets the TOTAL:
        # the third opened-without-send anketa still stops the idle walking.
        out, calls = self.go([skipped(), cycle_result(send_attempted=True, send_handler_returned=True),
                              skipped(), skipped()])
        self.assertEqual((out['status'], out['reason']), ('profiles-stopped', 'profile-recovery-limit'))
        self.assertEqual(calls, 4)
        self.assertEqual(out['failed_opens'], 3)
        self.assertEqual(out['send_attempts'], 1)

    def test_the_stop_reports_the_honest_counters_for_diagnostics(self):
        out, _ = self.go([skipped(), skipped(), skipped()])
        self.assertEqual(out['failed_open_limit'], profiles.MAX_FAILED_OPENS)
        self.assertEqual(out['read_recovery_limit'], profiles.MAX_READ_RECOVERIES)
        self.assertEqual(out['consecutive_read_recoveries'], 3)
        # The closed diagnostic projection accepts the new counters.
        from assistant_error_notify import diagnostic_json
        published = json.loads(diagnostic_json(dict(status='stopped', reason='profile-recovery-limit',
                                                   failed_opens=3, failed_open_limit=3,
                                                   consecutive_read_recoveries=3, read_recovery_limit=3))
                               .decode('utf-8'))['diagnostic']
        self.assertEqual(published['failed_opens'], 3)
        self.assertEqual(published['failed_open_limit'], 3)

    def test_summary_names_the_budget_and_the_limit_reason(self):
        from assistant_run import PROFILE_REASONS, summary
        out = dict(profiles.report(5), status='profiles-stopped', reason='profile-recovery-limit',
                   current_city='Псков', send_attempts=0, handlers_returned=0,
                   skipped_friends=0, skipped_existing_chat=0, failed_opens=3)
        text = summary(dict(tool_version='test', mode='full', status='stopped',
                            reason='profiles-not-finished', inbox=None, profiles=out,
                            preparation_failure=None))
        self.assertIn('открыто без отправки 3/3', text)
        self.assertIn(PROFILE_REASONS['profile-recovery-limit'], text)


class OneViewAcrossPorts(unittest.TestCase):
    """The released no-send claim no longer feeds a re-open carousel."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'db'
        self.old = Path(self.temp.name) / 'legacy'
        self.a = self.store(5557)
        self.b = self.store(5559)

    def store(self, port):
        return SharedStore(self.path, self.old, device_port=port)

    def test_released_peer_stays_un_openable_for_the_window(self):
        # Port A opened her anketa and failed to deliver (1.3.99 skip): the
        # claim is released, but the SHARED visit row keeps every port's
        # pre-filter skipping her anketa - no second view today. Port A's own
        # journal keeps its permanent same-account protection exactly as
        # before; port B keeps the freed claim's eligibility for any
        # journal-driven path - only the anketa re-open is closed for a day.
        pending_value = pending(peer='400')
        self.assertIsNotNone(self.a.reserve(pending_value, 'Hi', approved=True))
        self.assertTrue(self.a.peer_claimed(pending_value))
        self.a.release_reservation(pending_value)
        self.a.record_visit('400', visit_navigation())
        self.assertTrue(self.a.peer_claimed(pending_value))
        self.assertFalse(self.b.peer_claimed(pending_value))
        for store in (self.a, self.b):
            self.assertIn('400', store.visited_peers())
        # And the reservation itself still works on the freed claim.
        self.assertIsNotNone(self.b.reserve(pending(peer='401'), 'Hi', approved=True))

    def test_clear_history_keeps_the_shared_window_rows(self):
        # The manual «Очистить историю анкет» button forgets THIS port's own
        # verdicts and city reservation; the fleet-wide daily view protection
        # is exactly what must survive it (the dialog says so since 1.3.100),
        # including for the clearing port itself: no re-open of any anketa
        # some port opened inside the window.
        self.a.record_visit('402', visit_navigation())
        profiles.clear_history(self.a)
        self.assertIn('402', self.a.visited_peers())
        self.assertIn('402', self.b.visited_peers())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM m5557__profile_visits').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT peer FROM mumu_profile_visits').fetchall(), [('402',)])


if __name__ == '__main__':
    unittest.main()
