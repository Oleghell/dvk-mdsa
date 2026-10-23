"""Journal-filtered cached Chat models; no visible cells, gestures or body reads.

The fixed fields/getters/route come from the user's navigation definitions.
Runtime types and the constructed list indexer are checked before any invocation.
No load/refresh/send methods or guessed object offsets are used.
"""
import copy,json
import dialog_browser as browser
from assistant_store import StateError
from uikit_profile_navigation import replace_once
MAX_MODELS=100000
SLICE=64
SCAN_MILLISECONDS=4000
EXTRA_APIS=['il2cpp_class_get_field_from_name','il2cpp_field_get_parent',
 'il2cpp_field_get_type','il2cpp_field_get_flags','il2cpp_field_get_value',
 'il2cpp_class_value_size','il2cpp_class_is_enum','il2cpp_class_enum_basetype',
 'il2cpp_class_get_declaring_type','il2cpp_field_static_get_value']
BINDINGS="""field:bind('class_get_field_from_name','pointer',['pointer','pointer']),
 fieldOwner:bind('field_get_parent','pointer',['pointer']),fieldType:bind('field_get_type','pointer',['pointer']),
 fieldFlags:bind('field_get_flags','uint32',['pointer']),fieldValue:bind('field_get_value','void',['pointer','pointer','pointer']),
 valueSize:bind('class_value_size','int',['pointer','pointer']),isEnum:bind('class_is_enum','bool',['pointer']),
 enumBase:bind('class_enum_basetype','pointer',['pointer']),
 declaring:bind('class_get_declaring_type','pointer',['pointer']),
 staticFieldValue:bind('field_static_get_value','void',['pointer','pointer']),"""
PREPARE=r'''
  n.metadata_checkpoint='model-manager';
  s.managerField=f.field(s.filters,Memory.allocUtf8String('m_MessagesManager'));
  if(s.managerField.isNull()||!f.fieldOwner(s.managerField).equals(s.filters)||
     (f.fieldFlags(s.managerField)&16)!==0)throw new Error('signature');
  const ft=f.fieldType(s.managerField);
  if(ft.isNull()||f.byref(ft)||f.typeKind(ft)!==18||!f.classFromType(ft).equals(s.manager))throw new Error('signature');
  s.chatsClass=getClass('DV.Messages.dll','DV.CMs','ChatsCM');
  s.routerClass=getClass('DV.Messages.dll','DV.Routers.Messages','MessagesRouter');
  if(s.chatsClass.isNull()||s.routerClass.isNull())throw new Error('metadata');
  s.chats=checked(s.manager,'get_Chats',18,s.chatsClass);
  n.metadata_checkpoint='model-collection';
  s.modelCount=checked(s.chatsClass,'get_Count',8);
  s.modelItem=checked(s.chatsClass,'get_Item',18,s.chatModel,[{kind:8}],true);
  s.router=checked(s.manager,'get_MessagesRouter',18,s.routerClass);
  n.metadata_checkpoint='model-route';
  // APK v31: both enums are nested inside DV.Analytics.Stat, not top-level
  // types. Resolve them from the actual ShowChat parameters, then prove owner.
  n.metadata_checkpoint='model-route-owner';
  s.statClass=getClass('DV.dll','DV.Analytics','Stat');
  if(s.statClass.isNull()||f.isValueType(s.statClass))throw new Error('metadata');
  n.metadata_checkpoint='model-route-parameters';
  const show=f.method(s.routerClass,Memory.allocUtf8String('ShowChat'),3);
  if(show.isNull())throw new Error('signature');
  const ct=f.param(show,1),mt=f.param(show,2);
  if(ct.isNull()||mt.isNull()||f.byref(ct)||f.byref(mt))throw new Error('signature');
  s.contextClass=f.classFromType(ct);s.methodClass=f.classFromType(mt);
  const text=p=>{if(p.isNull())throw new Error('metadata');let out='';for(let i=0;i<96;i++){
   const c=p.add(i).readU8();if(c===0)return out;if(c<32||c>126)throw new Error('metadata');out+=String.fromCharCode(c);}throw new Error('metadata');};
  const enumType=(klass,label)=>{
   if(klass.isNull()||!f.isValueType(klass)||!f.isEnum(klass)||!f.declaring(klass).equals(s.statClass)||
      text(f.className(klass))!==label||text(f.classNamespace(klass))!==''||
      text(f.imageName(f.classImage(klass)))!=='DV.dll')throw new Error('signature');
   const base=f.enumBase(klass);if(base.isNull()||f.typeKind(base)!==8)throw new Error('signature');
   const align=Memory.alloc(4);align.writeU32(0);
   if(f.valueSize(klass,align)!==4||align.readU32()!==4)throw new Error('signature');
  };
  n.metadata_checkpoint='model-route-enums';
  enumType(s.contextClass,'EventSourcesContext');enumType(s.methodClass,'OpenChatMethod');
  s.contextKind=f.typeKind(ct);s.methodKind=f.typeKind(mt);
  if(![8,17].includes(s.contextKind)||![8,17].includes(s.methodKind))throw new Error('signature');
  s.routeLiteral=(klass,label)=>{
   const field=f.field(klass,Memory.allocUtf8String(label));
   if(field.isNull()||!f.fieldOwner(field).equals(klass)||(f.fieldFlags(field)&80)!==80)throw new Error('signature');
   const t=f.fieldType(field);
   if(t.isNull()||f.byref(t)||![8,17].includes(f.typeKind(t))||!f.classFromType(t).equals(klass))throw new Error('signature');
   const value=Memory.alloc(4);value.writeS32(-2147483648);f.staticFieldValue(field,value);return value.readS32();
  };
  // Named immutable enum literals: never synthesize a context or guess default0.
  n.metadata_checkpoint='model-route-literals';
  s.contextValue=s.routeLiteral(s.contextClass,'MESSAGES');
  s.methodValue=s.routeLiteral(s.methodClass,'LIST_ITEM_CLICK');
  n.metadata_checkpoint='model-route-signature';
  s.openModel=checked(s.routerClass,'ShowChat',1,null,[{kind:18,klass:s.chatModel},
    {kind:s.contextKind,klass:s.contextClass},{kind:s.methodKind,klass:s.methodClass}]);
'''
UTILS=r'''
  const cachedManager=current=>{
   // Revalidate the field's immutable declared contract on every read.
   const t=f.fieldType(s.managerField);
   if(!f.fieldOwner(s.managerField).equals(s.filters)||(f.fieldFlags(s.managerField)&16)!==0||
      f.typeKind(t)!==18||f.byref(t)||!f.classFromType(t).equals(s.manager))fail('signature-mismatch');
   const value=Memory.alloc(Process.pointerSize);value.writePointer(ptr(0));
   f.fieldValue(current,s.managerField,value);const manager=value.readPointer();
   if(manager.isNull()||!f.objectClass(manager).equals(s.manager))fail('identity-not-bound');own(manager);return manager;
  };
  const models=manager=>{const cm=call(s.chats,manager);
   if(cm.isNull()||!f.assignable(s.chatsClass,f.objectClass(cm)))fail('identity-not-bound');own(cm);return cm;};
  const modelAt=(cm,index)=>{const i=Memory.alloc(4);i.writeS32(index);
   const args=Memory.alloc(Process.pointerSize);args.writePointer(i);return call(s.modelItem,cm,args);};
  const stableModels=(current,manager,cm,count,index,chat)=>{
   if(!cachedManager(current).equals(manager))fail('selection-controller-changed');
   if(!models(manager).equals(cm))fail('selection-list-changed');
   if(int32(s.modelCount,cm)!==count)fail('selection-count-changed');
   if(index!==null&&!modelAt(cm,index).equals(chat))fail('selection-chat-changed');
  };
  const headerOrSkip=(chat,who)=>{
   try{return replyHeader(chat,who);}
   catch(error){
    // Only an unverified HEADER of an otherwise verified cached Chat is local.
    // Native exceptions, device/screen changes and base identity errors still stop.
    if(error!=='identity-not-bound')throw error;
    n.private_model_scan.skipped_headers++;return null;
   }
  };
  const scan=(current,candidate)=>{
   n.selection_checkpoint='model-list';const manager=cachedManager(current),cm=models(manager);
   const count=int32(s.modelCount,cm);if(count<0||count>100000)fail('collection-too-large');
   if(state.scanCount!==undefined&&state.scanCount!==count)fail('selection-count-changed');state.scanCount=count;
   if(state.scanIndex===undefined)state.scanIndex=modelOffset;
   if(state.scanIndex>count)fail('selection-count-changed');
   n.private_model_scan.count=count;n.scan_batches++;
   if(state.scanStarted===undefined)state.scanStarted=Date.now();
   for(let batch=0;batch<1&&state.scanIndex<count&&state.scanIndex<modelOffset+64&&(state.scanIndex===modelOffset||Date.now()-state.scanStarted<4000);batch++,state.scanIndex++){
    const opened=scope(()=>{
     if(state.countedIndex!==state.scanIndex){n.rows_scanned++;state.countedIndex=state.scanIndex;}const chat=modelAt(cm,state.scanIndex);if(chat.isNull())return false;own(chat);
     const model=modelIdentity(chat);if(model===null||!permitted(model.who))return false;
     if(!model.manager.equals(manager)||id64(s.accountId,manager)!==model.who.account)fail('identity-not-bound');
     n.selection_checkpoint='unread';let unread=null,header=null;
     if(unreadOnly||needsReplyOnly){unread=unreadCount(chat);if(unreadOnly&&unread===0){n.read_rows_skipped++;return false;}}
     if(needsReplyOnly){
      header=headerOrSkip(chat,model.who);if(header===null)return false;
      if(unread===0&&!header.incoming){n.waiting_rows_skipped++;return false;}
      if(unread===0&&alreadyHandled(model.who,header.id)){n.handled_rows_skipped++;return false;}
     }
     n.selection_checkpoint='model-stability';
     if(!checkView(current))fail('selection-screen-changed');
     if(!resolve(candidate).equals(current))fail('selection-controller-changed');
     stableModels(current,manager,cm,count,state.scanIndex,chat);
     const again=modelIdentity(chat);
     if(again===null||!same(model.who,again.who)||!again.user.equals(model.user)||!again.manager.equals(manager)||!permitted(again.who))fail('identity-changed');
     if(unreadOnly||needsReplyOnly){if(unreadCount(chat)!==unread)fail('selection-unread-changed');}
     if(needsReplyOnly){const fresh=headerOrSkip(chat,model.who);if(fresh===null)return false;
      if(!fresh.last.equals(header.last)||fresh.id!==header.id||fresh.sender!==header.sender||fresh.mine!==header.mine||fresh.chat!==header.chat)fail('selection-last-message-changed');}
     const router=call(s.router,manager);if(router.isNull()||!f.objectClass(router).equals(s.routerClass))fail('identity-not-bound');own(router);
     if(s.routeLiteral(s.contextClass,'MESSAGES')!==s.contextValue||s.routeLiteral(s.methodClass,'LIST_ITEM_CLICK')!==s.methodValue)fail('signature-mismatch');
     const context=Memory.alloc(4),method=Memory.alloc(4);context.writeS32(s.contextValue);method.writeS32(s.methodValue);
     const args=Memory.alloc(Process.pointerSize*3);args.writePointer(chat);args.add(Process.pointerSize).writePointer(context);args.add(Process.pointerSize*2).writePointer(method);
     save('selectedChat',chat);save('selectedUser',model.user);state.selectedIdentity=model.who;
     n.selection_verified=true;n.unread_verified=unreadOnly;n.reply_needed_verified=needsReplyOnly;
     n.selection_checkpoint='open';n.action_attempted=true;call(s.openModel,router,args);
     n.action_completed=true;n.phase='wait-chat';return true;
    });
    if(opened)return;
   }
   if(state.scanIndex>=count||state.scanIndex>=modelOffset+64||
      (state.scanIndex>modelOffset&&Date.now()-state.scanStarted>=4000)){
    // Yield only from a freshly verified list, BEFORE any open action. This is
    // completed read-only work, not a retry after a timeout or an unknown click.
    if(!checkView(current)||!resolve(candidate).equals(current))fail('selection-screen-changed');
    stableModels(current,manager,cm,count,null,null);
    n.private_model_scan.next=state.scanIndex<count?state.scanIndex:null;
    n.exhausted=true;n.selection_checkpoint='exhausted';finish();
   }
  };
'''

def build(*,allowed=(),entry='dialogs',unread_only=False,needs_reply_only=False,offset=0):
 if type(offset) is not int or not 0<=offset<=MAX_MODELS:raise ValueError('Invalid model offset')
 s=browser.build('open',allowed=allowed,entry=entry,unread_only=unread_only,needs_reply_only=needs_reply_only)
 s=replace_once(s,' const operation=', ' const modelOffset='+str(offset)+';\n const operation=')
 s=replace_once(s,'"il2cpp_class_get_parent"]','"il2cpp_class_get_parent",'+','.join(json.dumps(k) for k in EXTRA_APIS)+']')
 s=replace_once(s,'Object.assign(f,{classParent:', 'Object.assign(f,{'+BINDINGS+'classParent:')
 start=s.index("  n.metadata_checkpoint='scroll';");end=s.index("  n.metadata_checkpoint='chat-model';",start)
 s=s[:start]+PREPARE+s[end:]
 s=replace_once(s,"  n.metadata_checkpoint='open-handler';s.openCell=checked(s.filters,'OnCellDidClicked',1,null,[{kind:18,klass:s.chatCell},{kind:18,klass:s.chatModel}]);",'')
 start=s.index('  const cellAt=');end=s.index('  const finish=',start)
 s=s[:start]+s[end:]
 start=s.index('  const scan=(current,candidate)=>');end=s.index('  try {\n   const root=call',start)
 s=s[:start]+UTILS.replace('4000',str(SCAN_MILLISECONDS))+s[end:]
 s=replace_once(s,"phase:'entry',entry_verified:false", "private_model_scan:{next:null,count:0,skipped_headers:0,budget_yields:0},phase:'entry',entry_verified:false")
 # A read-only row may yield to another UI frame, but no action is repeated.
 s=replace_once(s,"} catch(e){\n   if(e==='frame-budget'", """} catch(e){
   if(e==='frame-budget'&&n.phase==='scan'&&n.entry_verified&&n.list_verified&&
      !n.action_attempted&&!n.action_completed&&state.stop===null&&
      !fixedCancellationRequested&&!n.cleanup_failed){
    if(state.budgetIndex!==state.scanIndex){state.budgetIndex=state.scanIndex;state.rowBudgetYields=0;}
    if(state.rowBudgetYields<3&&n.private_model_scan.budget_yields<12){
     state.rowBudgetYields++;n.private_model_scan.budget_yields++;return;
    }
   }
   if(e==='frame-budget'""")
 # The baseline wraps traversal in short handle scopes; preserve the same rule.
 s=s.replace('checkView(current)', 'scope(()=>checkView(current))').replace('resolve(candidate).equals(current)', 'scope(()=>resolve(candidate).equals(current))')
 return s

def validate(raw,*,allowed=(),unread_only=False,needs_reply_only=False,offset=0):
 raw=copy.deepcopy(raw);n=raw.get('navigation',{});scan=n.pop('private_model_scan',None)
 if not isinstance(scan,dict) or set(scan) not in ({'next','count','skipped_headers'},{'next','count','skipped_headers','budget_yields'}):raise ValueError('Invalid model evidence')
 if type(scan['count']) is not int or not 0<=scan['count']<=MAX_MODELS or type(scan['skipped_headers']) is not int or not 0<=scan['skipped_headers']<=SLICE:raise ValueError('Invalid model bounds')
 if type(scan.get('budget_yields',0)) is not int or not 0<=scan.get('budget_yields',0)<=12:raise ValueError('Invalid budget yields')
 nxt=scan['next']
 if nxt is not None and (type(nxt) is not int or not offset<nxt<=offset+SLICE or not nxt<scan['count']):raise ValueError('Invalid model cursor')
 result=browser.validate(raw,'open',allowed=allowed,unread_only=unread_only,needs_reply_only=needs_reply_only)
 if nxt is not None and result['state']!='exhausted':raise ValueError('Cursor on non-exhausted model slice')
 result['diagnostic']['header_rows_skipped']=scan['skipped_headers']
 return result,nxt

def perform(operation,executable,folder,cancelled=lambda:False,*,allowed=(),expected=None,entry='search',unread_only=False,needs_reply_only=False):
 if operation!='open':return browser.perform(operation,executable,folder,cancelled,allowed=allowed,expected=expected,entry=entry,unread_only=unread_only,needs_reply_only=needs_reply_only)
 if expected is not None:raise ValueError('Unexpected model binding')
 from one_chat_device import capture
 from search_online import inspect
 offset=0;skipped=0
 while True:
  if cancelled():raise StateError('cancelled')
  source=build(allowed=allowed,entry=entry,unread_only=unread_only,needs_reply_only=needs_reply_only,offset=offset)
  def validator(raw):return validate(raw,allowed=allowed,unread_only=unread_only,needs_reply_only=needs_reply_only,offset=offset)
  result,nxt=capture(executable,folder,cancelled,inspector=lambda port,token,cancel,binding:inspect(port,token,cancel,source_function=source,validator=validator))
  skipped+=result['diagnostic']['header_rows_skipped'];result['diagnostic']['header_rows_skipped']=skipped
  if nxt is None:return result
  offset=nxt;entry='dialogs'
