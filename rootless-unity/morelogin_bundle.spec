# One dependency analysis for three independent launchers; one shared runtime.
from pathlib import Path
source = Path(SPECPATH).resolve()
names = [('DvkAssistant','morelogin_app',False),
         ('DvkCloudWorker','morelogin_worker',True),
         ('DvkCloudInstaller','morelogin_installer',False)]
a=Analysis([str(source/(script+'.py')) for _,script,_ in names],pathex=[str(source)],
    binaries=[],datas=[],hiddenimports=[],hookspath=[],hooksconfig={},runtime_hooks=[],
    excludes=[],noarchive=False)
pyz=PYZ(a.pure)
entries={script for _,script,_ in names}
executables=[]
for name,script,console in names:
    scripts=[item for item in a.scripts if item[0] not in entries or item[0]==script]
    if sum(item[0] in entries for item in scripts)!=1:
        raise RuntimeError('Expected one independent launcher')
    executables.append(EXE(pyz,scripts,[],exclude_binaries=True,name=name,debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=console,
        disable_windowed_traceback=False,contents_directory='_internal'))
COLLECT(*executables,a.binaries,a.datas,strip=False,upx=False,name='DvkAssistant-windows-x64')
