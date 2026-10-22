"""Actual fixed JS with owned cache/router ABI, including non-visible models."""
from pathlib import Path
import subprocess,sys
import frida
import dialog_models as models
WHO=dict(account='100',peer='200',chat='300')
OTHER=dict(account='100',peer='201',chat='301')
def one(library,mode,slow=False):
 child=subprocess.Popen([sys.executable,'-u','-c',
 "import ctypes,sys,time\nl=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nl.fixture_init(int(sys.argv[2]));l.fixture_browser_entry(1)\nprint('ready',flush=True)\nfor _ in range(20000):\n l.fixture_tick();time.sleep(float(sys.argv[3]))",str(library),str(mode),str(.45 if slow else .003)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 session=script=None
 try:
  assert child.stdout.readline().strip()=='ready';session=frida.get_local_device().attach(child.pid)
  allowed=[OTHER,WHO] if mode==872 else [WHO];offset=0;skipped=0;slices=0
  while True:
   source=models.build(allowed=allowed,needs_reply_only=True,offset=offset)
   script=session.create_script(source+'''
rpc.exports={probe(){return probeUIKitRoot();},counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();return [r('fixture_handles'),r('fixture_bad_frees'),r('fixture_off_thread_calls'),r('fixture_model_visible_calls'),r('fixture_browser_clicks'),r('fixture_browser_backs'),r('fixture_route_bad'),r('fixture_model_clicks')];}};''')
   script.load();raw=script.exports_sync.probe()
   result,nxt=models.validate(raw,allowed=allowed,needs_reply_only=True,offset=offset)
   n=raw['navigation'];c=script.exports_sync.counts();slices+=1
   assert c[:7]==[0]*7,(mode,n,c)
   assert n['handles_acquired']==n['handles_released'],(mode,n)
   skipped+=result['diagnostic']['header_rows_skipped']
   if nxt is None:break
   assert result['state']=='exhausted' and not n['action_attempted']
   script.unload();script=None;offset=nxt
  if mode in (870,871,872):
   assert result['state']=='opened' and result['identity']==WHO and c[7]==1,(mode,n,c)
   assert skipped==(1 if mode==872 else 0),(mode,skipped)
   if mode==871:assert (slices>3 if slow else slices==3),(slices,n)
  elif mode in (873,874,882):
   assert result['state']=='exhausted' and c[7]==0,(mode,n,c)
   assert skipped==(0 if mode==882 else 1),(mode,skipped)
  else:
   assert result['state']=='stopped',(mode,n,c)
   if mode==877:assert n['error']=='identity-changed' and c[7]==1,(mode,n,c)
   else:assert c[7]==0,(mode,n,c)
   if mode==876:assert n['error']=='identity-not-bound' and skipped==0,(mode,n)
  print('Synthetic cached models',mode,result['state'],'slices',slices,'header skips',skipped,'passed',flush=True)
 finally:
  if script:
   try:script.unload()
   except Exception:pass
  if session:
   try:session.detach()
   except Exception:pass
  child.terminate()
  try:child.wait(timeout=3)
  except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
  child.stdout.close();child.stderr.close()
if __name__=='__main__':
 library=Path(sys.argv[1]).resolve(strict=True)
 for mode in range(870,890):one(library,mode)
 one(library,871,slow=True)

 from smoke_dialog_browser import integration
 integration(library,872,cached_models=True)
