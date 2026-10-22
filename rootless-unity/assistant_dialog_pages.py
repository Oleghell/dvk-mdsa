"""Serial checked paging; no fixed number of dialogs or guessed end-of-list."""
import copy,hashlib,json
import dialog_browser as browser
from assistant_contact_photo import Device
from assistant_store import StateError
from uikit_profile_navigation import replace_once

def page_source():
    source=browser.build('open',allowed=(),entry='dialogs')
    source=replace_once(source,"   if(state.scanIndex===undefined)state.scanIndex=0;", "   if(state.scanIndex===undefined){state.scanIndex=0;n.private_page=[];}")
    return replace_once(source,"     const model=modelIdentity(chat);if(model===null)return false;", "     const model=modelIdentity(chat);if(model===null)return false;\n     n.private_page.push(model.who);")

def page(executable,folder,cancelled):
    from one_chat_device import capture
    from one_chat_probe import identity
    from search_online import inspect
    def validator(value):
        value=copy.deepcopy(value);rows=value['navigation'].pop('private_page',None)
        result=browser.validate(value,'open',allowed=())
        if result['state']!='exhausted' or not isinstance(rows,list) or len(rows)>128:raise StateError('dialog-page-not-verified')
        checked=[identity(who) for who in rows]
        return hashlib.sha256(json.dumps(checked,sort_keys=True).encode()).hexdigest()
    source=page_source()
    return capture(executable,folder,cancelled,inspector=lambda port,token,cancel,binding:inspect(port,token,cancel,source_function=source,validator=validator))

class Pager:
    def __init__(self,settings,cancelled,*,device_factory=Device,reader=page):
        self.settings,self.cancelled,self.reader=settings,cancelled,reader
        self.device=device_factory(settings.adb,settings.folder,cancelled);self.seen=set();self.pages=0
    def token(self):return self.reader(self.settings.adb,self.settings.folder,self.cancelled)
    def reset(self):
        # Start at the top, even if a previous pass ended at the bottom. End
        # detection uses verified identities, not a screen hash containing a clock.
        previous=self.token();seen={previous}
        while True:
            self.device.swipe(up=False);current=self.token()
            if current==previous or current in seen:break
            seen.add(current);previous=current
        self.seen={current};self.pages=1
    def advance(self):
        before=self.token();self.device.swipe(up=True);after=self.token()
        if before==after or after in self.seen:return False
        self.seen.add(after);self.pages+=1
        return True
