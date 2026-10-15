import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image, ImageDraw
from bubble_detector import detect
from chat_core import InputError, process
from synthetic_image import scene
ROOT=Path(__file__).resolve().parents[1]

class DetectorTests(unittest.TestCase):
    def test_three_bubbles(self):
        bubbles=detect(scene(),[0,0,800,600])
        self.assertEqual([b['direction'] for b in bubbles],['outgoing_candidate','incoming_candidate','incoming_candidate'])
    def test_scales(self):
        for scale in (1,2,3):
            with self.subTest(scale=scale):
                self.assertEqual(len(detect(scene(scale),[0,0,800*scale,600*scale])),3)
    def test_blank(self):
        for color in ((235,237,242),(255,255,255),(222,245,247),(20,20,20)):
            self.assertEqual(detect(Image.new('RGB',(800,600),color),[0,0,800,600]),[])
    def test_dark_unsupported(self):
        self.assertEqual(detect(scene(theme='dark'),[0,0,800,600]),[])
    def test_clipped_top(self):
        self.assertEqual(len(detect(scene(),[0,70,800,530])),2)
    def test_clipped_bottom(self):
        self.assertEqual(len(detect(scene(),[0,0,800,365])),2)
    def test_clipped_left(self):
        self.assertEqual(len(detect(scene(),[40,0,760,600])),1)
    def test_wrong_side(self):
        im=Image.new('RGB',(800,600),(235,237,242))
        ImageDraw.Draw(im).rectangle((20,30,300,100),fill=(222,245,247))
        self.assertEqual(detect(im,[0,0,800,600]),[])
    def test_small_icons(self):
        im=Image.new('RGB',(800,600),(235,237,242))
        ImageDraw.Draw(im).rectangle((20,30,40,50),fill='white')
        self.assertEqual(detect(im,[0,0,800,600]),[])
    def test_black_text_holes(self):
        im=scene(); draw=ImageDraw.Draw(im)
        for y in (55,95):
            for x in range(400,650,20):draw.rectangle((x,y,x+9,y+16),fill='black')
        self.assertEqual(len(detect(im,[0,0,800,600])),3)
    def test_two_same_sender_separate(self):
        self.assertEqual(sum(b['direction']=='incoming_candidate' for b in detect(scene(),[0,0,800,600])),2)
    def test_roi_offsets(self):
        result=detect(scene(),[0,10,800,550])
        self.assertEqual(len(result),3)
        self.assertLessEqual(abs(result[0]['bounds'][1]-30),2)
    def test_bounds_inside_image(self):
        for b in detect(scene(),[0,0,800,600]):
            x,y,w,h=b['bounds'];self.assertLessEqual(x+w,800);self.assertLessEqual(y+h,600)
    def test_deterministic(self):
        self.assertEqual(detect(scene(),[0,0,800,600]),detect(scene(),[0,0,800,600]))
    def test_invalid_roi(self):
        for roi in ([0,0,801,600],[-1,0,800,600],[0.,0,800,600],[0,0,0,600]):
            with self.subTest(roi=roi),self.assertRaises(InputError):detect(scene(),roi)
    def test_pipeline(self):
        doc=json.loads((ROOT/'examples/synthetic-chat.json').read_text())
        doc['bubbles']=detect(scene(),[0,0,800,600])
        result=process(doc)
        self.assertEqual(len(result['message_candidates']),2)
        self.assertEqual(result['message_candidates'][0]['source_indices'],[0,1])
        self.assertFalse(result['bubble_boundaries_verified'])
        self.assertFalse(result['automatic_reply_enabled'])
    def test_cli_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic.png';scene().save(path)
            run=subprocess.run([sys.executable,str(ROOT/'chat_core.py'),'--image',str(path),'--roi','0','0','800','600','--input',str(ROOT/'examples/synthetic-chat.json')],capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            result=json.loads(run.stdout)
            self.assertEqual(result['bubble_detection']['candidate_count'],3)
    def test_missing_roi_rejected(self):
        run=subprocess.run([sys.executable,str(ROOT/'chat_core.py'),'--image','not-needed.png','--input',str(ROOT/'examples/synthetic-chat.json')],capture_output=True)
        self.assertEqual(run.returncode,2)
        self.assertNotIn(b'Traceback',run.stderr)
