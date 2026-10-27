"""Reports 357-362: 1.3.64 aborted run-inbox with cloud-database-permission (read)
because five live chain_exit_notices tables were created by an admin session and
the application role had no privileges on them. The code cannot self-heal another
role's tables, but the exported diagnostic must name the denied logical relation
exactly like 42P01 already does, so the cause is visible from last-monitor alone.
Synthetic only; no live service is contacted."""
import sys
import types
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import cloud_database as cloud


class DeniedRelation(Exception):
    sqlstate = '42501'
    def __init__(self, schema, table):
        self.diag = types.SimpleNamespace(schema_name=schema, table_name=table)


class MessageOnlyDenied(Exception):
    """Real PostgreSQL 42501 message form; diag relation fields may stay empty."""
    sqlstate = '42501'
    def __init__(self, message):
        super().__init__(message)
        self.diag = types.SimpleNamespace(schema_name=None, table_name=None, message_primary=message)


class DeniedRaw:
    def __init__(self, error): self.error=error
    def execute(self, *args, **kwargs): raise self.error


class PermissionDiagnosticTests(unittest.TestCase):
    def _diagnostic(self, error):
        runtime=types.SimpleNamespace(phase=lambda _name:nullcontext())
        db=cloud.Connection(DeniedRaw(error),{}, {})
        with patch.dict(sys.modules, assistant_runtime=runtime):
            with self.assertRaises(cloud.CloudDatabaseError) as caught:
                db._run('SELECT * FROM some_table')
        return cloud.diagnostic(caught.exception)

    def test_diag_fields_export_redacted_logical_name(self):
        result=self._diagnostic(DeniedRelation('dvk_private','i'+'a'*20+'_m5569__chain_exit_notices'))
        self.assertEqual(result,dict(code='cloud-database-permission',operation='read',automatic_retry=False,relation='chain_exit_notices'))
        self.assertNotIn('a'*20,str(result))

    def test_message_only_denied_table_exports_redacted_name(self):
        result=self._diagnostic(MessageOnlyDenied('permission denied for table i'+'b'*20+'_m5569__chain_exit_notices'))
        self.assertEqual(result['relation'],'chain_exit_notices')
        self.assertNotIn('b'*20,str(result))

    def test_message_only_unqualified_denied_table_uses_session_schema(self):
        result=self._diagnostic(MessageOnlyDenied('permission denied for table inbox_reply_policy'))
        self.assertEqual(result['relation'],'inbox_reply_policy')

    def test_message_only_foreign_schema_denied_table_is_not_exported(self):
        result=self._diagnostic(MessageOnlyDenied('permission denied for table public.users'))
        self.assertNotIn('relation',result)

    def test_unrecognized_denied_table_is_impersonal(self):
        result=self._diagnostic(MessageOnlyDenied('permission denied for table i'+'c'*20+'_m5569__private_identifier'))
        self.assertEqual(result['relation'],'other-application-table')
        self.assertNotIn('private_identifier',str(result))

    def test_denied_message_without_relation_exports_nothing(self):
        result=self._diagnostic(MessageOnlyDenied('permission denied for schema PRIVATE'))
        self.assertEqual(result,dict(code='cloud-database-permission',operation='read',automatic_retry=False))

    def test_cleaner_accepts_permission_relation_and_rejects_leaks(self):
        base=dict(code='cloud-database-permission',operation='read',automatic_retry=False)
        self.assertEqual(cloud.clean_diagnostic(dict(base,relation='chain_exit_notices')),
                         dict(base,relation='chain_exit_notices'))
        self.assertIsNone(cloud.clean_diagnostic(dict(base,relation='users_private')))
        self.assertIsNone(cloud.clean_diagnostic(dict(code='cloud-database-unavailable',operation='read',automatic_retry=False,relation='chain_dialogs')))

    def test_preparation_message_names_the_logical_table(self):
        import run_preparation as preparation
        error=cloud.CloudDatabaseError('cloud-database-permission');error.operation='read';error.relation='chain_exit_notices'
        with patch.dict(sys.modules, assistant_runtime=types.SimpleNamespace(phase=lambda _name:nullcontext())):
            recorded=preparation.record(error,'run-inbox')
        self.assertEqual(recorded['database'],dict(code='cloud-database-permission',operation='read',automatic_retry=False,relation='chain_exit_notices'))
        text=preparation.message({'last_preparation_failure':recorded})
        self.assertIn('chain_exit_notices',text);self.assertIn('cloud-database-permission',text)


if __name__=='__main__':unittest.main()
