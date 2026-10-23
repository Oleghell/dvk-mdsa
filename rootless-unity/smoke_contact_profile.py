"""Real read-only JS profile/page probes against owned synthetic objects."""
from pathlib import Path
import subprocess,sys,time
import frida
from assistant_contact_photo import profile_source
from assistant_dialog_pages import page_source
import dialog_browser as browser
WHO=dict(account='100',peer='200',chat='300')

def one(library,mode,phase):
 child=subprocess.Popen([sys.executable,'-u','-c',
  "import ctypes,sys,time\nl=ctypes.CDLL(sys.argv[1],mode=ctypes.RTLD_GLOBAL)\nl.fixture_init(int(sys.argv[2]));l.fixture_browser_entry(int(sys.argv[3]))\nprint('ready',flush=True)\nfor _ in range(12000):\n l.fixture_tick();time.sleep(.003)",
  str(library),str(mode),str(phase)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 session=script=None
 try:
  assert child.stdout.readline().strip()=='ready'
  session=frida.get_local_device().attach(child.pid)
  source=page_source() if phase==1 else profile_source(WHO)
  script=session.create_script(source+'''
rpc.exports={probe(){return probeUIKitRoot();},counts(){const r=n=>new NativeFunction(Module.getGlobalExportByName(n),'int',[])();return [r('fixture_handles'),r('fixture_bad_frees'),r('fixture_off_thread_calls'),r('fixture_browser_clicks'),r('fixture_browser_backs'),r('fixture_route_bad')];}};''')
  script.load();raw=script.exports_sync.probe();n=raw['navigation'];counts=script.exports_sync.counts()
  assert counts==[0]*6,(mode,n,counts)
  assert n['handles_acquired']==n['handles_released'],(mode,n)
  if phase==1:
   rows=n.pop('private_page');out=browser.validate(raw,'open',allowed=())
   assert out['state']=='exhausted' and len(rows)==2 and rows[1]==WHO,(rows,out)
  elif mode==860:
   assert n['stage']=='navigation-ready' and n['error']=='none' and n['destination_verified'] and n['private_profile_peer']==WHO['peer'],(mode,n)
  elif mode==862:
   assert n['stage']=='not-attempted' and n['metadata_checkpoint']!='ready' and not n['destination_verified'],(mode,n)
  else:
   # Reusing the tabs owner reduces calls: hidden views now hit frame bound first.
   expected={861:'identity-not-bound',862:'signature-mismatch',863:'identity-changed',864:'frame-limit'}[mode]
   assert n['error']==expected and not n['destination_verified'],(mode,n)
  print('Synthetic contact profile/page',mode,phase,'passed',flush=True)
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
 one(library,800,1)
 for mode in range(860,865):one(library,mode,4)
 one(library,860,5)
