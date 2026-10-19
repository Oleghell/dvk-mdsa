import sys,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import navigate_profile_device as gui

class CompactProfileGUI(unittest.TestCase):
    def test_status_shows_actual_navigation_error(self):
        value={'status':'navigation-stopped','gadget':{'uikit_root':{'navigation':{'error':'frame-budget'}}}}
        self.assertEqual(gui.result_status(value),'Остановлен: frame-budget')
        value['profile_may_remain_open']=True
        self.assertIn('вручную',gui.result_status(value))
    def test_success_and_preflight_failure(self):
        self.assertIn('подтверждён',gui.result_status({'status':'navigation-ready'}))
        self.assertEqual(gui.result_status({'status':'preflight-failed'}),'Остановлен: preflight-failed')
    def test_friends_count_is_short_and_unknown_is_not_zero(self):
        value={'status':'navigation-ready','gadget':{'uikit_root':{'navigation':{'friends_status':'read','friends_count':49,'friends_eligible':True}}}}
        self.assertIn('49 (меньше 50)',gui.result_status(value))
        self.assertIn('неизвестно',gui.result_status({'status':'navigation-ready'}))
    def test_compact_controls_can_be_constructed_without_device(self):
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk
        # Headless construction is not a native Windows rendering test.
        tk.Tk.return_value.winfo_height.return_value=300
        ttk.Frame.return_value.winfo_reqheight.return_value=260
        frida=MagicMock();frida.__version__='17.24.1'
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox,'frida':frida}):
            gui.launch_gui(self_check=True)
        tk.Tk.return_value.geometry.assert_called_once_with('640x300')
        labels=[call.kwargs.get('text','') for call in ttk.Label.call_args_list]
        self.assertLess(sum(map(len,labels)),220)
        self.assertEqual([c.kwargs['text'] for c in ttk.Button.call_args_list][-3:],['Проверить профиль','Стоп','Отчёт'])
        self.assertEqual(tk.StringVar.call_args_list[0].kwargs['value'],'C:/Users/XXX/Desktop/platform-tools/adb.exe')
        ttk.Checkbutton.assert_not_called()
        tk.BooleanVar.assert_not_called()
        tk.messagebox.showinfo.assert_not_called()
        tk.Tk.return_value.destroy.assert_called_once()

    def test_manual_button_starts_once_without_extra_confirmation(self):
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk
        tk.Tk.return_value.winfo_height.return_value=300
        ttk.Frame.return_value.winfo_reqheight.return_value=260
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}),patch.object(gui.threading,'Thread') as thread:
            gui.launch_gui()
            thread.assert_not_called() # Opening the window must not start a visit.
            commands={c.kwargs.get('text'):c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Проверить профиль']()
            thread.assert_called_once()
            thread.return_value.start.assert_called_once()
            commands['Проверить профиль']()
            thread.return_value.start.assert_called_once() # Still busy: no duplicate visit.
            commands['Стоп']()
        tk.messagebox.showinfo.assert_not_called()
        ttk.Checkbutton.assert_not_called()

    def test_metadata_button_needs_no_adb_or_profile_visit(self):
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk
        tk.Tk.return_value.winfo_height.return_value=300
        ttk.Frame.return_value.winfo_reqheight.return_value=260
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}),patch.object(gui.threading,'Thread') as thread:
            gui.launch_gui()
            commands={c.kwargs.get('text'):c.kwargs.get('command') for c in ttk.Button.call_args_list}
            commands['Найти счётчик']()
            self.assertEqual(thread.call_args.kwargs['target'].__name__,'catalog_worker')
            self.assertEqual(len(thread.call_args.kwargs['args']),1)
            thread.return_value.start.assert_called_once()
        self.assertIn('пришли отчёт',gui.result_status({'mode':'offline-friends-catalog','status':'catalog-ready'}))
