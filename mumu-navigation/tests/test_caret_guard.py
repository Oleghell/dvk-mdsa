from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from mumu_bridge import input_context_sha256, content_pixel_sha256, AdbReader, BridgeError

def frame(caret=False,changed=None):
    im=Image.new('RGB',(900,1600),'white')
    if caret:im.paste('black',(160,1497,161,1535))
    if changed:im.putpixel(changed,(0,0,0))
    b=BytesIO();im.save(b,format='PNG');return b.getvalue()

class CaretTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name)/'adb.exe';p.touch();self.r=AdbReader(p);self.r.helper_ready=True
    def tearDown(self):self.tmp.cleanup()
    def test_caret_only_normalized_in_input_guard(self):
        self.assertEqual(input_context_sha256(frame()),input_context_sha256(frame(True)))
        self.assertNotEqual(content_pixel_sha256(frame()),content_pixel_sha256(frame(True)))
    def test_name_history_and_send_button_still_protected(self):
        for pixel in [(120,80),(250,500),(820,1515),(151,1490),(748,1490),(160,1544)]:
            with self.subTest(pixel=pixel):self.assertNotEqual(input_context_sha256(frame()),input_context_sha256(frame(changed=pixel)))
    def test_finish_uses_selected_variant_and_zero_y(self):
        sha=input_context_sha256(frame())
        with patch.object(self.r,'screen',return_value=frame(True)),patch.object(self.r,'_instrument',return_value=('input_injected','')) as call:
            result=self.r.finish_greeting_input(sha,0)
        call.assert_called_once_with('finish_input',sha,0,0)
        self.assertFalse(result['windows_escape_injected']);self.assertFalse(result['ui_transition_verified'])
    def test_changed_outside_field_blocks_finish(self):
        with patch.object(self.r,'screen',return_value=frame(changed=(300,300))),patch.object(self.r,'_instrument') as call:
            with self.assertRaises(BridgeError):self.r.finish_greeting_input(input_context_sha256(frame()),0)
        call.assert_not_called()
    def test_wrong_native_text_refusal_does_not_claim_transition(self):
        with patch.object(self.r,'screen',return_value=frame()),patch.object(self.r,'_instrument',return_value=('denied_text','')):
            with self.assertRaises(BridgeError):self.r.finish_greeting_input(input_context_sha256(frame()),0)
        self.assertFalse(self.r.action_uncertain)
    def test_unknown_back_result_stops_navigation(self):
        with patch.object(self.r,'screen',return_value=frame()),patch.object(self.r,'_instrument',return_value=('indeterminate_after_attempt','')):
            with self.assertRaises(BridgeError):self.r.finish_greeting_input(input_context_sha256(frame()),0)
        self.assertTrue(self.r.action_uncertain)
    def test_no_arbitrary_greeting_in_finish(self):
        with self.assertRaises(BridgeError):self.r.finish_greeting_input(input_context_sha256(frame()),'anything')
    def test_shared_action_limit_applies(self):
        self.r.action_attempts=30
        with self.assertRaises(BridgeError):self.r.finish_greeting_input(input_context_sha256(frame()),0)

if __name__=='__main__':unittest.main()
