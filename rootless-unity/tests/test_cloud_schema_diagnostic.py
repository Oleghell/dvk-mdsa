import sys
import types
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import cloud_database as cloud

class MissingRelation(Exception):
    sqlstate = '42P01'
    def __init__(self, schema, table):
        self.diag = types.SimpleNamespace(schema_name=schema, table_name=table)

class MessageOnlyRelation(Exception):
    """Real PostgreSQL 42P01: no diag schema/table fields, message only."""
    sqlstate = '42P01'
    def __init__(self, message):
        super().__init__(message)
        self.diag = types.SimpleNamespace(schema_name=None, table_name=None, message_primary=message)

class MissingRaw:
    def __init__(self, error): self.error=error
    def execute(self, *args, **kwargs): raise self.error

class CloudSchemaDiagnosticTests(unittest.TestCase):
    def _diagnostic(self, schema, table):
        runtime=types.SimpleNamespace(phase=lambda _name:nullcontext())
        db=cloud.Connection(MissingRaw(MissingRelation(schema,table)),{}, {})
        with patch.dict(sys.modules, assistant_runtime=runtime):
            with self.assertRaises(cloud.CloudDatabaseError) as caught:
                db._run('SELECT * FROM missing_relation')
        return cloud.diagnostic(caught.exception)

    def test_namespaced_known_relation_is_redacted(self):
        result=self._diagnostic('dvk_private','i'+'a'*20+'_m5563__chain_dialogs')
        self.assertEqual(result,dict(code='cloud-schema-missing',operation='read',automatic_retry=False,relation='chain_dialogs'))
        self.assertNotIn('a'*20,str(result))

    def test_unrecognized_relation_is_not_exported_verbatim(self):
        result=self._diagnostic('dvk_private','i'+'b'*20+'_m5563__private_identifier')
        self.assertEqual(result['relation'],'other-application-table')
        self.assertNotIn('private_identifier',str(result))

    def test_other_schema_name_is_not_exported(self):
        result=self._diagnostic('public','users')
        self.assertNotIn('relation',result)

    def test_cleaner_rejects_unredacted_or_unrelated_relation(self):
        base=dict(code='cloud-schema-missing',operation='read',automatic_retry=False)
        self.assertIsNone(cloud.clean_diagnostic(dict(base,relation='users_private')))
        self.assertIsNone(cloud.clean_diagnostic(dict(code='cloud-database-unavailable',operation='read',automatic_retry=False,relation='chain_dialogs')))

    def _message_diagnostic(self, message):
        runtime=types.SimpleNamespace(phase=lambda _name:nullcontext())
        db=cloud.Connection(MissingRaw(MessageOnlyRelation(message)),{}, {})
        with patch.dict(sys.modules, assistant_runtime=runtime):
            with self.assertRaises(cloud.CloudDatabaseError) as caught:
                db._run('SELECT * FROM missing_relation')
        return cloud.diagnostic(caught.exception)

    def test_message_only_namespaced_relation_is_redacted(self):
        # Real 42P01 carries no diag schema/table fields; the parsed message
        # must still export the redacted logical table name.
        result=self._message_diagnostic('relation "i'+'c'*20+'_m5563__chain_seen" does not exist')
        self.assertEqual(result['relation'],'chain_seen')
        self.assertNotIn('c'*20,str(result))

    def test_message_only_unqualified_relation_uses_session_schema(self):
        result=self._message_diagnostic('relation "inbox_reply_policy" does not exist')
        self.assertEqual(result['relation'],'inbox_reply_policy')

    def test_message_only_foreign_qualified_relation_is_not_exported(self):
        result=self._message_diagnostic('relation "public.users" does not exist')
        self.assertNotIn('relation',result)

    def test_message_only_unknown_relation_is_impersonal(self):
        result=self._message_diagnostic('relation "i'+'d'*20+'_m5563__private_identifier" does not exist')
        self.assertEqual(result['relation'],'other-application-table')
        self.assertNotIn('private_identifier',str(result))

    def test_message_without_relation_name_exports_nothing(self):
        result=self._message_diagnostic('syntax error PRIVATE')
        self.assertNotIn('relation',result)

if __name__=='__main__':unittest.main()
