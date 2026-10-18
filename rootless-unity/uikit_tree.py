"""Bounded, data-minimal UIKit structure snapshot. No text, coordinates or actions."""
from uikit_root import build_function,validate as validate_root

MAX_NODES=64
MAX_DEPTH=8
MAX_CHILDREN=32
MAX_COLLECTION=4096
MAX_CALLS=512
BUDGET_MS=150
KINDS=['UIWindow','DVButton','Button','TextField','UITextView','Label','Control','UIView-derived']
REASONS=['node-limit','depth-limit','children-limit','time-budget','managed-call-limit','repeated-reference']
ERRORS=['none','metadata-not-ready','signature-mismatch','unsupported-collection','collection-count-out-of-range',
        'unexpected-object','null-object','managed-exception','native-call-failed','handle-allocation-failed']
EXTRA_APIS=['il2cpp_class_is_valuetype','il2cpp_class_get_name','il2cpp_class_get_namespace','il2cpp_class_get_image',
            'il2cpp_class_from_type','il2cpp_method_get_param','il2cpp_gchandle_get_target']
HELPERS=r'''
 function emptyUIKitTree(){return {stage:'not-attempted',complete:false,error:'none',nodes:[],
  managed_calls:0,handles_acquired:0,handles_released:0,cleanup_failed:false,truncated_reasons:[],repeated_references:0};}
 function prepareUIKitTree(f,getClass,get,signature){
  const view=getClass('Core.dll','UIKit','UIView'),control=getClass('Core.dll','UIKit','Control');
  if(view.isNull()||control.isNull())throw new Error('metadata');
  const hidden=get(view,'get_EffectivelyHidden'),interaction=get(view,'get_UserInteractionEnabled');
  const children=get(view,'get_Subviews'),enabled=get(control,'get_Enabled');
  if(!signature(hidden,false,2)||!signature(interaction,false,2)||!signature(enabled,false,2)||children.isNull()||f.arity(children)!==0)throw new Error('signature');
  const bits=Memory.alloc(4);bits.writeU32(0);if((f.flags(children,bits)&16)!==0)throw new Error('signature');
  const ret=f.returnType(children);if(ret.isNull()||![18,21].includes(f.typeKind(ret)))throw new Error('signature');
  const kinds=[['UIWindow','Core.dll','UIKit','UIWindow'],['DVButton','DV.dll','DV','DVButton'],
   ['Button','Core.dll','UIKit','Button'],['TextField','Core.dll','UIKit','TextField'],
   ['UITextView','Core.dll','UIKit','UITextView'],['Label','Core.dll','UIKit','Label'],['Control','Core.dll','UIKit','Control']]
   .map(([label,im,ns,name])=>[label,getClass(im,ns,name)]).filter(([,k])=>!k.isNull());
  return {view,control,hidden,interaction,children,enabled,kinds};
 }
 function readUIKitTree(f,s,window){
  const out=emptyUIKitTree();out.stage='tree-error';
  const reasons=new Set(),held=[],seen=new Set(),queue=[],cache=new Map();const deadline=Date.now()+150;
  const fail=e=>{throw e;};
  const budget=()=>{if(Date.now()>deadline)fail('time-budget');if(out.managed_calls>=512)fail('managed-call-limit');};
  const own=obj=>{if(obj.isNull())fail('null-object');const h=f.keep(obj,1);if(h.isNull())fail('handle-allocation-failed');out.handles_acquired++;return h;};
  const release=h=>{try{f.release(h);out.handles_released++;}catch(_){out.cleanup_failed=true;}};
  const target=h=>{const obj=f.target(h);if(obj.isNull())fail('null-object');return obj;};
  const call=(method,receiver,params=ptr(0))=>{
   budget();const ex=Memory.alloc(8);ex.writePointer(ptr(0));out.managed_calls++;
   const v=f.invoke(method,target(receiver),params,ex);if(!ex.readPointer().isNull())fail('managed-exception');return v;
  };
  const boolean=boxed=>{if(boxed.isNull())fail('signature-mismatch');const p=f.unbox(boxed);if(p.isNull())fail('signature-mismatch');const v=p.readU8();if(v!==0&&v!==1)fail('signature-mismatch');return v===1;};
  const smallName=p=>{if(p.isNull())return null;let value='';for(let i=0;i<96;i++){const c=p.add(i).readU8();if(c===0)return value;if(c<32||c>126)return null;value+=String.fromCharCode(c);}return null;};
  const collectionMethods=klass=>{
   if(klass.isNull()||f.isValueType(klass))fail('unsupported-collection');
   const key=klass.toString();if(cache.has(key))return cache.get(key);
   const im=f.classImage(klass);if(im.isNull())fail('unsupported-collection');
   const name=smallName(f.className(klass)),ns=smallName(f.classNamespace(klass)),image=smallName(f.imageName(im));
   const allowed=(image==='Core.dll'&&ns==='Core.Collections'&&['ReadOnlyList`1','CoreList`1','IndexedList`1'].includes(name))||
    (image==='Core.dll'&&ns==='UIKit'&&name==='ModifiableCoreList`1')||
    (image==='mscorlib.dll'&&ns==='System.Collections.Generic'&&name==='List`1');
   if(!allowed)fail('unsupported-collection');
   const count=f.method(klass,Memory.allocUtf8String('get_Count'),0),item=f.method(klass,Memory.allocUtf8String('get_Item'),1);
   const checked=(method,arity,kind)=>{
    if(method.isNull()||f.arity(method)!==arity)return false;
    const flags=Memory.alloc(4);flags.writeU32(0);const t=f.returnType(method);
    return (f.flags(method,flags)&16)===0&&!t.isNull()&&f.typeKind(t)===kind;
   };
   if(!checked(count,0,8)||!checked(item,1,18))fail('signature-mismatch');
   const param=f.param(item,0);if(param.isNull()||f.typeKind(param)!==8)fail('signature-mismatch');
   const itemClass=f.classFromType(f.returnType(item));if(itemClass.isNull()||!f.assignable(s.view,itemClass))fail('signature-mismatch');
   const value={count,item};cache.set(key,value);return value;
  };
  const enqueue=(obj,parent,depth)=>{
   if(!f.assignable(s.view,f.objectClass(obj)))fail('unexpected-object');
   // Each queued view has a pinned opaque handle for the duration of this snapshot.
   const key=obj.toString();if(seen.has(key)){out.repeated_references++;reasons.add('repeated-reference');return;}
   if(held.length>=64){reasons.add('node-limit');return;}
   const h=own(obj);held.push(h);seen.add(key);queue.push({h,parent,depth});
  };
  try {
   enqueue(window,null,0);
   while(queue.length){
    budget();const entry=queue.shift(),klass=f.objectClass(target(entry.h));
    let kind='UIView-derived';for(const [label,k] of s.kinds)if(f.assignable(k,klass)){kind=label;break;}
    const node={id:out.nodes.length,parent:entry.parent,depth:entry.depth,kind,
     effectively_hidden:null,user_interaction_enabled:null,control_enabled:null,child_count:null};out.nodes.push(node);
    node.effectively_hidden=boolean(call(s.hidden,entry.h));
    node.user_interaction_enabled=boolean(call(s.interaction,entry.h));
    if(f.assignable(s.control,klass))node.control_enabled=boolean(call(s.enabled,entry.h));
    const list=call(s.children,entry.h);if(list.isNull()){node.child_count=0;continue;}
    let listHandle=ptr(0);
    try {
     listHandle=own(list);const methods=collectionMethods(f.objectClass(target(listHandle)));
     const boxed=call(methods.count,listHandle);if(boxed.isNull())fail('signature-mismatch');const number=f.unbox(boxed);if(number.isNull())fail('signature-mismatch');
     const count=number.readS32();if(count<0||count>4096)fail('collection-count-out-of-range');node.child_count=count;
     if(entry.depth>=8){if(count)reasons.add('depth-limit');continue;}
     if(count>32)reasons.add('children-limit');
     for(let i=0;i<Math.min(count,32);i++){
      budget();if(held.length>=64){reasons.add('node-limit');break;}
      const index=Memory.alloc(4);index.writeS32(i);const params=Memory.alloc(8);params.writePointer(index);
      const child=call(methods.item,listHandle,params);if(child.isNull())fail('null-object');enqueue(child,node.id,entry.depth+1);
     }
    }finally{if(!listHandle.isNull())release(listHandle);}
   }
   out.stage=reasons.size?'tree-limited':'tree-ready';out.complete=reasons.size===0;
  }catch(e){
   if(['time-budget','managed-call-limit'].includes(e)){reasons.add(e);out.stage='tree-limited';}
   else{out.stage='tree-error';out.error=__ERRORS__.includes(e)?e:'native-call-failed';}
  }finally{
   for(const h of held.reverse())release(h);
   out.truncated_reasons=Array.from(reasons);
   if(out.cleanup_failed||out.handles_released!==out.handles_acquired){out.cleanup_failed=true;out.complete=false;out.stage='cleanup-failed';}
  }
  return out;
 }
'''
# Keep the whitelist encoded as data, never splice names as executable instructions.
import json
HELPERS=HELPERS.replace('__ERRORS__',json.dumps(ERRORS))
BINDINGS="""Object.assign(f,{
 isValueType:bind('class_is_valuetype','bool',['pointer']),className:bind('class_get_name','pointer',['pointer']),classNamespace:bind('class_get_namespace','pointer',['pointer']),
 classImage:bind('class_get_image','pointer',['pointer']),classFromType:bind('class_from_type','pointer',['pointer']),
 param:bind('method_get_param','pointer',['pointer','uint32']),target:bind('gchandle_get_target','pointer',['pointer'])});"""
# DV.dll is only used for fixed type classification, never for content getters.
FUNCTION=build_function(extra_apis=EXTRA_APIS,helpers=HELPERS,init='r.tree=emptyUIKitTree();',
 bindings=BINDINGS,setup='setup.tree=prepareUIKitTree(f,getClass,get,signature);',
 body='r.tree=readUIKitTree(f,setup.tree,window);if(r.tree.cleanup_failed)r.cleanup_failed=true;')
FUNCTION=FUNCTION.replace("['Core.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll'].includes(name)",
 "['Core.dll','DV.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll'].includes(name)")


def validate_tree(v):
    fields={'stage','complete','error','nodes','managed_calls','handles_acquired','handles_released','cleanup_failed','truncated_reasons','repeated_references'}
    if not isinstance(v,dict) or set(v)!=fields:raise ValueError('Unexpected tree report fields')
    if v['stage'] not in ('not-attempted','tree-ready','tree-limited','tree-error','cleanup-failed') or v['error'] not in ERRORS:raise ValueError('Unexpected tree stage/error')
    if type(v['complete']) is not bool or type(v['cleanup_failed']) is not bool:raise ValueError('Invalid tree flag')
    for k,limit in (('managed_calls',MAX_CALLS),('handles_acquired',MAX_NODES*2),('handles_released',MAX_NODES*2),('repeated_references',MAX_CALLS)):
        if type(v[k]) is not int or not 0<=v[k]<=limit:raise ValueError('Invalid tree counter')
    if v['handles_released']>v['handles_acquired']:raise ValueError('Invalid release counter')
    reasons=v['truncated_reasons']
    if not isinstance(reasons,list) or len(reasons)!=len(set(reasons)) or any(x not in REASONS for x in reasons):raise ValueError('Unexpected truncation reason')
    if not isinstance(v['nodes'],list) or len(v['nodes'])>MAX_NODES:raise ValueError('Invalid tree size')
    fields={'id','parent','depth','kind','effectively_hidden','user_interaction_enabled','control_enabled','child_count'}
    for i,n in enumerate(v['nodes']):
        if not isinstance(n,dict) or set(n)!=fields or type(n['id']) is not int or n['id']!=i:raise ValueError('Invalid node fields/id')
        if type(n['depth']) is not int or not 0<=n['depth']<=MAX_DEPTH or n['kind'] not in KINDS:raise ValueError('Invalid node type/depth')
        if i==0:
            if n['parent'] is not None or n['depth']!=0:raise ValueError('Invalid root node')
        elif type(n['parent']) is not int or not 0<=n['parent']<i or n['depth']!=v['nodes'][n['parent']]['depth']+1:raise ValueError('Invalid parent edge')
        for k in ('effectively_hidden','user_interaction_enabled','control_enabled'):
            if n[k] is not None and type(n[k]) is not bool:raise ValueError('Invalid node flag')
        c=n['child_count']
        if c is not None and (type(c) is not int or not 0<=c<=MAX_COLLECTION):raise ValueError('Invalid child count')
    if v['stage']=='tree-ready':
        if not v['complete'] or v['error']!='none' or v['cleanup_failed'] or reasons or not v['nodes'] or v['handles_acquired']!=v['handles_released']:raise ValueError('Inconsistent complete tree')
        for n in v['nodes']:
            if any(n[k] is None for k in ('effectively_hidden','user_interaction_enabled','child_count')):raise ValueError('Incomplete ready node')
            if sum(x['parent']==n['id'] for x in v['nodes'])!=n['child_count']:raise ValueError('Incomplete child coverage')
    elif v['complete']:raise ValueError('Non-ready tree marked complete')
    if not v['cleanup_failed'] and v['handles_acquired']!=v['handles_released']:raise ValueError('Unreported handle leak')
    if (v['stage']=='cleanup-failed')!=v['cleanup_failed']:raise ValueError('Inconsistent cleanup stage')
    if v['stage']=='not-attempted' and (v['nodes'] or v['managed_calls'] or v['handles_acquired'] or reasons or v['error']!='none'):raise ValueError('Unexpected unattempted data')
    if v['stage']=='tree-limited' and (not reasons or v['error']!='none'):raise ValueError('Missing truncation explanation')
    if v['stage']=='tree-error' and v['error']=='none':raise ValueError('Missing failure explanation')
    return v


def validate(value):
    if not isinstance(value,dict) or 'tree' not in value:raise ValueError('Missing tree result')
    base={k:v for k,v in value.items() if k!='tree'};validate_root(base)
    tree=validate_tree(value['tree'])
    if tree['stage']!='not-attempted' and not (base['main_thread_confirmed'] and base['object_classes_validated']):raise ValueError('Tree without confirmed root/thread')
    if tree['cleanup_failed'] and not base['cleanup_failed']:raise ValueError('Tree cleanup failure not propagated')
    return value
