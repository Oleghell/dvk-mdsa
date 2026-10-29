"""User report (v1.3.77 live run): «заходит в профиль, потом в личку и ничего
не пишет, хотя 20 анкет просмотрел». The live shared registry had grown to
12,220 greeting claims (plus ~1,000/day across two installations) while the
uploaded pre-filter snapshot still carried only the FRESHEST 2,000 claims and
600 blocks, so ~84% of claimed peers were invisible to the native
selection-time check (batchSeen). Every such peer cost a full cycle - profile
opened, chat opened, host peer_claimed() said "already greeted", verified
no-send Back - and the pass reported «просмотрено N» with zero greetings sent,
because the search feed keeps re-serving peers some port had already greeted
(reports 500/506: checked=3/0, send_attempts=0, shared_peer_skips=2/2).

Fix under test: the snapshot uploads the FULL shared registries; the native
pre-filter then skips already-greeted peers BEFORE their profile or chat is
ever opened. Only when the combined snapshot would exceed the safety ceiling
(raised 10,000 -> 100,000, pinned equal in store and JS contract) do the
shared sources degrade to the freshest rows that still fit; own journals stay
complete, and reserve()/peer_claimed() keep checking the full registry as the
dedup authority, so a duplicate greeting remains impossible.

Synthetic SQLite only; no device, cloud, worker process or native script."""
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import assistant_pass
from assistant_store import StateError
from mumu_store import SharedStore

BASE = datetime(2026, 10, 20, 12, 0, 0)
# v1.3.87: a greeting claim shields the peer from other ports for 24 hours
# only, so registry-size fixtures must stamp claims INSIDE that window while
# keeping their relative age order (older first, freshest last).
FRESH = datetime.now(timezone.utc).replace(microsecond=0)


def peer_at(base, offset):
    return str(base + offset)


class Constants(unittest.TestCase):
    def test_snapshot_ceiling_is_100000_in_both_layers(self):
        self.assertIs(type(SharedStore.VISITED_SNAPSHOT_LIMIT), int)
        self.assertEqual(SharedStore.VISITED_SNAPSHOT_LIMIT, 100000)
        self.assertIs(type(assistant_pass.SNAPSHOT_VISITED_LIMIT), int)
        self.assertEqual(assistant_pass.SNAPSHOT_VISITED_LIMIT, 100000)

    def test_store_and_js_contract_limits_are_pinned_equal(self):
        self.assertEqual(SharedStore.VISITED_SNAPSHOT_LIMIT,
                         assistant_pass.SNAPSHOT_VISITED_LIMIT)

    def test_js_cumulative_cap_uses_the_new_ceiling(self):
        source = assistant_pass.prepared_source('Привет')
        self.assertIn('if(assistantVisitedParts.length>100000){'
                      'assistantVisitedParts=null;return false;}', source)

    def test_js_per_piece_cap_is_unchanged(self):
        source = assistant_pass.prepared_source('Привет')
        self.assertIn('!Array.isArray(values)||values.length>10000)return false;',
                      source)

    def test_pieces_stay_at_the_transport_safe_chunk(self):
        self.assertEqual(assistant_pass.HISTORY_UPLOAD_CHUNK, 1000)

    def test_build_rejects_beyond_the_ceiling_and_accepts_at_it(self):
        with patch.object(assistant_pass, 'SNAPSHOT_VISITED_LIMIT', 10):
            with self.assertRaises(ValueError):
                assistant_pass.build('Hi', [str(i) for i in range(2, 13)])
            built = assistant_pass.build('Hi', [str(i) for i in range(1, 11)])
        self.assertIn('batchSeen=new Set(["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"])', built)

    def test_upload_pieces_cover_the_live_registry_size(self):
        visited = [str(i) for i in range(12220)]
        pieces = [visited[index:index + assistant_pass.HISTORY_UPLOAD_CHUNK]
                  for index in range(0, len(visited), assistant_pass.HISTORY_UPLOAD_CHUNK)]
        self.assertEqual(len(pieces), 13)
        self.assertEqual(sum(map(len, pieces)), 12220)
        self.assertTrue(all(len(piece) <= 1000 for piece in pieces))


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'assistant.sqlite3'
        self.legacy = Path(self.tmp.name) / 'old'
        self.port = 5557

    def store(self, limit=None):
        value = SharedStore(self.path, self.legacy, device_port=self.port)
        if limit is not None:
            # Degradation is exercised with a small ceiling; the production
            # value is pinned by Constants above.
            value.VISITED_SNAPSHOT_LIMIT = limit
        return value

    @contextmanager
    def raw(self):
        db = sqlite3.connect(self.path)
        try:
            yield db
        finally:
            db.close()

    def insert_claims(self, db, peers, *, start=0, step=1):
        for offset, peer in enumerate(peers):
            stamp = (FRESH + timedelta(seconds=start + offset * step)).strftime('%Y-%m-%d %H:%M:%S')
            db.execute('INSERT OR IGNORE INTO mumu_greeting_claims(peer,device,account,created_at) '
                       'VALUES(?,?,?,?)', (peer, '9104:5563', '101', stamp))

    def insert_blocks(self, db, peers, *, start=0, step=1):
        for offset, peer in enumerate(peers):
            stamp = (BASE + timedelta(seconds=start + offset * step)).strftime('%Y-%m-%d %H:%M:%S')
            db.execute('INSERT OR IGNORE INTO mumu_peer_blocks(peer,reason,device,account,chat,created_at) '
                       'VALUES(?,?,?,?,?,?)', (peer, 'contact-refused', '9104:5563', '101', 'c' + peer, stamp))

    def insert_visits(self, db, peers):
        for offset, peer in enumerate(peers):
            stamp = (BASE + timedelta(seconds=offset)).strftime('%Y-%m-%d %H:%M:%S')
            db.execute('INSERT OR IGNORE INTO m%d__profile_visits(peer,friends_count,history_status,checked_at) '
                       'VALUES(?,10,?,?)' % self.port, (peer, 'read', stamp))

    def test_live_sized_registry_uploads_completely(self):
        store = self.store()
        claims = [peer_at(5000000000, i) for i in range(12220)]
        blocks = [peer_at(8000000000, i) for i in range(600)]
        visits = [peer_at(6000000000, i) for i in range(300)]
        with self.raw() as db:
            self.insert_claims(db, claims)
            self.insert_blocks(db, blocks)
            self.insert_visits(db, visits)
            db.commit()
        visited = set(store.visited_peers())
        # Everything fits: the pre-filter sees the WHOLE registry, so an
        # already-greeted peer is skipped at selection without opening
        # anything - no more "просмотрено 20, отправлено 0".
        self.assertTrue(all(peer in visited for peer in claims))
        self.assertTrue(all(peer in visited for peer in blocks))
        self.assertTrue(all(peer in visited for peer in visits))
        self.assertEqual(len(visited), 12220 + 600 + 300)

    def test_degradation_keeps_own_journals_complete_and_slices_freshest(self):
        store = self.store(limit=3000)
        own = [peer_at(6000000000, i) for i in range(500)]
        claims = [peer_at(5000000000, i) for i in range(3000)]
        with self.raw() as db:
            self.insert_claims(db, claims)  # older first, freshest last
            self.insert_visits(db, own)
            db.commit()
        visited = set(store.visited_peers())
        # Own journals always upload COMPLETE: only the native filter prevents
        # reopening the port's own visited profiles.
        self.assertTrue(all(peer in visited for peer in own))
        # Claims degrade freshest-first to whatever still fits - never past
        # the ceiling, never a dead port.
        self.assertEqual(len(visited), 3000)
        self.assertTrue(all(peer_at(5000000000, i) in visited for i in range(500, 3000)))
        self.assertFalse(any(peer_at(5000000000, i) in visited for i in range(500)))

    def test_degradation_shares_the_remaining_budget_with_blocks(self):
        store = self.store(limit=3000)
        own = [peer_at(6000000000, i) for i in range(500)]
        claims = [peer_at(5000000000, i) for i in range(2000)]
        blocks = [peer_at(8000000000, i) for i in range(700)]
        with self.raw() as db:
            self.insert_claims(db, claims)
            self.insert_blocks(db, blocks)
            self.insert_visits(db, own)
            db.commit()
        visited = set(store.visited_peers())
        self.assertTrue(all(peer in visited for peer in own))
        self.assertTrue(all(peer in visited for peer in claims))
        # Blocks take the remaining 500 slots freshest-first.
        self.assertTrue(all(peer_at(8000000000, i) in visited for i in range(200, 700)))
        self.assertFalse(any(peer_at(8000000000, i) in visited for i in range(200)))
        self.assertEqual(len(visited), 3000)

    def test_own_journal_overflow_still_stops_with_the_archive_hint(self):
        store = self.store(limit=10)
        own = [peer_at(6000000000, i) for i in range(11)]
        with self.raw() as db:
            self.insert_visits(db, own)
            db.commit()
        with self.assertRaisesRegex(StateError, 'безопасного лимита снимка'):
            store.visited_peers()

    def test_claimed_peer_is_filtered_by_the_snapshot_exactly_like_peer_claimed(self):
        """The pre-filter must agree with the authoritative host check."""
        store = self.store()
        claimed = [peer_at(5000000000, i) for i in range(50)]
        with self.raw() as db:
            self.insert_claims(db, claimed)
            db.commit()
        visited = set(store.visited_peers())
        for peer in claimed:
            pending = dict(attempt=1, account='101', peer=peer, chat='-1', variant=0)
            from cohort_pass import Store as LegacyStore
            self.assertTrue(store.peer_claimed(LegacyStore.check(pending)),
                            'authoritative check lost a claimed peer')
            self.assertIn(peer, visited, 'pre-filter lost a claimed peer')


if __name__ == '__main__':
    unittest.main()
