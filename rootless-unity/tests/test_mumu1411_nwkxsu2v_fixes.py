"""Reports dropmefiles NwkXSU2V (v1.3.110, ports 5559/5561/5563): the startup-killing catalog phantoms.

Every port stopped at stage journal-initialization as CloudDatabaseError with
database=dict(code='cloud-schema-missing',operation='write',
relation='chain_dialogs'). Root cause chain, pinned here end to end:

  1. the 1.3.110 database cleanup dropped the physical legacy m<port>__*
     tables while their _dvk_schema catalog rows stayed (130 phantoms);
  2. the app-level sqlite_master view was served FROM that bare catalog, so
     peer-policy backfill_contacts() saw the phantom m<port>__chain_dialogs
     names and authored INSERT ... SELECT FROM a table that cannot exist;
  3. PostgreSQL answers 42P01, the write-side hard stop fires and every port
     of every installation dies on every start (last-startup.json shape).

Families pinned:
  - the sqlite_master translation joins pg_class/pg_namespace, so the catalog
    view mirrors PHYSICAL reality: a catalog row without its table never
    surfaces, while another process's committed table stays visible;
  - the shared catalog itself is healed at journal-initialization BEFORE any
    sqlite_master consumer runs - one worker's start repairs the dataset for
    every other worker and installation on it;
  - memory_snapshot iterates only physically existing tables;
  - the maintenance clean() heals the catalog after dropping tables (and
    status() makes phantom drift visible), so the workflow that created the
    phantoms can never leave them behind again;
  - the exact NwkXSU2V diagnostic shape (legacy m<port>__ relation,
    message-only 42P01, operation write) stays nameable and redacted.
"""
import importlib.util
import sys
import types
import unittest
from contextlib import nullcontext
from inspect import getsource
from pathlib import Path
from unittest.mock import Mock, patch

import cloud_database as cloud
import mumu_peer_policy as policy
import mumu_store

RUNTIME = types.SimpleNamespace(phase=lambda _name: nullcontext())


class Rows:
    """psycopg-shaped cursor: fetchall only."""
    def __init__(self, rows):
        self.rows = list(rows)
        self.description = None
        self.rowcount = -1
    def fetchall(self):
        return self.rows


class MessageOnlyRelation(Exception):
    """Real PostgreSQL 42P01: no diag schema/table fields, message only."""
    sqlstate = '42P01'
    def __init__(self, message):
        super().__init__(message)
        self.diag = types.SimpleNamespace(schema_name=None, table_name=None, message_primary=message)


class RecordingRaw:
    """Fake PostgreSQL: records every statement, answers catalog queries."""
    closed = False
    def __init__(self, real_tables=()):
        self.real = list(real_tables)
        self.queries = []
    def execute(self, sql, params=None, **kwargs):
        self.queries.append((sql, params))
        if sql.startswith('SELECT s.name FROM _dvk_schema'):
            wanted = params[1] if params and len(params) == 2 and isinstance(params[1], str) else None
            return Rows([(name,) for name in self.real if wanted is None or name == wanted])
        return Rows([])
    def close(self):
        pass


class RaisingRaw(RecordingRaw):
    """The broken 1.3.110 database: any phantom reference dies as 42P01."""
    def __init__(self, real_tables=()):
        super().__init__(real_tables)
    def execute(self, sql, params=None, **kwargs):
        if 'm5557__chain_dialogs' in sql:
            self.queries.append((sql, params))
            raise MessageOnlyRelation('relation "m5557__chain_dialogs" does not exist')
        return super().execute(sql, params, **kwargs)


class SqliteMasterPhysicalTruth(unittest.TestCase):
    """The app-level sqlite_master view mirrors physical reality."""

    def _run(self, sql, params=()):
        raw = RecordingRaw()
        db = cloud.Connection(raw, {}, {})
        with patch.dict(sys.modules, assistant_runtime=RUNTIME):
            db.execute(sql, params)
        return raw

    def test_catalog_listing_joins_the_physical_table_set(self):
        raw = self._run("SELECT name FROM sqlite_master WHERE type='table'")
        sql, params = raw.queries[0]
        self.assertIn('JOIN pg_class c ON c.relname=s.name', sql)
        self.assertIn("c.relkind='r'", sql)
        self.assertIn('pg_namespace', sql)
        self.assertEqual(params, (cloud.SCHEMA,))

    def test_bound_point_check_stays_namespaced_and_physical(self):
        raw = self._run("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", ('manual_actions',))
        sql, params = raw.queries[0]
        self.assertIn('JOIN pg_class c ON c.relname=s.name', sql)
        self.assertIn('AND s.name=%s', sql)
        self.assertEqual(params, (cloud.SCHEMA, 'manual_actions'))

    def test_literal_point_check_stays_namespaced_and_physical(self):
        raw = self._run("SELECT 1 FROM sqlite_master WHERE name='chain_dialogs'")
        sql, params = raw.queries[0]
        self.assertIn('AND s.name=%s', sql)
        self.assertEqual(params, (cloud.SCHEMA, 'chain_dialogs'))

    def test_bare_catalog_listing_is_gone(self):
        # The unverified catalog reads answered phantom names in 1.3.110.
        source = getsource(cloud.Connection.execute)
        self.assertNotIn("'SELECT name FROM _dvk_schema ORDER BY name'", source)
        self.assertNotIn("'SELECT name FROM _dvk_schema WHERE name=%s'", source)


class CatalogSelfHeal(unittest.TestCase):
    """journal-initialization heals the shared catalog before anything reads it."""

    def test_heal_deletes_only_rows_without_a_physical_table(self):
        raw = RecordingRaw()
        db = cloud.Connection(raw, {}, {})
        with patch.dict(sys.modules, assistant_runtime=RUNTIME):
            cloud.heal_catalog(db)
        sql, params = raw.queries[0]
        self.assertIn('DELETE FROM _dvk_schema', sql)
        self.assertIn('NOT EXISTS', sql)
        self.assertIn('pg_class', sql)
        self.assertIn('c.relkind', sql)
        self.assertEqual(params, (cloud.SCHEMA, 'r'))

    def test_local_sqlite_is_untouched(self):
        local = Mock()
        cloud.heal_catalog(local)
        local.assert_not_called()

    def test_store_heals_before_any_sqlite_master_consumer(self):
        source = getsource(mumu_store.SharedStore.__init__)
        self.assertLess(source.index('heal_catalog(db)'), source.index('backfill_contacts(db)'))


class StartupSurvivesPhantomCatalog(unittest.TestCase):
    """The exact NwkXSU2V shape: phantom catalog rows no longer reach SQL."""

    REAL = ['chain_dialogs', 'chain_contact_outbox', 'mumu_peer_blocks',
            'mumu_manual_silences', 'manual_actions']

    def test_backfill_never_authors_sql_against_phantom_names(self):
        # PostgreSQL with the fixed translation hides catalog rows whose table
        # is gone; backfill_contacts then only ever sees REAL names even when
        # _dvk_schema still carries the 130 phantom legacy rows. The write
        # runs inside the caller's journal-initialization transaction exactly
        # as SharedStore.__init__ does it.
        raw = RaisingRaw(self.REAL)
        db = cloud.Connection(raw, {}, {})
        with patch.dict(sys.modules, assistant_runtime=RUNTIME):
            db.execute('BEGIN IMMEDIATE')
            policy.backfill_contacts(db)
            db.execute('COMMIT')
        authored = [sql for sql, _ in raw.queries]
        self.assertTrue(any('INSERT INTO mumu_peer_blocks' in sql for sql in authored))
        for sql in authored:
            self.assertNotIn('m5557__', sql)
            self.assertNotIn('m5559__', sql)
            self.assertNotIn('m5561__', sql)

    def test_the_1_3_110_failure_diagnostic_stays_nameable(self):
        # The last-startup.json database block of all three ports, pinned:
        # a write against a dropped legacy table reports the closed shape.
        runtime = RUNTIME
        db = cloud.Connection(RaisingRaw(self.REAL), {}, {})
        with patch.dict(sys.modules, assistant_runtime=runtime):
            with self.assertRaises(cloud.CloudDatabaseError) as caught:
                db._run('INSERT INTO mumu_peer_blocks SELECT * FROM m5557__chain_dialogs')
        self.assertEqual(cloud.diagnostic(caught.exception),
                         dict(code='cloud-schema-missing', operation='write',
                              automatic_retry=False, relation='chain_dialogs'))
        self.assertNotIn('m5557', str(cloud.diagnostic(caught.exception)))


class MemorySnapshotPhantoms(unittest.TestCase):
    def test_snapshot_iterates_only_physical_tables(self):
        source = getsource(cloud.memory_snapshot)
        self.assertIn('JOIN pg_class c ON c.relname=s.name', source)
        self.assertIn("c.relkind='r'", source)
        self.assertNotIn("'SELECT name,sqlite_sql FROM _dvk_schema ORDER BY name'", source)


def load_maintenance():
    path = Path(__file__).resolve().parents[2] / 'tools' / 'supabase_maintenance.py'
    spec = importlib.util.spec_from_file_location('supabase_maintenance_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MaintenanceCatalogHeal(unittest.TestCase):
    """The workflow that created the phantoms can never leave them behind."""

    def setUp(self):
        self.tool = load_maintenance()

    def test_drop_sql_quotes_every_name(self):
        block = self.tool.drop_sql(['m5557__chain_dialogs', 'm5559__chain_seen'])
        self.assertIn('DROP TABLE IF EXISTS dvk_private."m5557__chain_dialogs";', block)
        self.assertIn('DROP TABLE IF EXISTS dvk_private."m5559__chain_seen";', block)

    def test_catalog_heal_script_is_one_transaction_with_restored_membership(self):
        script = self.tool.catalog_heal_script('dvk_app_d7557edc')
        self.assertTrue(script.startswith('BEGIN;'))
        self.assertTrue(script.rstrip().endswith('COMMIT;'))
        self.assertIn('GRANT dvk_app_d7557edc TO postgres WITH SET TRUE;', script)
        self.assertIn('SET ROLE dvk_app_d7557edc;', script)
        self.assertIn(self.tool.PHANTOM_DELETE, script)
        self.assertIn('RESET ROLE;', script)
        self.assertIn('GRANT dvk_app_d7557edc TO postgres WITH SET FALSE;', script)

    def test_suspicious_role_names_are_rejected(self):
        for name in (None, '', 'x; DROP TABLE dvk_private._dvk_schema',
                     'Public.roles', 'user--inject'):
            self.assertIsNone(self.tool.catalog_heal_script(name), name)

    def test_clean_heals_the_catalog_after_dropping(self):
        source = getsource(self.tool.clean)
        self.assertIn('heal_catalog(token', source)

    def test_status_and_report_surface_phantom_drift(self):
        self.assertIn('PHANTOM_COUNT', getsource(self.tool.collect))
        self.assertIn('phantoms', getsource(self.tool.show))

    def test_phantom_delete_targets_only_rows_without_physical_tables(self):
        sql = self.tool.PHANTOM_DELETE
        self.assertIn('DELETE FROM dvk_private._dvk_schema', sql)
        self.assertIn('NOT EXISTS', sql)
        self.assertIn("n.nspname='dvk_private'", sql)
        self.assertIn("c.relkind='r'", sql)


if __name__ == '__main__':
    unittest.main()
