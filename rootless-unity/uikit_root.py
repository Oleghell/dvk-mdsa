"""One-shot root presence probe on an observed, independently checked UI thread.

Hooks only the exported IL2CPP invocation API, not guessed MethodInfo code offsets.
It never invokes frame methods, writes arguments/returns or traverses UI contents.
"""
import json
from il2cpp_exports import with_module_exports

APIS=['il2cpp_domain_get','il2cpp_thread_current','il2cpp_thread_attach','il2cpp_thread_detach',
 'il2cpp_domain_get_assemblies','il2cpp_assembly_get_image','il2cpp_image_get_name','il2cpp_class_from_name',
 'il2cpp_class_get_method_from_name','il2cpp_method_get_param_count','il2cpp_method_get_flags',
 'il2cpp_method_get_return_type','il2cpp_type_get_type','il2cpp_runtime_invoke','il2cpp_object_unbox',
 'il2cpp_object_get_class','il2cpp_class_is_assignable_from','il2cpp_gchandle_new','il2cpp_gchandle_free']
SOURCES=['uikit-component-update','uikit-runtime-update','unity-execute-tasks']
STAGES={'not-started','unsupported-pointer-size','api-incomplete','metadata-not-ready','signature-mismatch',
 'native-call-failed','managed-exception','original-frame-exception','hook-unavailable','hook-limit',
 'callback-timeout','off-main-thread','runtime-not-ready','window-not-ready','object-class-mismatch',
 'root-ready','cleanup-failed'}
STEPS={'not-started','resolve-api','metadata','prepare-observer','observe-frame','main-thread-check','runtime-get','window-get','done'}
_TEMPLATE=with_module_exports(r'''
function probeUIKitRoot() {
 __INIT_HELPERS__
 const r={stage:'not-started',step:'not-started',api_available:false,metadata_ready:false,
  observer_installed:false,observed_callback:false,main_thread_confirmed:false,
  runtime_available:false,window_available:false,object_classes_validated:false,
  hooks_detached:false,cleanup_failed:false,metadata_thread_attached:false,
  metadata_thread_detached:false,runtime_handle_acquired:false,window_handle_acquired:false,
  runtime_handle_released:false,window_handle_released:false,observed_calls:0,managed_calls:0,
  watched_sources:{'uikit-component-update':false,'uikit-runtime-update':false,'unity-execute-tasks':false},
  frame_source:'not-observed'};
 __INIT_REPORT__
 if(Process.pointerSize!==8){r.stage='unsupported-pointer-size';return Promise.resolve(r);}
 let f=null,addresses={},thread=ptr(0),attachedHere=false,setup=null;
 try {
  r.step='resolve-api';
  for(const n of __APIS__) {const p=Module.findGlobalExportByName(n);if(p===null){r.stage='api-incomplete';return Promise.resolve(r);}addresses[n]=p;}
  r.api_available=true;
  const bind=(n,ret,args)=>new NativeFunction(addresses['il2cpp_'+n],ret,args,{exceptions:'steal'});
  f={domain:bind('domain_get','pointer',[]),current:bind('thread_current','pointer',[]),
   attach:bind('thread_attach','pointer',['pointer']),detach:bind('thread_detach','void',['pointer']),
   assemblies:bind('domain_get_assemblies','pointer',['pointer','pointer']),image:bind('assembly_get_image','pointer',['pointer']),
   imageName:bind('image_get_name','pointer',['pointer']),klass:bind('class_from_name','pointer',['pointer','pointer','pointer']),
   method:bind('class_get_method_from_name','pointer',['pointer','pointer','int']),
   arity:bind('method_get_param_count','uint32',['pointer']),flags:bind('method_get_flags','uint32',['pointer','pointer']),
   returnType:bind('method_get_return_type','pointer',['pointer']),typeKind:bind('type_get_type','int',['pointer']),
   invoke:bind('runtime_invoke','pointer',['pointer','pointer','pointer','pointer']),
   unbox:bind('object_unbox','pointer',['pointer']),objectClass:bind('object_get_class','pointer',['pointer']),
   assignable:bind('class_is_assignable_from','bool',['pointer','pointer']),
   keep:bind('gchandle_new','pointer',['pointer','bool']),release:bind('gchandle_free','void',['pointer'])};
  __EXTRA_BINDINGS__
  r.step='metadata';const domain=f.domain();if(domain.isNull()){r.stage='metadata-not-ready';return Promise.resolve(r);}
  if(f.current().isNull()) {
   thread=f.attach(domain);if(thread.isNull()){r.stage='metadata-not-ready';return Promise.resolve(r);}
   attachedHere=true;r.metadata_thread_attached=true;
  }
  const size=Memory.alloc(8);size.writeU64(0);const all=f.assemblies(domain,size);const n=size.readU64().toNumber();
  if(!Number.isSafeInteger(n)||n<1||n>2048||all.isNull()){r.stage='metadata-not-ready';return Promise.resolve(r);}
  const images={};const deadline=Date.now()+2500;
  for(let i=0;i<n;i++) {
   if(Date.now()>deadline){r.stage='metadata-not-ready';return Promise.resolve(r);}
   const a=all.add(i*8).readPointer();if(a.isNull())continue;
   const im=f.image(a);if(im.isNull())continue;const p=f.imageName(im);if(p.isNull())continue;
   let name='',terminated=false;
   for(let j=0;j<192;j++){const c=p.add(j).readU8();if(c===0){terminated=true;break;}if(!((c>=48&&c<=57)||(c>=65&&c<=90)||(c>=97&&c<=122)||c===46||c===45||c===95))break;name+=String.fromCharCode(c);}
   if(terminated&&['Core.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll'].includes(name))images[name]=im;
  }
  const getClass=(image,ns,name)=>images[image]?f.klass(images[image],Memory.allocUtf8String(ns),Memory.allocUtf8String(name)):ptr(0);
  const runtime=getClass('Core.dll','UIKit','UIRuntime'),window=getClass('Core.dll','UIKit','UIWindow');
  const component=getClass('UIKit.Unity.dll','UIKit','UIRuntimeComponent');
  const sync=getClass('UnityEngine.CoreModule.dll','UnityEngine','UnitySynchronizationContext');
  if(runtime.isNull()||window.isNull()){r.stage='metadata-not-ready';return Promise.resolve(r);}
  const get=(k,name)=>k.isNull()?ptr(0):f.method(k,Memory.allocUtf8String(name),0);
  const guard=get(runtime,'get_IsOnMainThread'),instance=get(runtime,'get_OptionalInstance'),root=get(runtime,'get_MainWindow');
  const signature=(m,isStatic,kind)=>{
   if(m.isNull()||f.arity(m)!==0)return false;
   const flags=Memory.alloc(4);flags.writeU32(0);const actual=f.flags(m,flags);
   const t=f.returnType(m);return !t.isNull()&&((actual&16)!==0)===isStatic&&f.typeKind(t)===kind;
  };
  // IL2CPP type kinds: VOID=1, BOOLEAN=2, CLASS=18. No guessed MethodInfo offsets.
  if(!signature(guard,true,2)||!signature(instance,true,18)||!signature(root,false,18)){
   r.stage='signature-mismatch';return Promise.resolve(r);
  }
  const specs=[['uikit-component-update',get(component,'Update'),false],
   ['uikit-runtime-update',get(runtime,'OnUnityUpdate'),false],['unity-execute-tasks',get(sync,'ExecuteTasks'),true]];
  const watchers=[];
  for(const [label,m,isStatic] of specs)if(signature(m,isStatic,1)){watchers.push([label,m]);r.watched_sources[label]=true;}
  if(watchers.length===0){r.stage='metadata-not-ready';return Promise.resolve(r);}
  setup={runtime,window,guard,instance,root,watchers};__SETUP_EXTENSION__r.metadata_ready=true;
 } catch(_) {setup=null;r.stage='native-call-failed';}
 finally {
  if(attachedHere&&f!==null){try{f.detach(thread);r.metadata_thread_detached=f.current().isNull();if(!r.metadata_thread_detached)r.cleanup_failed=true;}catch(_){r.cleanup_failed=true;}}
 }
 if(r.cleanup_failed){r.stage='cleanup-failed';return Promise.resolve(r);}
 if(setup===null)return Promise.resolve(r);
 return new Promise(resolve=>{
  let listener=null,timer=null,active=true,settled=false;
  const finish=(stage)=>{
   if(settled)return;settled=true;active=false;if(timer!==null)clearTimeout(timer);
   if(listener!==null){try{listener.detach();r.hooks_detached=true;}catch(_){r.cleanup_failed=true;}}
   r.stage=r.cleanup_failed?'cleanup-failed':stage;if(stage==='root-ready')r.step='done';resolve(r);
  };
  const invoke=(method,obj)=>{
   const exception=Memory.alloc(8);exception.writePointer(ptr(0));r.managed_calls++;
   const result=f.invoke(method,obj,ptr(0),exception);
   if(!exception.readPointer().isNull())throw 'managed-exception';
   return result;
  };
  try {
   r.step='prepare-observer';
   listener=Interceptor.attach(addresses.il2cpp_runtime_invoke,{
    onEnter(args){
     this.uiFrame=false;
     if(!active)return;
     r.observed_calls++;
     if(r.observed_calls>10000){r.observed_calls=10000;finish('hook-limit');return;}
     for(const [label,method] of setup.watchers)if(args[0].equals(method)){
      this.uiFrame=true;this.uiSource=label;this.uiException=args[3];break;
     }
    },
    onLeave(_retval){
     if(!active||!this.uiFrame)return;
     active=false;r.observed_callback=true;r.frame_source=this.uiSource;r.step='observe-frame';
     let runtimeHandle=ptr(0),windowHandle=ptr(0),stage='native-call-failed';
     try {
      if(!this.uiException.isNull()&&!this.uiException.readPointer().isNull())throw 'original-frame-exception';
      // No attach here: observation must already be on an IL2CPP-owned thread.
      if(f.current().isNull())throw 'off-main-thread';
      r.step='main-thread-check';const boxed=invoke(setup.guard,ptr(0));
      if(boxed.isNull())throw 'signature-mismatch';
      const value=f.unbox(boxed);if(value.isNull())throw 'signature-mismatch';const yes=value.readU8();
      if(yes!==0&&yes!==1)throw 'signature-mismatch';
      if(yes!==1)throw 'off-main-thread';r.main_thread_confirmed=true;
      r.step='runtime-get';const runtime=invoke(setup.instance,ptr(0));r.runtime_available=!runtime.isNull();
      if(runtime.isNull())throw 'runtime-not-ready';
      runtimeHandle=f.keep(runtime,0);r.runtime_handle_acquired=!runtimeHandle.isNull();if(runtimeHandle.isNull())throw 'native-call-failed';
      if(!f.assignable(setup.runtime,f.objectClass(runtime)))throw 'object-class-mismatch';
      r.step='window-get';const window=invoke(setup.root,runtime);r.window_available=!window.isNull();
      if(window.isNull())throw 'window-not-ready';
      windowHandle=f.keep(window,0);r.window_handle_acquired=!windowHandle.isNull();if(windowHandle.isNull())throw 'native-call-failed';
      if(!f.assignable(setup.window,f.objectClass(window)))throw 'object-class-mismatch';
      r.object_classes_validated=true;__BODY_EXTENSION__stage='root-ready';
     } catch(e) {stage=(typeof e==='string'&&__STAGES__.includes(e))?e:'native-call-failed';}
     finally {
      for(const [label,h] of [['window',windowHandle],['runtime',runtimeHandle]])if(!h.isNull()){try{f.release(h);r[label+'_handle_released']=true;}catch(_){r.cleanup_failed=true;}}
     }
     finish(stage);
    }
   });
   r.observer_installed=true;r.step='observe-frame';
   timer=setTimeout(()=>finish('callback-timeout'),8000);Interceptor.flush();
  }catch(_){finish('hook-unavailable');}
 });
}
''')


def build_function(*,extra_apis=(),helpers='',init='',bindings='',setup='',body=''):
    # Internal build-time composition only; never accepts RPC/user-supplied code.
    return (_TEMPLATE.replace('__APIS__',json.dumps(APIS+list(extra_apis)))
        .replace('__STAGES__',json.dumps(sorted(STAGES)))
        .replace('__INIT_HELPERS__',helpers).replace('__INIT_REPORT__',init)
        .replace('__EXTRA_BINDINGS__',bindings).replace('__SETUP_EXTENSION__',setup)
        .replace('__BODY_EXTENSION__',body))


FUNCTION=build_function()


def validate(value):
    flags=['api_available','metadata_ready','observer_installed','observed_callback','main_thread_confirmed',
           'runtime_available','window_available','object_classes_validated','hooks_detached','cleanup_failed',
           'metadata_thread_attached','metadata_thread_detached','runtime_handle_acquired','window_handle_acquired',
           'runtime_handle_released','window_handle_released']
    fields=set(flags)|{'stage','step','observed_calls','managed_calls','watched_sources','frame_source'}
    if not isinstance(value,dict) or set(value)!=fields:raise ValueError('Unexpected root probe fields')
    if value['stage'] not in STAGES or value['step'] not in STEPS:raise ValueError('Unexpected root probe stage')
    if any(type(value[k]) is not bool for k in flags):raise ValueError('Invalid root probe flag')
    for k,limit in (('observed_calls',10000),('managed_calls',3)):
        if type(value[k]) is not int or not 0<=value[k]<=limit:raise ValueError('Invalid root probe count')
    sources=value['watched_sources']
    if not isinstance(sources,dict) or set(sources)!=set(SOURCES) or any(type(v) is not bool for v in sources.values()):raise ValueError('Invalid watched source map')
    if value['frame_source'] not in SOURCES+['not-observed']:raise ValueError('Invalid frame source')
    if value['managed_calls'] and not value['observed_callback']:raise ValueError('UI calls without frame observation')
    for resource in ('runtime','window'):
        if value[resource+'_handle_released'] and not value[resource+'_handle_acquired']:
            raise ValueError('Release without acquired handle')
    if value['stage']=='root-ready':
        needed=['api_available','metadata_ready','observer_installed','observed_callback','main_thread_confirmed',
                'runtime_available','window_available','object_classes_validated','hooks_detached',
                'runtime_handle_acquired','window_handle_acquired','runtime_handle_released','window_handle_released']
        if not all(value[k] for k in needed) or value['cleanup_failed'] or value['managed_calls']!=3 or value['frame_source']=='not-observed':raise ValueError('Inconsistent root probe success')
        if value['metadata_thread_attached'] and not value['metadata_thread_detached']:raise ValueError('Unfinished metadata thread cleanup')
    return value
