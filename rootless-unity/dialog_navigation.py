"""Fixed search -> private dialog list -> SAME search. No messages or list data.

The SwitchToTab signature and MessagesTabController/ChatsViewController names
come from the user's 2026-10-20 definitions. Runtime signatures, UI attachment,
modal state and object identity are still checked. A catalogue is NOT live proof.
"""
import copy
import json
import uikit_navigation as nav
from uikit_profile_navigation import replace_once

VERSION = '0.4.1'
KINDS = nav.KINDS - {'filters'} | {'dialogs', 'messages-tab'}
PHASES = {'search', 'wait-dialogs', 'confirm-dialogs', 'wait-return', 'done'}
PREPARE = r'''
 function routeSignature(f,e,m){
  if(m.isNull()||f.arity(m)!==2)return false;
  const flags=Memory.alloc(4);flags.writeU32(0);
  const owner=f.methodClass(m);
  if((f.flags(m,flags)&(16|1024))!==0||owner.isNull()||!f.assignable(owner,e.klass))return false;
  const ret=f.returnType(m);if(ret.isNull()||f.byref(ret)||f.typeKind(ret)!==2)return false;
  const a=f.param(m,0),b=f.param(m,1);
  return !a.isNull()&&!b.isNull()&&!f.byref(a)&&!f.byref(b)&&f.typeKind(a)===18&&
   f.classFromType(a).equals(e.typeClass)&&f.typeKind(b)===2;
 }
 function prepareDialogRoute(f,s,getClass){
  s.typeClass=getClass('mscorlib.dll','System','Type');
  s.messageTab=getClass('DV.Messages.dll','DV','MessagesTabController');
  if(s.typeClass.isNull()||s.messageTab.isNull()||!f.assignable(s.vc,s.messageTab))throw new Error('metadata');
  s.switchTab={klass:s.tabs,kind:2,arity:2,typeClass:s.typeClass,routeChecked:true};
  s.switchTab.m=f.method(s.tabs,Memory.allocUtf8String('DV.IMainTabsController.SwitchToTab'),2);
  if(!routeSignature(f,s.switchTab,s.switchTab.m)||!f.methodClass(s.switchTab.m).equals(s.tabs))throw new Error('signature');
 }
'''
ROUTE = r'''
  const switchTab=klass=>{
   if(!state.tabs||state.tabs.isNull())fail('unexpected-object');
   const tabs=target(state.tabs);if(!checkView(tabs))fail('screen-not-ready');
   const nativeType=f.classType(klass);if(nativeType.isNull())fail('signature-mismatch');
   const reflected=f.typeObject(nativeType);if(reflected.isNull())fail('unexpected-object');own(reflected);
   if(!f.assignable(s.typeClass,f.objectClass(reflected)))fail('signature-mismatch');
   const animate=Memory.alloc(1);animate.writeU8(0);
   const args=Memory.alloc(Process.pointerSize*2);args.writePointer(reflected);args.add(Process.pointerSize).writePointer(animate);
   const result=call(s.switchTab,tabs,args);if(result.isNull())fail('signature-mismatch');
   const box=f.unbox(result);if(box.isNull())fail('signature-mismatch');const yes=box.readU8();
   if(yes!==1)fail(yes===0?'screen-not-ready':'signature-mismatch');
  };
'''

def build():
    s = nav.FUNCTION
    # The baseline fixed observer supplies main-thread/frame/modal/attachment
    # checks; it must never retain either original filter handler.
    s = replace_once(s, "filters:['DV.Search.dll','DV.Search','SearchSettingsCardController']", "filters:['DV.Messages.dll','DV.Messages','ChatsViewController']")
    s = replace_once(s, '!f.assignable(s.card,s.filters)', '!f.assignable(s.vc,s.filters)')
    s = replace_once(s, "   ['canClose','card','get_CanBeClosedByUser',2],\n", '')
    s = replace_once(s, "   ['open','search','ShowSearchSettings',1],['cancel','card','DismissWithCancel',1]", '')
    s = replace_once(s, ' function prepareNavigation(', PREPARE + '\n function prepareNavigation(')
    s = replace_once(s, 'setup.navigation=prepareNavigation(f,getClass,get,signature);', 'setup.navigation=prepareNavigation(f,getClass,get,signature);prepareDialogRoute(f,setup.navigation,getClass);')
    s = replace_once(s, nav.BINDINGS, nav.BINDINGS + "\n Object.assign(f,{classType:bind('class_get_type','pointer',['pointer']),typeObject:bind('type_get_object','pointer',['pointer'])});")
    anchor = json.dumps(nav.APIS[-1]) + ']'
    s = replace_once(s, anchor, json.dumps(nav.APIS[-1]) + ',"il2cpp_class_get_type","il2cpp_type_get_object"]')
    s = replace_once(s, "['Core.dll','DV.dll','DV.Search.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll'].includes(name)", "['Core.dll','DV.dll','DV.Search.dll','DV.Messages.dll','DV.Profile.dll','mscorlib.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll'].includes(name)")
    s = replace_once(s, '   let m=entry.m;', "   if(entry.routeChecked&&!routeSignature(f,entry,entry.m))fail('signature-mismatch');\n   let m=entry.m;")
    s = replace_once(s, '   if(entry.arity===1)', "   if(entry.routeChecked&&!routeSignature(f,entry,m))fail('signature-mismatch');\n   if(entry.arity===1)")
    s = replace_once(s, "   if(klass.equals(s.search))return 'search';", "   if(klass.equals(s.messageTab))return 'messages-tab';\n   if(klass.equals(s.search))return 'search';")
    s = replace_once(s, "    if(k==='other')fail", "    if(k==='main-tabs'){\n     if(!state.tabs||state.tabs.isNull()){state.tabs=own(current);held.splice(held.indexOf(state.tabs),1);}\n     else if(!current.equals(target(state.tabs)))fail('identity-changed');\n    }\n    if(k==='other')fail")
    s = replace_once(s, "    if(k==='root'&&bool(s.loading,current))", "    if(k==='messages-tab'){\n     const entry=f.assignable(s.dvContainer,f.objectClass(current))?s.dvCurrent:\n      f.assignable(s.uiContainer,f.objectClass(current))?s.uiCurrent:s.top;\n     const child=call(entry,current);if(child.isNull()||child.equals(current))return ptr(0);\n     current=child;continue;\n    }\n    if(k==='root'&&bool(s.loading,current))")
    s = replace_once(s, '  try {\n   const root=call', ROUTE + '  try {\n   const root=call')
    # Resolve the root path as well as the last presented view, so the real main
    # tabs owner is found even if UIKit exposes the selected child as last view.
    s = replace_once(s, '   const current=resolve(candidate);', '   resolve(root);\n   const current=resolve(candidate);')
    s = replace_once(s, 'n.open_attempted=true;call(s.open,current);', 'n.open_attempted=true;switchTab(s.messageTab);')
    s = replace_once(s, "    if(!bool(s.canClose,current))fail('screen-not-ready');\n", '')
    s = replace_once(s, 'n.cancel_attempted=true;call(s.cancel,current);', 'n.cancel_attempted=true;switchTab(s.search);')
    s = replace_once(s, "for(const key of ['card','origin'])", "for(const key of ['card','origin','tabs'])")
    # Public terminology describes the actual operation, not old filter aliases.
    s = s.replace('filters_verified', 'dialogs_verified').replace('wait-filters', 'wait-dialogs').replace('confirm-filters', 'confirm-dialogs').replace("'filters'", "'dialogs'")
    s = s.replace('cancel_attempted', 'back_attempted').replace('cancel_completed', 'back_completed')
    return s

FUNCTION = build()


def validate(value):
    if not isinstance(value,dict) or not isinstance(value.get('navigation'),dict):
        raise ValueError('Missing route evidence')
    checked = copy.deepcopy(value)
    n = checked['navigation']
    if (not isinstance(n,dict) or any(k in n for k in ('filters_verified','cancel_attempted','cancel_completed'))
            or n.get('phase') not in PHASES or not isinstance(n.get('controller_path'),list)):
        raise ValueError('Invalid route fields')
    n['filters_verified'] = n.pop('dialogs_verified')
    n['cancel_attempted'] = n.pop('back_attempted')
    n['cancel_completed'] = n.pop('back_completed')
    n['phase'] = {'wait-dialogs': 'wait-filters', 'confirm-dialogs': 'confirm-filters'}.get(n['phase'], n['phase'])
    def old(k):
        return {'dialogs': 'filters', 'messages-tab': 'dv-container'}.get(k,k)
    if any(k not in KINDS for k in n['controller_path']) or n['phase'] not in nav.PHASES:
        raise ValueError('Invalid route')
    for key in ('root_top_kind','last_presented_kind'):
        if n[key] not in KINDS: raise ValueError('Invalid screen')
        n[key] = old(n[key])
    n['controller_path'] = [old(k) for k in n['controller_path']]
    nav.validate(checked)
    return value


def inspect(port, token, cancelled, expected=None, **kwargs):
    if expected is not None: raise ValueError('Route takes no chat identity')
    from search_online import inspect as transport
    return transport(port, token, cancelled, source_function=FUNCTION, validator=validate, **kwargs)


def run(executable, folder, cancelled=lambda: False):
    # Caller owns the operation lock, including report writing.
    from one_chat_device import capture
    return capture(executable, folder, cancelled, inspector=inspect)
