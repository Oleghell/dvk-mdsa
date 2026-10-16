"""Live-control fixtures + adversarial offline images. No accounts or device I/O."""
import base64
from io import BytesIO
import json
from pathlib import Path
import random
import unittest
from PIL import Image, ImageDraw, ImageEnhance
from filter_state import online_filter_state, classify_switch, SWITCH_BOX, LABEL_BOX, FILTER_BOX

ROOT=Path(__file__).parent
FIX=json.loads((ROOT/'session-ui-fixtures.json').read_text())
CASES=json.loads((ROOT/'filter-control-cases.json').read_text())['cases']

def decode(item):return Image.open(BytesIO(base64.b64decode(item['png']))).convert('RGB')
def png(im):
    b=BytesIO();im.save(b,format='PNG');return b.getvalue()
def frame(crop):
    im=Image.new('RGB',(900,1600),'black')
    for key in ['filter','online_label']:
        item=FIX[key];im.paste(decode(item),tuple(item['box'][:2]))
    im.paste(crop,SWITCH_BOX[:2]);return im

class FilterStateTests(unittest.TestCase):
    def test_all_saved_labelled_real_controls(self):
        self.assertEqual(len(CASES),6)
        for c in CASES:
            with self.subTest(c=c['label']):
                self.assertEqual(online_filter_state(png(frame(decode(c)))),c['expected'])
    def test_all_on_captures_match_without_whole_crop_hash(self):
        values=[c['png'] for c in CASES if c['expected']=='on']
        self.assertGreaterEqual(len(set(values)),3)
        for c in CASES:
            if c['expected']=='on':self.assertEqual(classify_switch(decode(c)),'on')
    def test_true_off_is_never_on(self):
        for c in CASES:
            if c['expected']=='off':self.assertEqual(classify_switch(decode(c)),'off')
    def test_wrong_label_and_wrong_dialog_refused(self):
        for box in [LABEL_BOX,FILTER_BOX]:
            im=frame(decode(FIX['online']));im.paste('black',box)
            self.assertEqual(online_filter_state(png(im)),'unknown')
    def test_label_pixel_change_not_tolerated(self):
        im=frame(decode(FIX['online']));im.putpixel(LABEL_BOX[:2],(255,0,255))
        self.assertEqual(online_filter_state(png(im)),'unknown')
    def test_switch_alone_on_wrong_page_not_enough(self):
        im=Image.new('RGB',(900,1600));im.paste(decode(FIX['online']),SWITCH_BOX[:2])
        self.assertEqual(online_filter_state(png(im)),'unknown')
    def test_invalid_and_wrong_resolution_refused(self):
        for data in [b'',b'not png',png(Image.new('RGB',(450,800))),png(Image.new('RGB',(1600,900)))]:
            self.assertEqual(online_filter_state(data),'unknown')
    def test_solid_colours_refused(self):
        for colour in ['white','black',(0,178,165),(49,52,49),(24,28,33)]:
            self.assertEqual(classify_switch(Image.new('RGB',(102,63),colour)),'unknown')
    def test_missing_thumb_and_track_refused(self):
        for key in ['online','offline']:
            for box in [(0,0,102,63),(12,16,90,46),(0,0,40,63),(62,0,102,63)]:
                im=decode(FIX[key]);im.paste((24,28,33),box)
                self.assertEqual(classify_switch(im),'unknown')
    def test_inverted_track_thumb_combinations_refused(self):
        for key in ['online','offline']:
            im=decode(FIX[key]).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            self.assertEqual(classify_switch(im),'unknown')
    def test_intermediate_thumb_positions_refused(self):
        for center in range(35,68):
            im=Image.new('RGB',(102,63),(24,28,33));d=ImageDraw.Draw(im)
            d.rounded_rectangle((0,0,101,62),31,fill=(0,178,165))
            d.ellipse((center-26,5,center+26,57),fill='white')
            self.assertEqual(classify_switch(im),'unknown',center)
    def test_extra_white_blob_refused(self):
        for key in ['online','offline']:
            im=decode(FIX[key]);ImageDraw.Draw(im).rectangle((3,3,6,6),fill='white')
            self.assertEqual(classify_switch(im),'unknown')
    def test_shifted_or_scaled_control_refused(self):
        for dx,dy in [(4,0),(-4,0),(0,4),(0,-4)]:
            im=Image.new('RGB',(102,63),(24,28,33));im.paste(decode(FIX['online']),(dx,dy))
            self.assertEqual(classify_switch(im),'unknown')
        for size in [(90,55),(110,70)]:
            im=Image.new('RGB',(102,63),(24,28,33));im.paste(decode(FIX['online']).resize(size),(0,0))
            self.assertEqual(classify_switch(im),'unknown')
    def test_dimmed_loading_or_bright_overlay_refused(self):
        for ratio in [0.25,0.5,0.8,1.3,1.6]:
            im=ImageEnhance.Brightness(decode(FIX['online'])).enhance(ratio)
            self.assertEqual(classify_switch(im),'unknown')
    def test_light_theme_refused(self):
        im=decode(FIX['online']);px=im.load()
        for y in range(63):
            for x in range(102):
                if max(px[x,y])<70:px[x,y]=(240,240,240)
        self.assertEqual(classify_switch(im),'unknown')
    def test_one_bad_core_pixel_refuses(self):
        for xy in [(71,31),(20,31),(1,1)]:
            im=decode(FIX['online']);im.putpixel(xy,(255,0,255))
            self.assertEqual(classify_switch(im),'unknown')
    def test_antialias_edge_variations_dont_relabel_off(self):
        rng=random.Random(142)
        # Fixed seed, 250 independent noisy OFF frames, up to 80 altered pixels.
        for _ in range(250):
            im=decode(FIX['offline'])
            for i in range(rng.randint(1,80)):
                im.putpixel((rng.randrange(102),rng.randrange(63)),tuple(rng.randrange(256) for _ in range(3)))
            self.assertNotEqual(classify_switch(im),'on')
    def test_random_images_are_unknown(self):
        rng=random.Random(421)
        for _ in range(25):
            im=Image.frombytes('RGB',(102,63),rng.randbytes(102*63*3))
            self.assertEqual(classify_switch(im),'unknown')

if __name__=='__main__':unittest.main()
