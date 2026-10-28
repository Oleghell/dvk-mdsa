"""Fixed, consented search/filter/cancel workflow; no generic action RPC.

UIKit controller hierarchy is the semantic backend for this Unity app. These
are actual UI handlers, not Android accessibility clicks. Unknown screens stop.
"""
from uikit_root import build_function, validate as validate_root

MAX_FRAMES=180
MAX_CALLS=6000
ERRORS={'cancelled','none','wrong-screen','screen-not-ready','unexpected-screen','identity-changed',
        'transition-timeout','frame-limit','call-limit','frame-budget','managed-exception',
        'signature-mismatch','unexpected-object','handle-allocation-failed','native-call-failed',
        'observer-stopped','cleanup-failed','controller-cycle','controller-depth-limit','presentation-not-resolved','view-parent-cycle','view-parent-depth-limit','modal-ambiguous','modal-count-invalid','modal-changed','handle-limit'}
PHASES={'search','wait-filters','confirm-filters','wait-return','done'}
KINDS={'not-checked','none','search','filters','other','root','main-tabs','dv-container','ui-container','dv-navigation','ui-navigation'}
HELPERS=r'''
 function emptyNavigation(){return {stage:'not-attempted',phase:'search',error:'none',frames:0,
  managed_calls:0,handles_acquired:0,handles_released:0,cleanup_failed:false,
  search_verified:false,filters_verified:false,return_verified:false,
  open_attempted:false,open_completed:false,cancel_attempted:false,cancel_completed:false,
  root_top_kind:'not-checked',last_presented_kind:'not-checked',controller_path:[],
  readiness_check:'not-checked',view_parent_depth:0,readiness:{has_view:null,is_presented:null,hidden:null,interactive:null,attached_to_main_window:null},
  action_backend:'semantic-controller-handlers',ui_text_read:false};}
 function prepareNavigation(f,getClass,get,signature){
  const spec={view:['Core.dll','UIKit','UIView'],vc:['Core.dll','UIKit','UIViewController'],
   dv:['DV.dll','DV.Common','DVViewController'],card:['DV.dll','DV','CardViewController'],
   search:['DV.Search.dll','DV.Search','SearchTabController'],
   filters:['DV.Search.dll','DV.Search','SearchSettingsCardController'],
   appRoot:['DV.dll','DV','RootViewController'],tabs:['DV.dll','DV','MainTabsController'],
   dvContainer:['DV.dll','DV.Common','DVContainerViewController'],
   uiContainer:['Core.dll','UIKit','UIContainerViewController'],
   dvNav:['DV.dll','DV.Common','DVNavigationController'],
   uiNav:['Core.dll','UIKit','UINavigationController']};
  const s={};for(const [key,args] of Object.entries(spec)){
   s[key]=getClass(...args);if(s[key].isNull())throw new Error('metadata');
  }
  if(!f.assignable(s.vc,s.search)||!f.assignable(s.card,s.filters)||
     !f.assignable(s.dv,s.search))throw new Error('hierarchy');
  const specs=[['windowRoot','window','get_RootViewController',18,'vc'],
   ['lastView','window','GetLastPresentedView',18,'view'],
   ['top','vc','get_TopViewController',18,'vc'],
   ['viewController','view','get_ViewController',18,'vc'],
   ['hasView','vc','get_HasView',2],['viewOf','vc','get_View',18,'view'],
   ['presenting','vc','get_IsBeingPresented',2],['dismissing','vc','get_IsBeingDismissed',2],['isPresented','vc','get_IsPresented',2],
   ['parent','view','get_Parent',18,'view'],
   ['hidden','view','get_EffectivelyHidden',2],['interactive','view','get_UserInteractionEnabled',2],
   ['canClose','card','get_CanBeClosedByUser',2],
   ['rootNav','appRoot','get_MainNavigationController',18,'vc'],
   ['loading','appRoot','get_IsShowingLoadingView',2],
   ['tabCurrent','tabs','get_CurrentViewController',18,'vc'],
   ['dvCurrent','dvContainer','get_CurrentViewController',18,'vc'],
   ['uiCurrent','uiContainer','get_CurrentViewController',18,'vc'],
   ['dvTransition','dvNav','get_InTransition',2],['uiTransition','uiNav','get_InTransition',2],
   ['hasPresented','vc','HasPresentedViewControllers',2],
   ['presented','vc','get_PresentedViewControllers',21],
   ['nearestPresenter','vc','get_NearestPresentingViewController',18,'vc'],
   ['open','search','ShowSearchSettings',1],['cancel','card','DismissWithCancel',1]];
  for(const [key,owner,name,kind,result] of specs){
   const klass=owner==='window'?getClass('Core.dll','UIKit','UIWindow'):s[owner];
   const m=get(klass,name);
   if(!signature(m,false,kind)||!f.methodClass(m).equals(klass)||f.byref(f.returnType(m)))throw new Error('signature');
   if(result&&!f.assignable(s[result],f.classFromType(f.returnType(m))))throw new Error('return-type');
   s[key]={m,klass,kind,arity:0};
  }
  // Exact declared reference collection; never treat it as a boxed iterator.
  const klass=f.classFromType(f.returnType(s.presented.m));
  const small=p=>{if(p.isNull())return '';let value='';for(let i=0;i<96;i++){const c=p.add(i).readU8();if(c===0)return value;if(c<32||c>126)throw new Error('signature');value+=String.fromCharCode(c);}throw new Error('signature');};
  if(klass.isNull()||f.isValueType(klass)||small(f.className(klass))!=='ReadOnlyList`1'||
     small(f.classNamespace(klass))!=='Core.Collections'||small(f.imageName(f.classImage(klass)))!=='Core.dll')throw new Error('signature');
  s.modalClass=klass;
  const count=f.method(klass,Memory.allocUtf8String('get_Count'),0);
  const item=f.method(klass,Memory.allocUtf8String('get_Item'),1);
  if(!signature(count,false,8)||!f.methodClass(count).equals(klass)||f.byref(f.returnType(count)))throw new Error('signature');
  const bits=Memory.alloc(4);bits.writeU32(0);
  if(item.isNull()||f.arity(item)!==1||(f.flags(item,bits)&(16|1024))!==0||!f.methodClass(item).equals(klass)||
     f.typeKind(f.returnType(item))!==18||f.byref(f.returnType(item))||!f.classFromType(f.returnType(item)).equals(s.vc))throw new Error('signature');
  const param=f.param(item,0);if(param.isNull()||f.typeKind(param)!==8||f.byref(param))throw new Error('signature');
  s.modalCount={m:count,klass,kind:8,arity:0};s.modalItem={m:item,klass,kind:18,arity:1};
  return s;
 }
 function navigationTick(f,s,window,n,state){
  const held=[];const deadline=Date.now()+100;
  n.readiness_check='not-checked';n.view_parent_depth=0;n.readiness={has_view:null,is_presented:null,hidden:null,interactive:null,attached_to_main_window:null};
  const fail=e=>{throw e;};
  const own=obj=>{
   if(obj.isNull())fail('unexpected-object');if(held.length>=64)fail('handle-limit');const h=f.keep(obj,1);
   if(h.isNull())fail('handle-allocation-failed');n.handles_acquired++;held.push(h);return h;
  };
  const target=h=>{const obj=f.target(h);if(obj.isNull())fail('unexpected-object');return obj;};
  const call=(entry,obj,params=ptr(0))=>{
   if(state.stop!==null)fail(state.stop);if(fixedCancellationRequested)fail('cancelled');
   if(Date.now()>deadline)fail('frame-budget');if(n.managed_calls>=6000)fail('call-limit');
   if(obj.isNull()||!f.assignable(entry.klass,f.objectClass(obj)))fail('unexpected-object');
   let m=entry.m;const flags=Memory.alloc(4);flags.writeU32(0);
   if((f.flags(m,flags)&64)!==0){
    m=f.virtualMethod(obj,m);if(m.isNull()||f.arity(m)!==entry.arity||f.typeKind(f.returnType(m))!==entry.kind||f.byref(f.returnType(m)))fail('signature-mismatch');
    const owner=f.methodClass(m);if(owner.isNull()||!f.assignable(owner,f.objectClass(obj)))fail('signature-mismatch');
   }
   if(entry.arity===1){if(!f.classFromType(f.returnType(m)).equals(s.vc))fail('signature-mismatch');const p=f.param(m,0);if(p.isNull()||f.typeKind(p)!==8||f.byref(p))fail('signature-mismatch');}
   const flags2=Memory.alloc(4);flags2.writeU32(0);
   if((f.flags(m,flags2)&(16|1024))!==0)fail('signature-mismatch');
   const ex=Memory.alloc(8);ex.writePointer(ptr(0));n.managed_calls++;
   const out=f.invoke(m,obj,params,ex);if(!ex.readPointer().isNull())fail('managed-exception');return out;
  };
  const bool=(entry,obj)=>{
   const b=call(entry,obj);if(b.isNull())fail('signature-mismatch');
   const p=f.unbox(b);if(p.isNull())fail('signature-mismatch');const v=p.readU8();
   if(v!==0&&v!==1)fail('signature-mismatch');return v===1;
  };
  const kind=obj=>{
   if(obj.isNull())return 'none';const klass=f.objectClass(obj);
   if(klass.equals(s.search))return 'search';if(klass.equals(s.filters))return 'filters';
   for(const [label,key] of [['root','appRoot'],['main-tabs','tabs'],['dv-navigation','dvNav'],
    ['ui-navigation','uiNav'],['dv-container','dvContainer'],['ui-container','uiContainer']])
    if(f.assignable(s[key],klass))return label;
   return 'other';
  };
  const modal=current=>{
   const list=call(s.presented,current);if(list.isNull())return ptr(0);
   own(list);if(!f.objectClass(list).equals(s.modalClass))fail('unexpected-object');
   const count=()=>{const b=call(s.modalCount,list);if(b.isNull())fail('signature-mismatch');const p=f.unbox(b);if(p.isNull())fail('signature-mismatch');return p.readS32();};
   const length=count();if(length<0||length>8)fail('modal-count-invalid');
   if(length===0)return ptr(0);
   n.readiness_check='modal-list';
   // No stack-order guess: only one exact, stable controller is actionable.
   if(length!==1)fail('modal-ambiguous');
   const index=Memory.alloc(4);index.writeS32(0);const params=Memory.alloc(Process.pointerSize);params.writePointer(index);
   const item=call(s.modalItem,list,params);if(item.isNull())fail('unexpected-object');own(item);
   if(!f.assignable(s.vc,f.objectClass(item)))fail('unexpected-object');
   if(count()!==length)fail('modal-changed');
   const again=call(s.modalItem,list,params);if(!again.equals(item))fail('modal-changed');
   return item;
  };
  const resolve=current=>{
   const seen=new Set();n.controller_path=[];
   for(let depth=0;depth<12;depth++){
    if(current.isNull())return ptr(0);
    const h=own(current),key=target(h).toString();
    if(seen.has(key))fail('controller-cycle');seen.add(key);
    const k=kind(current);n.controller_path.push(k);
    if(k==='other')fail(n.phase==='search'?'wrong-screen':'unexpected-screen');
    if(bool(s.presenting,current)||bool(s.dismissing,current))return ptr(0);
    const presented=modal(current);
    if(!presented.isNull()){current=presented;continue;}
    if(k==='search'||k==='filters'){
     // A selected search tab can delegate presentation to an owner outside its
     // container path. Resolve that owner's real collection, not a screen tap.
     if(k==='search'&&bool(s.hasPresented,current)){
      const owner=call(s.nearestPresenter,current);if(owner.isNull())fail('presentation-not-resolved');own(owner);
      const pending=modal(owner);
      if(pending.isNull()){n.readiness_check='modal-pending';if(n.phase==='search')fail('presentation-not-resolved');return ptr(0);}
      current=pending;continue;
     }
     return current;
    }
    if(k==='root'&&bool(s.loading,current))return ptr(0);
    if(k==='dv-navigation'&&bool(s.dvTransition,current))return ptr(0);
    if(k==='ui-navigation'&&bool(s.uiTransition,current))return ptr(0);
    const entry=k==='root'?s.rootNav:k==='main-tabs'?s.tabCurrent:
     k==='dv-container'?s.dvCurrent:s.uiCurrent;
    current=call(entry,current);
   }
   fail('controller-depth-limit');
  };
  const checkView=(current)=>{
   n.readiness={has_view:null,is_presented:null,hidden:null,interactive:null,attached_to_main_window:null};
   n.view_parent_depth=0;n.readiness_check='has-view';
   n.readiness.has_view=bool(s.hasView,current);if(!n.readiness.has_view)return false;
   // IsPresented describes presentation, not visibility of a selected child tab.
   n.readiness.is_presented=bool(s.isPresented,current);
   const view=call(s.viewOf,current);own(view);
   n.readiness_check='view-hidden';n.readiness.hidden=bool(s.hidden,view);if(n.readiness.hidden)return false;
   n.readiness_check='view-interactive';n.readiness.interactive=bool(s.interactive,view);if(!n.readiness.interactive)return false;
   n.readiness_check='view-parent-chain';const seen=new Set();let cursor=view;
   for(let depth=0;depth<32;depth++){
    n.view_parent_depth=depth;const key=cursor.toString();
    if(seen.has(key))fail('view-parent-cycle');seen.add(key);
    if(cursor.equals(window)){n.readiness.attached_to_main_window=true;n.readiness_check='ready';return true;}
    cursor=call(s.parent,cursor);
    if(cursor.isNull()){n.readiness.attached_to_main_window=false;return false;}
    own(cursor);
   }
   fail('view-parent-depth-limit');
  };
  try {
   const root=call(s.windowRoot,window);own(root);
   const rootTop=call(s.top,root);if(!rootTop.isNull())own(rootTop);n.root_top_kind=kind(rootTop);
   const last=call(s.lastView,window);n.last_presented_kind='none';
   let candidate=root;
   if(!last.isNull()){
    own(last);n.readiness_check='presented-view';n.readiness.hidden=bool(s.hidden,last);n.readiness.interactive=bool(s.interactive,last);if(n.readiness.hidden||!n.readiness.interactive)return;
    candidate=call(s.viewController,last);if(candidate.isNull())fail('unexpected-object');own(candidate);
    n.last_presented_kind=kind(candidate);
   }
   const current=resolve(candidate);if(current.isNull())return;
   const k=kind(current);
   if(n.phase==='search'&&k!=='search')fail('wrong-screen');
   if(n.phase!=='search'&&!['search','filters'].includes(k))fail('unexpected-screen');
   if(bool(s.presenting,current)||bool(s.dismissing,current))return;
   if(!checkView(current))return;
   if(n.phase==='search'){
    n.search_verified=true;state.origin=own(current);held.splice(held.indexOf(state.origin),1);
    n.open_attempted=true;call(s.open,current);n.open_completed=true;n.phase='wait-filters';return;
   }
   if(n.phase==='wait-filters'){
    if(k==='search'){
     if(!current.equals(target(state.origin)))fail('identity-changed');return;
    }
    n.filters_verified=true;state.card=own(current);held.splice(held.indexOf(state.card),1);
    n.phase='confirm-filters';return;
   }
   if(n.phase==='confirm-filters'){
    if(k!=='filters'||!current.equals(target(state.card)))fail('identity-changed');
    if(!bool(s.canClose,current))fail('screen-not-ready');
    n.cancel_attempted=true;call(s.cancel,current);n.cancel_completed=true;n.phase='wait-return';return;
   }
   if(n.phase==='wait-return'){
    if(k==='filters'){
     if(!current.equals(target(state.card)))fail('identity-changed');return;
    }
    if(!current.equals(target(state.origin)))fail('identity-changed');
    n.return_verified=true;n.phase='done';n.stage='navigation-ready';
   }
  } catch(e){n.error=typeof e==='string'&&__NAV_ERRORS__.includes(e)?e:'native-call-failed';n.stage='navigation-stopped';}
  finally {
   for(const h of held)try{f.release(h);n.handles_released++;}catch(_){n.cleanup_failed=true;}
  }
 }
 function cleanupNavigation(f,n,state){
  for(const key of ['card','origin'])if(state[key]&&!state[key].isNull()){
   try{f.release(state[key]);n.handles_released++;}catch(_){n.cleanup_failed=true;}state[key]=ptr(0);
  }
  if(n.cleanup_failed){n.stage='cleanup-failed';n.error='cleanup-failed';}
 }
'''
APIS=['il2cpp_method_get_class','il2cpp_type_is_byref','il2cpp_class_from_type',
      'il2cpp_gchandle_get_target','il2cpp_object_get_virtual_method',
      'il2cpp_method_get_param','il2cpp_class_is_valuetype','il2cpp_class_get_name','il2cpp_class_get_namespace','il2cpp_class_get_image']
BINDINGS="""Object.assign(f,{
 methodClass:bind('method_get_class','pointer',['pointer']),byref:bind('type_is_byref','bool',['pointer']),
 classFromType:bind('class_from_type','pointer',['pointer']),target:bind('gchandle_get_target','pointer',['pointer']),
 param:bind('method_get_param','pointer',['pointer','uint']),isValueType:bind('class_is_valuetype','bool',['pointer']),
 className:bind('class_get_name','pointer',['pointer']),classNamespace:bind('class_get_namespace','pointer',['pointer']),classImage:bind('class_get_image','pointer',['pointer']),
 virtualMethod:bind('object_get_virtual_method','pointer',['pointer','pointer'])});"""
FUNCTION=build_function(extra_apis=APIS,helpers=HELPERS.replace('__NAV_ERRORS__',__import__('json').dumps(sorted(ERRORS))),
 init='r.navigation=emptyNavigation();const navState={origin:ptr(0),card:ptr(0),stop:null};',
 bindings=BINDINGS,setup="setup.navigation=prepareNavigation(f,getClass,get,signature);setup.watchers=setup.watchers.slice(0,1);for(const label of Object.keys(r.watched_sources))r.watched_sources[label]=setup.watchers.some(item=>item[0]===label);",
 body="r.navigation.stage='navigation-running';navigationTick(f,setup.navigation,window,r.navigation,navState);if(r.navigation.cleanup_failed)r.cleanup_failed=true;")
# This module owns a bounded multi-frame observer; root-only/tree-only code stays unchanged.
FUNCTION=FUNCTION.replace("['Core.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll'].includes(name)",
 "['Core.dll','DV.dll','DV.Search.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll'].includes(name)")
FUNCTION=FUNCTION.replace("if(timer!==null)clearTimeout(timer);", """if(timer!==null)clearTimeout(timer);
   if(r.navigation.stage==='navigation-running'){
    r.navigation.stage='navigation-stopped';r.navigation.error='observer-stopped';
   }
   if(f!==null)cleanupNavigation(f,r.navigation,navState);
   if(r.navigation.cleanup_failed)r.cleanup_failed=true;""")
FUNCTION=FUNCTION.replace("active=false;r.observed_callback=true;", "active=false;r.navigation.frames++;r.observed_callback=true;")
FUNCTION=FUNCTION.replace("     finish(stage);", """     if(fixedCancellationRequested){navState.stop='cancelled';
      // Same truthfulness guard as the deferred-finish application above: a
      // frame that completed the navigation keeps its verified state; only a
      // still running navigation is stopped by the cancellation.
      if(r.navigation.stage==='navigation-running'){r.navigation.stage='navigation-stopped';r.navigation.error='cancelled';}}
     if(stage==='root-ready'&&r.navigation.stage==='navigation-running'&&!r.cleanup_failed){
      if(r.navigation.frames>=180){r.navigation.stage='navigation-stopped';r.navigation.error='frame-limit';}
      else {active=true;return;}
     }
     finish(stage);""")
FUNCTION=FUNCTION.replace("timer=setTimeout(()=>finish('callback-timeout'),8000);", """timer=setTimeout(()=>{
   navState.stop='transition-timeout';if(r.navigation.stage==='navigation-running'){r.navigation.stage='navigation-stopped';r.navigation.error='transition-timeout';}
   finish('callback-timeout');},16000);""")


def validate(value, *, max_calls=MAX_CALLS, max_frames=MAX_FRAMES, phases=PHASES, errors=ERRORS, kinds=KINDS, allow_ui_text=False):
    if not isinstance(value,dict) or 'navigation' not in value:raise ValueError('Missing navigation report')
    n=value['navigation']
    flags={'cleanup_failed','search_verified','filters_verified','return_verified','open_attempted',
           'open_completed','cancel_attempted','cancel_completed','ui_text_read'}
    fields=flags|{'stage','phase','error','frames','managed_calls','handles_acquired','handles_released',
                  'root_top_kind','last_presented_kind','controller_path','action_backend','readiness_check','readiness','view_parent_depth'}
    if not isinstance(n,dict) or set(n)!=fields:raise ValueError('Unexpected navigation fields')
    if n['stage'] not in {'not-attempted','navigation-running','navigation-ready','navigation-stopped','cleanup-failed'} or n['phase'] not in phases or n['error'] not in errors:raise ValueError('Invalid navigation state')
    if n['stage']=='navigation-running':raise ValueError('Unfinished navigation')
    if any(type(n[k]) is not bool for k in flags):raise ValueError('Invalid navigation flag')
    for key,limit in [('frames',max_frames),('managed_calls',max_calls),('handles_acquired',max_frames*64+2),('handles_released',max_frames*64+2)]:
        if type(n[key]) is not int or not 0<=n[key]<=limit:raise ValueError('Invalid navigation count')
    if n['handles_released']>n['handles_acquired'] or (not n['cleanup_failed'] and n['handles_acquired']!=n['handles_released']):raise ValueError('Unreported handle leak')
    if any(n[k] not in kinds for k in ('root_top_kind','last_presented_kind')) or n['action_backend']!='semantic-controller-handlers' or (n['ui_text_read'] and not allow_ui_text):raise ValueError('Unexpected backend or screen data')
    path=n['controller_path']
    if not isinstance(path,list) or len(path)>12 or any(type(k) is not str or k not in kinds-{'not-checked','none'} for k in path):raise ValueError('Invalid controller path')
    readiness=n['readiness']
    if not isinstance(readiness,dict) or set(readiness)!={'has_view','is_presented','hidden','interactive','attached_to_main_window'} or any(v is not None and type(v) is not bool for v in readiness.values()):raise ValueError('Invalid readiness flags')
    if n['readiness_check'] not in {'not-checked','has-view','view-hidden','view-interactive','view-parent-chain','ready','presented-view','modal-pending','modal-list'}:raise ValueError('Invalid readiness step')
    if type(n['view_parent_depth']) is not int or not 0<=n['view_parent_depth']<32:raise ValueError('Invalid parent depth')
    if n['stage']=='navigation-ready' and (n['readiness_check']!='ready' or readiness['has_view'] is not True or readiness['hidden'] is not False or readiness['interactive'] is not True or readiness['attached_to_main_window'] is not True):raise ValueError('Navigation without ready attached view')
    chain=['search_verified','open_attempted','open_completed','filters_verified','cancel_attempted','cancel_completed','return_verified']
    for earlier,later in zip(chain,chain[1:]):
        if n[later] and not n[earlier]:raise ValueError('Out-of-order navigation')
    base={k:v for k,v in value.items() if k!='navigation'}
    count=base.get('managed_calls')
    if type(count) is not int or not 0<=count<=3*n['frames']:raise ValueError('Invalid observer call count')
    # Reuse the root schema; its success invariant is three calls per callback.
    checked=dict(base);checked['managed_calls']=min(count,3)
    validate_root(checked)
    if n['managed_calls'] and not (base['main_thread_confirmed'] and base['object_classes_validated']):raise ValueError('Navigation without confirmed UI thread')
    if n['cleanup_failed'] and not base['cleanup_failed']:raise ValueError('Cleanup failure not propagated')
    if n['stage']=='navigation-ready':
        if n['phase']!='done' or n['error']!='none' or not all(n[k] for k in chain) or n['cleanup_failed'] or base['stage']!='root-ready' or count!=n['frames']*3:raise ValueError('Inconsistent navigation success')
    if (n['stage']=='cleanup-failed')!=n['cleanup_failed']:raise ValueError('Inconsistent navigation cleanup')
    if n['stage']=='not-attempted' and (n['managed_calls'] or n['handles_acquired'] or any(n[k] for k in chain) or n['error']!='none'):raise ValueError('Unexpected unattempted navigation')
    if n['stage']=='navigation-stopped' and n['error']=='none':raise ValueError('Missing stop reason')
    return value

# Fixed cancellation only stops this workflow; it never clicks or restores a screen.
FUNCTION="let cancelFixedNavigation=null;let fixedCancellationRequested=false;\n"+FUNCTION
FUNCTION=FUNCTION.replace("const navState={origin:ptr(0),card:ptr(0),stop:null};", "const navState={origin:ptr(0),card:ptr(0),stop:null};if(fixedCancellationRequested){r.navigation.stage='navigation-stopped';r.navigation.error='cancelled';r.stage='callback-timeout';return Promise.resolve(r);}")
FUNCTION=FUNCTION.replace("if(settled)return;settled=true;active=false;", "if(settled)return;settled=true;active=false;cancelFixedNavigation=null;")
FUNCTION=FUNCTION.replace("   r.step='prepare-observer';", """   cancelFixedNavigation=()=>{
    // NativeFunction may yield to another RPC: defer cleanup until the frame's finally.
    navState.stop='cancelled';if(!active)return;
    r.navigation.stage='navigation-stopped';r.navigation.error='cancelled';finish('callback-timeout');
   };
   r.step='prepare-observer';""")
FUNCTION+="\nfunction cancelNavigation(){fixedCancellationRequested=true;if(cancelFixedNavigation!==null)cancelFixedNavigation();}\n"

# A Frida native call can cooperatively yield to a timer/RPC. Never resolve or
# release persistent handles until the callback's temporary-handle finally ran.
FUNCTION=FUNCTION.replace("let listener=null,timer=null,active=true,settled=false;", "let listener=null,timer=null,active=true,settled=false,frameBusy=false,pendingFinish=null;")
FUNCTION=FUNCTION.replace("if(settled)return;settled=true;", "if(settled)return;if(frameBusy){pendingFinish=stage;return;}settled=true;")
FUNCTION=FUNCTION.replace("active=false;r.navigation.frames++;", "active=false;frameBusy=true;r.navigation.frames++;")
FUNCTION=FUNCTION.replace("     if(fixedCancellationRequested){", """     frameBusy=false;if(pendingFinish!==null){stage=pendingFinish;
      // Report 499 (v1.3.74): the absolute cycle timer can fire while the
      // final frame is still running (a Frida native call cooperatively
      // yields), so the deferred finish is applied after that frame. The
      // unconditional rewrite used to corrupt a frame that had JUST completed
      // the cycle - a verified search return became navigation-stopped and
      // the whole port died at 'Unverified direct search return'. Only a
      // still-running navigation may be stopped here; a completed (ready) or
      // already-stopped navigation keeps its own truthful state.
      if(r.navigation.stage==='navigation-running'){r.navigation.stage='navigation-stopped';r.navigation.error=navState.stop||'observer-stopped';}}
     if(fixedCancellationRequested){""")
