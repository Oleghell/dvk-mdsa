"""One visible non-promoted search result -> its profile -> same search.

Specializes the tested fixed observer, not a general method/action RPC. No text,
IDs, images, coordinate queries, synthetic touches, auth or installation.
"""
import json
import uikit_navigation as base
from uikit_root import APIS as ROOT_APIS

VERSION='0.3.3'
METADATA_CHECKPOINTS=('base', 'classes', 'method:avatarUser', 'method:cellAvatar', 'method:cellEntry', 'method:child', 'method:childCount', 'method:children', 'method:contentUser', 'method:currentContent', 'method:entryCount', 'method:entryItem', 'method:entryUser', 'method:enumerator', 'method:next', 'method:open', 'method:profileChecked', 'method:promo', 'method:recordEntries', 'method:rowItems', 'method:scroll', 'method:selfUser', 'method:visible', 'method:visibleCount', 'method:visibleItem', 'nested', 'ready')
SELECTION_CHECKS={'not-checked','visible-list','row-binding','row-children','cell-entry','promotion','record-items','entry-membership','entry-user','avatar-user','visible-stability','row-stability','cell-stability','items-stability','promotion-stability','selected'}
EXTRA_APIS=['il2cpp_class_get_nested_types','il2cpp_class_get_declaring_type']
PREPARE=r'''
 function prepareProfile(f,s,getClass,get,signature){
  r.navigation.metadata_checkpoint='classes';const required={table:['Core.dll','UIKit','TableView'],tableCell:['Core.dll','UIKit','TableCell'],
   searchTable:['DV.Search.dll','DV.Search','SearchTableView'],cell:['DV.Search.dll','DV','SearchCell'],
   entry:['DV.Search.dll','DV.Search','SearchEntry'],entryInterface:['DV.Search.dll','DV.Search','ISearchEntry'],
   avatar:['DV.dll','DV','AvatarView'],resource:['DV.dll','DV.Common','ResourceImageView'],
   user:['DV.dll','DV.Models','User'],content:['DV.Profile.dll','DV.Profiles','ProfileViewController']};
  for(const [key,args] of Object.entries(required)){s[key]=getClass(...args);if(s[key].isNull())throw new Error('metadata');}
  const name=p=>{if(p.isNull())throw new Error('metadata');let out='';for(let i=0;i<96;i++){const c=p.add(i).readU8();if(c===0)return out;if(c<32||c>126)throw new Error('metadata');out+=String.fromCharCode(c);}throw new Error('metadata');};
  const typeName=(k,ns,n)=>!k.isNull()&&name(f.className(k))===n&&name(f.classNamespace(k))===ns&&name(f.imageName(f.classImage(k)))==='Core.dll';
  r.navigation.metadata_checkpoint='nested';const nested={};const cursor=Memory.alloc(Process.pointerSize);cursor.writePointer(ptr(0));
  for(let i=0;i<64;i++){const k=f.nested(s.searchTable,cursor);if(k.isNull())break;
   const label=name(f.className(k));if(['LineCell','BlockACell','BlockBCell','LineRecord','BlockARecord','BlockBRecord','RowRecord'].includes(label)){
    if(!f.declaring(k).equals(s.searchTable)||name(f.classNamespace(k))!=='')throw new Error('metadata');nested[label]=k;
   }
   if(i===63)throw new Error('metadata');
  }
  if(Object.keys(nested).length!==7)throw new Error('metadata');s.rows=[nested.LineCell,nested.BlockACell,nested.BlockBCell];
  s.rowRecords=[nested.LineRecord,nested.BlockARecord,nested.BlockBRecord];s.record=nested.RowRecord;
  const checked=(klass,label,kind,result=null,args=[],unboxed=false,ownerExact=true,allowReferenceReturn=false)=>{
   const m=f.method(klass,Memory.allocUtf8String(label),args.length),bits=Memory.alloc(4);bits.writeU32(0);
   if(m.isNull()||f.arity(m)!==args.length||(f.flags(m,bits)&(16|1024))!==0||f.typeKind(f.returnType(m))!==kind)throw new Error('signature');
   const byref=!!f.byref(f.returnType(m));
   // CoreList<T>.get_Item(Int32) is ref T in this APK. runtime_invoke already
   // normalizes ref-to-reference returns to Il2CppObject*, not a slot pointer.
   // Only the two exact typed CoreList indexers opt in; all others stay strict.
   if(byref&&!(allowReferenceReturn&&kind===18&&result!==null&&!f.isValueType(result)))throw new Error('signature');
   const owner=f.methodClass(m);if(owner.isNull()||(ownerExact?!owner.equals(klass):!f.assignable(owner,klass)))throw new Error('signature');
   if(result&&!f.classFromType(f.returnType(m)).equals(result))throw new Error('signature');
   for(let i=0;i<args.length;i++){const t=f.param(m,i);if(t.isNull()||f.byref(t)||f.typeKind(t)!==args[i].kind||(args[i].klass&&!f.classFromType(t).equals(args[i].klass)))throw new Error('signature');}
   return {m,klass,kind,arity:args.length,params:args,result,unboxed,byref};
  };
  r.navigation.metadata_checkpoint='method:profileChecked';s.profileChecked=checked;
  r.navigation.metadata_checkpoint='method:scroll';s.scroll=checked(s.search,'get_ScrollView',18);
  r.navigation.metadata_checkpoint='method:visible';s.visible=checked(s.table,'get_VisibleCells',21);
  s.visibleClass=f.classFromType(f.returnType(s.visible.m));
  if(f.isValueType(s.visibleClass)||!typeName(s.visibleClass,'Core.Collections','CoreList`1'))throw new Error('signature');
  r.navigation.metadata_checkpoint='method:visibleCount';s.visibleCount=checked(s.visibleClass,'get_Count',8);
  r.navigation.metadata_checkpoint='method:visibleItem';s.visibleItem=checked(s.visibleClass,'get_Item',18,s.tableCell,[{kind:8}],false,true,true);
  r.navigation.metadata_checkpoint='method:children';s.children=checked(s.view,'get_Subviews',21);
  s.iterator=f.classFromType(f.returnType(s.children.m));const owner=f.declaring(s.iterator);
  if(!f.isValueType(s.iterator)||!typeName(s.iterator,'','Iterator')||!typeName(owner,'Core.Collections.StructBased','ShortList`1')||!f.isValueType(owner))throw new Error('signature');
  r.navigation.metadata_checkpoint='method:enumerator';s.enumerator=checked(s.iterator,'GetEnumerator',21,s.iterator,[],true);
  r.navigation.metadata_checkpoint='method:childCount';s.childCount=checked(s.iterator,'get_Count',8,null,[],true);
  r.navigation.metadata_checkpoint='method:next';s.next=checked(s.iterator,'MoveNext',2,null,[],true);r.navigation.metadata_checkpoint='method:child';s.child=checked(s.iterator,'get_Current',18,s.view,[],true);
  r.navigation.metadata_checkpoint='method:rowItems';s.rowItems=s.rows.map((row,i)=>checked(row,'get_Item',18,s.rowRecords[i],[],false,false));
  r.navigation.metadata_checkpoint='method:recordEntries';s.recordEntries=checked(s.record,'get_Items',21);s.entryList=f.classFromType(f.returnType(s.recordEntries.m));
  if(f.isValueType(s.entryList)||!typeName(s.entryList,'Core.Collections','CoreList`1'))throw new Error('signature');
  r.navigation.metadata_checkpoint='method:entryCount';s.entryCount=checked(s.entryList,'get_Count',8);r.navigation.metadata_checkpoint='method:entryItem';s.entryItem=checked(s.entryList,'get_Item',18,s.entry,[{kind:8}],false,true,true);
  r.navigation.metadata_checkpoint='method:promo';s.promo=checked(s.record,'IsPromoEntry',2,null,[{kind:18,klass:s.entryInterface}]);
  r.navigation.metadata_checkpoint='method:cellEntry';s.cellEntry=checked(s.cell,'get_Entry',18,s.entry);r.navigation.metadata_checkpoint='method:cellAvatar';s.cellAvatar=checked(s.cell,'get_AvatarView',18,s.avatar);
  r.navigation.metadata_checkpoint='method:entryUser';s.entryUser=checked(s.entry,'get_User',18,s.user);r.navigation.metadata_checkpoint='method:avatarUser';s.avatarUser=checked(s.avatar,'get_User',18,s.user);
  r.navigation.metadata_checkpoint='method:selfUser';s.selfUser=checked(s.user,'get_IsCurrentUser',2);
  r.navigation.metadata_checkpoint='method:currentContent';s.currentContent=checked(s.profile,'get_CurrentProfileController',18,s.content);
  r.navigation.metadata_checkpoint='method:contentUser';s.contentUser=checked(s.content,'get_User',18,s.user);
  r.navigation.metadata_checkpoint='method:open';s.open=checked(s.search,'DV.Search.SearchTableView.IDelegate.OnUserSelected',1,null,
   [{kind:18,klass:s.entry},{kind:2},{kind:18,klass:s.resource}]);
  r.navigation.metadata_checkpoint='ready';return s;
 }
'''
TICK=r'''
  const integer=(entry,obj)=>{const box=call(entry,obj);if(box.isNull())fail('signature-mismatch');const value=f.unbox(box);if(value.isNull())fail('signature-mismatch');return value.readS32();};
  const args=(values)=>{const out=Memory.alloc(values.length*Process.pointerSize);values.forEach((value,i)=>out.add(i*Process.pointerSize).writePointer(value));return out;};
  const indexed=(entry,list,index)=>{const value=Memory.alloc(4);value.writeS32(index);return call(entry,list,args([value]));};
  const attached=(view,required)=>{
   if(view.isNull()||!f.assignable(s.view,f.objectClass(view)))fail('unexpected-object');
   if(bool(s.hidden,view)||!bool(s.interactive,view))return false;
   let seenRequired=false,cursor=view;const seen=new Set();
   for(let i=0;i<32;i++){
    if(cursor.isNull())return false;own(cursor);const key=cursor.toString();if(seen.has(key))fail('view-parent-cycle');seen.add(key);
    if(cursor.equals(required))seenRequired=true;
    if(cursor.equals(window))return seenRequired;
    cursor=call(s.parent,cursor);
   }
   fail('view-parent-depth-limit');
  };
  const childViews=view=>{
   const list=call(s.children,view);if(list.isNull())return [];
   own(list);if(!f.objectClass(list).equals(s.iterator))fail('unexpected-object');
   const iterator=call(s.enumerator,list);if(iterator.isNull())fail('unexpected-object');own(iterator);
   if(!f.objectClass(iterator).equals(s.iterator))fail('unexpected-object');
   const count=integer(s.childCount,iterator);if(count<0||count>16)fail('selection-limit');
   const result=[];
   for(let i=0;i<count;i++){
    if(!bool(s.next,iterator))fail('selection-changed');const child=call(s.child,iterator);
    if(child.isNull()||!f.assignable(s.view,f.objectClass(child)))fail('unexpected-object');own(child);result.push(child);
   }
   if(bool(s.next,iterator))fail('selection-changed');return result;
  };
  const promoted=(record,entry)=>{
   const box=call(s.promo,record,args([entry]));if(box.isNull())fail('signature-mismatch');
   const value=f.unbox(box);if(value.isNull())fail('signature-mismatch');const result=value.readU8();
   if(result!==0&&result!==1)fail('signature-mismatch');return result===1;
  };
  const chooseVisibleCandidate=search=>{
   n.selection_check='visible-list';n.selection_status='no-visible-row';
   const table=call(s.scroll,search);if(table.isNull())return null;own(table);
   if(!f.objectClass(table).equals(s.searchTable))fail('unexpected-object');
   if(!attached(table,table))return null;
   const visible=call(s.visible,table);if(visible.isNull())return null;own(visible);
   if(!f.objectClass(visible).equals(s.visibleClass))fail('unexpected-object');
   const count=integer(s.visibleCount,visible);if(count<0||count>24)fail('selection-limit');
   // Only actual TableView.VisibleCells, never cached users or the whole scene.
   for(let i=0;i<count;i++){
    const row=indexed(s.visibleItem,visible,i);if(row.isNull())fail('unexpected-object');own(row);
    const ri=s.rows.findIndex(k=>f.objectClass(row).equals(k));if(ri<0)continue;
    if(!attached(row,table))continue;
    n.selection_check='row-binding';const record=call(s.rowItems[ri],row);if(record.isNull())continue;own(record);
    n.selection_status='no-eligible-cell';const queue=[{view:row,depth:0}],seen=new Set();let visited=0;
    while(queue.length){
     const item=queue.shift();if(++visited>16)fail('selection-limit');const key=item.view.toString();if(seen.has(key))fail('view-parent-cycle');seen.add(key);
     if(f.objectClass(item.view).equals(s.cell)){
      const cell=item.view;if(!attached(cell,row))continue;
      n.selection_check='cell-entry';const entry=call(s.cellEntry,cell);if(entry.isNull())continue;own(entry);
      n.selection_check='promotion';if(promoted(record,entry))continue;
      n.selection_check='record-items';const entries=call(s.recordEntries,record);if(entries.isNull())fail('selection-changed');own(entries);
      if(!f.objectClass(entries).equals(s.entryList))fail('unexpected-object');
      const total=integer(s.entryCount,entries);if(total<0||total>16)fail('selection-limit');let member=-1;
      n.selection_check='entry-membership';for(let j=0;j<total;j++)if(indexed(s.entryItem,entries,j).equals(entry)){member=j;break;}
      if(member<0)fail('selection-changed');
      n.selection_check='entry-user';const user=call(s.entryUser,entry);if(user.isNull())continue;own(user);
      if(bool(s.selfUser,user))continue;
      const avatar=call(s.cellAvatar,cell);if(avatar.isNull())continue;own(avatar);
      n.selection_check='avatar-user';if(!call(s.avatarUser,avatar).equals(user))fail('selection-changed');
      if(!attached(avatar,cell))continue;
      n.selection_check='visible-stability';if(integer(s.visibleCount,visible)!==count||!indexed(s.visibleItem,visible,i).equals(row))fail('selection-changed');
      n.selection_check='row-stability';if(!call(s.rowItems[ri],row).equals(record))fail('selection-changed');
      n.selection_check='cell-stability';if(!call(s.cellEntry,cell).equals(entry)||!call(s.cellAvatar,cell).equals(avatar)||!call(s.entryUser,entry).equals(user))fail('selection-changed');
      n.selection_check='items-stability';if(!call(s.recordEntries,record).equals(entries)||integer(s.entryCount,entries)!==total||!indexed(s.entryItem,entries,member).equals(entry))fail('selection-changed');
      n.selection_check='promotion-stability';if(promoted(record,entry))fail('selection-changed');
      n.selection_check='selected';
      n.selection_status='selected';return {entry,user,avatar};
     }
     if(item.depth<3){n.selection_check='row-children';for(const child of childViews(item.view))queue.push({view:child,depth:item.depth+1});}
    }
   }
   return null;
  };
  const verifyProfile=queue=>{
   const content=call(s.currentContent,queue);if(content.isNull())return false;own(content);
   if(!f.objectClass(content).equals(s.content))fail('unexpected-object');
   if(!state.content.isNull()&&!content.equals(target(state.content)))fail('identity-changed');
   const user=call(s.contentUser,content);if(user.isNull())return false;
   if(state.targetUser.isNull()||!user.equals(target(state.targetUser)))fail('identity-changed');
   if(!modal(content).isNull())fail('unexpected-screen');
   if(bool(s.presenting,content)||bool(s.dismissing,content))return false;
   if(!checkView(content))return false;
   if(!call(s.currentContent,queue).equals(content)||!call(s.contentUser,content).equals(user))fail('identity-changed');
   if(state.content.isNull()){state.content=own(content);held.splice(held.indexOf(state.content),1);}
   n.target_user_verified=true;n.profile_content_verified=true;return true;
  };
'''


def replace_once(text,old,new):
    if text.count(old)!=1:raise RuntimeError('Fixed observer specialization no longer matches')
    return text.replace(old,new,1)


def build():
    helpers=base.HELPERS.replace('__NAV_ERRORS__',json.dumps(sorted(base.ERRORS|{'selection-limit','selection-changed'})))
    helpers=helpers.replace('filters','profile').replace('cancel_attempted','close_attempted').replace('cancel_completed','close_completed')
    helpers=replace_once(helpers,"'DV.Search.dll','DV.Search','SearchSettingsCardController'", "'DV.Profile.dll','DV.Profiles','ProfilesQueueViewController'")
    helpers=replace_once(helpers,'!f.assignable(s.card,s.profile)','!f.assignable(s.vc,s.profile)')
    helpers=replace_once(helpers,"['canClose','card','get_CanBeClosedByUser',2],",'')
    helpers=replace_once(helpers,"['open','search','ShowSearchSettings',1],['cancel','card','DismissWithCancel',1]", "['cancel','profile','DV.Profiles.ProfileViewController.IDelegate.OnCloseRequested',1]")
    helpers=replace_once(helpers,'  return s;\n }','  return prepareProfile(f,s,getClass,get,signature);\n }')
    helpers=replace_once(helpers,"action_backend:'semantic-controller-handlers',ui_text_read:false", "metadata_checkpoint:'base',selection_check:'not-checked',selection_retries:0,selection_status:'not-checked',target_user_verified:false,profile_content_verified:false,action_backend:'semantic-controller-handlers',ui_text_read:false")
    helpers=replace_once(helpers,"if(entry.arity===1){if(!f.classFromType", "if(entry.params){for(let i=0;i<entry.params.length;i++){const t=f.param(m,i),a=entry.params[i];if(t.isNull()||f.byref(t)||f.typeKind(t)!==a.kind||(a.klass&&!f.classFromType(t).equals(a.klass)))fail('signature-mismatch');}if(entry.result&&!f.classFromType(f.returnType(m)).equals(entry.result))fail('signature-mismatch');}\n   else if(entry.arity===1){if(!f.classFromType")
    helpers=replace_once(helpers,"||f.byref(f.returnType(m)))fail('signature-mismatch');","||!!f.byref(f.returnType(m))!==!!entry.byref)fail('signature-mismatch');")
    helpers=replace_once(helpers,'const out=f.invoke(m,obj,params,ex);',"let receiver=obj;if(entry.unboxed){receiver=f.unbox(obj);if(receiver.isNull())fail('signature-mismatch');}\n   const out=f.invoke(m,receiver,params,ex);")
    helpers=replace_once(helpers,"if(!ex.readPointer().isNull())fail('managed-exception');return out;","if(!ex.readPointer().isNull())fail('managed-exception');if(entry.byref&&!out.isNull()&&!f.assignable(entry.result,f.objectClass(out)))fail('unexpected-object');return out;")
    helpers=replace_once(helpers,"} catch(e){n.error=typeof e==='string'", "} catch(e){if(e==='selection-changed'&&n.phase==='search'&&!n.open_attempted&&n.selection_retries<2){n.selection_retries++;return;}n.error=typeof e==='string'")
    helpers=replace_once(helpers,'const held=[];const deadline=Date.now()+100;', 'const held=[];const heldByObject=new Map();const deadline=Date.now()+100;')
    helpers=replace_once(helpers,"if(obj.isNull())fail('unexpected-object');if(held.length>=64)", "if(obj.isNull())fail('unexpected-object');const key=obj.toString();if(heldByObject.has(key))return heldByObject.get(key);if(held.length>=64)")
    helpers=replace_once(helpers,'held.push(h);return h;', 'held.push(h);heldByObject.set(key,h);return h;')
    helpers=replace_once(helpers,'  try {\n   const root=',TICK+'\n  try {\n   const root=')
    helpers=replace_once(helpers,"n.search_verified=true;state.origin=own(current);", "n.search_verified=true;const selected=chooseVisibleCandidate(current);if(selected===null)return;\n    state.targetUser=own(selected.user);held.splice(held.indexOf(state.targetUser),1);\n    state.origin=own(current);")
    helpers=replace_once(helpers,'n.open_attempted=true;call(s.open,current);',"const promotion=Memory.alloc(1);promotion.writeU8(0);\n    n.open_attempted=true;call(s.open,current,args([selected.entry,promotion,selected.avatar]));")
    helpers=replace_once(helpers,'n.profile_verified=true;state.card=own(current);','if(!verifyProfile(current))return;\n    n.profile_verified=true;state.card=own(current);')
    helpers=replace_once(helpers,"if(!bool(s.canClose,current))fail('screen-not-ready');",'if(!verifyProfile(current))return;')
    helpers=replace_once(helpers,"['card','origin']","['content','targetUser','card','origin']")
    # Keep the proven cancellation, lifetime, main-thread and frame guards byte-for-byte.
    old=base.HELPERS.replace('__NAV_ERRORS__',json.dumps(sorted(base.ERRORS)))
    result=replace_once(base.FUNCTION,old,PREPARE+helpers)
    result=replace_once(result,json.dumps(ROOT_APIS+base.APIS),json.dumps(ROOT_APIS+base.APIS+EXTRA_APIS))
    result=replace_once(result,"['Core.dll','DV.dll','DV.Search.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll']", "['Core.dll','DV.dll','DV.Search.dll','DV.Profile.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll']")
    result=replace_once(result,base.BINDINGS,base.BINDINGS+"\nObject.assign(f,{nested:bind('class_get_nested_types','pointer',['pointer','pointer']),declaring:bind('class_get_declaring_type','pointer',['pointer'])});")
    result=replace_once(result,'const navState={origin:ptr(0),card:ptr(0),stop:null}', 'const navState={origin:ptr(0),card:ptr(0),content:ptr(0),targetUser:ptr(0),stop:null}')
    return result

FUNCTION=build()


def validate(value):
    if not isinstance(value,dict) or not isinstance(value.get('navigation'),dict):raise ValueError('Missing profile navigation')
    import copy
    out=copy.deepcopy(value);n=out['navigation']
    flags={'cleanup_failed','search_verified','profile_verified','return_verified','open_attempted','open_completed','close_attempted','close_completed','ui_text_read'}
    fields=flags|{'stage','phase','error','frames','managed_calls','handles_acquired','handles_released','root_top_kind','last_presented_kind','controller_path','action_backend','readiness_check','readiness','view_parent_depth','selection_status','target_user_verified','profile_content_verified','metadata_checkpoint','selection_check','selection_retries'}
    if set(n)!=fields:raise ValueError('Unexpected profile fields')
    if n.pop('metadata_checkpoint',None) not in METADATA_CHECKPOINTS:raise ValueError('Unexpected metadata checkpoint')
    if n.pop('selection_check',None) not in SELECTION_CHECKS:raise ValueError('Unexpected selection checkpoint')
    retries=n.pop('selection_retries',None)
    if type(retries) is not int or not 0<=retries<=2:raise ValueError('Invalid selection retry count')
    if n.get('phase') not in {'search','wait-profile','confirm-profile','wait-return','done'}:raise ValueError('Unexpected profile phase')
    path=n.get('controller_path')
    kinds=base.KINDS-{'filters'}|{'profile'}
    if any(n.get(k) not in kinds for k in ('root_top_kind','last_presented_kind')) or not isinstance(path,list) or any(k not in kinds for k in path if isinstance(k,str)):raise ValueError('Unexpected profile path')
    if n.get('open_attempted') and n.get('selection_status')!='selected':raise ValueError('Action without a selected visible result')
    if n.pop('selection_status',None) not in {'not-checked','no-visible-row','no-eligible-cell','selected'}:raise ValueError('Invalid selection category')
    extra={k:n.pop(k,None) for k in ('target_user_verified','profile_content_verified')}
    if any(type(v) is not bool for v in extra.values()):raise ValueError('Invalid profile verification')
    if n.get('profile_verified') and not all(extra.values()):raise ValueError('Unverified profile identity')
    for old,new in [('profile_verified','filters_verified'),('close_attempted','cancel_attempted'),('close_completed','cancel_completed')]:
        if old not in n:raise ValueError('Missing profile step')
        n[new]=n.pop(old)
    for key in ('root_top_kind','last_presented_kind'):
        if n.get(key)=='profile':n[key]='filters'
    if isinstance(n.get('controller_path'),list):n['controller_path']=['filters' if v=='profile' else v for v in n['controller_path']]
    if n.get('phase') in ('wait-profile','confirm-profile'):n['phase']=n['phase'].replace('profile','filters')
    if n.get('error') in ('selection-limit','selection-changed'):n['error']='unexpected-object'
    # Four permanent identities rather than two; retain the base strict schema.
    for key in ('handles_acquired','handles_released'):
        if type(n.get(key)) is not int or not 0<=n[key]<=180*64+4:raise ValueError('Invalid profile handle count')
    base.validate(out)
    return value
