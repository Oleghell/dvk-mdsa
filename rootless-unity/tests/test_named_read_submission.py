"""252/253: optional read metadata must never cross the strict send boundary."""
import unittest
from unittest.mock import MagicMock,patch
import one_chat_send as native
import one_chat_send_device as transport
import test_guided_chain as guide

class NamedSubmission(guide.WholeChain):
    def test_named_history_can_reach_real_strict_submission_adapter(self):
        before=guide.snapshot(('Привет',False))
        after=guide.snapshot(('Привет',False),('Как настроение?',True))
        self.chain.bind(guide.snapshot(),(guide.GREETING,),approved=True)
        self.chain.responder=MagicMock(return_value=dict(decision='reply',text='Как настроение?'))
        def fixed_sender(snapshot,text):
            return transport.submit('synthetic-adb','synthetic-folder',snapshot,self.stop.is_set,text=text)
        with patch.object(self,'send',side_effect=fixed_sender),patch.object(transport,'capture',return_value=dict(attempted=True,handler_returned=True)) as capture:
            out=self.walk([before,before,after],until_waiting=True)
        self.assertEqual(out['reason'],'wait-mood',out['diagnostics'])
        self.assertEqual(out['handler_returns'],1)
        self.assertEqual(capture.call_count,1)
        self.assertTrue(out['diagnostics']['post_send_checked'])
        self.assertNotIn('send_host_failure',out['diagnostics'])

    def test_strict_native_adapter_still_rejects_extra_metadata_before_device_access(self):
        with patch.object(transport,'capture') as capture:
            with self.assertRaises(ValueError):transport.submit('unused','unused',guide.snapshot())
        capture.assert_not_called()
        with self.assertRaises(ValueError):native.checked(dict(identity=guide.WHO,messages=guide.snapshot()['messages'],private='PRIVATE'))

for name in dir(guide.WholeChain):
    if name.startswith('test_') and name not in NamedSubmission.__dict__:setattr(NamedSubmission,name,None)
