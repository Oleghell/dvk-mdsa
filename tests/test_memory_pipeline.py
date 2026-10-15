import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from chat_core import InputError, process_memory_document
from synthetic_image import scene
ROOT=Path(__file__).resolve().parents[1]

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.doc=json.loads((ROOT/'examples/synthetic-chat.json').read_text(encoding='utf-8'))
        image=io.BytesIO();scene().save(image,format='PNG')
        self.doc.update(image_png_base64=base64.b64encode(image.getvalue()).decode('ascii'),roi=[0,0,800,600])
    def test_group_without_disk(self):
        result=process_memory_document(self.doc)
        self.assertEqual(result['message_candidates'][0]['source_indices'],[0,1])
        self.assertEqual(result['bubble_detection']['candidate_count'],3)
    def test_image_not_echoed(self):
        result=process_memory_document(self.doc)
        self.assertNotIn('image_png_base64',json.dumps(result))
    def test_bad_base64(self):
        self.doc['image_png_base64']='!!!'
        with self.assertRaises(InputError):process_memory_document(self.doc)
    def test_bad_png(self):
        self.doc['image_png_base64']=base64.b64encode(b'not png').decode()
        with self.assertRaises(InputError):process_memory_document(self.doc)
    def test_dimension_mismatch(self):
        self.doc['image_width']=799
        with self.assertRaises(InputError):process_memory_document(self.doc)
    def test_missing_roi(self):
        del self.doc['roi']
        with self.assertRaises(InputError):process_memory_document(self.doc)
    def test_memory_cli(self):
        run=subprocess.run([sys.executable,str(ROOT/'chat_core.py')],input=json.dumps(self.doc).encode(),capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(len(json.loads(run.stdout)['message_candidates']),2)
    def test_no_input_mutation(self):
        before=json.dumps(self.doc,sort_keys=True)
        process_memory_document(self.doc)
        self.assertEqual(json.dumps(self.doc,sort_keys=True),before)
