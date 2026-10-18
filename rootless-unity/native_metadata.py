"""Bounded IL2CPP metadata-only C API probe; never invokes managed/UI methods."""
import json

EXPORTS=['il2cpp_domain_get','il2cpp_thread_current','il2cpp_thread_attach','il2cpp_thread_detach',
         'il2cpp_domain_get_assemblies','il2cpp_assembly_get_image','il2cpp_image_get_name',
         'il2cpp_class_from_name','il2cpp_class_get_method_from_name']
TYPES=[
 ('UnityEngine.Object','UnityEngine.CoreModule.dll','UnityEngine','Object'),
 ('UnityEngine.GameObject','UnityEngine.CoreModule.dll','UnityEngine','GameObject'),
 ('UnityEngine.Component','UnityEngine.CoreModule.dll','UnityEngine','Component'),
 ('UnityEngine.Transform','UnityEngine.CoreModule.dll','UnityEngine','Transform'),
 ('UnityEngine.Resources','UnityEngine.CoreModule.dll','UnityEngine','Resources'),
 ('UnityEngine.UnitySynchronizationContext','UnityEngine.CoreModule.dll','UnityEngine','UnitySynchronizationContext'),
 ('UnityEngine.SceneManagement.SceneManager','UnityEngine.CoreModule.dll','UnityEngine.SceneManagement','SceneManager'),
 ('UnityEngine.SceneManagement.Scene','UnityEngine.CoreModule.dll','UnityEngine.SceneManagement','Scene'),
 ('UnityEngine.UI.Button','UnityEngine.UI.dll','UnityEngine.UI','Button'),
 ('UnityEngine.UI.InputField','UnityEngine.UI.dll','UnityEngine.UI','InputField'),
 ('UnityEngine.UI.Text','UnityEngine.UI.dll','UnityEngine.UI','Text'),
 ('UnityEngine.UI.Toggle','UnityEngine.UI.dll','UnityEngine.UI','Toggle'),
 ('UnityEngine.UI.ScrollRect','UnityEngine.UI.dll','UnityEngine.UI','ScrollRect'),
 ('TMPro.TMP_Text','Unity.TextMeshPro.dll','TMPro','TMP_Text'),
 ('TMPro.TMP_InputField','Unity.TextMeshPro.dll','TMPro','TMP_InputField'),
 ('System.Threading.SynchronizationContext','mscorlib.dll','System.Threading','SynchronizationContext'),
]
METHODS=[('UnityEngine.Object','get_name',0),('UnityEngine.Component','get_transform',0),
 ('UnityEngine.Transform','get_childCount',0),('UnityEngine.Transform','GetChild',1),
 ('UnityEngine.Resources','FindObjectsOfTypeAll',1),
 ('UnityEngine.SceneManagement.SceneManager','GetActiveScene',0),
 ('UnityEngine.SceneManagement.Scene','GetRootGameObjects',0),
 ('UnityEngine.UnitySynchronizationContext','Post',2),
 ('System.Threading.SynchronizationContext','Post',2),
 ('UnityEngine.UI.Button','get_onClick',0),('UnityEngine.UI.InputField','get_text',0),
 ('TMPro.TMP_InputField','get_text',0)]
IMAGES=sorted({t[1] for t in TYPES}|{'Assembly-CSharp.dll','System.Private.CoreLib.dll'})
METHOD_KEYS=[f'{t}.{name}/{arity}' for t,name,arity in METHODS]
STAGES={'not-started','unsupported-pointer-size','metadata-api-incomplete','domain-not-ready',
        'thread-attach-failed','assemblies-not-ready','unsafe-assembly-count','metadata-limited',
        'metadata-ready','native-call-failed','metadata-cleanup-failed'}
STEPS={'not-started','resolve-api','bind-api','domain-get','thread-current','thread-attach',
       'domain-assemblies','image-name','class-lookup','method-lookup','done'}

_TEMPLATE = r'''
function nativeMetadata() {
  const typeSpecs=__TYPES__;
  const methodSpecs=__METHODS__;
  const images=__IMAGES__;
  const exports=__EXPORTS__;
  const result={stage:'not-started',step:'not-started',native_calls_performed:false,
    api_exports:{},domain_available:false,current_thread_initially_attached:null,
    thread_attach_performed:false,thread_detach_confirmed:false,cleanup_failed:false,
    assembly_count:0,assemblies_scanned:0,metadata_limit_reached:false,
    known_images:{},known_types:{},known_methods:{}};
  for(const name of exports) result.api_exports[name]=false;
  for(const name of images) result.known_images[name]=false;
  for(const [key] of typeSpecs) result.known_types[key]=false;
  for(const [key,name,arity] of methodSpecs) result.known_methods[key+'.'+name+'/'+arity]=false;
  if(Process.pointerSize !== 8) {result.stage='unsupported-pointer-size';return result;}
  let attachedHere=false,attachedThread=ptr(0),f=null;
  try {
    result.step='resolve-api';
    const addresses={};
    for(const name of exports) {
      const address=Module.findGlobalExportByName(name);
      result.api_exports[name]=address !== null;
      if(address !== null) addresses[name]=address;
    }
    if(exports.some(name=>!result.api_exports[name])) {result.stage='metadata-api-incomplete';return result;}
    result.step='bind-api';
    const bind=(name,ret,args)=>new NativeFunction(addresses[name],ret,args,{exceptions:'steal'});
    f={domain:bind('il2cpp_domain_get','pointer',[]),
       current:bind('il2cpp_thread_current','pointer',[]),
       attach:bind('il2cpp_thread_attach','pointer',['pointer']),
       detach:bind('il2cpp_thread_detach','void',['pointer']),
       assemblies:bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),
       image:bind('il2cpp_assembly_get_image','pointer',['pointer']),
       imageName:bind('il2cpp_image_get_name','pointer',['pointer']),
       klass:bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),
       method:bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int'])};
    result.step='domain-get';result.native_calls_performed=true;
    const domain=f.domain();result.domain_available=!domain.isNull();
    if(domain.isNull()) {result.stage='domain-not-ready';return result;}
    result.step='thread-current';const current=f.current();
    result.current_thread_initially_attached=!current.isNull();
    if(current.isNull()) {
      result.step='thread-attach';attachedThread=f.attach(domain);
      if(attachedThread.isNull()) {result.stage='thread-attach-failed';return result;}
      attachedHere=true;result.thread_attach_performed=true;
    }
    const deadline=Date.now()+2500;
    result.step='domain-assemblies';const count=Memory.alloc(8);count.writeU64(0);
    const assemblies=f.assemblies(domain,count);
    const n=count.readU64().toNumber();
    if(!Number.isSafeInteger(n)||n<0||n>2048) {result.stage='unsafe-assembly-count';return result;}
    result.assembly_count=n;
    if(n===0||assemblies.isNull()) {result.stage='assemblies-not-ready';return result;}
    const loaded={};
    const readName=(p)=>{
      if(p.isNull()) return null;
      let name='';
      for(let j=0;j<192;j++) {
        const c=p.add(j).readU8();
        if(c===0) return name;
        if(!((c>=48&&c<=57)||(c>=65&&c<=90)||(c>=97&&c<=122)||c===46||c===45||c===95)) return null;
        name+=String.fromCharCode(c);
      }
      return null;
    };
    for(let i=0;i<n;i++) {
      if(Date.now()>deadline) {result.metadata_limit_reached=true;break;}
      result.step='image-name';const assembly=assemblies.add(i*8).readPointer();
      if(assembly.isNull()) continue;
      const image=f.image(assembly);if(image.isNull()) continue;
      const raw=readName(f.imageName(image));
      result.assemblies_scanned++;
      if(raw===null) continue;
      const name=raw.endsWith('.dll')?raw:raw+'.dll';
      if(images.includes(name)) {result.known_images[name]=true;loaded[name]=image;}
    }
    const classes={};
    for(const [key,imageName,namespace,name] of typeSpecs) {
      if(Date.now()>deadline) {result.metadata_limit_reached=true;break;}
      const image=loaded[imageName] || (imageName==='mscorlib.dll'?loaded['System.Private.CoreLib.dll']:null);
      if(!image) continue;
      result.step='class-lookup';
      const klass=f.klass(image,Memory.allocUtf8String(namespace),Memory.allocUtf8String(name));
      result.known_types[key]=!klass.isNull();
      if(!klass.isNull()) classes[key]=klass;
    }
    for(const [key,name,arity] of methodSpecs) {
      if(Date.now()>deadline) {result.metadata_limit_reached=true;break;}
      if(!classes[key]) continue;
      result.step='method-lookup';
      result.known_methods[key+'.'+name+'/'+arity]=!f.method(classes[key],Memory.allocUtf8String(name),arity).isNull();
    }
    result.stage=result.metadata_limit_reached?'metadata-limited':'metadata-ready';result.step='done';
  } catch(_) {
    result.stage='native-call-failed';
  } finally {
    if(attachedHere && f!==null) {
      try {
        f.detach(attachedThread);
        result.thread_detach_confirmed=f.current().isNull();
        result.cleanup_failed=!result.thread_detach_confirmed;
      } catch(_) {result.cleanup_failed=true;}
      if(result.cleanup_failed) result.stage='metadata-cleanup-failed';
    }
  }
  return result;
}
'''


def build_native_function(types,methods,images):
    # Catalogs are build-time constants, never RPC inputs. JSON encoding prevents
    # names from becoming executable JS. The native call set stays fixed.
    type_keys=[t[0] for t in types]
    method_keys=[f'{t}.{name}/{arity}' for t,name,arity in methods]
    if len(set(type_keys))!=len(type_keys) or len(set(method_keys))!=len(method_keys):
        raise ValueError('Duplicate catalog entry')
    if not 0<len(types)<=64 or len(methods)>128 or len(images)>32:
        raise ValueError('Catalog exceeds fixed limits')
    if any(image not in images for _,image,_,_ in types) or any(t not in type_keys or type(n) is not int or not 0<=n<=16 for t,_,n in methods):
        raise ValueError('Invalid catalog reference')
    return _TEMPLATE.replace('__TYPES__',json.dumps(types)).replace('__METHODS__',json.dumps(methods)).replace('__IMAGES__',json.dumps(images)).replace('__EXPORTS__',json.dumps(EXPORTS))


NATIVE_FUNCTION=build_native_function(TYPES,METHODS,IMAGES)


def validate_metadata(value,*,types=TYPES,methods=METHODS,images=IMAGES):
    expected={'stage','step','native_calls_performed','api_exports','domain_available','current_thread_initially_attached',
              'thread_attach_performed','thread_detach_confirmed','cleanup_failed','assembly_count','assemblies_scanned',
              'metadata_limit_reached','known_images','known_types','known_methods'}
    if not isinstance(value,dict) or set(value)!=expected:raise ValueError('Unexpected native metadata fields')
    if value['stage'] not in STAGES or value['step'] not in STEPS:raise ValueError('Unexpected metadata stage')
    for key in ('native_calls_performed','domain_available','thread_attach_performed','thread_detach_confirmed','cleanup_failed','metadata_limit_reached'):
        if type(value[key]) is not bool:raise ValueError('Invalid metadata flag')
    if value['current_thread_initially_attached'] is not None and type(value['current_thread_initially_attached']) is not bool:
        raise ValueError('Invalid thread flag')
    for key in ('assembly_count','assemblies_scanned'):
        if type(value[key]) is not int or not 0<=value[key]<=2048:raise ValueError('Invalid assembly count')
    if value['assemblies_scanned']>value['assembly_count']:raise ValueError('Invalid scan count')
    for key,allowed in (('api_exports',EXPORTS),('known_images',images),('known_types',[t[0] for t in types]),('known_methods',[f'{t}.{name}/{arity}' for t,name,arity in methods])):
        data=value[key]
        if not isinstance(data,dict) or set(data)!=set(allowed) or any(type(v) is not bool for v in data.values()):
            raise ValueError('Unexpected metadata map')
    if value['stage']=='metadata-ready' and (not all(value['api_exports'].values()) or not value['domain_available'] or value['assembly_count']==0 or value['metadata_limit_reached'] or value['cleanup_failed'] or not value['native_calls_performed'] or not (value['current_thread_initially_attached'] is True or (value['thread_attach_performed'] and value['thread_detach_confirmed']))):
        raise ValueError('Inconsistent metadata success')
    return value
