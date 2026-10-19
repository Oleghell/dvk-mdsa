"""Fixed, metadata-only IL2CPP graph. No objects, invocation, hooks or UI actions."""
import json

VERSION='0.3.15'
ROOTS=[('DV.Profile.dll','DV.Profiles','ProfilesQueueViewController'),
       ('DV.Profile.dll','DV.Profiles','ProfileOverlayView'),
       ('DV.Messages.dll','DV.Messages','MessagesViewController'),
       ('DV.Messages.dll','DV.Messages','Chat'),
       ('DV.Messages.dll','DV.CMs','MessagesCM'),
       ('DV.Messages.dll','DV.Messages','MessagesManager'),
       ('DV.Messages.dll','DV.Routers.Messages','MessagesRouter')]
IMAGES=['Core.dll','DV.dll','DV.Profile.dll','DV.Messages.dll','mscorlib.dll']
APIS={'domain_get':('pointer',[]),'thread_current':('pointer',[]),'thread_attach':('pointer',['pointer']),
      'thread_detach':('void',['pointer']),'domain_get_assemblies':('pointer',['pointer','pointer']),
      'assembly_get_image':('pointer',['pointer']),'image_get_name':('pointer',['pointer']),
      'class_from_name':('pointer',['pointer','pointer','pointer']),'class_get_name':('pointer',['pointer']),
      'class_get_namespace':('pointer',['pointer']),'class_get_image':('pointer',['pointer']),
      'class_get_parent':('pointer',['pointer']),'class_get_methods':('pointer',['pointer','pointer']),
      'class_get_fields':('pointer',['pointer','pointer']),'field_get_name':('pointer',['pointer']),
      'field_get_type':('pointer',['pointer']),'field_get_flags':('uint32',['pointer']),
      'method_get_name':('pointer',['pointer']),'method_get_class':('pointer',['pointer']),
      'method_get_param_count':('uint32',['pointer']),'method_get_param':('pointer',['pointer','uint32']),
      'method_get_flags':('uint32',['pointer','pointer']),'method_get_return_type':('pointer',['pointer']),
      'type_get_type':('int',['pointer']),'type_is_byref':('bool',['pointer']),
      'class_from_type':('pointer',['pointer'])}
STEPS={'resolve-api','domain','thread','assemblies','roots','types','done'}
REASONS={'none','api-missing','domain-unavailable','thread-unavailable','invalid-metadata','limits','native-call-failed','cleanup-failed'}
_TEMPLATE=r'''
function nativeMetadata(){
 const roots=__ROOTS__,images=__IMAGES__,api=__APIS__;
 const r={stage:'chat-runtime-stopped',step:'resolve-api',reason:'none',api_available:false,
  thread_attach_performed:false,thread_detach_confirmed:false,current_thread_initially_attached:null,
  cleanup_failed:false,native_calls:0,assemblies_scanned:0,limited:false,
  ui_actions_attempted:false,method_values_read:false,chat_opened:false,history_read:false,messages_sent:0,
  roots:roots.map(([image,namespace,type])=>({image,namespace,type,found:false,class_index:null})),types:[]};
 if(Process.pointerSize!==8){r.reason='invalid-metadata';return r;}
 let f={},raw={},thread=ptr(0),attached=false;const deadline=Date.now()+5000;
 const fail=reason=>{throw reason;};
 const bounded=()=>{if(Date.now()>deadline||r.native_calls>=50000){r.limited=true;fail('limits');}};
 const text=p=>{if(p.isNull())fail('invalid-metadata');let s='';for(let j=0;j<512;j++){bounded();const c=p.add(j).readU8();if(c===0)return s;if(c<32||c>126)fail('invalid-metadata');s+=String.fromCharCode(c);}fail('invalid-metadata');};
 try{
  for(const [n,[ret,args]] of Object.entries(api)){
   const p=Module.findGlobalExportByName('il2cpp_'+n);if(p===null)fail('api-missing');
   raw[n]=new NativeFunction(p,ret,args,{exceptions:'steal'});
   f[n]=(...args)=>{bounded();r.native_calls++;return raw[n](...args);};
  }
  r.api_available=true;r.step='domain';const domain=f.domain_get();if(domain.isNull())fail('domain-unavailable');
  r.step='thread';r.current_thread_initially_attached=!f.thread_current().isNull();
  if(!r.current_thread_initially_attached){thread=f.thread_attach(domain);if(thread.isNull())fail('thread-unavailable');attached=true;r.thread_attach_performed=true;}
  r.step='assemblies';const size=Memory.alloc(8);size.writeU64(0);const all=f.domain_get_assemblies(domain,size),n=size.readU64();
  if(n.compare(1)<0||n.compare(2048)>0||all.isNull())fail('invalid-metadata');const loaded={};
  for(let i=0;i<n.toNumber();i++){
   bounded();const a=all.add(i*8).readPointer();if(a.isNull())fail('invalid-metadata');
   const im=f.assembly_get_image(a);if(im.isNull())fail('invalid-metadata');const name=text(f.image_get_name(im));r.assemblies_scanned++;
   if(images.includes(name)){if(loaded[name])fail('invalid-metadata');loaded[name]=im;}
  }
  const identity=k=>{if(k.isNull())return null;const im=f.class_get_image(k);if(im.isNull())fail('invalid-metadata');
   return {image:text(f.image_get_name(im)),namespace:text(f.class_get_namespace(k)),type:text(f.class_get_name(k))};};
  const describe=t=>{if(t.isNull())fail('invalid-metadata');return {kind:f.type_get_type(t),byref:!!f.type_is_byref(t),target:identity(f.class_from_type(t))};};
  const queue=[],seen=new Map();
  const enqueue=(k,depth)=>{
   if(k.isNull())return null;const key=k.toString();if(seen.has(key))return seen.get(key);
   const id=identity(k);if(!images.includes(id.image))return null;
   if(depth>8||queue.length>=64){r.limited=true;return null;}
   const index=queue.length;seen.set(key,index);queue.push({k,depth});return index;
  };
  r.step='roots';for(const root of r.roots){const im=loaded[root.image];if(!im)continue;
   const k=f.class_from_name(im,Memory.allocUtf8String(root.namespace),Memory.allocUtf8String(root.type));
   if(!k.isNull()){const id=identity(k);if(id.image!==root.image||id.namespace!==root.namespace||id.type!==root.type)fail('invalid-metadata');root.found=true;root.class_index=enqueue(k,0);}
  }
  r.step='types';let totalMethods=0,totalFields=0,totalParams=0;
  for(let index=0;index<queue.length;index++){
   bounded();const {k,depth}=queue[index],parent=f.class_get_parent(k);
   if(parent.equals(k))fail('invalid-metadata');
   const node={index,identity:identity(k),depth,parent:identity(parent),parent_index:enqueue(parent,depth+1),methods:[],fields:[],truncated:false};r.types.push(node);
   const cursor=Memory.alloc(8);cursor.writePointer(ptr(0));
   for(let j=0;j<=256;j++){
    const m=f.class_get_methods(k,cursor);if(m.isNull())break;
    if(j===256||totalMethods>=8192){node.truncated=true;r.limited=true;break;}
    const name=text(f.method_get_name(m)),arity=f.method_get_param_count(m),bits=Memory.alloc(4);bits.writeU32(0);
    if(arity>255)fail('invalid-metadata');const flags=f.method_get_flags(m,bits),ret=f.method_get_return_type(m),owner=f.method_get_class(m);
    const entry={method:name,arity,static:!!(flags&16),abstract:!!(flags&1024),virtual:!!(flags&64),owner:identity(owner),owner_matches:owner.equals(k),return_type:describe(ret),parameters:[],parameters_truncated:false};
    for(let p=0;p<arity;p++){if(p>=16||totalParams>=16384){entry.parameters_truncated=true;node.truncated=true;r.limited=true;break;}entry.parameters.push(describe(f.method_get_param(m,p)));totalParams++;}
    node.methods.push(entry);totalMethods++;
    if(arity===0&&!entry.static&&/^get_(Chat|MessagesCM|MessagesManager|Strategy)$/.test(name))enqueue(f.class_from_type(ret),depth+1);
   }
   cursor.writePointer(ptr(0));
   for(let j=0;j<=96;j++){
    const field=f.class_get_fields(k,cursor);if(field.isNull())break;
    if(j===96||totalFields>=4096){node.truncated=true;r.limited=true;break;}
    node.fields.push({field:text(f.field_get_name(field)),static:!!(f.field_get_flags(field)&16),declared_type:describe(f.field_get_type(field))});totalFields++;
   }
  }
  for(const node of r.types){const visited=new Set();let i=node.index;while(i!==null){if(visited.has(i))fail('invalid-metadata');visited.add(i);i=r.types[i].parent_index;}}
  r.stage=r.limited?'chat-runtime-limited':'chat-runtime-ready';r.reason=r.limited?'limits':'none';r.step='done';
 }catch(e){r.reason=__REASONS__.includes(e)?e:'native-call-failed';r.stage=r.limited?'chat-runtime-limited':'chat-runtime-stopped';}
 finally{if(attached){try{raw.thread_detach(thread);r.thread_detach_confirmed=raw.thread_current().isNull();if(!r.thread_detach_confirmed)r.cleanup_failed=true;}catch(_){r.cleanup_failed=true;}if(r.cleanup_failed){r.stage='chat-runtime-stopped';r.reason='cleanup-failed';}}}
 return r;
}
'''
FUNCTION=(_TEMPLATE.replace('__ROOTS__',json.dumps(ROOTS)).replace('__IMAGES__',json.dumps(IMAGES))
          .replace('__APIS__',json.dumps(APIS)).replace('__REASONS__',json.dumps(sorted(REASONS))))


def validate(value):
    fields={'stage','step','reason','api_available','thread_attach_performed','thread_detach_confirmed','current_thread_initially_attached','cleanup_failed','native_calls','assemblies_scanned','limited','ui_actions_attempted','method_values_read','chat_opened','history_read','messages_sent','roots','types'}
    def exact(x,keys):
        if not isinstance(x,dict) or set(x)!=set(keys):raise ValueError('Unexpected metadata fields')
    def integer(x,lo,hi):
        if type(x) is not int or not lo<=x<=hi:raise ValueError('Invalid metadata integer')
    def boolean(x):
        if type(x) is not bool:raise ValueError('Invalid metadata flag')
    def label(x):
        if not isinstance(x,str) or len(x)>511 or any(not 32<=ord(ch)<=126 for ch in x):raise ValueError('Invalid metadata label')
    def identity(x,nullable=False):
        if x is None and nullable:return
        exact(x,('image','namespace','type'))
        for v in x.values():label(v)
        if not x['image'] or not x['type']:raise ValueError('Empty metadata identity')
    def descriptor(x):
        exact(x,('kind','byref','target'));integer(x['kind'],0,255);boolean(x['byref']);identity(x['target'],True)
    exact(value,fields)
    if value['stage'] not in {'chat-runtime-ready','chat-runtime-limited','chat-runtime-stopped'} or value['step'] not in STEPS or value['reason'] not in REASONS:raise ValueError('Invalid metadata stage')
    for k in ('api_available','thread_attach_performed','thread_detach_confirmed','cleanup_failed','limited','ui_actions_attempted','method_values_read','chat_opened','history_read'):boolean(value[k])
    if value['current_thread_initially_attached'] is not None:boolean(value['current_thread_initially_attached'])
    if any(value[k] for k in ('ui_actions_attempted','method_values_read','chat_opened','history_read')) or type(value['messages_sent']) is not int or value['messages_sent']!=0:raise ValueError('Forbidden app access')
    integer(value['native_calls'],0,50000);integer(value['assemblies_scanned'],0,2048)
    if value['thread_attach_performed'] and value['current_thread_initially_attached'] is not False:raise ValueError('Invalid thread ownership')
    if value['thread_detach_confirmed'] and not value['thread_attach_performed']:raise ValueError('Invalid thread detach')
    if value['thread_attach_performed'] and not value['thread_detach_confirmed'] and not value['cleanup_failed']:raise ValueError('Unreported thread leak')
    roots=value['roots'];nodes=value['types']
    if not isinstance(roots,list) or len(roots)!=len(ROOTS) or not isinstance(nodes,list) or len(nodes)>64:raise ValueError('Invalid graph size')
    for root,expected in zip(roots,ROOTS):
        exact(root,('image','namespace','type','found','class_index'));boolean(root['found'])
        if tuple(root[k] for k in ('image','namespace','type'))!=expected:raise ValueError('Unexpected root')
        if root['class_index'] is not None:integer(root['class_index'],0,63)
        if not root['found'] and root['class_index'] is not None:raise ValueError('Missing root indexed')
    methods=field_count=parameters=0
    for i,node in enumerate(nodes):
        exact(node,('index','identity','depth','parent','parent_index','methods','fields','truncated'));integer(node['index'],i,i);integer(node['depth'],0,8);identity(node['identity']);identity(node['parent'],True);boolean(node['truncated'])
        if node['identity']['image'] not in IMAGES:raise ValueError('Unexpected graph assembly')
        if node['parent_index'] is not None:integer(node['parent_index'],0,63)
        if not isinstance(node['methods'],list) or len(node['methods'])>256 or not isinstance(node['fields'],list) or len(node['fields'])>96:raise ValueError('Invalid member budget')
        methods+=len(node['methods']);field_count+=len(node['fields'])
        for m in node['methods']:
            exact(m,('method','arity','static','abstract','virtual','owner','owner_matches','return_type','parameters','parameters_truncated'));label(m['method']);integer(m['arity'],0,255);identity(m['owner'],True);descriptor(m['return_type'])
            for k in ('static','abstract','virtual','owner_matches','parameters_truncated'):boolean(m[k])
            if not isinstance(m['parameters'],list) or len(m['parameters'])>16 or len(m['parameters'])>m['arity']:raise ValueError('Invalid method parameters')
            if m['parameters_truncated']!=(len(m['parameters'])<m['arity']):raise ValueError('Inconsistent parameters')
            for p in m['parameters']:descriptor(p)
            parameters+=len(m['parameters'])
            if m['owner_matches'] and m['owner']!=node['identity']:raise ValueError('Invalid declaring class')
        for f in node['fields']:
            exact(f,('field','static','declared_type'));label(f['field']);boolean(f['static']);descriptor(f['declared_type'])
    if methods>8192 or field_count>4096 or parameters>16384:raise ValueError('Graph exceeds total budget')
    if value['stage']=='chat-runtime-ready':
        if value['reason']!='none' or value['step']!='done' or value['limited'] or value['cleanup_failed'] or not value['api_available'] or not value['assemblies_scanned'] or not value['native_calls'] or not (value['current_thread_initially_attached'] or value['thread_detach_confirmed']):raise ValueError('Inconsistent success')
        if any(n['truncated'] or any(m['parameters_truncated'] for m in n['methods']) for n in nodes):raise ValueError('Hidden truncation')
        for root in roots:
            idx=root['class_index']
            if root['found'] and (idx is None or idx>=len(nodes) or nodes[idx]['identity']!={k:root[k] for k in ('image','namespace','type')}):raise ValueError('Invalid root index')
        for node in nodes:
            idx=node['parent_index']
            if idx is not None and (idx>=len(nodes) or nodes[idx]['identity']!=node['parent']):raise ValueError('Invalid parent index')
            seen=set();i=node['index']
            while i is not None:
                if i in seen:raise ValueError('Parent cycle')
                seen.add(i);i=nodes[i]['parent_index']
    if value['stage']=='chat-runtime-limited' and not value['limited']:raise ValueError('Unmarked limit')
    if value['cleanup_failed'] and (value['stage']!='chat-runtime-stopped' or value['reason']!='cleanup-failed'):raise ValueError('Invalid cleanup failure')
    return value
