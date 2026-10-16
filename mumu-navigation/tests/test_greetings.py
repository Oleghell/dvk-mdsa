from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from mumu_bridge import AdbReader, BridgeError, content_pixel_sha256, input_context_sha256, visual_header_fingerprint, GREETINGS, SERIAL, HELPER_COMPONENT
from greeting_budget import GreetingBudget, BudgetError

def frame(color='white'):
    out=BytesIO();Image.new('RGB',(900,1600),color).save(out,format='PNG');return out.getvalue()

class GreetingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);adb=self.path/'adb.exe';adb.touch()
        self.r=AdbReader(adb);self.r.helper_ready=True;self.r.greeting_budget=GreetingBudget(self.path/'budget.sqlite')
        self.png=frame();self.sha=input_context_sha256(self.png)
    def tearDown(self):self.r.greeting_budget.close();self.tmp.cleanup()
    def test_ten_fixed_variants(self): self.assertEqual(len(GREETINGS),10);self.assertEqual(len(set(GREETINGS)),10)
    def test_first_greeting_native_verified_never_claims_sent(self):
        with patch.object(self.r,'screen',return_value=self.png),patch.object(self.r,'_instrument',return_value=('greeting_draft_verified','')) as call:
            result=self.r.prepare_greeting(self.sha,0)
        call.assert_called_once_with('greeting',self.sha,0,0)
        self.assertEqual(result['text'],'Привет');self.assertFalse(result['message_sent']);self.assertFalse(result['app_composition_verified'])
        self.assertFalse(result['identity_verified']);self.assertFalse(result['empty_history_automatically_verified'])
    def test_only_fixed_variants(self):
        for v in (-1,10,True,'Привет','0'):
            with self.subTest(v=v),self.assertRaises(BridgeError):self.r.prepare_greeting(self.sha,v)
    def test_stale_screen_does_not_reserve_budget(self):
        with patch.object(self.r,'screen',return_value=self.png),patch.object(self.r,'_instrument') as call:
            with self.assertRaises(BridgeError):self.r.prepare_greeting('0'*64,0)
        call.assert_not_called();self.assertEqual(self.r.greeting_budget.used(),0)
    def test_nonempty_refusal_consumes_budget_never_retries(self):
        with patch.object(self.r,'screen',return_value=self.png),patch.object(self.r,'_instrument',return_value=('denied_nonempty_draft','')) as call:
            with self.assertRaises(BridgeError):self.r.prepare_greeting(self.sha,0)
            with self.assertRaises(BridgeError):self.r.prepare_greeting(self.sha,1)
        self.assertEqual(call.call_count,1);self.assertEqual(self.r.greeting_budget.used(),1)
    def test_timeout_stops_input_across_restart(self):
        with patch.object(self.r,'screen',return_value=self.png),patch.object(self.r,'_instrument',side_effect=BridgeError('timeout')):
            with self.assertRaises(BridgeError):self.r.prepare_greeting(self.sha,0)
        other=GreetingBudget(self.path/'budget.sqlite')
        try:
            with self.assertRaises(BudgetError):other.reserve('a'*64)
        finally:other.close()
        self.assertTrue(self.r.action_uncertain)
    def test_unknown_result_stops_next_navigation(self):
        with patch.object(self.r,'screen',return_value=self.png),patch.object(self.r,'_instrument',return_value=('indeterminate_after_attempt','')):
            with self.assertRaises(BridgeError):self.r.prepare_greeting(self.sha,0)
        with self.assertRaises(BridgeError):self.r.navigate('back',self.sha)
    def test_no_budget_no_input(self):
        budget=self.r.greeting_budget;self.r.greeting_budget=None
        try:
            with self.assertRaises(BridgeError):self.r.prepare_greeting(self.sha,0)
        finally:self.r.greeting_budget=budget
    def test_budget_persists_five_across_connections(self):
        for i in range(5):
            fp=str(i)*64;self.r.greeting_budget.reserve(fp);self.r.greeting_budget.finish(fp,'draft_verified')
        other=GreetingBudget(self.path/'budget.sqlite')
        try:
            with self.assertRaises(BudgetError):other.reserve('f'*64)
        finally:other.close()
    def test_no_repeat_after_verified_draft(self):
        with patch.object(self.r,'screen',return_value=self.png),patch.object(self.r,'_instrument',return_value=('greeting_draft_verified','')) as call:
            self.r.prepare_greeting(self.sha,0)
            with self.assertRaises(BridgeError):self.r.prepare_greeting(self.sha,1)
        self.assertEqual(call.call_count,1)
    def test_reserved_crash_state_blocks_new_attempt(self):
        self.r.greeting_budget.reserve('a'*64)
        other=GreetingBudget(self.path/'budget.sqlite')
        try:
            with self.assertRaises(BudgetError):other.reserve('b'*64)
        finally:other.close()
    def test_visual_fingerprint_ignores_status_line_not_name(self):
        a=Image.open(BytesIO(self.png)).convert('RGB');a.putpixel((120,125),(0,0,0));out=BytesIO();a.save(out,format='PNG')
        self.assertEqual(visual_header_fingerprint(self.png),visual_header_fingerprint(out.getvalue()))
        a.putpixel((120,80),(0,0,0));out=BytesIO();a.save(out,format='PNG')
        self.assertNotEqual(visual_header_fingerprint(self.png),visual_header_fingerprint(out.getvalue()))
    def test_adb_cannot_take_arbitrary_text_argument(self):
        args=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','op','greeting','-e','expected_content_sha256',self.sha,'-e','x','Привет','-e','y','0',HELPER_COMPONENT]
        with patch('subprocess.run') as call:
            with self.assertRaises(BridgeError):self.r._run(args)
        call.assert_not_called()
    def test_journal_stores_no_greeting_text(self):
        fp='a'*64;self.r.greeting_budget.reserve(fp);self.r.greeting_budget.finish(fp,'draft_verified')
        self.assertNotIn('Привет'.encode(),(self.path/'budget.sqlite').read_bytes())

if __name__=='__main__':unittest.main()
