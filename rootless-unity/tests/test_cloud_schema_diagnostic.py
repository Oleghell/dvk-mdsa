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

if __name__=='__main__':unittest.main()
