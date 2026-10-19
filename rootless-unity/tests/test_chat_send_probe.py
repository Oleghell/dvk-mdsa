import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import chat_send_probe as p
import diagnose_device as d
from test_chat_state_probe import ready,ChatFake

def result(attempted=True,returned=True):
    r=ready();n=r['navigation'];n.update(greeting_variant=0,action_backend='one-greeting-handler',send_attempted=attempted,send_handler_returned=returned,app_actions_attempted=attempted,messages_sent=None if attempted else 0)
    return r
class GreetingTests(unittest.TestCase):
    def test_submission_is_not_delivery(self):p.validate(result())
    def test_invalid_submission_flags(self):
        for key,value in [('greeting_variant',30),('greeting_variant',True),('greeting_variant',None),('messages_sent',1),('messages_sent',0),('send_attempted',False),('send_handler_returned',False),('app_actions_attempted',False),('history_status','not-empty')]:
            r=result();r['navigation'][key]=value
            with self.assertRaises(ValueError,msg=key):p.validate(r)
    def test_no_attempt_unknown_is_accepted(self):
        r=result(False,False);r['navigation'].update(stage='navigation-stopped',error='chat-not-empty',history_status='unknown',message_count=None,samples=1);p.validate(r)
    def test_lock_is_atomic_and_retained_after_attempt(self):
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)
            r={'gadget':{'uikit_root':result()}}
            with patch.object(d,'diagnose',return_value=(r,f/'report.json')) as run:
                p.send_once(None,f)
                with self.assertRaises(d.TestError):p.send_once(None,f)
                self.assertEqual(run.call_count,1)
    def test_lock_releases_only_explicit_no_attempt(self):
        for attempted in (False,None):
            with tempfile.TemporaryDirectory() as t:
                f=Path(t);r={'gadget':{'uikit_root':{'navigation':{'send_attempted':attempted}}}}
                with patch.object(d,'diagnose',return_value=(r,f/'report.json')):p.send_once(None,f)
                self.assertEqual((f/'.dvk-one-greeting.lock').exists(),attempted is None)
    def test_send_transport_uses_only_fixed_root_rpc(self):
        # ChatFake overwrites root while constructing script; override the returned fixture instead.
        class SendFake(ChatFake):
            def create_script(self,source,name):
                x=super().create_script(source,name);x.exports_sync.root=lambda:result();return x
        f=SendFake();r=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,chat_send_probe=True)
        self.assertEqual(r['stage'],'navigation-ready');self.assertIn('OnSendText',f.script_source)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_read_only_and_send_modes_do_not_mix(self):
        with self.assertRaises(d.TestError):d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=ChatFake(),chat_send_probe=True,chat_state_probe=True)
