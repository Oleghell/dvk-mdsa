"""Verified profile screenshot, fixed MuMu #4 only. No persistent plaintext image files."""
import json,os,struct,subprocess,tempfile,time,zlib
from pathlib import Path
from test_device import TARGET
from target_only import TargetOnlyAdb,preflight,recheck
from assistant_store import StateError
from one_chat_probe import identity

MAX_PNG=10*1024*1024

class ProfilePhotoNotStarted(StateError):
    """Only the pre-tap chat check failed; no profile navigation was attempted."""
    def __init__(self, error):
        super().__init__('profile-photo-unavailable')
        from one_chat_device import ReadStopped, safe_read_failure
        from assistant_failure import category
        self.diagnostic=dict(photo_checkpoint='before-profile-open',action_attempted=False,
                             host_failure=category(error))
        if isinstance(error, ReadStopped):
            self.diagnostic['last_read_failure']=safe_read_failure(error)


class ProfileReturnUnverified(StateError):
    """After a tap, the current chat/profile could not be independently proven."""
    def __init__(self, error, *, checkpoint='profile-return-check', back_attempted=False, back_completed=False, read_retries=0):
        super().__init__('profile-return-not-verified')
        from one_chat_device import ReadStopped, safe_read_failure
        from assistant_failure import category
        self.diagnostic=dict(photo_checkpoint=checkpoint,action_attempted=True,
                             chat_back_attempted=back_attempted,chat_back_completed=back_completed,
                             photo_read_retries=read_retries,host_failure=category(error))
        if isinstance(error, ReadStopped):
            self.diagnostic['last_read_failure']=safe_read_failure(error)


def png_size(data):
    if not isinstance(data,bytes) or not 45<=len(data)<=MAX_PNG or data[:8]!=b'\x89PNG\r\n\x1a\n':raise StateError('profile-photo-invalid')
    pos=8;dimensions=None;ended=False;has_pixels=False
    while pos+12<=len(data):
        n=struct.unpack('>I',data[pos:pos+4])[0];kind=data[pos+4:pos+8];end=pos+12+n
        if end>len(data) or n>MAX_PNG:raise StateError('profile-photo-invalid')
        value=data[pos+8:pos+8+n];crc=struct.unpack('>I',data[pos+8+n:end])[0]
        if zlib.crc32(kind+value)&0xffffffff!=crc:raise StateError('profile-photo-invalid')
        if pos==8:
            if kind!=b'IHDR' or n!=13:raise StateError('profile-photo-invalid')
            dimensions=struct.unpack('>II',value[:8])
            if not all(200<=v<=5000 for v in dimensions):raise StateError('profile-photo-invalid')
        if kind==b'IDAT' and n:has_pixels=True
        if kind==b'IEND':
            if n:raise StateError('profile-photo-invalid')
            ended=True;pos=end;break
        pos=end
    if not ended or not has_pixels or pos!=len(data):raise StateError('profile-photo-invalid')
    return dimensions

class Device:
    def __init__(self,executable,folder,cancelled=lambda:False):
        self.adb=TargetOnlyAdb(executable,Path(folder).resolve(strict=True));self.boot=preflight(self.adb);self.cancelled=cancelled
    def run(self,operation):
        if self.cancelled():raise StateError('cancelled')
        recheck(self.adb,self.boot)
        # This separate narrow transport does not widen the generic ADB allowlist.
        if operation!=['exec-out','screencap','-p'] and operation!=['shell','input','keyevent','4']:
            if len(operation)==5 and operation[:3]==['shell','input','tap']:
                x,y=map(int,operation[3:])
                if not (0<x<=5000 and 0<y<=5000):raise StateError('profile-command-blocked')
            elif len(operation)==8 and operation[:3]==['shell','input','swipe']:
                if not (all(x.isdecimal() and 0<int(x)<=5000 for x in operation[3:]) and operation[-1]=='400'):raise StateError('profile-command-blocked')
            else:raise StateError('profile-command-blocked')
        env=os.environ.copy()
        for key in ('ADB_SERVER_SOCKET','ANDROID_ADB_SERVER_PORT','ANDROID_SERIAL'):env.pop(key,None)
        env['ADB_SERVER_SOCKET']='tcp:localhost:5037'
        with tempfile.TemporaryFile() as out:
            try:
                r=subprocess.run([self.adb.executable,'-s',TARGET,*operation],shell=False,env=env,stdout=out,stderr=subprocess.DEVNULL,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            except Exception:raise StateError('profile-device-unavailable') from None
            out.seek(0);data=out.read(MAX_PNG+1)
        recheck(self.adb,self.boot)
        if self.cancelled():raise StateError('cancelled')
        if r.returncode or len(data)>MAX_PNG:raise StateError('profile-device-unavailable')
        return data
    def screen(self):
        data=self.run(['exec-out','screencap','-p']);png_size(data);return data
    def pause(self):
        for _ in range(12):
            if self.cancelled():raise StateError('cancelled')
            time.sleep(.1)
    def swipe(self,up=True):
        w,h=png_size(self.screen())
        a,b=(.78,.32) if up else (.32,.78)
        self.run(['shell','input','swipe',str(w//2),str(int(h*a)),str(w//2),str(int(h*b)),'400']);self.pause()

def profile_source(who):
    import dialog_browser as b
    from uikit_profile_navigation import replace_once
    who=identity(who);s=b.build('back',expected=who)
    s=s.replace("'DV.Messages.dll','mscorlib.dll'", "'DV.Messages.dll','DV.Profile.dll','mscorlib.dll'")
    anchor="  n.metadata_checkpoint='ready';\n }"
    prepare="""  s.profileQueue=getClass('DV.Profile.dll','DV.Profiles','ProfilesQueueViewController');
  s.profileContent=getClass('DV.Profile.dll','DV.Profiles','ProfileViewController');
  if(s.profileQueue.isNull()||s.profileContent.isNull())throw new Error('metadata');
  s.activeProfile=checked(s.profileQueue,'get_CurrentProfileController',18,s.profileContent);
  s.profileUser=checked(s.profileContent,'get_User',18,s.user);
"""
    s=replace_once(s,anchor,prepare+anchor)
    s=replace_once(s,"   if(klass.equals(s.chatController))return 'chat';", "   if(klass.equals(s.profileQueue)||klass.equals(s.profileContent))return 'contact-profile';\n   if(klass.equals(s.chatController))return 'chat';")
    s=replace_once(s,"if(k==='search'||k==='dialogs'||k==='chat'||k==='profile'){", "if(k==='search'||k==='dialogs'||k==='chat'||k==='profile'||k==='contact-profile'){")
    start=s.index('   if(!scope(()=>checkView(current))){resetDestination();return;}');end=s.index('\n  } catch(e)',start)
    tick="""   if(k!=='contact-profile')fail('wrong-screen');
   if(!scope(()=>checkView(current)))return;
   const content=f.objectClass(current).equals(s.profileContent)?current:call(s.activeProfile,current);
   if(content.isNull()||!f.objectClass(content).equals(s.profileContent))fail('identity-not-bound');own(content);
   const user=call(s.profileUser,content);if(user.isNull()||!f.objectClass(user).equals(s.user))fail('identity-not-bound');own(user);
   const peer=id64(s.peerId,user);if(peer!==expectedIdentity.peer)fail('identity-not-bound');
   if(!scope(()=>resolve(candidate).equals(current))||!call(s.profileUser,content).equals(user))fail('identity-changed');
   n.private_profile_peer=peer;n.stage='navigation-ready';n.error='none';n.phase='done';n.destination_verified=true;
"""
    return s[:start]+tick+s[end:]

def verify_profile(executable,folder,who,cancelled):
    from one_chat_device import capture
    from search_online import inspect
    def validator(value):
        n=value.get('navigation',{})
        if (n.get('stage')!='navigation-ready' or n.get('error')!='none' or n.get('cleanup_failed') is not False or n.get('private_profile_peer')!=who['peer'] or n.get('handles_acquired')!=n.get('handles_released') or not n.get('destination_verified')):raise StateError('profile-not-verified')
        return True
    source=profile_source(who)
    return capture(executable,folder,cancelled,inspector=lambda port,token,cancel,binding:inspect(port,token,cancel,source_function=source,validator=validator))

def capture_profile(executable,folder,who,cancelled=lambda:False,*,device_factory=Device,chat_reader=None,profile_reader=verify_profile,read_pause=time.sleep):
    from one_chat_device import capture,ReadStopped,safe_read_failure
    from assistant_history_wait import verified_read_budget,verified_loading
    who=identity(who)
    if chat_reader is None:
        chat_reader=lambda exe,folder,cancel,binding:capture(exe,folder,cancel)
    device=device_factory(executable,folder,cancelled)
    back_attempted=False;back_completed=False
    def check_chat(checkpoint='profile-noop-check',retries=0):
        for attempt in range(retries+1):
            try:
                value=chat_reader(executable,folder,cancelled,who)
                if identity(value['identity'])!=who:raise StateError('profile-not-verified')
                return
            except Exception as error:
                if cancelled():raise StateError('cancelled') from None
                detail=safe_read_failure(error) if isinstance(error,ReadStopped) else None
                retryable=detail is not None and (verified_read_budget(detail) or verified_loading(detail))
                if retryable and attempt<retries:
                    read_pause(.2)
                    continue
                raise ProfileReturnUnverified(error,checkpoint=checkpoint,back_attempted=back_attempted,
                    back_completed=back_completed,read_retries=attempt) from None
    # The fixed no-expected reader reads identity only, not messages. Compare
    # its canonical identity with the bound chat before any UI operation.
    try:
        value=chat_reader(executable,folder,cancelled,who)
        if identity(value['identity'])!=who:raise StateError('profile-not-verified')
    except Exception as error:
        if cancelled():raise StateError('cancelled') from None
        raise ProfilePhotoNotStarted(error) from None
    w,h=png_size(device.screen())
    if not .4<=w/h<=.8:raise StateError('profile-layout-unsupported')
    try:
        device.run(['shell','input','tap',str(int(w*.075)),str(int(h*.06))]);device.pause()
    except Exception as error:
        if cancelled():raise StateError('cancelled') from None
        raise ProfileReturnUnverified(error,checkpoint='profile-open-call') from None
    image=None;failure=None;profile_verified=False
    try:
        if profile_reader(executable,folder,who,cancelled) is not True:raise StateError('profile-not-verified')
        image=device.screen()
        if profile_reader(executable,folder,who,cancelled) is not True:raise StateError('profile-not-verified')
        profile_verified=True
    except Exception:failure=StateError('profile-photo-unavailable')
    if not profile_verified:
        # A no-op/unknown tap still needs fresh evidence. Never Back merely
        # because a chat read failed or a profile was seen before the screenshot.
        try:check_chat()
        except Exception:
            if cancelled():raise StateError('cancelled')
            try:
                if profile_reader(executable,folder,who,cancelled) is not True:raise StateError('profile-not-verified')
                profile_verified=True
            except Exception:
                check_chat()
                raise StateError('profile-photo-unavailable') from None
    if profile_verified:
        # Latest proof is the exact native profile AFTER the PNG. Do not run a
        # full chat-history reader while that known profile is still on screen.
        try:
            back_attempted=True
            device.run(['shell','input','keyevent','4']);back_completed=True;device.pause()
        except Exception as error:
            if cancelled():raise StateError('cancelled') from None
            raise ProfileReturnUnverified(error,checkpoint='profile-back-call',back_attempted=True,
                back_completed=back_completed) from None
        # Retry observations only. A wrong identity/schema or unknown Back never
        # qualifies; no second Back/tap or message is issued during recovery.
        check_chat('profile-after-back',retries=2)
    if failure:raise failure
    return image
