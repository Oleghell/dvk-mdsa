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
    def test_compact_controls_can_be_constructed_without_device(self):
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk
        # Headless construction is not a native Windows rendering test.
        tk.Tk.return_value.winfo_height.return_value=340
        ttk.Frame.return_value.winfo_reqheight.return_value=300
        frida=MagicMock();frida.__version__='17.24.1'
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox,'frida':frida}),patch.object(gui,'find_adb',return_value='adb.exe'):
            gui.launch_gui(self_check=True)
        tk.Tk.return_value.geometry.assert_called_once_with('640x340')
        labels=[call.kwargs.get('text','') for call in ttk.Label.call_args_list]
        self.assertLess(sum(map(len,labels)),220)
        self.assertEqual([c.kwargs['text'] for c in ttk.Button.call_args_list][-3:],['Проверить профиль','Стоп','Отчёт'])
        tk.messagebox.showinfo.assert_not_called()
        tk.Tk.return_value.destroy.assert_called_once()
