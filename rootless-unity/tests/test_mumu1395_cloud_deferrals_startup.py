"""1.3.95 regressions: the deferral ladder's schema must cross the cloud bridge alive.

Reported (all four ports of one cloud-primary installation, monitor reports
576-579): «теперь такие ошибки ловлю при старте… оно сначала при запуске
должно проверять диалоги и отвечать на неотвеченные либо прочитанные, а
потом идти к новым анкетам и так по кругу» - every port stopped at
prepare-inbox-targets-failed / ValueError with passes_completed=0, so the
dialogs-then-profiles cycle never even began. The 1.3.94 CREATE for
inbox_history_deferrals shipped `deferrals INTEGER NOT NULL DEFAULT 0`;
the cloud bridge's CREATE gate (cloud_sql.schema_info) accepts only
NULL/CURRENT_TIMESTAMP defaults and runs BEFORE the already-registered
no-op, so every cloud startup died inside checkpoint('inbox-targets').
A local SQLite store executes CREATE directly and never runs that gate -
which is why the full CI suite stayed green while production was dead.

These tests pin the gate itself: the shipped DDL must survive schema_info,
the migration of a LIVE pre-1.3.94 cloud table must complete through the
same statement shapes the bridge really issues (registered no-op CREATE,
probe SELECT, passthrough ALTER), a concurrent migration may never kill a
port, and no shipped module may ever again hand the gate a DDL it rejects.
Synthetic only; no device, no live services, no real cloud connection.
"""
import ast
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistant_history_wait as history_wait
from assistant_store import Store
from cloud_sql import create_sql, schema_info

WHO = dict(account='100', peer='200', chat='2000')

# The bridge's own native-Postgres bootstrap DDL: executed raw against the
# server (never through the CREATE gate) and intentionally not SQLite SQL.
NATIVE_POSTGRES_DDL = {('cloud_migration.py', '_dvk_meta'), ('cloud_migration.py', '_dvk_schema')}


class CountingStore(Store):
    """Counts every SQL statement the store executes, per connection."""

    def __init__(self, *args, **kwargs):
        self.queries = []  # before super(): Store.__init__ already opens the journal
        super().__init__(*args, **kwargs)

    @contextmanager
    def _counting(self, method):
        with method() as db:
            outer = self

            class Proxy:
                def __getattr__(self, key):
                    return getattr(db, key)

                def execute(self, sql, params=()):
                    outer.queries.append(sql)
                    return db.execute(sql, params)
            yield Proxy()

    def connection(self):
        return self._counting(super().connection)

    def read_connection(self):
        return self._counting(super().read_connection)


class CloudGateStore:
    """A local SQLite store wearing the cloud bridge's CREATE contract.

    Every CREATE TABLE IF NOT EXISTS must first survive cloud_sql.schema_info
    - the exact gate that killed cloud startups in 1.3.94 - and a table whose
    name is already registered in the catalog is NOT re-created and NOT
    re-registered, exactly like the live bridge's ``if name in self.schemas``
    no-op on the user's migrated store. ALTER/SELECT/INSERT pass straight
    through to SQLite, exactly like the bridge's translate() passthrough.
    """

    def __init__(self, store):
        self._store = store
        self._catalog = {}

    def __getattr__(self, key):
        return getattr(self._store, key)

    def register(self, name, ddl):
        self._catalog[name] = ddl

    def ensure_tables(self, *statements):
        for sql in statements:
            info = schema_info(sql)  # the gate: raises before anything else
            if info['name'] in self._catalog:
                continue
            with self._store.connection() as db:
                db.execute(sql)
            self._catalog[info['name']] = sql

    def connection(self):
        return self._store.connection()

    def read_connection(self):
        return self._store.read_connection()


class CloudGateStartup(unittest.TestCase):
    """The exact startup sequence of the user's four dead ports."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CloudGateStore(Store(Path(self.tmp.name) / 'a.sqlite3',
                                          Path(self.tmp.name) / 'old'))
        self.now = 1000.0

    def clock(self):
        return self.now

    def columns(self):
        with self.store.read_connection() as db:
            return {row[1] for row in db.execute('PRAGMA table_info(inbox_history_deferrals)')}

    def test_a_fresh_cloud_store_creates_the_table_through_the_gate(self):
        # 1.3.94 died HERE with ValueError('Unsupported column type/default')
        # before a single dialog was checked; the gate must accept the DDL.
        history_wait.initialize(self.store)
        self.assertIn('deferrals', self.columns())
        until = history_wait.defer(self.store, WHO, clock=self.clock)
        self.assertAlmostEqual(until - self.now, history_wait.COOLDOWN_SECONDS)

    def test_the_shipped_ddl_carries_no_default_the_gate_rejects(self):
        info = schema_info(history_wait.DEFERRALS_DDL)
        self.assertEqual([c[1] for c in info['columns']],
                         ['account', 'peer', 'chat', 'retry_after', 'deferrals'])
        postgres = create_sql(info)
        self.assertNotIn('DEFAULT', postgres)
        self.assertIn('"deferrals" BIGINT NOT NULL', postgres)

    def test_a_live_pre_1_3_94_cloud_table_migrates_in_place(self):
        # The user's real store: the OLD four-column table is already created
        # and registered in the catalog, so the new CREATE is a registered
        # no-op (after the gate), the probe SELECT fails on the missing
        # column, and the ALTER - a plain passthrough on the bridge - adds it.
        history_wait.initialize(self.store)  # the store the user had BEFORE 1.3.94
        OLD_DDL = '''CREATE TABLE IF NOT EXISTS inbox_history_deferrals(
                account TEXT NOT NULL,peer TEXT NOT NULL,chat TEXT NOT NULL,
                retry_after REAL NOT NULL,PRIMARY KEY(account,peer))'''
        with self.store._store.connection() as db:
            db.execute('DROP TABLE inbox_history_deferrals')
            db.execute(OLD_DDL)
            db.execute('INSERT INTO inbox_history_deferrals VALUES(?,?,?,?)',
                       (WHO['account'], WHO['peer'], WHO['chat'], 5.0))
        self.store.register('inbox_history_deferrals', OLD_DDL)
        self.store._dvk_deferrals_migrated = False
        history_wait.initialize(self.store)
        self.assertEqual(self.columns(),
                         {'account', 'peer', 'chat', 'retry_after', 'deferrals'})
        with self.store.read_connection() as db:
            row = db.execute('SELECT retry_after,deferrals FROM inbox_history_deferrals').fetchone()
        self.assertEqual(row, (5.0, 0))  # the ALTER's DEFAULT 0 backfill
        until = history_wait.defer(self.store, WHO, clock=self.clock)
        self.assertAlmostEqual(until - self.now, history_wait.COOLDOWN_SECONDS)
        attention, unread, skipped = history_wait.eligible(
            self.store, [], [dict(WHO)], clock=lambda: self.now + 1.0)
        self.assertEqual((attention, unread, skipped), ([], [], 1))

    def test_the_latch_keeps_the_warm_path_free_of_schema_work(self):
        counted = CountingStore(Path(self.tmp.name) / 'b.sqlite3', Path(self.tmp.name) / 'old')
        store = CloudGateStore(counted)
        history_wait.initialize(store)
        self.assertTrue(store._dvk_deferrals_migrated)
        counted.queries.clear()
        history_wait.initialize(store)
        self.assertEqual(counted.queries, [])


class SabotageCursor:
    """The ALTER fails with the cloud error shape; when the race is lost the
    OTHER process's ALTER has already landed (applied for real outside the
    sabotaged transaction, so the transaction's own rollback on the raise
    cannot undo the winner's work)."""

    def __init__(self, db, owner):
        self._db = db
        self._owner = owner

    def __getattr__(self, key):
        return getattr(self._db, key)

    def execute(self, sql, params=()):
        if sql.startswith('ALTER TABLE inbox_history_deferrals'):
            if self._owner._add_first:
                self._db.execute('COMMIT')  # end this transaction first
                self._db.execute(sql)      # the winner's ALTER, committed
            raise sqlite3.OperationalError(self._owner._code)
        return self._db.execute(sql, params)


class RacingStore:
    """Mimics a second process migrating the same store concurrently.

    The probe SELECT misses the column, then the ALTER both fails with the
    CLOUD error shape (a generic code - the bridge collapses Postgres'
    duplicate-column 42701 into 'cloud-database-unavailable', none of the
    SQLite 'duplicate column' wording 1.3.94 sniffed) and - when the race is
    lost because the OTHER process migrated - has actually added the column.
    """

    def __init__(self, store, *, add_first, code='cloud-database-unavailable'):
        self._store = store
        self._add_first = add_first
        self._code = code

    def __getattr__(self, key):
        return getattr(self._store, key)

    @contextmanager
    def connection(self):
        with self._store.connection() as db:
            yield SabotageCursor(db, self)

    def read_connection(self):
        return self._store.read_connection()

    def ensure_tables(self, *statements):
        return self._store.ensure_tables(*statements)


class ConcurrentMigration(unittest.TestCase):
    """A lost race may never kill a port; a real failure must still surface."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inner = Store(Path(self.tmp.name) / 'a.sqlite3', Path(self.tmp.name) / 'old')

    def raced(self):
        store = RacingStore(self.inner, add_first=True)
        with self.inner.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS inbox_history_deferrals(
                    account TEXT NOT NULL,peer TEXT NOT NULL,chat TEXT NOT NULL,
                    retry_after REAL NOT NULL,PRIMARY KEY(account,peer))''')
        self.inner._dvk_deferrals_migrated = False
        return store

    def test_a_lost_race_with_the_cloud_error_shape_survives(self):
        store = self.raced()
        history_wait.initialize(store)  # must not raise
        self.assertTrue(store._dvk_deferrals_migrated)
        with self.inner.read_connection() as db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(inbox_history_deferrals)')}
        self.assertIn('deferrals', columns)
        until = history_wait.defer(store, WHO, clock=lambda: 1000.0)
        self.assertAlmostEqual(until - 1000.0, history_wait.COOLDOWN_SECONDS)

    def test_a_lost_race_with_the_sqlite_wording_survives(self):
        store = self.raced()
        store._code = 'duplicate column name: deferrals'
        history_wait.initialize(store)
        self.assertTrue(store._dvk_deferrals_migrated)

    def test_a_real_migration_failure_still_surfaces(self):
        store = RacingStore(self.inner, add_first=False)
        with self.inner.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS inbox_history_deferrals(
                    account TEXT NOT NULL,peer TEXT NOT NULL,chat TEXT NOT NULL,
                    retry_after REAL NOT NULL,PRIMARY KEY(account,peer))''')
        self.inner._dvk_deferrals_migrated = False
        with self.assertRaises(sqlite3.OperationalError) as caught:
            history_wait.initialize(store)
        self.assertEqual(str(caught.exception), 'cloud-database-unavailable')
        self.assertFalse(getattr(store, '_dvk_deferrals_migrated', False))


def shipped_ddl_literals():
    """Every CREATE TABLE IF NOT EXISTS literal in the shipped runtime modules.

    Excluded by design: executescript bodies (local-only schemas on direct
    sqlite connections the bridge never translates), bare 'CREATE TABLE IF
    NOT EXISTS ' prefixes used for validation/concatenation (no table body),
    and the bridge's own native-Postgres bootstrap in cloud_migration.
    """
    root = Path(__file__).resolve().parents[1]
    modules = []
    for path in sorted(root.glob('*.py')):
        if path.name.startswith(('smoke_', 'check_')):
            continue
        modules.append((path.name, ast.parse(path.read_text(encoding='utf-8'))))
    executescript_bodies = set()
    for _, tree in modules:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'executescript'):
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        executescript_bodies.add(argument.value)
    shipped = []
    table_name = re.compile(r'\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z0-9_]+)\s*\(', re.I)
    for name, tree in modules:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value.lstrip().upper().startswith('CREATE TABLE IF NOT EXISTS')
                    and '(' in node.value and node.value not in executescript_bodies):
                # The whitelist check comes FIRST: the bridge's own bootstrap
                # DDL is native Postgres (BOOLEAN, CHECK) and never passes the
                # SQLite-shaped gate by design - it runs raw against the server.
                match = table_name.match(node.value)
                if (name, match.group(1) if match else None) in NATIVE_POSTGRES_DDL:
                    continue
                schema_info(node.value)  # the gate: must not raise
                shipped.append((name, node.lineno, node.value))
    return shipped


class ShippedCloudGateSweep(unittest.TestCase):
    """No shipped module may hand the cloud CREATE gate a DDL it rejects.

    This is the sweep that would have turned 1.3.94's startup crash red in
    CI: every ensure_tables statement the runtime ships must survive
    cloud_sql.schema_info (the gate runs on every cloud CREATE, even against
    tables already registered) and translate into server DDL.
    """

    def test_every_shipped_create_statement_survives_the_gate(self):
        statements = shipped_ddl_literals()
        self.assertTrue(statements)  # the sweep itself must see the corpus
        for name, line, ddl in statements:
            with self.subTest(module=name, line=line):
                info = schema_info(ddl)  # must not raise
                self.assertTrue(create_sql(info))

    def test_the_deferrals_table_is_in_the_swept_corpus(self):
        names = {info['name'] for _, _, ddl in shipped_ddl_literals()
                 for info in [schema_info(ddl)]}
        self.assertIn('inbox_history_deferrals', names)


if __name__ == '__main__':
    unittest.main()
