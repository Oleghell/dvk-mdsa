"""Mocked Tk UI: the key-check tab is independent and never persists input."""
import sys,threading,unittest
from unittest.mock import MagicMock,patch
import assistant_app as app
from assistant_settings import Settings

class Variable:
    def __init__(self,value='',**kw):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value

class KeyTab(unittest.TestCase):
    def setUp(self):
        self.tk=MagicMock();self.ttk=MagicMock();self.tk.ttk=self.ttk
        self.tk.StringVar.side_effect=Variable;self.tk.BooleanVar.side_effect=Variable
        self.ttk.Frame.side_effect=lambda *a,**kw:MagicMock()
        self.ttk.Combobox.side_effect=lambda *a,**kw:MagicMock()
        self.ttk.Button.side_effect=lambda *a,**kw:MagicMock()
        patches=[patch.dict(sys.modules,{'tkinter':self.tk,'tkinter.ttk':self.ttk,'tkinter.filedialog':self.tk.filedialog}),
            patch.object(app,'load',return_value=Settings()),patch.object(app,'save'),
            patch.object(app.telegram_notify,'load',side_effect=app.telegram_notify.TelegramError('x')),
            patch.object(app.threading,'Thread'),patch('telegram_statistics.start',return_value=threading.Event()),
            patch.object(app.assistant_ai,'check_entered_key'),patch.object(app.assistant_ai,'check_saved_keys')]
        self.mocks=[p.start() for p in patches]
        for p in patches:self.addCleanup(p.stop)
        app.launch();self.command('Настройки')()
        self.thread=self.mocks[4];self.check=self.mocks[6];self.save=self.mocks[2]
        tabs={c.kwargs['text']:c.args[0] for c in self.ttk.Notebook.return_value.add.call_args_list}
        self.assertIn('Проверка ключа',tabs);self.check_frame=tabs['Проверка ключа'];self.ai_frame=tabs['ИИ / ключи']
        boxes=[c for c in self.ttk.Combobox.call_args_list if c.args[0] is self.check_frame]
        self.provider=boxes[0].kwargs['textvariable'];self.model=boxes[1].kwargs['textvariable']
        keys=[c for c in self.ttk.Entry.call_args_list if c.args[0] is self.check_frame]
        self.assertEqual(keys[0].kwargs['show'],'*');self.key=keys[0].kwargs['textvariable']
    def command(self,text):return next(c.kwargs['command'] for c in self.ttk.Button.call_args_list if c.kwargs.get('text')==text)
    def test_empty_input_never_uses_saved_keys_or_starts_request(self):
        self.command('Проверить')();self.thread.assert_not_called();self.check.assert_not_called();self.mocks[7].assert_not_called()
    def test_captured_provider_model_and_key_are_not_saved(self):
        production=next(c.kwargs['textvariable'] for c in self.ttk.Combobox.call_args_list if c.args[0] is self.ai_frame)
        self.provider.set('gemini');self.model.set('gemini-3.1-flash-lite');self.key.set('synthetic-private')
        self.check.return_value=dict(answer_verified=True,requests=1)
        self.command('Проверить')();self.thread.call_args.kwargs['target']()
        args=self.check.call_args.args;self.assertEqual(args[:3],('gemini','gemini-3.1-flash-lite','synthetic-private'))
        self.assertEqual(production.get(),'groq');self.save.assert_not_called();self.mocks[7].assert_not_called()
    def test_close_clears_test_input_and_cancels(self):
        self.key.set('synthetic-private');self.command('Проверить')()
        target=self.thread.call_args.kwargs['target'];self.check.return_value=dict(answer_verified=True,requests=1)
        close=next(c.args[1] for c in self.tk.Toplevel.return_value.protocol.call_args_list if c.args[0]=='WM_DELETE_WINDOW')
        close();self.assertEqual(self.key.get(),'');target()
        self.assertTrue(self.check.call_args.args[3]())
