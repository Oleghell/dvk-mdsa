"""Bounded inventory for a future verified reply adapter. Definitions ONLY."""
import copy,json
import chat_runtime_metadata as base
VERSION='0.3.26'
ROOTS=base.ROOTS+[
 ('DV.Messages.dll','DV.Messages','Message'),
 ('DV.Messages.dll','DV.Messages','ChatsViewController'),
 ('Core.dll','UIKit','GenericString'),
 ('DV.dll','DV.Models','User')]
APIS={**base.APIS,'image_get_class_count':('uint64',['pointer']),'image_get_class':('pointer',['pointer','uint64']),'class_is_assignable_from':('bool',['pointer','pointer'])}
DISCOVER=r'''
  // Definitions of private-message subclasses only, not users' message values.
  const mi=loaded['DV.Messages.dll'];
  if(mi){
   const message=f.class_from_name(mi,Memory.allocUtf8String('DV.Messages'),Memory.allocUtf8String('Message'));
   const rawCount=f.image_get_class_count(mi);if(rawCount.compare(16384)>0)fail('limits');const count=rawCount.toNumber();
   if(!message.isNull())for(let i=0;i<count;i++){
    bounded();const k=f.image_get_class(mi,i);if(k.isNull())fail('invalid-metadata');
    const id=identity(k);
    if(id.namespace==='DV.Messages'&&f.class_is_assignable_from(message,k))enqueue(k,0);
   }
  }
'''
IDENTITY_CACHE=r'''
  // Immutable definition pointers only, scoped to this single inventory call.
  // Never cache application objects or their values.
  const identityCache=new Map(),descriptorCache=new Map();
  const identity=k=>{
   bounded();if(k.isNull())return null;const key=k.toString();
   if(identityCache.has(key))return identityCache.get(key);
   if(identityCache.size>=16384)fail('limits');
   const im=f.class_get_image(k);if(im.isNull())fail('invalid-metadata');
   const result={image:text(f.image_get_name(im)),namespace:text(f.class_get_namespace(k)),type:text(f.class_get_name(k))};
   identityCache.set(key,result);return result;
  };
  const describe=t=>{
   bounded();if(t.isNull())fail('invalid-metadata');const key=t.toString();
   if(descriptorCache.has(key))return descriptorCache.get(key);
   if(descriptorCache.size>=8192)fail('limits');
   const result={kind:f.type_get_type(t),byref:!!f.type_is_byref(t),target:identity(f.class_from_type(t))};
   descriptorCache.set(key,result);return result;
  };
'''
def build():
    t=base._TEMPLATE.replace("  r.step='types';let totalMethods=0,totalFields=0,totalParams=0;",DISCOVER+"  r.step='types';let totalMethods=0,totalFields=0,totalParams=0;")
    start=t.index('  const identity=k=>')
    end=t.index('  const queue=[],seen=new Map();',start)
    t=t[:start]+IDENTITY_CACHE+t[end:]
    # Keep every existing global limit, including the five-second deadline.
    # Cache exhaustion must use the same closed, marked-limited result.
    t=t.replace("const fail=reason=>{throw reason;};",
                "const fail=reason=>{if(reason==='limits')r.limited=true;throw reason;};")
    # Include the real constructed list/field/string owners, never guess generic bindings.
    t=t.replace("/^get_(Chat|MessagesCM|MessagesManager|Strategy)$/", "/^get_(Chat|Chats|ConversationsChats|MessagesCM|MessagesManager|MessagesRouter|Strategy|Value|Text|Content|Body|PreviewText)$/")
    t=t.replace('enqueue(f.class_from_type(ret),depth+1);',"{const kind=f.type_get_type(ret);if(kind===18||kind===21)enqueue(f.class_from_type(ret),depth+1);}")
    return t.replace('__ROOTS__',json.dumps(ROOTS)).replace('__IMAGES__',json.dumps(base.IMAGES)).replace('__APIS__',json.dumps(APIS)).replace('__REASONS__',json.dumps(sorted(base.REASONS)))
FUNCTION=build()
def validate(value):
    # Reuse every base graph invariant, including ownership/cycles/budgets/privacy.
    v=copy.deepcopy(value)
    if not isinstance(v.get('roots'),list) or len(v['roots'])!=len(ROOTS):raise ValueError('Invalid reply roots')
    for root,expected in zip(v['roots'],ROOTS):
        if not isinstance(root,dict) or set(root)!={'image','namespace','type','found','class_index'} or tuple(root.get(k) for k in ('image','namespace','type'))!=expected:raise ValueError('Unexpected reply root')
        if type(root.get('found')) is not bool:raise ValueError('Invalid root presence')
        idx=root.get('class_index')
        if idx is not None and (type(idx) is not int or not 0<=idx<64):raise ValueError('Invalid reply root index')
        if not root['found'] and idx is not None:raise ValueError('Missing reply root indexed')
        if root['found'] and v.get('stage')=='chat-runtime-ready' and (idx is None or idx>=len(v['types']) or v['types'][idx]['identity']!={k:root[k] for k in ('image','namespace','type')}):raise ValueError('Unverified reply root')
    v['roots']=v['roots'][:len(base.ROOTS)];base.validate(v)
    return value
