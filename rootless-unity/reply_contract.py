"""Fixed runtime definition checks for the missing reply adapter contract.

No object discovery, values, fields, frame hooks, app handlers or global type
inventory. A ready result proves signatures only, never history order or delivery.
"""
import json

VERSION = '0.3.28'
ROOTS = [
    ('controller', 'DV.Messages.dll', 'DV.Messages', 'MessagesViewController'),
    ('chat', 'DV.Messages.dll', 'DV.Messages', 'Chat'),
    ('history', 'DV.Messages.dll', 'DV.CMs', 'MessagesCM'),
    ('message', 'DV.Messages.dll', 'DV.Messages', 'Message'),
    ('text_message', 'DV.Messages.dll', 'DV.Messages', 'TextMessage'),
    ('manager', 'DV.Messages.dll', 'DV.Messages', 'MessagesManager'),
    ('user', 'DV.dll', 'DV.Models', 'User'),
]
# label, receiver, method, return kind, exact return class/root, parameter kinds.
SPECS = [
    ('controller_chat', 'controller', 'get_Chat', 18, 'chat', []),
    ('controller_user', 'controller', 'get_User', 18, 'user', []),
    ('chat_id', 'chat', 'get_Id', 10, None, []),
    ('chat_peer', 'chat', 'get_DialogOpponent', 18, 'user', []),
    ('chat_dialog', 'chat', 'get_Dialog', 2, None, []),
    ('chat_actual', 'chat', 'get_IsActual', 2, None, []),
    ('chat_draft', 'chat', 'get_IsDraftChat', 2, None, []),
    ('chat_has_history', 'chat', 'get_HasMessagesCM', 2, None, []),
    ('chat_history', 'chat', 'get_MessagesCM', 18, 'history', []),
    ('chat_manager', 'chat', 'get_MessagesManager', 18, 'manager', []),
    ('account_id', 'manager', 'get_CurrentUserId', 10, None, []),
    ('user_id', 'user', 'get_Id', 10, None, []),
    ('user_name', 'user', 'get_Name', 14, None, []),
    ('message_id', 'message', 'get_Id', 10, None, []),
    ('message_sender', 'message', 'get_SenderId', 10, None, []),
    ('message_chat', 'message', 'get_ChatId', 10, None, []),
    ('message_is_mine', 'message', 'get_IsMine', 2, None, []),
    ('message_text', 'text_message', 'get_Text', 14, None, []),
    ('history_count', 'list', 'get_Count', 8, None, []),
    ('history_item', 'list', 'get_Item', 18, 'message', [8]),
    ('history_loading', 'content', 'get_LoadInProgress', 2, None, []),
    ('history_loaded_field', 'content', 'get_AllIsLoaded', 21, 'loaded', []),
    ('history_loaded_value', 'loaded', 'get_Value', 2, None, []),
]
APIS = {
    'domain_get': ('pointer', []), 'thread_current': ('pointer', []),
    'thread_attach': ('pointer', ['pointer']), 'thread_detach': ('void', ['pointer']),
    'domain_get_assemblies': ('pointer', ['pointer', 'pointer']),
    'assembly_get_image': ('pointer', ['pointer']), 'image_get_name': ('pointer', ['pointer']),
    'class_from_name': ('pointer', ['pointer', 'pointer', 'pointer']),
    'class_get_parent': ('pointer', ['pointer']),
    'class_get_image': ('pointer', ['pointer']), 'class_get_name': ('pointer', ['pointer']),
    'class_get_namespace': ('pointer', ['pointer']),
    'class_get_method_from_name': ('pointer', ['pointer', 'pointer', 'int']),
    'method_get_class': ('pointer', ['pointer']),
    'method_get_param_count': ('uint32', ['pointer']),
    'method_get_flags': ('uint32', ['pointer', 'pointer']),
    'method_get_return_type': ('pointer', ['pointer']),
    'method_get_param': ('pointer', ['pointer', 'uint32']),
    'type_get_type': ('int', ['pointer']), 'type_is_byref': ('bool', ['pointer']),
    'class_from_type': ('pointer', ['pointer']),
    'class_is_assignable_from': ('bool', ['pointer', 'pointer']),
}
IMAGES = ('Core.dll', 'DV.dll', 'DV.Messages.dll', 'mscorlib.dll')
REASONS = {'none', 'unsupported-pointer-size', 'api-missing', 'domain-unavailable',
           'thread-unavailable', 'invalid-metadata', 'limits', 'native-call-failed', 'cleanup-failed'}
CHECK_STATUSES = {'not-checked', 'ready', 'class-missing', 'method-missing',
                  'signature-mismatch', 'owner-mismatch', 'return-type-mismatch', 'parameter-mismatch'}
MAX_CALLS = 12000
MAX_MS = 5000

_TEMPLATE = r'''
function nativeMetadata(){
 const roots=__ROOTS__,specs=__SPECS__,api=__APIS__;
 const r={schema_version:1,tool_version:__VERSION__,mode:'targeted-reply-contract-definitions',
  stage:'contract-stopped',reason:'none',api_available:false,current_thread_initially_attached:null,
  thread_attach_performed:false,thread_detach_confirmed:false,cleanup_failed:false,
  native_calls:0,assemblies_scanned:0,limited:false,all_required_signatures_verified:false,
  method_values_read:false,history_read:false,ui_actions_attempted:false,messages_sent:0,
  chronological_order_verified:false,live_replies_available:false,
  roots:roots.map(([key,image,namespace,type])=>({key,image,namespace,type,found:false})),
  checks:specs.map(([label])=>({label,status:'not-checked',owner:null,return_type:null,
    arity:null,static:null,abstract:null,parameters:[]}))};
 if(Process.pointerSize!==8){r.reason='unsupported-pointer-size';return r;}
 let f={},raw={},thread=ptr(0),attached=false;const deadline=Date.now()+5000;
 const fail=reason=>{if(reason==='limits')r.limited=true;throw reason;};
 const bounded=()=>{if(Date.now()>deadline||r.native_calls>=12000){r.limited=true;fail('limits');}};
 const name=p=>{
  if(p.isNull())fail('invalid-metadata');let value='';
  for(let i=0;i<192;i++){bounded();const c=p.add(i).readU8();if(c===0)return value;
   if(c<32||c>126)fail('invalid-metadata');value+=String.fromCharCode(c);}
  fail('invalid-metadata');
 };
 const identity=k=>{
  if(k.isNull())return null;const im=f.class_get_image(k);if(im.isNull())fail('invalid-metadata');
  const value={image:name(f.image_get_name(im)),namespace:name(f.class_get_namespace(k)),type:name(f.class_get_name(k))};
  if(!__IMAGES__.includes(value.image))fail('invalid-metadata');return value;
 };
 const exact=(k,im,ns,type)=>{const id=identity(k);return id!==null&&id.image===im&&id.namespace===ns&&id.type===type;};
 const chain=k=>{
  const out=[],seen=new Set();
  for(let i=0;i<10&&!k.isNull();i++){
   bounded();const key=k.toString();if(seen.has(key))fail('invalid-metadata');seen.add(key);out.push(k);k=f.class_get_parent(k);
  }
  if(!k.isNull())fail('limits');return out;
 };
 const describe=t=>{
  if(t.isNull())fail('invalid-metadata');const kind=f.type_get_type(t),byref=!!f.type_is_byref(t);
  if(kind<0||kind>255)fail('invalid-metadata');return {kind,byref,target:identity(f.class_from_type(t))};
 };
 try{
  for(const [n,[ret,args]] of Object.entries(api)){
   const p=Module.findGlobalExportByName('il2cpp_'+n);if(p===null)fail('api-missing');
   raw[n]=new NativeFunction(p,ret,args,{exceptions:'steal'});
   f[n]=(...args)=>{bounded();r.native_calls++;return raw[n](...args);};
  }
  r.api_available=true;const domain=f.domain_get();if(domain.isNull())fail('domain-unavailable');
  r.current_thread_initially_attached=!f.thread_current().isNull();
  if(!r.current_thread_initially_attached){
   thread=f.thread_attach(domain);if(thread.isNull())fail('thread-unavailable');attached=true;r.thread_attach_performed=true;
  }
  const size=Memory.alloc(8);size.writeU64(0);const all=f.domain_get_assemblies(domain,size),count=size.readU64();
  if(all.isNull()||count.compare(1)<0||count.compare(2048)>0)fail('invalid-metadata');
  const images={},classes={};
  for(let i=0;i<count.toNumber();i++){
   bounded();const assembly=all.add(i*8).readPointer();if(assembly.isNull())fail('invalid-metadata');
   const image=f.assembly_get_image(assembly);if(image.isNull())fail('invalid-metadata');
   const label=name(f.image_get_name(image));r.assemblies_scanned++;
   if(__IMAGES__.includes(label)){if(images[label])fail('invalid-metadata');images[label]=image;}
  }
  for(let i=0;i<roots.length;i++){
   const [key,image,ns,type]=roots[i];classes[key]=ptr(0);
   if(images[image]){
    const k=f.class_from_name(images[image],Memory.allocUtf8String(ns),Memory.allocUtf8String(type));
    if(!k.isNull()){if(!exact(k,image,ns,type))fail('invalid-metadata');classes[key]=k;r.roots[i].found=true;}
   }
  }
  classes.list=ptr(0);classes.content=ptr(0);classes.loaded=ptr(0);
  for(const k of chain(classes.history)){
   if(exact(k,'Core.dll','DataKit','BaseDataList`1')){
    if(!classes.list.isNull())fail('invalid-metadata');classes.list=k;
   }
   if(exact(k,'DV.dll','DV.CMs','ContentDataList`1')){
    if(!classes.content.isNull())fail('invalid-metadata');classes.content=k;
   }
  }
  if(!classes.text_message.isNull()&&!classes.message.isNull()&&
     !f.class_is_assignable_from(classes.message,classes.text_message))fail('invalid-metadata');
  for(let i=0;i<specs.length;i++){
   const [label,key,method,kind,target,params]=specs[i],out=r.checks[i],klass=classes[key];
   if(!klass||klass.isNull()){out.status='class-missing';continue;}
   const m=f.class_get_method_from_name(klass,Memory.allocUtf8String(method),params.length);
   if(m.isNull()){out.status='method-missing';continue;}
   out.status='signature-mismatch';const owner=f.method_get_class(m);out.owner=identity(owner);
   const arity=f.method_get_param_count(m);if(arity>255)fail('invalid-metadata');out.arity=arity;
   const bits=Memory.alloc(4);bits.writeU32(0);
   const flags=f.method_get_flags(m,bits);out.static=!!(flags&16);out.abstract=!!(flags&1024);
   const returnType=f.method_get_return_type(m);out.return_type=describe(returnType);
   if(arity!==params.length||out.static||out.abstract){out.status='signature-mismatch';continue;}
   if(!chain(klass).some(k=>k.equals(owner))){out.status='owner-mismatch';continue;}
   if(out.return_type.kind!==kind||out.return_type.byref){out.status='return-type-mismatch';continue;}
   const returnClass=f.class_from_type(returnType);
   if(label==='history_loaded_field'){
    if(!exact(returnClass,'Core.dll','DataKit','DataField`1')){out.status='return-type-mismatch';continue;}
    classes.loaded=returnClass;
   }else if(target&&(!classes[target]||classes[target].isNull()||!returnClass.equals(classes[target]))){
    out.status='return-type-mismatch';continue;
   }
   let valid=true;
   for(let j=0;j<params.length;j++){
    const value=describe(f.method_get_param(m,j));out.parameters.push(value);
    if(value.kind!==params[j]||value.byref)valid=false;
   }
   out.status=valid?'ready':'parameter-mismatch';
  }
  r.all_required_signatures_verified=r.roots.every(x=>x.found)&&r.checks.every(x=>x.status==='ready');
  r.stage=r.all_required_signatures_verified?'contract-ready':'contract-incomplete';
 }catch(e){r.reason=__REASONS__.includes(e)?e:'native-call-failed';r.stage='contract-stopped';r.all_required_signatures_verified=false;}
 finally{
  if(attached){
   try{raw.thread_detach(thread);r.thread_detach_confirmed=raw.thread_current().isNull();if(!r.thread_detach_confirmed)r.cleanup_failed=true;}
   catch(_){r.cleanup_failed=true;}
   if(r.cleanup_failed){r.stage='contract-stopped';r.reason='cleanup-failed';r.all_required_signatures_verified=false;}
  }
 }
 return r;
}
'''
FUNCTION = (_TEMPLATE.replace('__ROOTS__', json.dumps(ROOTS)).replace('__SPECS__', json.dumps(SPECS))
            .replace('__APIS__', json.dumps(APIS)).replace('__VERSION__', json.dumps(VERSION))
            .replace('__IMAGES__', json.dumps(IMAGES)).replace('__REASONS__', json.dumps(sorted(REASONS))))


def validate(value):
    fields = {'schema_version', 'tool_version', 'mode', 'stage', 'reason', 'api_available',
              'current_thread_initially_attached', 'thread_attach_performed', 'thread_detach_confirmed',
              'cleanup_failed', 'native_calls', 'assemblies_scanned', 'limited',
              'all_required_signatures_verified', 'method_values_read', 'history_read',
              'ui_actions_attempted', 'messages_sent', 'chronological_order_verified',
              'live_replies_available', 'roots', 'checks'}
    def exact(x, keys):
        if not isinstance(x, dict) or set(x) != set(keys):
            raise ValueError('Unexpected contract fields')
    def integer(x, lo, hi):
        if type(x) is not int or not lo <= x <= hi:
            raise ValueError('Invalid contract counter')
    def identity(x):
        if x is None:
            return
        exact(x, ('image', 'namespace', 'type'))
        if x['image'] not in IMAGES:
            raise ValueError('Unexpected contract image')
        for k, v in x.items():
            if not isinstance(v, str) or len(v) > 191 or any(not 32 <= ord(c) <= 126 for c in v):
                raise ValueError('Invalid definition identity')
            if k != 'namespace' and not v:
                raise ValueError('Empty definition identity')
    def descriptor(x):
        exact(x, ('kind', 'byref', 'target'))
        integer(x['kind'], 0, 255)
        if type(x['byref']) is not bool:
            raise ValueError('Invalid byref flag')
        identity(x['target'])
    exact(value, fields)
    integer(value['schema_version'], 1, 1)
    if value['tool_version'] != VERSION or value['mode'] != 'targeted-reply-contract-definitions':
        raise ValueError('Unexpected contract version/mode')
    if value['stage'] not in ('contract-ready', 'contract-incomplete', 'contract-stopped') or value['reason'] not in REASONS:
        raise ValueError('Unexpected contract result')
    flags = fields - {'schema_version', 'tool_version', 'mode', 'stage', 'reason', 'native_calls',
                      'assemblies_scanned', 'messages_sent', 'roots', 'checks', 'current_thread_initially_attached'}
    if any(type(value[k]) is not bool for k in flags):
        raise ValueError('Invalid contract flag')
    if value['current_thread_initially_attached'] is not None and type(value['current_thread_initially_attached']) is not bool:
        raise ValueError('Invalid initial thread flag')
    integer(value['native_calls'], 0, MAX_CALLS)
    integer(value['assemblies_scanned'], 0, 2048)
    integer(value['messages_sent'], 0, 0)
    if any(value[k] for k in ('method_values_read', 'history_read', 'ui_actions_attempted',
                             'chronological_order_verified', 'live_replies_available')):
        raise ValueError('Definitions cannot imply live data/actions')
    if value['thread_attach_performed'] and value['current_thread_initially_attached'] is not False:
        raise ValueError('Unexpected thread ownership')
    if value['thread_detach_confirmed'] and not value['thread_attach_performed']:
        raise ValueError('Unexpected thread detach')
    if value['thread_attach_performed'] and not value['thread_detach_confirmed'] and not value['cleanup_failed']:
        raise ValueError('Unreported thread leak')
    if not isinstance(value['roots'], list) or len(value['roots']) != len(ROOTS):
        raise ValueError('Invalid contract roots')
    for root, spec in zip(value['roots'], ROOTS):
        exact(root, ('key', 'image', 'namespace', 'type', 'found'))
        if tuple(root[k] for k in ('key', 'image', 'namespace', 'type')) != spec or type(root['found']) is not bool:
            raise ValueError('Unexpected contract root')
    if not isinstance(value['checks'], list) or len(value['checks']) != len(SPECS):
        raise ValueError('Invalid contract check count')
    for check, spec in zip(value['checks'], SPECS):
        exact(check, ('label', 'status', 'owner', 'return_type', 'arity', 'static', 'abstract', 'parameters'))
        if check['label'] != spec[0] or check['status'] not in CHECK_STATUSES:
            raise ValueError('Unexpected contract check')
        identity(check['owner'])
        if check['return_type'] is not None:
            descriptor(check['return_type'])
        if check['arity'] is not None:
            integer(check['arity'], 0, 255)
        for k in ('static', 'abstract'):
            if check[k] is not None and type(check[k]) is not bool:
                raise ValueError('Invalid method flag')
        if not isinstance(check['parameters'], list) or len(check['parameters']) > len(spec[5]):
            raise ValueError('Invalid method parameters')
        for param in check['parameters']:
            descriptor(param)
        if check['status'] in ('not-checked', 'class-missing', 'method-missing'):
            if any(check[k] is not None for k in ('owner', 'return_type', 'arity', 'static', 'abstract')) or check['parameters']:
                raise ValueError('Unexpected method data')
        if check['status'] == 'ready':
            ret = check['return_type']
            if (check['owner'] is None or ret is None or ret['kind'] != spec[3] or ret['byref']
                    or check['arity'] != len(spec[5]) or check['static'] is not False or check['abstract'] is not False
                    or len(check['parameters']) != len(spec[5])
                    or any(x['kind'] != kind or x['byref'] for x, kind in zip(check['parameters'], spec[5]))):
                raise ValueError('Unverified ready signature')
            if spec[4]:
                expected = next(({'image': r[1], 'namespace': r[2], 'type': r[3]} for r in ROOTS if r[0] == spec[4]),
                                {'image': 'Core.dll', 'namespace': 'DataKit', 'type': 'DataField`1'})
                if ret['target'] != expected:
                    raise ValueError('Unverified return class')
    complete = all(r['found'] for r in value['roots']) and all(c['status'] == 'ready' for c in value['checks'])
    if value['stage'] != 'contract-stopped':
        if (value['reason'] != 'none' or value['limited'] or value['cleanup_failed'] or not value['api_available']
                or value['current_thread_initially_attached'] is None
                or complete != value['all_required_signatures_verified']
                or (value['stage'] == 'contract-ready') != complete
                or any(c['status'] == 'not-checked' for c in value['checks'])):
            raise ValueError('Inconsistent contract completion')
    elif value['reason'] == 'none' or value['all_required_signatures_verified']:
        raise ValueError('Unexplained contract failure')
    if value['cleanup_failed'] and value['reason'] != 'cleanup-failed':
        raise ValueError('Cleanup failure not propagated')
    return value
