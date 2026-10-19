import copy,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch,MagicMock
import reply_metadata as p
import diagnose_device as d
from test_chat_runtime_metadata import ready,RuntimeFake

# Extend an existing valid inventory with absent (never fabricated) new roots.
def reply_ready():
    r=ready()
    for image,namespace,name in p.ROOTS[len(p.base.ROOTS):]:r['roots'].append(dict(image=image,namespace=namespace,type=name,found=False,class_index=None))
    return r
class ReplyMetadata(unittest.TestCase):
    def test_schema_and_no_values(self):
        p.validate(reply_ready())
        for name in ('runtime_invoke','field_get_value','gchandle_new','OnSendText','Memory.scan','get_Text()'):self.assertNotIn(name,p.FUNCTION)
        self.assertIn('image_get_class_count',p.FUNCTION);self.assertIn('class_is_assignable_from',p.FUNCTION)
    def test_unknown_root_and_fabricated_identity_rejected(self):
        for key,value in [('found',True),('class_index',True),('type','PRIVATE')]:
            r=reply_ready();r['roots'][-1][key]=value
            with self.assertRaises(ValueError,msg=key):p.validate(r)
        r=reply_ready();r['roots'][-1]['private']='PRIVATE'
        with self.assertRaises(ValueError):p.validate(r)
    def test_conflicting_modes(self):
        for key in ('automatic_probe','batch_probe','chat_state_probe','chat_send_probe','chat_runtime_probe','uikit_root_probe'):
            with self.assertRaises(d.TestError):d.inspect_gadget(37149,'a'*64,lambda:False,replies_probe=True,frida_api=RuntimeFake(),**{key:True})
    def test_transport_never_calls_root_and_uses_reply_inventory(self):
        class Fake(RuntimeFake):
            def create_script(self,source,name):
                super().create_script(source,name);self.exports_sync.native=reply_ready;return self
        f=Fake();out=d.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f,replies_probe=True)
        self.assertEqual(out['stage'],'chat-runtime-ready');self.assertIn('image_get_class_count',f.script_source)
        self.assertNotIn('rpc.exports.root',f.script_source);self.assertNotIn('rpc.exports.cancel',f.script_source)
    def test_compact_button_does_not_start_replies(self):
        import navigate_profile_device as gui
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk;tk.Tk.return_value.winfo_height.return_value=300;ttk.Frame.return_value.winfo_reqheight.return_value=260
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}),patch.object(gui.threading,'Thread') as thread:
            gui.launch_gui();thread.assert_not_called()
            commands={c.kwargs.get('text'):c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Подготовить ответы · без отправки']();self.assertIs(thread.call_args.kwargs['args'][7],True)
            commands['Автопроход · до 10 анкет']();thread.return_value.start.assert_called_once()
        ttk.Checkbutton.assert_not_called()
