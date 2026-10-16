"""Exercise real Tk window and consent; mock only device/thread startup."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
import tkinter as tk
from tkinter import filedialog,messagebox
import mumu_bridge
import bridge_startup


def main():
    original_tk=tk.Tk
    cases=[]
    for accepted in (False,True):
        roots=[]
        def factory():
            root=original_tk();roots.append(root)
            def exercise():
                root.update_idletasks();root.update()
                def walk(widget):
                    yield widget
                    for child in widget.winfo_children():yield from walk(child)
                buttons={widget.cget('text'):widget for widget in walk(root) if isinstance(widget,tk.Button)}
                assert 'Включить универсальное управление MuMu' not in buttons
                assert 'Разрешить подключение' not in buttons
                start=buttons['Включить MuMu'];stop=buttons['Остановить доступ']
                extra=buttons['Дополнительно: ADB и ограниченный тест']
                adb=buttons['Выбрать ADB MuMu']
                assert not adb.winfo_ismapped()
                for widget in (start,stop):
                    assert widget.winfo_ismapped()
                    assert widget.winfo_rooty()>=root.winfo_rooty()
                    assert widget.winfo_rooty()+widget.winfo_height()<=root.winfo_rooty()+root.winfo_height()
                assert start.winfo_rooty()<extra.winfo_rooty()
                extra.invoke();root.update_idletasks();assert adb.winfo_ismapped()
                extra.invoke();root.update_idletasks();assert not adb.winfo_ismapped()
                dialog_errors=[]
                def answer_consent():
                    dialog=None
                    try:
                        dialog=root.nametowidget('.startup_consent')
                        dialog.update_idletasks()
                        choices={w.cget('text'):w for w in walk(dialog) if isinstance(w,tk.Button)}
                        assert set(choices)=={'Разрешить','Отмена'}
                        for widget in choices.values():
                            assert widget.winfo_ismapped()
                            assert 0<=widget.winfo_rooty()
                            assert widget.winfo_rooty()+widget.winfo_height()<=root.winfo_screenheight()
                        choices['Разрешить' if accepted else 'Отмена'].invoke()
                    except Exception as exc:
                        dialog_errors.append(str(exc))
                        if dialog is not None:dialog.destroy()
                root.after(100,answer_consent)
                start.invoke()
                assert not dialog_errors,dialog_errors
                consent.assert_called_once();picker.assert_not_called();device.assert_not_called()
                if accepted:
                    assert start.cget('state')=='disabled'
                    thread.assert_called_once();thread.return_value.start.assert_called_once()
                else:
                    assert start.cget('state')=='normal';thread.assert_not_called()
                cases.append({'consent_accepted':accepted,'visible_controls':True,'startup_scheduled':accepted})
            root.mainloop=exercise
            return root
        try:
            with patch.object(tk,'Tk',side_effect=factory),patch.object(bridge_startup,'discover_adb',return_value='SYNTHETIC/adb.exe'),patch.object(bridge_startup,'confirm_startup',wraps=bridge_startup.confirm_startup) as consent,patch.object(filedialog,'askopenfilename') as picker,patch.object(mumu_bridge,'AdbReader') as device,patch.object(mumu_bridge.threading,'Thread') as thread:
                mumu_bridge.main()
        finally:
            for root in roots:
                try:root.destroy()
                except tk.TclError:pass
    report={'passed':True,'cases':cases,'real_tk_window_tested':True,'real_consent_dialog_tested':True,'windows_runtime_tested':sys.platform=='win32','real_device_tested':False}
    out=Path(__file__).resolve().parent.parent/'out'/'gui-autotests';out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return 0


if __name__=='__main__':raise SystemExit(main())
