import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_metadata as m


def ready_metadata():
    return {'stage':'metadata-ready','step':'done','native_calls_performed':True,
        'api_exports':dict.fromkeys(m.EXPORTS,True),'domain_available':True,
        'current_thread_initially_attached':False,'thread_attach_performed':True,
        'thread_detach_confirmed':True,'cleanup_failed':False,'assembly_count':4,
        'assemblies_scanned':4,'metadata_limit_reached':False,
        'known_images':dict.fromkeys(m.IMAGES,False),
        'known_types':dict.fromkeys([t[0] for t in m.TYPES],False),
        'known_methods':dict.fromkeys(m.METHOD_KEYS,False)}


class Metadata(unittest.TestCase):
    def test_valid_ready(self):
        self.assertEqual(m.validate_metadata(ready_metadata())['stage'],'metadata-ready')
    def test_existing_thread_allowed_without_detach(self):
        v=ready_metadata();v.update(current_thread_initially_attached=True,thread_attach_performed=False,thread_detach_confirmed=False)
        m.validate_metadata(v)
    def test_extra_fields_rejected(self):
        v=ready_metadata();v['private']='secret'
        with self.assertRaises(ValueError):m.validate_metadata(v)
    def test_missing_fields_rejected(self):
        v=ready_metadata();del v['step']
        with self.assertRaises(ValueError):m.validate_metadata(v)
    def test_counts_bounded(self):
        for n in (-1,2049,True,1.5,'4'):
            v=ready_metadata();v['assembly_count']=n
            with self.assertRaises(ValueError):m.validate_metadata(v)
    def test_scan_count_cannot_exceed_total(self):
        v=ready_metadata();v['assemblies_scanned']=5
        with self.assertRaises(ValueError):m.validate_metadata(v)
    def test_exact_fixed_maps(self):
        for key in ('known_images','known_types','known_methods','api_exports'):
            v=ready_metadata();v[key]['private']=True
            with self.assertRaises(ValueError):m.validate_metadata(v)
            v=ready_metadata();v[key][next(iter(v[key]))]='private'
            with self.assertRaises(ValueError):m.validate_metadata(v)
    def test_success_requires_valid_call_and_cleanup(self):
        for change in ({'domain_available':False},{'native_calls_performed':False},
                       {'thread_detach_confirmed':False},{'metadata_limit_reached':True},
                       {'cleanup_failed':True},{'assembly_count':0,'assemblies_scanned':0}):
            v=ready_metadata();v.update(change)
            with self.assertRaises(ValueError):m.validate_metadata(v)
    def test_stage_whitelist(self):
        v=ready_metadata();v['stage']='private exception'
        with self.assertRaises(ValueError):m.validate_metadata(v)
    def test_no_managed_invocation_or_hooks(self):
        for name in ('il2cpp_runtime_invoke','il2cpp_runtime_class_init','Interceptor','Java.perform','set_text','setText'):
            self.assertNotIn(name,m.NATIVE_FUNCTION)
        self.assertEqual(len(m.EXPORTS),9)
        self.assertEqual(len(m.TYPES),16)
        self.assertIn('n>2048',m.NATIVE_FUNCTION)
        self.assertIn('j<192',m.NATIVE_FUNCTION)
        self.assertIn('finally',m.NATIVE_FUNCTION)

if __name__=='__main__':unittest.main()
