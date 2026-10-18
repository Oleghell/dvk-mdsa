import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from module_evidence import EVIDENCE_FUNCTION, MODULES, EXPORTS, validate_evidence, classify_evidence


def empty():
    return {'maps_available':True,'maps_complete':True,'map_line_count':0,'map_limit_reached':False,
            'mapped_ranges':{n:0 for n in MODULES},'apk_mappings_present':False,
            'global_export_api_available':True,'global_exports':{n:False for n in EXPORTS},'global_export_errors':0}


def javascript(lines, *, available=True, repeat=False, export=False):
    code=EVIDENCE_FUNCTION+'\n'+f'''
const lines={json.dumps(lines)};
let cursor=0;let closed=false;
class File {{constructor(path,mode) {{
  if(path !== '/proc/self/maps' || mode !== 'r') throw Error('wrong path');
  if(!{str(available).lower()}) throw Error('permission denied');
}}
readLine() {{return {str(repeat).lower()} ? lines[0] : (cursor < lines.length ? lines[cursor++] : '');}}
close() {{closed=true;}} }};
const Module={{findGlobalExportByName(name) {{return {str(export).lower()} && name === 'il2cpp_domain_get' ? {{}} : null;}}}};
const result=moduleEvidence();
if({str(available).lower()} && !closed) throw Error('file not closed');
console.log(JSON.stringify(result));
'''
    result=subprocess.run([shutil.which('node'),'-e',code],capture_output=True,text=True,check=True,timeout=10)
    return validate_evidence(json.loads(result.stdout))


@unittest.skipUnless(shutil.which('node'),'Node needed for isolated JS parser test')
class Parser(unittest.TestCase):
    def test_sanitized_mapping_metadata_and_deleted_suffix(self):
        lines=['1000-2000 r-xp 0000 00:01 1 /data/app/private/pkg/lib/arm64/libunity.so',
               '3000-4000 r-xp 0000 00:01 2 /data/app/private/pkg/lib/arm64/libil2cpp.so (deleted)',
               '5000-6000 r--p 0000 00:01 3 /data/user/0/drug.vokrug/SECRET-PROFILE.db',
               '7000-8000 r--p 0000 00:01 4 /data/app/private/pkg/base.apk']
        value=javascript(lines)
        self.assertTrue(value['maps_complete']);self.assertTrue(value['apk_mappings_present'])
        self.assertEqual(value['mapped_ranges']['libunity.so'],1)
        self.assertEqual(value['mapped_ranges']['libil2cpp.so'],1)
        for secret in ('SECRET-PROFILE','1000-2000','/data/app','private/pkg'):
            self.assertNotIn(secret,json.dumps(value))
    def test_empty_string_eof_is_complete(self):
        value=javascript([])
        self.assertTrue(value['maps_complete']);self.assertEqual(value['map_line_count'],0)
    def test_permission_denial_does_not_request_root(self):
        value=javascript([],available=False)
        self.assertFalse(value['maps_available']);self.assertFalse(value['maps_complete'])
    def test_line_limit_bounds_work(self):
        value=javascript(['1000-2000 rw-p 0000 00:00 0 [anon]'],repeat=True)
        self.assertTrue(value['map_limit_reached']);self.assertFalse(value['maps_complete'])
        self.assertEqual(value['map_line_count'],20000)
    def test_long_line_stops_without_leaking_content(self):
        value=javascript(['PRIVATE'+'x'*9000])
        self.assertTrue(value['map_limit_reached']);self.assertEqual(value['map_line_count'],0)
        self.assertNotIn('PRIVATE',json.dumps(value))
    def test_global_export_lookup_returns_only_boolean(self):
        value=javascript([],export=True)
        self.assertTrue(value['global_exports']['il2cpp_domain_get'])
        self.assertFalse(value['global_exports']['il2cpp_thread_attach'])


class Schema(unittest.TestCase):
    def test_reject_arbitrary_fields_addresses_or_paths(self):
        for value in ({**empty(),'address':'0x123'},{**empty(),'path':'private'}, {**empty(),'map_line_count':True}):
            with self.assertRaises(ValueError):validate_evidence(value)
    def test_classification_mapped_not_enumerated(self):
        value=empty();value['mapped_ranges']['libunity.so']=3;value['mapped_ranges']['libil2cpp.so']=4
        self.assertEqual(classify_evidence({n:False for n in MODULES},value),'engine-mapped-not-fully-enumerated')
    def test_incomplete_not_misreported_as_missing(self):
        value=empty();value['maps_complete']=False;value['map_limit_reached']=True
        self.assertEqual(classify_evidence({n:False for n in MODULES},value),'module-evidence-incomplete')
    def test_no_native_function_or_user_data_reads(self):
        self.assertIn("new File('/proc/self/maps','r')",EVIDENCE_FUNCTION)
        for text in ('NativeFunction','Interceptor','readByteArray','/data/user','/data/data','sendMessage','Memory.read','Module.load'):
            self.assertNotIn(text,EVIDENCE_FUNCTION)


if __name__=='__main__':unittest.main()
