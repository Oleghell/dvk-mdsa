import base64
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from mumu_bridge import profile_guard, content_pixel_sha256, AdbReader, BridgeError, SERIAL, HELPER_COMPONENT

def image(gift='red', other=False, bad_button=False):
    im=Image.new('RGB',(900,1600),'white')
    icon=Image.open(BytesIO(base64.b64decode((Path(__file__).resolve().parents[1]/'button-fixture-base64.txt').read_text()))).convert('RGB')
    im.paste(icon,(274,1468));im.paste(gift,(727,830,879,981))
    if other: im.putpixel((30,1000),(0,0,0))
    if bad_button:im.putpixel((321,1515),(255,255,255))
    out=BytesIO();im.save(out,format='PNG');return out.getvalue()

class ProfileGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();adb=Path(self.tmp.name)/'adb.exe';adb.touch();self.r=AdbReader(adb);self.r.helper_ready=True
        self.a=image();self.sha=profile_guard(self.a)['profile_sha256']
    def tearDown(self):self.tmp.cleanup()
    def test_gift_changes_do_not_change_profile_hash(self):
        self.assertEqual(self.sha,profile_guard(image('blue'))['profile_sha256'])
        self.assertNotEqual(content_pixel_sha256(self.a),content_pixel_sha256(image('blue')))
    def test_exact_lower_button_matches(self): self.assertTrue(profile_guard(self.a)['button_matches'])
    def test_button_change_refused(self):
        with patch.object(self.r,'screen',return_value=image(bad_button=True)),patch.object(self.r,'_instrument') as call:
            with self.assertRaises(BridgeError):self.r.open_profile_chat(self.sha)
        call.assert_not_called()
    def test_profile_name_region_change_refused(self):
        with patch.object(self.r,'screen',return_value=image(other=True)),patch.object(self.r,'_instrument') as call:
            with self.assertRaises(BridgeError):self.r.open_profile_chat(self.sha)
        call.assert_not_called()
    def test_gift_change_allows_only_fixed_cloud_coordinate(self):
        with patch.object(self.r,'screen',return_value=image('blue')),patch.object(self.r,'_instrument',return_value=('input_injected','')) as call:
            r=self.r.open_profile_chat(self.sha)
        call.assert_called_once_with('profile_chat',self.sha,321,1515)
        self.assertEqual(r['fixed_target'],[321,1515]);self.assertFalse(r['ui_transition_verified'])
    def test_no_arbitrary_coordinates_in_adb_profile_operation(self):
        args=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','op','profile_chat','-e','expected_content_sha256',self.sha,'-e','x','800','-e','y','950',HELPER_COMPONENT]
        with patch('subprocess.run') as run:
            with self.assertRaises(BridgeError):self.r._run(args)
        run.assert_not_called()
    def test_unknown_result_stops_both_navigation_paths(self):
        with patch.object(self.r,'screen',return_value=self.a),patch.object(self.r,'_instrument',return_value=('indeterminate_after_attempt','')):
            with self.assertRaises(BridgeError):self.r.open_profile_chat(self.sha)
        with self.assertRaises(BridgeError):self.r.navigate('back','0'*64)
        with self.assertRaises(BridgeError):self.r.open_profile_chat(self.sha)
    def test_shared_budget(self):
        self.r.action_attempts=50
        with self.assertRaises(BridgeError):self.r.open_profile_chat(self.sha)
    def test_android_refusal_consumes_budget_not_uncertainty(self):
        with patch.object(self.r,'screen',return_value=self.a),patch.object(self.r,'_instrument',return_value=('denied_context_or_layout','')):
            with self.assertRaises(BridgeError):self.r.open_profile_chat(self.sha)
        self.assertFalse(self.r.action_uncertain);self.assertEqual(self.r.action_attempts,1)
    def test_mask_does_not_cover_lower_controls(self):
        im=Image.open(BytesIO(self.a)).convert('RGB');im.putpixel((400,1515),(0,0,0));out=BytesIO();im.save(out,format='PNG')
        self.assertNotEqual(self.sha,profile_guard(out.getvalue())['profile_sha256'])
    def test_profile_back_uses_no_touch_coordinates(self):
        with patch.object(self.r,'screen',return_value=image('blue')),patch.object(self.r,'_instrument',return_value=('input_injected','')) as call:
            result=self.r.leave_profile(self.sha)
        call.assert_called_once_with('profile_back',self.sha,0,0)
        self.assertIsNone(result['fixed_target'])
    def test_background_around_circle_is_not_part_of_button_anchor(self):
        im=Image.open(BytesIO(self.a)).convert('RGB')
        im.putpixel((274,1468),(17,29,43))
        out=BytesIO();im.save(out,format='PNG')
        changed=out.getvalue()
        self.assertTrue(profile_guard(changed)['button_matches'])
        # Background is still part of the contextual guard: no broad new mask.
        self.assertNotEqual(self.sha,profile_guard(changed)['profile_sha256'])
    def test_inner_button_change_still_rejected(self):
        self.assertFalse(profile_guard(image(bad_button=True))['button_matches'])
    def test_wrong_dimensions_refused(self):
        im=Image.new('RGB',(450,800));out=BytesIO();im.save(out,format='PNG')
        with self.assertRaises(BridgeError):profile_guard(out.getvalue())

if __name__=='__main__':unittest.main()
