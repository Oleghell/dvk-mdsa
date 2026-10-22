"""Fixed journal-filtered visible dialog selection, back, and search return.

No body/name reads, sends, arbitrary methods, taps, scrolling or history exports.
Only validated decimal identities may cross this private transport boundary.
"""
import copy
import json
import re
import dialog_navigation as route
import uikit_navigation as nav
from one_chat_probe import identity
from uikit_profile_navigation import replace_once

VERSION='0.4.7'
MAX_BACK_BUDGET_RETRIES=3
LIMIT=32
MAX_TARGETS=1000
# Fixed categories only: never export object pointers, IDs or text.
SELECTION_ERRORS={'selection-screen-changed','selection-controller-changed','selection-table-changed',
                  'selection-list-changed','selection-count-changed','selection-cell-changed',
                  'selection-chat-changed','selection-detached','selection-unread-changed','selection-last-message-changed'}
ERRORS=nav.ERRORS|SELECTION_ERRORS|{'identity-not-bound','selection-changed','collection-too-large','binding-unavailable','unread-count-invalid'}
KINDS=route.KINDS|{'chat'}
PHASES={'entry','wait-list','scan','wait-chat','wait-back','wait-search','done'}
CHECKPOINTS={'model-route-owner','model-route-parameters','model-route-enums','model-route-literals','model-route-signature','model-manager','model-collection','model-route','not-checked','classes','scroll','visible','count','item','cell-binding','chat-model','unread-count','chat-controller','open-handler','back-handler','ready'}
SELECTION={'model-list','model-stability','not-checked','table','visible','cell','binding','filter','unread','stability','open','verify-chat','back','search','exhausted'}
FLAGS={'cleanup_failed','ui_text_read','entry_verified','list_verified','chat_verified','destination_verified','action_attempted','action_completed','selection_verified','exhausted','unread_filter_applied','unread_verified','reply_filter_applied','reply_needed_verified'}
EXTRAS=FLAGS|{'stage','phase','error','frames','managed_calls','handles_acquired','handles_released','root_top_kind','last_presented_kind','controller_path','action_backend','readiness_check','readiness','view_parent_depth','private_identity','metadata_checkpoint','selection_checkpoint','rows_scanned','scan_batches','read_rows_skipped','back_budget_retries','waiting_rows_skipped','handled_rows_skipped'}


def targets(values):
    if not isinstance(values,(list,tuple)) or len(values)>MAX_TARGETS:raise ValueError('Invalid journal targets')
    out=[];seen=set()
    for value in values:
        if not isinstance(value,dict) or set(value) not in ({'account','peer','chat'},{'account','peer','chat','seen_ids'}):raise ValueError('Invalid target')
        if not isinstance(value['chat'],str) or not re.fullmatch(r'0|[1-9][0-9]{0,18}|-[1-9][0-9]{0,18}',value['chat']) or not -(2**63)<=int(value['chat'])<2**63:raise ValueError('Invalid initial chat')
        checked=identity(dict(account=value['account'],peer=value['peer'],chat=value['chat'] if int(value['chat'])>0 else '1'))
        checked['chat']=value['chat']
        if 'seen_ids' in value:
            ids=value['seen_ids']
            if not isinstance(ids,list) or len(ids)>20 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise ValueError('Invalid observed IDs')
            for message in ids:identity(dict(account=checked['account'],peer=checked['peer'],chat=message))
            checked['seen_ids']=list(ids)
        key=(checked['account'],checked['peer'])
        if key in seen:raise ValueError('Ambiguous target')
        seen.add(key);out.append(checked)
    return out


PREPARE=r'''
 function dialogSignature(f,e,m){
  if(m.isNull()||f.arity(m)!==e.arity)return false;
  const bits=Memory.alloc(4);bits.writeU32(0);const owner=f.methodClass(m),t=f.returnType(m);
  if(owner.isNull()||!f.assignable(owner,e.klass)||(f.flags(m,bits)&(16|1024))!==0||t.isNull()||f.typeKind(t)!==e.kind)return false;
  if(!!f.byref(t)!==e.byref||e.byref&&!e.allowRef)return false;
  if(e.result&&!f.classFromType(t).equals(e.result))return false;
  for(let i=0;i<e.params.length;i++){
   const p=f.param(m,i),spec=e.params[i];
   if(p.isNull()||f.byref(p)||f.typeKind(p)!==spec.kind||spec.klass&&!f.classFromType(p).equals(spec.klass))return false;
  }
  return true;
 }
 function prepareDialogBrowser(f,s,getClass){
  const n=r.navigation;n.metadata_checkpoint='classes';
  const defs={chatController:['DV.Messages.dll','DV.Messages','MessagesViewController'],chatCell:['DV.Messages.dll','DV.Messages','ChatCell'],
   chatModel:['DV.Messages.dll','DV.Messages','Chat'],manager:['DV.Messages.dll','DV.Messages','MessagesManager'],
   user:['DV.dll','DV.Models','User'],table:['Core.dll','UIKit','TableView'],tableCell:['Core.dll','UIKit','TableCell'],scrollView:['Core.dll','UIKit','ScrollView']};
  for(const [key,args] of Object.entries(defs)){s[key]=getClass(...args);if(s[key].isNull()||f.isValueType(s[key]))throw new Error('metadata');}
  if(!f.assignable(s.vc,s.chatController)||!f.assignable(s.tableCell,s.chatCell)||!f.assignable(s.view,s.tableCell)||!f.assignable(s.scrollView,s.table))throw new Error('hierarchy');
  const checked=(klass,label,kind,result=null,params=[],allowRef=false)=>{
   const m=f.method(klass,Memory.allocUtf8String(label),params.length);
   if(m.isNull())throw new Error('signature');
   const e={m,klass,kind,result,params,arity:params.length,dialogChecked:true,allowRef,byref:!!f.byref(f.returnType(m))};
   // Confirm the declared owner really is in the receiver's ancestry. No raw
   // generic pointer reinterpretation or unknown inherited getter invocation.
   let cur=klass,found=false;const seen=new Set();const owner=f.methodClass(m);
   for(let i=0;i<12&&!cur.isNull();i++){const k=cur.toString();if(seen.has(k))throw new Error('hierarchy');seen.add(k);if(cur.equals(owner)){found=true;break;}cur=f.classParent(cur);}
   if(!found||!dialogSignature(f,e,m))throw new Error('signature');return e;
  };
  n.metadata_checkpoint='scroll';s.listScroll=checked(s.filters,'get_ScrollView',18,s.scrollView);
  n.metadata_checkpoint='visible';s.visible=checked(s.table,'get_VisibleCells',21);s.visibleClass=f.classFromType(f.returnType(s.visible.m));
  if(s.visibleClass.isNull()||f.isValueType(s.visibleClass))throw new Error('signature');
  // CoreList<T> is the same collection used by the verified profile selector.
  const ascii=p=>{if(p.isNull())return '';let out='';for(let i=0;i<96;i++){const c=p.add(i).readU8();if(c===0)return out;if(c<32||c>126)throw new Error('signature');out+=String.fromCharCode(c);}throw new Error('signature');};
  if(ascii(f.className(s.visibleClass))!=='CoreList`1'||ascii(f.classNamespace(s.visibleClass))!=='Core.Collections'||ascii(f.imageName(f.classImage(s.visibleClass)))!=='Core.dll')throw new Error('signature');
  n.metadata_checkpoint='count';s.visibleCount=checked(s.visibleClass,'get_Count',8);
  n.metadata_checkpoint='item';s.visibleItem=checked(s.visibleClass,'get_Item',18,s.tableCell,[{kind:8}],true);
  n.metadata_checkpoint='cell-binding';s.cellChat=checked(s.chatCell,'get_Item',18,s.chatModel);
  n.metadata_checkpoint='chat-model';s.opponent=checked(s.chatModel,'get_DialogOpponent',18,s.user);s.isDialog=checked(s.chatModel,'get_Dialog',2);
  s.actual=checked(s.chatModel,'get_IsActual',2);s.draft=checked(s.chatModel,'get_IsDraftChat',2);
  s.chatManager=checked(s.chatModel,'get_MessagesManager',18,s.manager);s.accountId=checked(s.manager,'get_CurrentUserId',10);
  s.peerId=checked(s.user,'get_Id',10);s.chatId=checked(s.chatModel,'get_Id',10);
  // Exact definition from the pinned offline catalogue: Chat.get_UnreadCount,
  // zero-argument instance Int32. Never infer unread from body/order/last sender.
  if((unreadOnly||needsReplyOnly)&&operation==='open'){
   n.metadata_checkpoint='unread-count';s.unreadCount=checked(s.chatModel,'get_UnreadCount',8);
   n.unread_filter_applied=unreadOnly;
  }
  if(needsReplyOnly&&operation==='open'){
   s.lastMessageClass=getClass('DV.Messages.dll','DV.Messages','Message');
   if(s.lastMessageClass.isNull()||f.isValueType(s.lastMessageClass))throw new Error('metadata');
   s.lastMessage=checked(s.chatModel,'get_LastMessage',18,s.lastMessageClass);
   s.lastId=checked(s.lastMessageClass,'get_Id',10);
   s.lastSender=checked(s.lastMessageClass,'get_SenderId',10);
   s.lastChat=checked(s.lastMessageClass,'get_ChatId',10);
   s.lastMine=checked(s.lastMessageClass,'get_IsMine',2);
   n.reply_filter_applied=true;
  }
  n.metadata_checkpoint='chat-controller';s.currentChat=checked(s.chatController,'get_Chat',18,s.chatModel);s.currentUser=checked(s.chatController,'get_User',18,s.user);
  n.metadata_checkpoint='open-handler';s.openCell=checked(s.filters,'OnCellDidClicked',1,null,[{kind:18,klass:s.chatCell},{kind:18,klass:s.chatModel}]);
  n.metadata_checkpoint='back-handler';s.closeChat=checked(s.chatController,'DV.Messages.BottomBarView.IDelegate.OnBackButton',1);
  n.metadata_checkpoint='ready';
 }
'''
UTILS=r'''
  const save=(key,obj)=>{if(state[key]&&!state[key].isNull())fail('identity-changed');state[key]=own(obj);held.splice(held.indexOf(state[key]),1);};
  // Release temporary traversal handles before the next independent check.
  // A returned controller needs its own handle before traversal roots are freed.
  const scope=(body,retainResult=false)=>{
   const start=held.length;let retained=null;
   try{
    const result=body();
    if(retainResult&&!result.isNull()){retained=own(result);held.splice(held.indexOf(retained),1);}
    return result;
   }finally{
    while(held.length>start){const h=held.pop();try{f.release(h);n.handles_released++;}catch(_){n.cleanup_failed=true;}}
    if(retained!==null)held.push(retained);
   }
  };
  const int32=(entry,obj)=>{const box=call(entry,obj);if(box.isNull())fail('signature-mismatch');const p=f.unbox(box);if(p.isNull())fail('signature-mismatch');return p.readS32();};
  const unreadCount=chat=>{
   const value=int32(s.unreadCount,chat);if(value<0)fail('unread-count-invalid');return value;
  };
  const id64=(entry,obj)=>{const box=call(entry,obj);if(box.isNull())fail('identity-not-bound');const p=f.unbox(box);if(p.isNull())fail('identity-not-bound');const v=p.readS64();if(v.compare(0)<=0)fail('identity-not-bound');return v.toString();};
  // Headers only; never read a message body from the dialog list.
  const replyHeader=(chat,who)=>{
   const last=call(s.lastMessage,chat);if(last.isNull())return {last,id:null,incoming:false};
   own(last);if(!f.assignable(s.lastMessageClass,f.objectClass(last)))fail('identity-not-bound');
   const id=id64(s.lastId,last),sender=id64(s.lastSender,last),mine=bool(s.lastMine,last);
   const box=call(s.lastChat,last);if(box.isNull())fail('identity-not-bound');
   const scalar=f.unbox(box);if(scalar.isNull())fail('identity-not-bound');
   const chatId=scalar.readS64();
   if(chatId.compare(0)===0||chatId.compare(0)>0&&chatId.toString()!==who.chat||
      mine&&sender!==who.account||!mine&&sender!==who.peer||!mine&&chatId.compare(0)<0)fail('identity-not-bound');
   return {last,id,sender,mine,chat:chatId.toString(),incoming:!mine};
  };
  const alreadyHandled=(who,id)=>allowedTargets.some(x=>x.account===who.account&&x.peer===who.peer&&
    (new Int64(x.chat).compare(0)<=0||x.chat===who.chat)&&(x.seen_ids||[]).includes(id));
  const modelIdentity=chat=>{
   if(chat.isNull()||!f.objectClass(chat).equals(s.chatModel))fail('identity-not-bound');
   if(!bool(s.isDialog,chat)||!bool(s.actual,chat)||bool(s.draft,chat))return null;
   const user=call(s.opponent,chat);if(user.isNull())return null;own(user);if(!f.objectClass(user).equals(s.user))fail('identity-not-bound');
   const manager=call(s.chatManager,chat);if(manager.isNull()||!f.objectClass(manager).equals(s.manager))fail('identity-not-bound');own(manager);
   const who={account:id64(s.accountId,manager),peer:id64(s.peerId,user),chat:id64(s.chatId,chat)};
   if(who.account===who.peer)return null;return {who,user,manager};
  };
  const permitted=who=>allowedTargets.some(x=>x.account===who.account&&x.peer===who.peer&&(new Int64(x.chat).compare(0)<=0||x.chat===who.chat));
  const same=(a,b)=>a!==null&&b!==null&&a.account===b.account&&a.peer===b.peer&&a.chat===b.chat;
  const currentIdentity=current=>{
   const chat=call(s.currentChat,current);if(chat.isNull())fail('identity-not-bound');own(chat);
   const model=modelIdentity(chat);if(model===null)fail('identity-not-bound');
   if(!call(s.currentUser,current).equals(model.user))fail('identity-changed');return {chat,...model};
  };
  const attached=(view,required)=>scope(()=>{
   if(view.isNull()||!f.assignable(s.view,f.objectClass(view)))fail('unexpected-object');own(view);
   if(bool(s.hidden,view)||!bool(s.interactive,view))return false;
   let seenRequired=false,cur=view;const seen=new Set();
   for(let i=0;i<32;i++){
    const key=cur.toString();if(seen.has(key))fail('view-parent-cycle');seen.add(key);
    if(cur.equals(required))seenRequired=true;if(cur.equals(window))return seenRequired;
    cur=call(s.parent,cur);if(cur.isNull())return false;own(cur);
   }
   fail('view-parent-depth-limit');
  });
  const cellAt=(list,index)=>{const i=Memory.alloc(4);i.writeS32(index);const args=Memory.alloc(Process.pointerSize);args.writePointer(i);return call(s.visibleItem,list,args);};
  const stableList=(table,count,index,cell)=>{
   const list=call(s.visible,table);
   if(list.isNull()||!f.objectClass(list).equals(s.visibleClass))fail('selection-list-changed');
   own(list);
   if(int32(s.visibleCount,list)!==count)fail('selection-count-changed');
   if(index!==null&&cell!==null&&!cellAt(list,index).equals(cell))fail('selection-cell-changed');
   return list;
  };
  const finish=()=>{n.destination_verified=true;n.phase='done';n.stage='navigation-ready';};
  const scan=(current,candidate)=>{
   n.selection_checkpoint='table';const table=call(s.listScroll,current);if(table.isNull()||!f.assignable(s.table,f.objectClass(table)))fail('unexpected-object');own(table);
   const view=call(s.viewOf,current);if(view.isNull())fail('unexpected-object');own(view);if(!attached(table,view))fail('screen-not-ready');
   n.selection_checkpoint='visible';const list=call(s.visible,table);if(list.isNull()||!f.objectClass(list).equals(s.visibleClass))fail('unexpected-object');own(list);
   const count=int32(s.visibleCount,list);if(count<0||count>128)fail('collection-too-large');
   if(state.scanCount!==undefined&&state.scanCount!==count)fail('selection-count-changed');state.scanCount=count;
   if(state.scanIndex===undefined)state.scanIndex=0;
   n.scan_batches++;
   for(let batch=0;batch<(needsReplyOnly?2:4)&&state.scanIndex<count;batch++,state.scanIndex++){
    const opened=scope(()=>{
     n.rows_scanned++;n.selection_checkpoint='cell';
     const cell=cellAt(list,state.scanIndex);if(cell.isNull()||!f.assignable(s.tableCell,f.objectClass(cell)))fail('unexpected-object');own(cell);
     if(!f.assignable(s.chatCell,f.objectClass(cell)))return false;
     if(!attached(cell,table))return false;
     n.selection_checkpoint='binding';const chat=call(s.cellChat,cell);if(chat.isNull())return false;own(chat);
     const model=modelIdentity(chat);if(model===null)return false;
     n.selection_checkpoint='filter';if(!permitted(model.who))return false;
     let unread=null,header=null;
     if(unreadOnly||needsReplyOnly){
      n.selection_checkpoint='unread';unread=unreadCount(chat);
      if(unreadOnly&&unread===0){n.read_rows_skipped++;return false;}
     }
     if(needsReplyOnly){
      header=replyHeader(chat,model.who);
      if(unread===0&&!header.incoming){n.waiting_rows_skipped++;return false;}
      if(unread===0&&alreadyHandled(model.who,header.id)){n.handled_rows_skipped++;return false;}
     }
     n.selection_checkpoint='stability';
     // Preserve every original guard and its order; only explain WHICH one failed.
     if(!checkView(current))fail('selection-screen-changed');
     if(!resolve(candidate).equals(current))fail('selection-controller-changed');
     if(!call(s.listScroll,current).equals(table))fail('selection-table-changed');
     stableList(table,count,state.scanIndex,cell);
     if(!call(s.cellChat,cell).equals(chat))fail('selection-chat-changed');
     if(!attached(cell,table))fail('selection-detached');
     const again=modelIdentity(chat);if(again===null||!same(model.who,again.who)||!again.user.equals(model.user)||!permitted(again.who))fail('identity-changed');
     // Re-read after the complete identity/table/attachment stability checks.
     // A concurrent read or any count change cancels selection before the click.
     if(unreadOnly||needsReplyOnly){
      n.selection_checkpoint='unread';
      if(unreadCount(chat)!==unread)fail('selection-unread-changed');
      n.unread_verified=unreadOnly;
     }
     if(needsReplyOnly){
      const fresh=replyHeader(chat,model.who);
      if(!fresh.last.equals(header.last)||fresh.id!==header.id||fresh.sender!==header.sender||
         fresh.mine!==header.mine||fresh.chat!==header.chat)fail('selection-last-message-changed');
      n.reply_needed_verified=true;
     }
     save('selectedChat',chat);save('selectedUser',model.user);state.selectedIdentity=model.who;
     const args=Memory.alloc(Process.pointerSize*2);args.writePointer(cell);args.add(Process.pointerSize).writePointer(chat);
     n.selection_verified=true;n.selection_checkpoint='open';n.action_attempted=true;
     call(s.openCell,current,args);n.action_completed=true;n.phase='wait-chat';return true;
    });
    if(opened)return;
   }
   if(state.scanIndex>=count){
    if(!call(s.listScroll,current).equals(table))fail('selection-table-changed');
    stableList(table,count,null,null);
    n.exhausted=true;n.selection_checkpoint='exhausted';finish();
   }
  };
'''
TICK=r'''
   if(!checkView(current))return;
   if(n.phase==='entry'){
    const required=operation==='back'?'chat':operation==='return'?'dialogs':entryScreen;
    if(required==='either'?(k!=='search'&&k!=='dialogs'):k!==required)fail('wrong-screen');n.entry_verified=true;
    if(operation==='list'&&k==='dialogs'){n.list_verified=true;finish();return;}
    if(operation==='return'){
     n.list_verified=true;n.selection_checkpoint='search';n.action_attempted=true;switchTab(s.search);n.action_completed=true;n.phase='wait-search';return;
    }
    if(operation==='back'){
     const bound=currentIdentity(current);if(!same(bound.who,expectedIdentity))fail('identity-not-bound');
     if(!checkView(current)||!resolve(candidate).equals(current)||!same(currentIdentity(current).who,expectedIdentity))fail('identity-changed');
     n.chat_verified=true;n.private_identity=bound.who;n.selection_checkpoint='back';n.action_attempted=true;
     call(s.closeChat,current);n.action_completed=true;n.phase='wait-back';return;
    }
    if(k==='search'){
     n.action_attempted=true;switchTab(s.messageTab);n.action_completed=true;n.phase='wait-list';return;
    }
    n.list_verified=true;n.phase='scan';return;
   }
   if(n.phase==='wait-list'){
    if(k==='search')return;if(k!=='dialogs')fail('unexpected-screen');n.list_verified=true;
    if(operation==='list'){finish();return;}n.phase='scan';return;
   }
   if(n.phase==='scan'){
    if(k!=='dialogs')fail('unexpected-screen');scan(current,candidate);return;
   }
   if(n.phase==='wait-chat'){
    if(k==='dialogs')return;if(k!=='chat')fail('unexpected-screen');
    n.selection_checkpoint='verify-chat';const bound=currentIdentity(current);
    if(!bound.chat.equals(target(state.selectedChat))||!bound.user.equals(target(state.selectedUser))||!same(bound.who,state.selectedIdentity)||!permitted(bound.who))fail('identity-changed');
    if(!checkView(current)||!resolve(candidate).equals(current)||!same(currentIdentity(current).who,state.selectedIdentity))fail('identity-changed');
    n.chat_verified=true;n.private_identity=bound.who;finish();return;
   }
   if(n.phase==='wait-back'){
    if(k==='chat'){if(!same(currentIdentity(current).who,expectedIdentity))fail('identity-changed');return;}
    if(k!=='dialogs')fail('unexpected-screen');n.list_verified=true;finish();return;
   }
   if(n.phase==='wait-search'){
    if(k==='dialogs')return;if(k!=='search')fail('unexpected-screen');finish();return;
   }
'''


def build(operation, *, allowed=(), expected=None, entry='search', unread_only=False, needs_reply_only=False):
    if operation not in ('open','back','return','list') or entry not in ('search','dialogs','either') or (entry=='either' and operation!='list'):raise ValueError('Invalid fixed operation')
    if type(unread_only) is not bool or (unread_only and operation!='open'):raise ValueError('Invalid unread filter')
    if type(needs_reply_only) is not bool or (needs_reply_only and operation!='open'):raise ValueError('Invalid reply filter')
    allowed=targets(allowed);expected=identity(expected) if expected is not None else None
    if (operation=='back')!=(expected is not None) or (operation!='open' and allowed):raise ValueError('Invalid operation binding')
    s=route.FUNCTION
    s=replace_once(s,'function probeUIKitRoot() {','function probeUIKitRoot() {\n const operation='+json.dumps(operation)+',entryScreen='+json.dumps(entry)+',allowedTargets='+json.dumps(allowed)+',expectedIdentity='+json.dumps(expected)+',unreadOnly='+json.dumps(unread_only)+',needsReplyOnly='+json.dumps(needs_reply_only)+';')
    s=replace_once(s,' function prepareNavigation(',PREPARE+'\n function prepareNavigation(')
    s=replace_once(s,'prepareDialogRoute(f,setup.navigation,getClass);','prepareDialogRoute(f,setup.navigation,getClass);prepareDialogBrowser(f,setup.navigation,getClass);')
    s=replace_once(s,'r.navigation=emptyNavigation();','r.navigation=emptyNavigation();'+'''Object.assign(r.navigation,{phase:'entry',entry_verified:false,list_verified:false,chat_verified:false,destination_verified:false,action_attempted:false,action_completed:false,selection_verified:false,exhausted:false,private_identity:null,metadata_checkpoint:'not-checked',selection_checkpoint:'not-checked',rows_scanned:0,scan_batches:0,read_rows_skipped:0,back_budget_retries:0,unread_filter_applied:false,unread_verified:false,reply_filter_applied:false,reply_needed_verified:false,waiting_rows_skipped:0,handled_rows_skipped:0});
 for(const k of ['search_verified','dialogs_verified','return_verified','open_attempted','open_completed','back_attempted','back_completed'])delete r.navigation[k];''')
    s=replace_once(s,'"il2cpp_type_get_object"]','"il2cpp_type_get_object","il2cpp_class_get_parent"]')
    s=replace_once(s,"Object.assign(f,{classType:","Object.assign(f,{classParent:bind('class_get_parent','pointer',['pointer']),classType:")
    s=replace_once(s,'   let m=entry.m;',"   if(entry.dialogChecked&&!dialogSignature(f,entry,entry.m))fail('signature-mismatch');\n   let m=entry.m;")
    s=replace_once(s,'   if(entry.arity===1)',"   if(entry.dialogChecked&&!dialogSignature(f,entry,m))fail('signature-mismatch');\n   if(entry.arity===1&&!entry.dialogChecked)")
    # The baseline forbids ref returns. Only the exact typed CoreList indexer
    # opts into runtime_invoke's already-tested ref-to-reference normalization.
    s=replace_once(s,"||f.byref(f.returnType(m)))fail('signature-mismatch');", "||!!f.byref(f.returnType(m))!==!!entry.byref)fail('signature-mismatch');")
    s=replace_once(s,"   if(klass.equals(s.messageTab))", "   if(klass.equals(s.chatController))return 'chat';\n   if(klass.equals(s.messageTab))")
    s=replace_once(s,"if(k==='search'||k==='dialogs'){", "if(k==='search'||k==='dialogs'||k==='chat'){")
    s=s.replace("n.phase==='search'?'wrong-screen'", "n.phase==='entry'?'wrong-screen'")
    s=replace_once(s,'  try {\n   const root=call',UTILS+'  try {\n   const root=call')
    s=replace_once(s,'const current=resolve(candidate);if(current.isNull())return;',
                   'const current=scope(()=>resolve(candidate),true);if(current.isNull())return;')

    start=s.index("   if(n.phase==='search'&&k!=='search')")
    end=s.index('\n  } catch(e)',start)
    s=s[:start]+TICK+s[end:]
    # A slow frame AFTER the one verified back handler may be retried only as
    # observation. wait-back has no action calls and is never reset to entry.
    # Keep the baseline 100 ms/frame, total call/frame/time limits and cleanup.
    s=replace_once(s, "} catch(e){n.error=", """} catch(e){
   if(e==='frame-budget'&&operation==='back'&&n.phase==='wait-back'&&
      n.entry_verified&&n.chat_verified&&n.action_attempted&&n.action_completed&&
      same(n.private_identity,expectedIdentity)&&state.stop===null&&
      !fixedCancellationRequested&&!n.cleanup_failed&&n.back_budget_retries<"""+str(MAX_BACK_BUDGET_RETRIES)+"""){
    n.back_budget_retries++;return;
   }
   n.error=""")
    s=s.replace('checkView(current)', 'scope(()=>checkView(current))')
    s=s.replace('resolve(candidate).equals(current)', 'scope(()=>resolve(candidate).equals(current))')
    s=replace_once(s,"['card','origin','tabs']", "['card','origin','tabs','selectedChat','selectedUser']")
    s=replace_once(s,json.dumps(sorted(nav.ERRORS)),json.dumps(sorted(ERRORS)))
    return s


def validate(value,operation, *, allowed=(), expected=None, unread_only=False, needs_reply_only=False):
    if operation not in ('open','back','return','list'):raise ValueError('Invalid fixed operation')
    if type(unread_only) is not bool or (unread_only and operation!='open'):raise ValueError('Invalid unread filter')
    if type(needs_reply_only) is not bool or (needs_reply_only and operation!='open'):raise ValueError('Invalid reply filter')
    allowed=targets(allowed);expected=identity(expected) if expected is not None else None
    if (operation=='back')!=(expected is not None) or (operation!='open' and allowed):raise ValueError('Invalid operation binding')
    if not isinstance(value,dict) or not isinstance(value.get('navigation'),dict):raise ValueError('Missing dialog evidence')
    n=value['navigation']
    if set(n)!=EXTRAS or n['phase'] not in PHASES or n['error'] not in ERRORS:raise ValueError('Invalid dialog evidence')
    if any(type(n[k]) is not bool for k in FLAGS) or n['ui_text_read']:raise ValueError('Invalid flags')
    if n['metadata_checkpoint'] not in CHECKPOINTS or n['selection_checkpoint'] not in SELECTION:raise ValueError('Invalid checkpoint')
    for k,limit in [('rows_scanned',128),('scan_batches',180),('read_rows_skipped',128),('waiting_rows_skipped',128),('handled_rows_skipped',128),('back_budget_retries',MAX_BACK_BUDGET_RETRIES)]:
        if type(n[k]) is not int or not 0<=n[k]<=limit:raise ValueError('Invalid scan bounds')
    if n['back_budget_retries'] and (operation!='back' or n['phase'] not in ('wait-back','done') or not n['chat_verified'] or not n['action_completed']):raise ValueError('Invalid back recovery evidence')
    if n['read_rows_skipped']>n['rows_scanned']:raise ValueError('Invalid skipped rows')
    if not unread_only and (n['unread_filter_applied'] or n['unread_verified'] or n['read_rows_skipped']):raise ValueError('Unexpected unread evidence')
    if not needs_reply_only and (n['reply_filter_applied'] or n['reply_needed_verified'] or n['waiting_rows_skipped'] or n['handled_rows_skipped']):raise ValueError('Unexpected reply evidence')
    if n['waiting_rows_skipped']+n['handled_rows_skipped']>n['rows_scanned']:raise ValueError('Invalid reply skipped count')
    if n['reply_needed_verified'] and (not n['reply_filter_applied'] or not n['selection_verified']):raise ValueError('Invalid reply evidence')
    if n['unread_verified'] and (not n['unread_filter_applied'] or not n['selection_verified']):raise ValueError('Invalid unread evidence')
    if n['action_completed'] and not n['action_attempted']:raise ValueError('Action without attempt')
    if n['action_attempted'] and not n['entry_verified']:raise ValueError('Action without entry')
    if n['selection_verified'] and (operation!='open' or not n['list_verified']):raise ValueError('Invalid selection')
    if n['exhausted'] and (operation!='open' or n['selection_verified'] or not n['list_verified']):raise ValueError('Invalid exhaustion')
    private=identity(n['private_identity']) if n['private_identity'] is not None else None
    ready=n['stage']=='navigation-ready'
    if ready!=n['destination_verified']:raise ValueError('Invalid destination')
    if ready:
        if not n['entry_verified'] or n['metadata_checkpoint']!='ready':raise ValueError('Incomplete operation')
        if operation=='open':
            if needs_reply_only and (not n['reply_filter_applied'] or n['reply_needed_verified']==n['exhausted']):raise ValueError('Missing reply evidence')
            if unread_only and (not n['unread_filter_applied'] or n['unread_verified']==n['exhausted']):raise ValueError('Missing unread evidence')
            if n['exhausted']:
                if private is not None or n['chat_verified']:raise ValueError('Identity on exhaustion')
            elif not (n['selection_verified'] and n['chat_verified'] and n['action_completed'] and private is not None):raise ValueError('Missing opened binding')
        elif operation=='list':
            if (not n['list_verified'] or n['chat_verified'] or private is not None
                    or n['rows_scanned'] or n['scan_batches'] or n['selection_verified']
                    or n['selection_checkpoint']!='not-checked' or n['action_attempted']!=n['action_completed']):
                raise ValueError('Invalid dialog-list evidence')
        elif not n['action_completed'] or (operation=='back' and (not n['chat_verified'] or not n['list_verified'] or private!=expected)) or (operation=='return' and (not n['list_verified'] or private is not None)):
            raise ValueError('Missing return evidence')
    if private is not None:
        if operation=='open' and not any(x['account']==private['account'] and x['peer']==private['peer'] and (int(x['chat'])<=0 or x['chat']==private['chat']) for x in allowed):raise ValueError('Untracked private binding')
        if operation=='back' and private!=expected:raise ValueError('Different back binding')
        if operation in ('return','list') or not n['chat_verified']:raise ValueError('Unexpected identity')
    # Reuse the verified thread/root/handle/modal/readiness validator without
    # pretending our actual flags describe a search/filter/cancel operation.
    base=copy.deepcopy(value);bn=base['navigation']
    common={'cleanup_failed','ui_text_read','stage','phase','error','frames','managed_calls','handles_acquired','handles_released','root_top_kind','last_presented_kind','controller_path','action_backend','readiness_check','readiness','view_parent_depth'}
    for key in set(bn)-common:bn.pop(key)
    bn['phase']='done' if ready else 'search'
    for flag in ('search_verified','filters_verified','return_verified','open_attempted','open_completed','cancel_attempted','cancel_completed'):bn[flag]=ready
    def old(k):
        if k not in KINDS:raise ValueError('Invalid screen category')
        return {'dialogs':'filters','chat':'filters','messages-tab':'dv-container'}.get(k,k)
    for key in ('root_top_kind','last_presented_kind'):bn[key]=old(bn[key])
    if not isinstance(bn['controller_path'],list):raise ValueError('Invalid controller path')
    bn['controller_path']=[old(k) for k in bn['controller_path']]
    nav.validate(base,errors=ERRORS)
    diagnostic={k:n[k] for k in ('stage','error','phase','metadata_checkpoint','selection_checkpoint','rows_scanned','scan_batches','action_attempted','action_completed','destination_verified','unread_filter_applied','unread_verified','read_rows_skipped','back_budget_retries','reply_filter_applied','reply_needed_verified','waiting_rows_skipped','handled_rows_skipped')}
    return dict(state=('exhausted' if n['exhausted'] else 'opened' if operation=='open' else 'returned' if operation=='back' else 'dialogs-ready' if operation=='list' else 'search-ready') if ready else 'stopped',identity=private,diagnostic=diagnostic)


def perform(operation,executable,folder,cancelled=lambda:False, *, allowed=(),expected=None,entry='search',unread_only=False, needs_reply_only=False):
    from one_chat_device import capture
    from search_online import inspect
    from startup_failure import checkpoint
    with checkpoint('navigation-source'):
        source=build(operation,allowed=allowed,expected=expected,entry=entry,unread_only=unread_only,needs_reply_only=needs_reply_only)
    def checked(result):
        try:
            return validate(result,operation,allowed=allowed,expected=expected,unread_only=unread_only,needs_reply_only=needs_reply_only)
        except Exception as error:
            # A rejected result never becomes a usable result. Preserve ONLY the
            # independently validated public diagnostic; discard all raw RPC data.
            from assistant_navigation_check import safe_diagnostic
            keys=('stage','error','phase','metadata_checkpoint','selection_checkpoint',
                  'rows_scanned','scan_batches','action_attempted','action_completed',
                  'destination_verified','unread_filter_applied','unread_verified',
                  'read_rows_skipped','back_budget_retries','reply_filter_applied',
                  'reply_needed_verified','waiting_rows_skipped','handled_rows_skipped')
            try:
                public=safe_diagnostic({k:result['navigation'][k] for k in keys})
            except Exception:
                pass
            else:
                error._dvk_navigation=public
            raise
    def inspector(port,token,cancel,binding):
        return inspect(port,token,cancel,source_function=source,validator=checked)
    return capture(executable,folder,cancelled,inspector=inspector)
