"""UTF-8 source/fixture I/O must not depend on the Windows ANSI code page."""
import ast
import io
from pathlib import Path
import tempfile
import unittest
from run_encoding_autotests import legacy_cp1252_io

ROOT=Path(__file__).resolve().parents[1]


class TextEncodingTests(unittest.TestCase):
    def test_legacy_simulation_reproduces_the_actual_decode_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'utf8.txt';sample='Нальчик 🙂'
            path.write_bytes(sample.encode('utf-8'))
            with legacy_cp1252_io():
                self.assertEqual(io.text_encoding(None),'cp1252')
                # Deliberately omit encoding only here to prove the simulation.
                with self.assertRaises(UnicodeDecodeError):getattr(path,'read_text')()
                self.assertEqual(path.read_text(encoding='utf-8'),sample)
                path.write_text(sample,encoding='utf-8')
                self.assertEqual(path.read_bytes(),sample.encode('utf-8'))
    def test_all_project_path_text_reads_and_writes_are_explicit(self):
        missing=[]
        for path in ROOT.rglob('*.py'):
            if any(x in path.parts for x in ('out','__pycache__')):continue
            tree=ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('read_text','write_text'):
                    encoding=next((k.value for k in node.keywords if k.arg=='encoding'),None)
                    if not isinstance(encoding,ast.Constant) or encoding.value not in ('utf-8','utf8','ascii'):
                        missing.append(f'{path.relative_to(ROOT)}:{node.lineno}')
        self.assertEqual(missing,[],str(missing))
    def test_affected_sources_and_fixtures_are_readable_under_cp1252_defaults(self):
        paths=[ROOT/'mumu_bridge.py',ROOT/'control-android/test-emulator.py',ROOT/'README.md',ROOT/'tests/session-ui-fixtures.json']
        with legacy_cp1252_io():
            for path in paths:
                self.assertTrue(path.read_text(encoding='utf-8'))
    def test_binary_reads_are_not_changed_by_the_emulation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'binary';raw=bytes(range(256));path.write_bytes(raw)
            with legacy_cp1252_io():self.assertEqual(path.read_bytes(),raw)


if __name__=='__main__':unittest.main()
