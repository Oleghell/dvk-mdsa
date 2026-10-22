# Three launchers, one shared runtime. Keep the entire directory together.
from pathlib import Path
import hashlib
source = Path(SPECPATH).resolve()
names = [('DvkAssistant','morelogin_app.py',False),
         ('DvkCloudWorker','morelogin_worker.py',True),
         ('DvkCloudInstaller','morelogin_installer.py',False)]
analyses=[];executables=[]
for name,script,console in names:
    a=Analysis([str(source/script)],pathex=[str(source)],binaries=[],datas=[],
               hiddenimports=[],hookspath=[],hooksconfig={},runtime_hooks=[],excludes=[],noarchive=False)
    analyses.append(a)
    executables.append(EXE(PYZ(a.pure),a.scripts,[],exclude_binaries=True,
        name=name,debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
        console=console,disable_windowed_traceback=False,contents_directory='_internal'))
# Refuse conflicting files rather than silently selecting a different runtime.
seen={}
for a in analyses:
    for dest,src,kind in list(a.binaries)+list(a.datas):
        key=dest.replace('\\','/').casefold()
        if key in seen and seen[key]!=src:
            if hashlib.sha256(Path(seen[key]).read_bytes()).digest()!=hashlib.sha256(Path(src).read_bytes()).digest():
                raise RuntimeError('Conflicting shared runtime destination: '+dest)
        seen[key]=src
COLLECT(*executables,*(a.binaries for a in analyses),*(a.datas for a in analyses),
        strip=False,upx=False,name='DvkAssistant-windows-x64')
