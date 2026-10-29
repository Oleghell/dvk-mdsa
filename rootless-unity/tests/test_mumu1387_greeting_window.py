"""v1.3.87 user rules for the shared greeting registry, verified across ports.

«также внимательно сделай строгую проверку, если на одном порту уже написали
приветствие одной анкете, то на другом порту с другой анкете этого уже
невозможно сделать и анкета пропускается, фиксируй где-то в бд ... но это
работает так, это значит что больше с другого порта нельзя написать, можно
через сутки. основное правило следующее, если анкета оставила номер или
отказалась его давать то уже на других анкетах никогда ей не пишем. это все
идет сравнение по айди пользователя в профиле.»

So, per profile user ID (peer):
* A greeting claim is recorded in the shared DB (mumu_greeting_claims) and
  denies every OTHER port's new greeting for 24 hours only; after that
  another анкета may greet the same peer again and the claim row moves to
  the new port with a fresh 24-hour window.
* The claiming port's own journal keeps its permanent same-account replay
  protection (manual_actions), independent of the claim's age.
* A terminal outcome - the peer left a number (contact-received) or
  explicitly refused to give it (contact-refused), or a manual /num - is
  permanent for EVERY port, however old the row is.
* The native pre-filter snapshot (visited_peers) agrees with the reserve()
  authority: expired claims leave the snapshot, terminal blocks never do.

Synthetic SQLite only; no device, cloud, worker process or native script."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mumu_greetings
from mumu_peer_policy import ensure_communication_allowed, PeerCommunicationBlocked
from mumu_store import SharedStore, SharedPeerClaimed
from test_assistant import pending

NOW = datetime.now(timezone.utc).replace(microsecond=0)
PORTS = (5557, 5559, 5561)


def stamp(delta):
    return (NOW + delta).strftime('%Y-%m-%d %H:%M:%S')


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.path = self.base / 'assistant.sqlite3'
        self.legacy = self.base / 'old'
        self.stores = {port: SharedStore(self.path, self.legacy, device_port=port)
                       for port in PORTS}

    def raw(self):
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        return db

    def claim_row(self, peer):
        with self.raw() as db:
            return db.execute('SELECT device,account,created_at FROM mumu_greeting_claims '
                              'WHERE peer=?', (peer,)).fetchone()

    def age_claim(self, peer, delta):
        with self.raw() as db:
            db.execute('UPDATE mumu_greeting_claims SET created_at=? WHERE peer=?',
                       (stamp(delta), peer))
        db.commit()

    def test_fresh_claim_is_recorded_in_the_db_and_blocks_every_other_port(self):
        """Строгая проверка: приветствие зафиксировано в общей БД, другой порт
        не может написать, анкета пропускается (verified skip path)."""
        self.stores[5557].reserve(pending(account='101'), 'Привет', approved=True)
        row = self.claim_row('200')
        self.assertIsNotNone(row, 'приветствие должно фиксироваться в общей БД')
        self.assertEqual(row[0], '5557')
        for port in (5559, 5561):
            self.assertTrue(self.stores[port].peer_claimed(pending(account='102')),
                            'порт %d не должен иметь возможности написать' % port)
            with self.assertRaises(SharedPeerClaimed):
                self.stores[port].reserve(pending(account='102'), 'Привет', approved=True)
            self.assertIn('200', self.stores[port].visited_peers(),
                          'префильтр порта %d должен пропускать анкету без открытия' % port)

    def test_after_a_day_another_port_may_greet_again_and_the_window_restarts(self):
        """«можно через сутки»: истёкший клейм перестаёт блокировать чужие порты,
        новое приветствие переносит запись на новый порт и снова на 24 часа."""
        self.stores[5557].reserve(pending(account='101'), 'Привет', approved=True)
        self.age_claim('200', timedelta(hours=-25))
        for port in (5559, 5561):
            self.assertFalse(self.stores[port].peer_claimed(pending(account='102')))
            self.assertNotIn('200', self.stores[port].visited_peers())
        # Port 5559 greets the same peer again - the claim row is REPLACED,
        # never duplicated, and measures its age from the NEW greeting.
        self.stores[5559].reserve(pending(account='102'), 'Привет ещё раз', approved=True)
        row = self.claim_row('200')
        self.assertEqual(row[0], '5559')
        self.assertGreaterEqual(row[2], stamp(timedelta(hours=-1)))
        with self.raw() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM mumu_greeting_claims '
                                        'WHERE peer=?', ('200',)).fetchone()[0], 1)
        # The fresh 24-hour window shields the peer from the THIRD port again.
        self.assertTrue(self.stores[5561].peer_claimed(pending(account='103')))
        with self.assertRaises(SharedPeerClaimed):
            self.stores[5561].reserve(pending(account='103'), 'Привет', approved=True)

    def test_claiming_port_keeps_its_own_permanent_journal_protection(self):
        """Свой журнал порта вечен: свой порт не пишет повторно даже через сутки."""
        self.stores[5557].reserve(pending(account='101'), 'Привет', approved=True)
        self.age_claim('200', timedelta(hours=-48))
        self.assertTrue(self.stores[5557].peer_claimed(pending(account='101')))
        with self.assertRaises(SharedPeerClaimed):
            self.stores[5557].reserve(pending(account='101'), 'Ещё раз', approved=True)
        self.assertIn('200', self.stores[5557].visited_peers())

    def test_cutoff_helper_matches_the_engine_timestamp_format(self):
        self.assertEqual(mumu_greetings.CLAIM_WINDOW_SECONDS, 24 * 3600)
        value = mumu_greetings.claim_cutoff(NOW)
        self.assertEqual(value, stamp(timedelta(hours=-24)))
        self.assertRegex(value, r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
        self.assertEqual(mumu_greetings.claim_stamp(NOW), stamp(timedelta()))

    def test_snapshot_and_authority_agree_on_the_window_edge(self):
        store = self.stores[5559]
        with self.raw() as db:
            db.execute('INSERT INTO mumu_greeting_claims(peer,device,account,created_at) '
                       "VALUES('300','x:5557','101',?)", (stamp(timedelta(hours=-23)),))
            db.execute('INSERT INTO mumu_greeting_claims(peer,device,account,created_at) '
                       "VALUES('301','x:5557','101',?)", (stamp(timedelta(hours=-25)),))
            db.commit()
        visited = set(store.visited_peers())
        self.assertIn('300', visited)
        self.assertNotIn('301', visited)
        self.assertTrue(store.peer_claimed(pending(peer='300')))
        self.assertFalse(store.peer_claimed(pending(peer='301')))


class Terminal(unittest.TestCase):
    """Основное правило: номер получен или отказ → никогда не пишем ни с одной анкеты."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.path = self.base / 'assistant.sqlite3'
        self.legacy = self.base / 'old'
        self.stores = {port: SharedStore(self.path, self.legacy, device_port=port)
                       for port in PORTS}

    def raw(self):
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        return db

    def outcome(self, peer, reason, delta=timedelta(hours=-72)):
        with self.raw() as db:
            db.execute('INSERT OR IGNORE INTO mumu_peer_blocks(peer,reason,device,account,chat,created_at) '
                       'VALUES(?,?,?,?,?,?)',
                       (peer, reason, '9104:5557', '101', 'c' + peer, stamp(delta)))
            db.commit()

    def test_number_or_refusal_blocks_every_port_forever(self):
        for peer, reason in (('400', 'contact-received'), ('401', 'contact-refused'),
                             ('402', 'manual-block')):
            self.outcome(peer, reason)
            for port in PORTS:
                store = self.stores[port]
                self.assertTrue(store.peer_claimed(pending(peer=peer)),
                                '%s должен блокировать порт %d навсегда' % (reason, port))
                with self.assertRaises(SharedPeerClaimed):
                    store.reserve(pending(peer=peer, account=str(port)), 'Привет', approved=True)
                self.assertIn(peer, store.visited_peers(),
                              'терминальный запрет не покидает снимок порта %d' % port)

    def test_terminal_block_survives_and_outlives_expired_claims(self):
        self.stores[5557].reserve(pending(peer='400', account='101'), 'Привет', approved=True)
        self.outcome('400', 'contact-received')
        with self.raw() as db:
            db.execute("UPDATE mumu_greeting_claims SET created_at=? WHERE peer='400'",
                       (stamp(timedelta(hours=-100)),))
            db.commit()
        for port in (5559, 5561):
            self.assertTrue(self.stores[port].peer_claimed(pending(peer='400')))
            with self.assertRaises(SharedPeerClaimed):
                self.stores[port].reserve(pending(peer='400', account='102'), 'Привет', approved=True)
            self.assertIn('400', self.stores[port].visited_peers())

    def test_reply_flow_is_never_blocked_by_a_greeting_claim(self):
        """Клейм касается только НОВЫХ приветствий; начатая переписка не глушится
        (алгоритм идёт дальше), а вот терминальный запрет действует и на неё."""
        self.stores[5557].reserve(pending(account='101'), 'Привет', approved=True)
        who = dict(account='100', peer='200', chat='300')
        for port in (5559, 5561):
            ensure_communication_allowed(self.stores[port], who)
        self.outcome('200', 'contact-refused')
        for port in PORTS:
            with self.assertRaises(PeerCommunicationBlocked):
                ensure_communication_allowed(self.stores[port], who)


class Migration(unittest.TestCase):
    """Импорт старых журналов сохраняет возраст приветствия («фиксируй в бд»)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.path = self.base / 'assistant.sqlite3'
        self.legacy = self.base / 'old'

    def raw(self):
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        return db

    def test_backfill_keeps_the_journal_greeting_age(self):
        SharedStore(self.path, self.legacy, device_port=5557).reserve(
            pending(account='101'), 'Привет', approved=True)
        with self.raw() as db:
            # The port's own journal says the greeting is two days old; the
            # imported claim must carry THAT age, not the migration moment.
            db.execute("UPDATE m5557__manual_actions SET created_at=? WHERE peer='200'",
                       (stamp(timedelta(hours=-48)),))
            db.execute('DROP TABLE mumu_greeting_claims')
            db.commit()
        fresh = SharedStore(self.path, self.legacy, device_port=5559)
        with self.raw() as db:
            row = db.execute("SELECT created_at FROM mumu_greeting_claims WHERE peer='200'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], stamp(timedelta(hours=-48)),
                         'импорт должен сохранять возраст журнала, а не миграцию')
        # The historical greeting is inside its own port's journal forever...
        self.assertTrue(SharedStore(self.path, self.legacy, device_port=5557).peer_claimed(pending()))
        # ...and, being older than a day, no longer denies another анкета.
        self.assertFalse(fresh.peer_claimed(pending(account='102')))

    def test_window_constant_is_pinned_to_one_day(self):
        self.assertEqual(mumu_greetings.CLAIM_WINDOW_SECONDS, 86400)


class Refresh(unittest.TestCase):
    """Повторное приветствие обновляет ровно одну строку клейма."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.path = self.base / 'assistant.sqlite3'
        self.legacy = self.base / 'old'

    def raw(self):
        # sqlite3's ``with`` block only commits; the handle itself must be
        # closed (addCleanup) or Windows keeps the file locked for the
        # TemporaryDirectory cleanup (WinError 32).
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        return db

    def test_expired_claim_release_still_deletes_only_own_device_rows(self):
        first = SharedStore(self.path, self.legacy, device_port=5557)
        first.reserve(pending(account='101'), 'Привет', approved=True)
        with self.raw() as db:
            db.execute("UPDATE mumu_greeting_claims SET created_at=? WHERE peer='200'",
                       ((datetime.now(timezone.utc) - timedelta(hours=30)).strftime('%Y-%m-%d %H:%M:%S'),))
            db.commit()
        second = SharedStore(self.path, self.legacy, device_port=5559)
        second.reserve(pending(account='102'), 'Снова привет', approved=True)
        with self.raw() as db:
            self.assertEqual(db.execute('SELECT device FROM mumu_greeting_claims WHERE peer=?',
                                        ('200',)).fetchall(), [('5559',)])
        # A device-scoped release of the NEW owner returns the peer to the pool.
        self.assertTrue(second.release_reservation(pending(account='102')))
        with self.raw() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM mumu_greeting_claims WHERE peer=?',
                                        ('200',)).fetchone()[0], 0)
        # The previous owner's release never touches the other port's state:
        # its own journal row is finalized, and no NEW claim row appears.
        first.release_reservation(pending(account='101'))
        with self.raw() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM mumu_greeting_claims WHERE peer=?',
                                        ('200',)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM m5557__manual_actions "
                                        "WHERE peer='200' AND status='reserved-unknown'").fetchone()[0], 0)


class CloudTranslation(unittest.TestCase):
    """Облачная (PostgreSQL) трансляция новых SQL-форм клеймов."""

    def test_re_greeting_replaces_the_claim_row_with_a_fresh_window(self):
        from cloud_sql import schema_info, translate
        info = schema_info(
            'CREATE TABLE IF NOT EXISTS mumu_greeting_claims(\n'
            '        peer TEXT PRIMARY KEY,device TEXT NOT NULL,account TEXT NOT NULL,\n'
            '        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        sql, returning = translate(
            'INSERT OR REPLACE INTO mumu_greeting_claims(peer,device,account,created_at) VALUES(?,?,?,?)',
            {'mumu_greeting_claims': info})
        self.assertIsNone(returning)
        self.assertEqual(sql,
            'INSERT INTO mumu_greeting_claims(peer,device,account,created_at) VALUES(%s,%s,%s,%s)'
            ' ON CONFLICT ("peer") DO UPDATE SET "device"=EXCLUDED."device",'
            '"account"=EXCLUDED."account","created_at"=EXCLUDED."created_at"')

    def test_snapshot_sources_split_claims_window_from_permanent_blocks(self):
        from mumu_store import SharedStore
        sources = SharedStore.shared_visited_sources(None, 'CUTOFF_STAMP')
        claims_sql, claims_params = sources[0]
        blocks_sql, blocks_params = sources[1]
        self.assertEqual(claims_params, ('CUTOFF_STAMP',))
        self.assertEqual(blocks_params, ())
        self.assertIn('created_at>=?', claims_sql)
        self.assertIn('ORDER BY created_at DESC', claims_sql)
        self.assertNotIn('created_at>=?', blocks_sql)
        self.assertIn('ORDER BY created_at DESC', blocks_sql)

    def test_blocked_claim_query_filters_by_the_window_in_both_storages(self):
        from cloud_sql import placeholders
        sql = placeholders('SELECT 1 FROM mumu_greeting_claims WHERE peer=? AND created_at>=?')
        self.assertEqual(sql, 'SELECT 1 FROM mumu_greeting_claims WHERE peer=%s AND created_at>=%s')


if __name__ == '__main__':
    unittest.main()
