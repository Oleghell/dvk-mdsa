import io
import unittest
from unittest.mock import patch
from PIL import Image
from host_dark_reader import bright_text_mask,read_screen
from test_dark_bubbles import scene
from chat_core import InputError

class HostDarkTests(unittest.TestCase):
    def test_white_text_kept(self):
        self.assertEqual(bright_text_mask(Image.new('RGB',(10,10),'white')).getpixel((40,40)),0)
    def test_grey_labels_masked(self):
        self.assertEqual(bright_text_mask(Image.new('RGB',(10,10),(107,105,115))).getpixel((40,40)),255)
    def test_dark_background_masked(self):
        self.assertEqual(bright_text_mask(Image.new('RGB',(10,10),(24,28,33))).getpixel((40,40)),255)
    def test_ocr_words_not_silently_deleted(self):
        class Result:
            returncode=0
            stdout=b'level\tconf\ttext\n5\t97\t00:57\n5\t22\ta\n'
        with patch('host_dark_reader.subprocess.run',return_value=Result()) as runner:
            result=read_screen(scene(),[0,0,800,600])
        self.assertEqual(runner.call_count,3)
        self.assertEqual(result['message_candidates'][0]['text'],'00:57 a')
        self.assertTrue(result['message_candidates'][0]['words'][1]['uncertain'])
        self.assertFalse(result['message_candidates'][0]['text_verified'])
        self.assertFalse(result['automatic_reply_enabled']);self.assertEqual(result['messages_sent'],0)
        self.assertNotIn('image',result)
    def test_engine_error(self):
        with patch('host_dark_reader.subprocess.run',side_effect=OSError('not installed')):
            with self.assertRaises(InputError):read_screen(scene(),[0,0,800,600])

if __name__=='__main__':unittest.main()
