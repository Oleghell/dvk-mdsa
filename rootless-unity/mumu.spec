# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all
pg_datas,pg_bins,pg_hidden=collect_all('psycopg_binary')
root=Path(SPECPATH)
a=Analysis([str(root/'assistant_app.py')],pathex=[str(root)],binaries=pg_bins,datas=pg_datas+[(str(root/'supabase-ca.crt'),'.')],
    hiddenimports=pg_hidden+['psycopg','cloud_database','cloud_sql','cloud_migration','cloud_setup','mumu_profile_id','mumu_worker','mumu_controller','mumu_common','mumu_store','mumu_installation','mumu_namespace','mumu_greetings','mumu_cities','search_city_state','mumu_claims','mumu_fast_adb','mumu_bundle','mumu_ai','assistant_exit_photo'],
    hookspath=[],hooksconfig={},runtime_hooks=[],excludes=[],noarchive=False)
pyz=PYZ(a.pure)
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name='DvkAssistant',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False)
worker=EXE(pyz,a.scripts,[],exclude_binaries=True,name='DvkMumuWorker',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=True)
coll=COLLECT(gui,worker,a.binaries,a.datas,strip=False,upx=False,name='DvkAssistant-windows-x64')
