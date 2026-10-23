"""One manually opened dialog: read-only, stable loaded-history state. Never sends."""
import copy,json
import uikit_navigation as base
import uikit_root as root
from uikit_profile_navigation import replace_once

VERSION='0.3.27'
ERRORS=base.ERRORS|{'history-invalid','not-a-dialog','history-not-ready'}
READ_STEPS={'not-checked','identity','model','manager','loaded-flag','count','last-message','recheck','sample','complete'}
WAIT_REASONS={'not-checked','none','chat-not-actual','chat-draft','no-history-manager','null-history-manager','null-loaded-flag','history-loading','history-not-loaded','changing-count','changing-last-message','contradictory-last-message','view-not-ready','model-changed'}
CHECKPOINTS={'base','classes','chat-methods','cm-methods','loaded-type','loaded-value','ready'}
EXTRA=r'''
 function prepareChat(f,s,getClass){
  const n=r.navigation;n.metadata_checkpoint='classes';
  const defs={chatModel:['DV.Messages.dll','DV.Messages','Chat'],cm:['DV.Messages.dll','DV.CMs','MessagesCM'],
   user:['DV.dll','DV.Models','User'],message:['DV.Messages.dll','DV.Messages','Message']};
  for(const [key,args] of Object.entries(defs)){s[key]=getClass(...args);if(s[key].isNull())throw new Error('metadata');}
  const name=p=>{if(p.isNull())throw new Error('signature');let s='';for(let i=0;i<192;i++){const c=p.add(i).readU8();if(c===0)return s;if(c<32||c>126)throw new Error('signature');s+=String.fromCharCode(c);}throw new Error('signature');};
  const is=(k,image,ns,label)=>!k.isNull()&&name(f.className(k))===label&&name(f.classNamespace(k))===ns&&name(f.imageName(f.classImage(k)))===image;
  const checked=(klass,label,kind,result=null,unboxed=false,verifiedOwner=null)=>{
   const m=f.method(klass,Memory.allocUtf8String(label),0),bits=Memory.alloc(4);bits.writeU32(0);
   if(m.isNull()||f.arity(m)!==0||(f.flags(m,bits)&(16|1024))!==0||f.typeKind(f.returnType(m))!==kind||f.byref(f.returnType(m))||!f.methodClass(m).equals(verifiedOwner===null?klass:verifiedOwner))throw new Error('signature');
   if(result&&!f.classFromType(f.returnType(m)).equals(result))throw new Error('signature');
   return {m,klass,kind,arity:0,unboxed};
  };
  n.metadata_checkpoint='chat-methods';
  s.chatUser=checked(s.filters,'get_User',18,s.user);s.chat=checked(s.filters,'get_Chat',18,s.chatModel);
  s.dialog=checked(s.chatModel,'get_Dialog',2);s.opponent=checked(s.chatModel,'get_DialogOpponent',18,s.user);
  s.actual=checked(s.chatModel,'get_IsActual',2);s.draft=checked(s.chatModel,'get_IsDraftChat',2);
  s.hasCM=checked(s.chatModel,'get_HasMessagesCM',2);s.messages=checked(s.chatModel,'get_MessagesCM',18,s.cm);
  s.last=checked(s.chatModel,'get_LastMessage',18,s.message);
  n.metadata_checkpoint='cm-methods';let content=ptr(0),list=ptr(0),cursor=s.cm;const seen=new Set();
  for(let i=0;i<10&&!cursor.isNull();i++){
   const key=cursor.toString();if(seen.has(key))throw new Error('hierarchy');seen.add(key);
   if(is(cursor,'DV.dll','DV.CMs','ContentDataList`1'))content=cursor;
   if(is(cursor,'Core.dll','DataKit','BaseDataList`1'))list=cursor;
   cursor=f.classParent(cursor);
  }
  if(content.isNull()||list.isNull()||!f.assignable(content,s.cm)||!f.assignable(list,s.cm))throw new Error('hierarchy');
  s.historyLoading=checked(content,'get_LoadInProgress',2);s.all=checked(content,'get_AllIsLoaded',21);s.count=checked(list,'get_Count',8);
  n.metadata_checkpoint='loaded-type';s.loadedClass=f.classFromType(f.returnType(s.all.m));
  if(!is(s.loadedClass,'Core.dll','DataKit','DataField`1'))throw new Error('signature');
  n.metadata_checkpoint='loaded-value';const method=f.method(s.loadedClass,Memory.allocUtf8String('get_Value'),0);
  n.loaded_value_method_found=!method.isNull();
  let verifiedOwner=null;
  if(!method.isNull()){
   n.loaded_value_return_kind=f.typeKind(f.returnType(method));n.loaded_value_byref=!!f.byref(f.returnType(method));
   const bits=Memory.alloc(4);bits.writeU32(0);const flags=f.flags(method,bits),owner=f.methodClass(method);
   n.loaded_value_arity=f.arity(method);n.loaded_value_static=!!(flags&16);n.loaded_value_abstract=!!(flags&1024);
   n.loaded_value_owner_verified=false;n.loaded_value_owner_inherited=false;
   n.loaded_value_owner_scope=!owner.isNull()&&name(f.imageName(f.classImage(owner)))==='Core.dll'&&name(f.classNamespace(owner))==='DataKit';
   // Only the exact owner pointer on the actual bounded parent chain is accepted.
   // A matching generic name or assignability alone is never sufficient.
   let k=s.loadedClass;const owners=new Set();
   for(let i=0;i<10&&!k.isNull();i++){
    const key=k.toString();if(owners.has(key))throw new Error('hierarchy');owners.add(key);
    if(k.equals(owner)){
     n.loaded_value_owner_inherited=!k.equals(s.loadedClass);
     n.loaded_value_owner_verified=n.loaded_value_owner_scope&&!!f.assignable(owner,s.loadedClass);
     if(n.loaded_value_owner_verified)verifiedOwner=owner;
     break;
    }
    k=f.classParent(k);
   }
  }
  if(verifiedOwner===null)throw new Error('signature');
  s.value=checked(s.loadedClass,'get_Value',2,null,!!f.isValueType(s.loadedClass),verifiedOwner);
  n.metadata_checkpoint='ready';return s;
 }
'''
READ=r'''
   // No UI mutations: inspect only the exact already visible MessagesViewController.
   n.read_checkpoint='identity';n.wait_reason='none';
   for(const k of ['model_actual','model_draft','model_has_cm','cm_present','loaded_field_present','history_fully_loaded','history_loading','last_message_present'])n[k]=null;
   const user=call(s.chatUser,current);if(user.isNull())return;own(user);
   if(!f.objectClass(user).equals(s.user))fail('unexpected-object');
   const chat=call(s.chat,current);if(chat.isNull())return;own(chat);
   if(!f.objectClass(chat).equals(s.chatModel))fail('unexpected-object');
   if(!bool(s.dialog,chat))fail('not-a-dialog');
   if(!call(s.opponent,chat).equals(user))fail('identity-changed');
   const save=(key,obj)=>{if(!state[key].isNull()){if(!target(state[key]).equals(obj))fail('identity-changed');}
    else{state[key]=own(obj);held.splice(held.indexOf(state[key]),1);}};
   save('origin',current);save('card',chat);save('user',user);n.chat_identity_verified=true;
   const integer=(entry,obj)=>{const box=call(entry,obj);if(box.isNull())fail('signature-mismatch');const p=f.unbox(box);if(p.isNull())fail('signature-mismatch');return p.readS32();};
   const invalidate=reason=>{
    n.wait_reason=reason;n.history_status='not-ready';n.message_count=null;n.samples=0;state.sample=null;
    const signature=JSON.stringify([reason,n.model_actual,n.model_draft,n.model_has_cm]);
    if(state.waitSignature===signature&&Date.now()-state.waitAt>=1000)fail('history-not-ready');
    state.waitSignature=signature;state.waitAt=Date.now();state.nextActionAt=Date.now()+1000;
   };
   n.read_checkpoint='model';n.model_actual=bool(s.actual,chat);n.model_draft=bool(s.draft,chat);n.model_has_cm=bool(s.hasCM,chat);
   if(!n.model_actual||!n.model_has_cm){invalidate(!n.model_actual?'chat-not-actual':'no-history-manager');return;}
   n.read_checkpoint='manager';const cm=call(s.messages,chat);n.cm_present=!cm.isNull();if(cm.isNull()){invalidate('null-history-manager');return;}own(cm);
   if(!f.objectClass(cm).equals(s.cm))fail('unexpected-object');save('cm',cm);
   n.read_checkpoint='loaded-flag';const loading=bool(s.historyLoading,cm),field=call(s.all,cm);n.history_loading=loading;n.loaded_field_present=!field.isNull();if(field.isNull()){invalidate('null-loaded-flag');return;}own(field);
   if(!f.objectClass(field).equals(s.loadedClass))fail('unexpected-object');
   const all=bool(s.value,field);n.history_fully_loaded=all;n.read_checkpoint='count';
   const first=integer(s.count,cm),second=integer(s.count,cm);n.read_checkpoint='last-message';const lastMessage=call(s.last,chat);
   if(!lastMessage.isNull()){own(lastMessage);if(!f.assignable(s.message,f.objectClass(lastMessage)))fail('unexpected-object');}
   n.read_checkpoint='recheck';
   // Same binding/visibility and readiness before and after the sample.
   if(!call(s.chat,current).equals(chat)||!call(s.chatUser,current).equals(user)||!call(s.opponent,chat).equals(user)||!call(s.messages,chat).equals(cm))fail('identity-changed');
   const fieldAgain=call(s.all,cm);if(fieldAgain.isNull()){invalidate('null-loaded-flag');return;}own(fieldAgain);
   if(!f.objectClass(fieldAgain).equals(s.loadedClass))fail('unexpected-object');
   const allAgain=bool(s.value,fieldAgain),loadingAgain=bool(s.historyLoading,cm);
   const actualAgain=bool(s.actual,chat),draftAgain=bool(s.draft,chat),hasAgain=bool(s.hasCM,chat);
   if(!actualAgain||draftAgain!==n.model_draft||!hasAgain){n.model_actual=actualAgain;n.model_draft=draftAgain;n.model_has_cm=hasAgain;invalidate('model-changed');return;}
   if(bool(s.presenting,current)||bool(s.dismissing,current)||!checkView(current)){invalidate('view-not-ready');return;}
   if(!resolve(candidate).equals(current)||!call(s.chat,current).equals(chat)||!call(s.chatUser,current).equals(user))fail('identity-changed');
   const third=integer(s.count,cm),lastAgain=call(s.last,chat);if(!lastAgain.isNull())own(lastAgain);
   if(!lastAgain.equals(lastMessage)){invalidate('changing-last-message');return;}
   if(!call(s.chat,current).equals(chat)||!call(s.chatUser,current).equals(user)||!call(s.opponent,chat).equals(user)||!call(s.messages,chat).equals(cm))fail('identity-changed');
   n.history_fully_loaded=all&&allAgain;n.history_loading=loading||loadingAgain;n.last_message_present=!lastMessage.isNull();
   if(first<0||first>1000000||second<0||second>1000000)fail('history-invalid');
   if(loading||loadingAgain||!all||!allAgain||first!==second||first!==third){invalidate(loading||loadingAgain?'history-loading':!all||!allAgain?'history-not-loaded':'changing-count');return;}
   // A last-message marker contradicting Count=0 is not proof of empty history.
   if(first===0&&!lastMessage.isNull()){invalidate('contradictory-last-message');return;}
   n.read_checkpoint='sample';n.wait_reason='none';state.waitSignature=null;
   const sample={count:first,last:!lastMessage.isNull(),draft:n.model_draft};
   if(state.sample===null||state.sample.count!==sample.count||state.sample.last!==sample.last||state.sample.draft!==sample.draft){
    state.sample=sample;n.samples=1;n.history_status='checking';n.message_count=null;state.nextActionAt=Date.now()+1000;return;
   }
   n.read_checkpoint='complete';n.samples=2;n.message_count=first;n.history_status=first===0?'empty':'not-empty';n.phase='done';n.stage='navigation-ready';
'''


def build():
    helpers=base.HELPERS
    helpers=replace_once(helpers,"'DV.Search.dll','DV.Search','SearchSettingsCardController'", "'DV.Messages.dll','DV.Messages','MessagesViewController'")
    helpers=replace_once(helpers,'!f.assignable(s.card,s.filters)','!f.assignable(s.vc,s.filters)')
    helpers=replace_once(helpers,"['canClose','card','get_CanBeClosedByUser',2],",'')
    helpers=replace_once(helpers,"['open','search','ShowSearchSettings',1],['cancel','card','DismissWithCancel',1]",'')
    helpers=replace_once(helpers,'  return s;\n }','  return prepareChat(f,s,getClass);\n }')
    helpers=replace_once(helpers,"action_backend:'semantic-controller-handlers',ui_text_read:false", "action_backend:'read-only-chat-state',ui_text_read:false,metadata_checkpoint:'base',read_checkpoint:'not-checked',wait_reason:'not-checked',model_actual:null,model_draft:null,model_has_cm:null,cm_present:null,loaded_field_present:null,loaded_value_method_found:null,loaded_value_return_kind:null,loaded_value_byref:null,loaded_value_owner_verified:null,loaded_value_owner_inherited:null,loaded_value_owner_scope:null,loaded_value_static:null,loaded_value_abstract:null,loaded_value_arity:null,history_status:'unknown',message_count:null,history_fully_loaded:null,history_loading:null,last_message_present:null,samples:0,sample_interval_ms:1000,chat_identity_verified:false,app_actions_attempted:false,messages_sent:0")
    helpers=replace_once(helpers,"if(n.phase==='search'&&k!=='search')", "if(n.phase==='search'&&k!=='filters')")
    start=helpers.index("   if(n.phase==='search'){\n    n.search_verified=true;")
    end=helpers.index("  } catch(e)",start)
    helpers=helpers[:start]+READ+helpers[end:]
    helpers=replace_once(helpers,"const out=f.invoke(m,obj,params,ex);", "const receiver=entry.unboxed?f.unbox(obj):obj;if(receiver.isNull())fail('unexpected-object');\n   const out=f.invoke(m,receiver,params,ex);")
    helpers=replace_once(helpers,"['card','origin']","['cm','user','card','origin']")
    helpers=replace_once(helpers,"  if(n.cleanup_failed){n.stage='cleanup-failed';n.error='cleanup-failed';}", "  if(n.cleanup_failed){n.stage='cleanup-failed';n.error='cleanup-failed';}\n  if(n.stage!=='navigation-ready'){n.history_status='unknown';n.message_count=null;n.samples=Math.min(n.samples,1);}")
    original=base.HELPERS.replace('__NAV_ERRORS__',json.dumps(sorted(base.ERRORS)))
    result=replace_once(base.FUNCTION,original,EXTRA+helpers.replace('__NAV_ERRORS__',json.dumps(sorted(ERRORS))))
    result=replace_once(result,json.dumps(root.APIS+base.APIS),json.dumps(root.APIS+base.APIS+['il2cpp_class_get_parent']))
    result=replace_once(result,base.BINDINGS,base.BINDINGS+"\nObject.assign(f,{classParent:bind('class_get_parent','pointer',['pointer'])});")
    result=replace_once(result,"['Core.dll','DV.dll','DV.Search.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll']", "['Core.dll','DV.dll','DV.Search.dll','DV.Messages.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll']")
    result=replace_once(result,'const navState={origin:ptr(0),card:ptr(0),stop:null};', 'const navState={origin:ptr(0),card:ptr(0),user:ptr(0),cm:ptr(0),sample:null,waitSignature:null,waitAt:0,nextActionAt:Date.now()+1000,stop:null};')
    result=replace_once(result,'if(!active)return;\n     r.observed_calls++;','if(!active)return;\n     if(Date.now()<navState.nextActionAt)return;\n     r.observed_calls++;')
    return result.replace("'filters'","'chat'")

FUNCTION=build()


def validate(value, *, max_calls=base.MAX_CALLS):
    if not isinstance(value,dict) or not isinstance(value.get('navigation'),dict):raise ValueError('Missing chat state')
    v=copy.deepcopy(value);n=v['navigation']
    extras={'read_checkpoint','wait_reason','model_actual','model_draft','model_has_cm','cm_present','loaded_field_present','metadata_checkpoint','loaded_value_method_found','loaded_value_return_kind','loaded_value_byref','loaded_value_owner_verified','loaded_value_owner_inherited','loaded_value_owner_scope','loaded_value_static','loaded_value_abstract','loaded_value_arity','history_status','message_count','history_fully_loaded','history_loading','last_message_present','samples','sample_interval_ms','chat_identity_verified','app_actions_attempted','messages_sent'}
    if not extras<=set(n):raise ValueError('Missing chat state fields')
    x={k:n.pop(k) for k in extras}
    if x['metadata_checkpoint'] not in CHECKPOINTS:raise ValueError('Unknown checkpoint')
    if x['read_checkpoint'] not in READ_STEPS or x['wait_reason'] not in WAIT_REASONS:raise ValueError('Invalid read diagnostic')
    if x['history_status'] not in {'unknown','not-ready','checking','empty','not-empty'}:raise ValueError('Invalid history state')
    for k in ('model_actual','model_draft','model_has_cm','cm_present','loaded_field_present','loaded_value_method_found','loaded_value_byref','loaded_value_owner_verified','loaded_value_owner_inherited','loaded_value_owner_scope','loaded_value_static','loaded_value_abstract','history_fully_loaded','history_loading','last_message_present'):
        if x[k] is not None and type(x[k]) is not bool:raise ValueError('Invalid history flag')
    if x['loaded_value_return_kind'] is not None and (type(x['loaded_value_return_kind']) is not int or not 0<=x['loaded_value_return_kind']<=255):raise ValueError('Invalid return kind')
    if x['loaded_value_arity'] is not None and (type(x['loaded_value_arity']) is not int or not 0<=x['loaded_value_arity']<=255):raise ValueError('Invalid getter arity')
    for k in ('chat_identity_verified','app_actions_attempted'):
        if type(x[k]) is not bool:raise ValueError('Invalid chat flag')
    if type(x['messages_sent']) is not int or x['messages_sent']!=0 or x['app_actions_attempted']:raise ValueError('Forbidden chat action')
    if type(x['samples']) is not int or not 0<=x['samples']<=2 or type(x['sample_interval_ms']) is not int or x['sample_interval_ms']!=1000:raise ValueError('Invalid sample count')
    if n.get('action_backend')!='read-only-chat-state':raise ValueError('Invalid chat backend')
    forbidden=('search_verified','filters_verified','return_verified','open_attempted','open_completed','cancel_attempted','cancel_completed')
    if any(n.get(k) is not False for k in forbidden):raise ValueError('Unexpected UI action')
    state=x['history_status'];classified=state in {'empty','not-empty'}
    if classified:
        count=x['message_count']
        if type(count) is not int or not 0<=count<=1000000 or (state=='empty')!=(count==0):raise ValueError('Invalid history count')
        if x['metadata_checkpoint']!='ready' or x['loaded_value_method_found'] is not True or x['loaded_value_return_kind']!=2 or x['loaded_value_byref'] is not False or x['loaded_value_owner_verified'] is not True or x['loaded_value_owner_scope'] is not True or type(x['loaded_value_owner_inherited']) is not bool or x['loaded_value_static'] is not False or x['loaded_value_abstract'] is not False or x['loaded_value_arity']!=0 or not x['chat_identity_verified'] or x['samples']!=2 or x['history_fully_loaded'] is not True or x['history_loading'] is not False or n.get('stage')!='navigation-ready':raise ValueError('Unverified history state')
        if x['read_checkpoint']!='complete' or x['wait_reason']!='none' or x['model_actual'] is not True or type(x['model_draft']) is not bool or any(x[k] is not True for k in ('model_has_cm','cm_present','loaded_field_present')):raise ValueError('Unverified model state')
        if state=='empty' and x['last_message_present'] is not False:raise ValueError('Contradictory empty state')
    elif x['message_count'] is not None or x['samples']==2:raise ValueError('Unknown count must stay unknown')
    if n.get('stage')=='navigation-ready' and not classified:raise ValueError('Missing history classification')
    # Reuse all existing frame, thread, visibility, lifetime and root invariants.
    for key in ('root_top_kind','last_presented_kind'):
        if n.get(key)=='filters':raise ValueError('Unexpected filters screen')
        if n.get(key)=='chat':n[key]='filters'
    if isinstance(n.get('controller_path'),list):
        if 'filters' in n['controller_path']:raise ValueError('Unexpected filters path')
        n['controller_path']=['filters' if k=='chat' else k for k in n['controller_path']]
    if n.get('error') not in ERRORS:raise ValueError('Unknown chat stop reason')
    if n['error'] not in base.ERRORS:n['error']='native-call-failed'
    n['action_backend']='semantic-controller-handlers'
    if n.get('stage')=='navigation-ready':
        for k in forbidden:n[k]=True
    base.validate(v,max_calls=max_calls)
    return value
