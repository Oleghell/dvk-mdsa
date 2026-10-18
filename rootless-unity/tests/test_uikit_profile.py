from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uikit_profile as p
import native_metadata as m


class Profile(unittest.TestCase):
    def test_fixed_profile_and_references(self):
        self.assertEqual(len(p.TYPES),13);self.assertEqual(len(p.METHODS),29)
        self.assertEqual(p.IMAGES,['Core.dll','DV.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll'])
        keys={t[0] for t in p.TYPES}
        self.assertTrue(all(t in keys for t,_,_ in p.METHODS))
    def test_compiled_script_has_no_actual_managed_invocation(self):
        # set_Text/OnDidClicked are queried metadata names, not calls.
        for bad in ('il2cpp_runtime_invoke','il2cpp_runtime_class_init','Interceptor.attach','Java.perform','sendMessage'):
            self.assertNotIn(bad,p.SCRIPT)
        self.assertNotIn('UnityEngine.UI.Button',p.SCRIPT)
        self.assertIn('UIKit.UIRuntime',p.SCRIPT)
    def test_duplicate_catalog_rejected(self):
        with self.assertRaises(ValueError):m.build_native_function(p.TYPES+p.TYPES[:1],p.METHODS,p.IMAGES)
    def test_dangling_method_rejected(self):
        with self.assertRaises(ValueError):m.build_native_function(p.TYPES,[('Other','Exec',0)],p.IMAGES)
    def test_result_validates_exact_profile_not_legacy(self):
        from test_native_metadata import ready_metadata
        value=ready_metadata()
        value['known_types']=dict.fromkeys([t[0] for t in p.TYPES],False)
        value['known_methods']=dict.fromkeys([f'{t}.{name}/{n}' for t,name,n in p.METHODS],False)
        value['known_images']=dict.fromkeys(p.IMAGES,False)
        p.validate(value)
        with self.assertRaises(ValueError):m.validate_metadata(value)
    def test_source_layout_is_not_runtime_pointer_offset(self):
        # Profile must not embed app addresses or assumed native MethodInfo offsets.
        self.assertNotIn('readPointer()',Path(p.__file__).read_text())
        self.assertNotIn('0x',Path(p.__file__).read_text())


if __name__=='__main__':unittest.main()
