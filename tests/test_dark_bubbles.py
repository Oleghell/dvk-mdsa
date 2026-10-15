"""Synthetic known-dark-palette regressions. No user image/text is embedded."""
import unittest
from PIL import Image, ImageDraw
from bubble_detector import detect

BG=(24,28,33)
IN=(41,44,49)
OUT=(0,44,41)
def scene(scale=1,delta=0):
    color=lambda rgb: tuple(min(255,c+delta) for c in rgb)
    image=Image.new('RGB',(800*scale,600*scale),color(BG))
    draw=ImageDraw.Draw(image)
    for coords,fill in [((380,30,769,169),OUT),((20,220,359,289),IN),((20,330,359,399),IN)]:
        draw.rounded_rectangle(tuple(n*scale for n in coords),radius=12*scale,fill=color(fill))
    return image
class DarkTests(unittest.TestCase):
    def test_known_palette(self):
        self.assertEqual([b['direction'] for b in detect(scene(),[0,0,800,600])],['outgoing_candidate','incoming_candidate','incoming_candidate'])
    def test_scales(self):
        for s in (1,2,3):
            with self.subTest(scale=s): self.assertEqual(len(detect(scene(s),[0,0,800*s,600*s])),3)
    def test_small_shade_shift(self):
        self.assertEqual(len(detect(scene(delta=5),[0,0,800,600])),3)
    def test_blank_backgrounds(self):
        for bg in (BG,IN,OUT,(35,35,40)):
            with self.subTest(bg=bg): self.assertEqual(detect(Image.new('RGB',(800,600),bg),[0,0,800,600]),[])
    def test_white_text_not_incoming(self):
        im=Image.new('RGB',(800,600),BG)
        ImageDraw.Draw(im).rectangle((20,220,359,289),fill='white')
        self.assertEqual(detect(im,[0,0,800,600]),[])
    def test_profile_above_explicit_roi_excluded(self):
        im=scene();ImageDraw.Draw(im).rounded_rectangle((20,0,359,20),radius=4,fill=IN)
        result=detect(im,[0,25,800,550])
        self.assertEqual(len(result),3);self.assertTrue(all(b['bounds'][1]>=25 for b in result))
    def test_small_separator_not_a_bubble(self):
        im=scene();ImageDraw.Draw(im).line((20,440,770,440),fill=OUT,width=2)
        self.assertEqual(len(detect(im,[0,0,800,600])),3)
    def test_light_text_holes(self):
        im=scene();draw=ImageDraw.Draw(im)
        for x in range(400,650,20): draw.rectangle((x,55,x+9,71),fill='white')
        self.assertEqual(len(detect(im,[0,0,800,600])),3)
    def test_wrong_side(self):
        im=Image.new('RGB',(800,600),BG);ImageDraw.Draw(im).rectangle((20,30,300,100),fill=OUT)
        self.assertEqual(detect(im,[0,0,800,600]),[])
    def test_clipped(self): self.assertEqual(len(detect(scene(),[0,70,800,530])),2)
    def test_one_pixel_gap_not_merged(self):
        im=Image.new('RGB',(800,600),BG);draw=ImageDraw.Draw(im)
        draw.rectangle((20,220,359,289),fill=IN);draw.rectangle((20,291,359,360),fill=IN)
        self.assertFalse(any(b['bounds'][1]<290 and b['bounds'][1]+b['bounds'][3]>291 for b in detect(im,[0,0,800,600])))
    def test_deterministic(self): self.assertEqual(detect(scene(),[0,0,800,600]),detect(scene(),[0,0,800,600]))

if __name__=='__main__':unittest.main()
