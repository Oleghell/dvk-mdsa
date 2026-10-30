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

VERSION='0.4.10'
MAX_BACK_BUDGET_RETRIES=3
MAX_OBSERVATION_BUDGET_RETRIES=3
MAX_ENTRY_READ_BUDGET_RETRIES=3
# Reports 486/488 (v1.3.72): a cold-restoring app presents the chat controller
# with its view already attached while the chat MODEL is still loading (the
# failing startups observed only 3-16 frames). The startup list recovery
# demanded a fully bound chat on the very first frame and stopped the port
# with identity-not-bound. The binding there is read-only and precedes every
# action, so a bounded frame wait replaces the instant fail; structural
# identity failures stay fatal, and an exhausted wait still fails closed -
# but with its own closed code (v1.3.80, reports QZ2X7 ports 525/527: a
# cold-restoring app left the chat model unbound past the whole wait on two
# ports, the shared identity-not-bound label matched the recovery BLOCK set
# and both ports stayed dead instead of recovering). entry-binding-timeout
# is a readiness outcome: the recovery supervisor retries it like
# wrong-screen, while every structural identity mismatch keeps the fatal
# identity-not-bound code.
MAX_ENTRY_BINDING_WAITS=25
LIMIT=32
MAX_TARGETS=1000
# Fixed categories only: never export object pointers, IDs or text.
SELECTION_ERRORS={'selection-screen-changed','selection-controller-changed','selection-table-changed',
                  'selection-list-changed','selection-count-changed','selection-cell-changed',
                  'selection-chat-changed','selection-detached','selection-unread-changed','selection-last-message-changed'}
ERRORS=nav.ERRORS|SELECTION_ERRORS|{'identity-not-bound','entry-binding-timeout','selection-changed','collection-too-large','binding-unavailable','unread-count-invalid'}
KINDS=route.KINDS|{'chat','profile'}
PHASES={'entry','wait-list','scan','wait-chat','wait-back','wait-search','done'}
CHECKPOINTS={'model-route-owner','model-route-parameters','model-route-enums','model-route-literals','model-route-signature','model-manager','model-collection','model-route','not-checked','classes','scroll','visible','count','item','cell-binding','chat-model','unread-count','chat-controller','open-handler','back-handler','profile-queue','profile-close','ready'}
SELECTION={'model-list','model-stability','not-checked','table','visible','cell','binding','filter','unread','stability','open','verify-chat','back','search','exhausted'}
FLAGS={'cleanup_failed','ui_text_read','entry_verified','list_verified','chat_verified','destination_verified','action_attempted','action_completed','selection_verified','exhausted','unread_filter_applied','unread_verified','reply_filter_applied','reply_needed_verified','entry_search_recovered','profile_closed'}
EXTRAS=FLAGS|{'stage','phase','error','frames','managed_calls','handles_acquired','handles_released','root_top_kind','last_presented_kind','controller_path','action_backend','readiness_check','readiness','view_parent_depth','private_identity','metadata_checkpoint','selection_checkpoint','rows_scanned','scan_batches','read_rows_skipped','back_budget_retries','observation_budget_retries','entry_read_budget_retries','entry_binding_waits','entry_search_recovered','waiting_rows_skipped','handled_rows_skipped','selected_message'}


MAX_HIDDEN_PEERS=2000


def hidden_peers(values):
    """v1.3.88: rows the native scan must refuse to open, even in adoption mode.

    Deny-only host data: exact (account, peer) pairs hide one own chat, the
    '*' account hides a peer under every account (the manual deny registry is
    peer-scoped). Never a permit, never a target: a hidden peer stays out of
    allowedTargets and is skipped by permitted() BEFORE the adoption arm.
    """
    if not isinstance(values,(list,tuple)) or len(values)>MAX_HIDDEN_PEERS:raise ValueError('Invalid hidden peers')
    out=[];seen=set()
    for value in values:
        if not isinstance(value,dict) or set(value)!={'account','peer'}:raise ValueError('Invalid hidden peer')
        account,peer=value['account'],value['peer']
        def decimal(text):
            return isinstance(text,str) and re.fullmatch(r'[1-9][0-9]{0,18}',text) is not None \
                and (len(text)<19 or text<='9223372036854775807')
        if (account!='*' and not decimal(account)) or not decimal(peer):raise ValueError('Invalid hidden peer')
        key=(account,peer)
        if key in seen:raise ValueError('Ambiguous hidden peer')
        seen.add(key);out.append(dict(account=account,peer=peer))
    return out


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
            if not isinstance(ids,list) or len(ids)>128 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise ValueError('Invalid observed IDs')
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
  // The assistant opens chats ON TOP of a profile card, so closing a stuck
  // chat legitimately lands on the profile screen. The profile queue and its
  // verified close handler (the same OnCloseRequested the profile navigation
  // itself uses) let the fixed list/back flows perform the bounded Esc press
  // a human would: close the profile once, then continue to the list.
  n.metadata_checkpoint='profile-queue';s.profileQueue=getClass('DV.Profile.dll','DV.Profiles','ProfilesQueueViewController');
  if(s.profileQueue.isNull()||f.isValueType(s.profileQueue)||!f.assignable(s.vc,s.profileQueue))throw new Error('metadata');
  n.metadata_checkpoint='profile-close';s.closeProfile=checked(s.profileQueue,'DV.Profiles.ProfileViewController.IDelegate.OnCloseRequested',1);
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
  // v1.3.88: deliberately EXCLUDED peers (manual /num silences, manual blocks,
  // active history cooldowns, run-scoped reply exclusions) must never be opened
  // by the adoption filter either - that open -> verified Back -> next pass
  // cycle was the reported reopen loop. '*' as the account hides the peer under
  // every account (the manual deny registry is peer-scoped); an exact
  // account:peer key hides exactly one own chat. The set is host data
  // re-uploaded with every fresh script, so a cooldown that expires stops
  // hiding the peer on the next open.
  const hiddenPeer=who=>hiddenPeers!==null&&(hiddenPeers.has(who.account+':'+who.peer)||hiddenPeers.has('*:'+who.peer));
  const permitted=who=>!hiddenPeer(who)&&(adoptUntracked||allowedTargets.some(x=>x.account===who.account&&x.peer===who.peer&&(new Int64(x.chat).compare(0)<=0||x.chat===who.chat)));
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
  const resetDestination=()=>{
   if(state.destination&&!state.destination.isNull()){
    try{f.release(state.destination);n.handles_released++;}catch(_){n.cleanup_failed=true;fail('cleanup-failed');}
    state.destination=ptr(0);
   }
  };
  const stableDestination=current=>{
   if(!state.destination||state.destination.isNull()){save('destination',current);return false;}
   if(!current.equals(target(state.destination)))fail('identity-changed');return true;
  };
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
      // v1.3.96 «открываю только диалоги с новыми сообщениями, а не
      // непрочитанными»: the badge alone never admits a row for the
      // assistant's reply filter - UnreadCount is read-state shared with the
      // operator (his manual open clears it, our own open clears it), so a
      // cleared badge hides genuine unhandled input and a stale badge opens
      // rows with nothing to answer. The badge stays the ADMISSION signal
      // only for the standalone read-check tool (unread_only alone, the
      // 0.4.6 user-confirmed contract); for the reply filter it is evidence
      // and stability only (selection-unread-changed below).
      if(unreadOnly&&!needsReplyOnly&&unread===0){n.read_rows_skipped++;return false;}
     }
     if(needsReplyOnly){
      header=replyHeader(chat,model.who);
      // The new-message admission itself: only a genuinely NEW INCOMING last
      // message opens the row. Our own message last means the peer was
      // already answered - skipped regardless of any unread badge.
      if(!header.incoming){n.waiting_rows_skipped++;return false;}
      if(alreadyHandled(model.who,header.id)){n.handled_rows_skipped++;return false;}
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
     // v1.3.90: the row's last message id the needs-reply filter judged. The
     // host records it as the durable skip marker when the chat is deliberately
     // left read-only, so the same state is never re-entered on later passes.
     if(needsReplyOnly)n.selected_message=header.id;
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
   if(!checkView(current)){resetDestination();return;}
   if(n.phase==='entry'){
    const required=operation==='back'?'chat':operation==='return'?'dialogs':entryScreen;
    // Explicit startup list recovery only. The exact typed current chat is
    // bound twice before one Back call; no body/name/send/row reads occur.
    // Unknown screens, modals and changed identities still fail closed.
    if(operation==='list'&&entryScreen==='either'&&k==='chat'){
     // A chat screen restored before its chat model loads waits a bounded
     // number of frames here (the binding read itself is the readiness
     // probe); structural failures and an exhausted wait still fail closed.
     const pending=call(s.currentChat,current);
     if(pending.isNull()||modelIdentity(pending)===null){
      if(n.entry_binding_waits>=25)fail('entry-binding-timeout');
      n.entry_binding_waits++;return;
     }
     const bound=currentIdentity(current);
     if(!checkView(current)||!resolve(candidate).equals(current)||!same(currentIdentity(current).who,bound.who))fail('identity-changed');
     state.startupReturnIdentity=bound.who;n.entry_verified=true;n.action_attempted=true;
     call(s.closeChat,current);n.action_completed=true;n.phase='wait-back';return;
    }
    if(operation==='list'&&k==='profile'){
     // A stuck profile card holds no unconsumed peer state: closing it once
     // via the verified handler is the bounded Esc press. No identity binding
     // is guessed here; the destination list is verified as usual afterwards.
     n.entry_verified=true;n.profile_closed=true;n.action_attempted=true;
     call(s.closeProfile,current);n.action_completed=true;n.phase='wait-back';return;
    }
    if(operation==='open'&&entryScreen==='dialogs'&&k==='search'){
     if(!checkView(current)||!resolve(candidate).equals(current)||!scope(()=>resolve(root).equals(current)))fail('identity-changed');
     n.entry_verified=true;n.entry_search_recovered=true;n.action_attempted=true;
     switchTab(s.messageTab);n.action_completed=true;n.phase='wait-list';return;
    }
    if(required==='either'?(k!=='search'&&k!=='dialogs'):k!==required)fail('wrong-screen');n.entry_verified=true;
    if(operation==='list'&&k==='dialogs'){n.list_verified=true;if(stableDestination(current))finish();return;}
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
    if(k==='search'){resetDestination();return;}if(k!=='dialogs')fail('unexpected-screen');if(!stableDestination(current))return;n.list_verified=true;
    if(operation!=='open'){finish();return;}resetDestination();n.phase='scan';return;
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
    if(k==='chat'){resetDestination();if(!same(currentIdentity(current).who,operation==='list'?state.startupReturnIdentity:expectedIdentity))fail('identity-changed');return;}
    // The assistant's chats sit on top of a profile card: after the verified
    // chat Back the next screen is the PROFILE, not the dialog list. Close it
    // once (the second Esc press), then continue from the search screen.
    if(k==='profile'&&!n.profile_closed){n.profile_closed=true;n.action_attempted=true;call(s.closeProfile,current);n.action_completed=true;return;}
    if(k==='search'&&n.profile_closed&&operation!=='return'){n.action_attempted=true;switchTab(s.messageTab);n.action_completed=true;n.phase='wait-list';return;}
    if(k!=='dialogs')fail('unexpected-screen');if(!stableDestination(current))return;n.list_verified=true;finish();return;
   }
   if(n.phase==='wait-search'){
    if(k==='dialogs'){resetDestination();return;}if(k!=='search')fail('unexpected-screen');if(stableDestination(current))finish();return;
   }
'''


def build(operation, *, allowed=(), expected=None, entry='search', unread_only=False, needs_reply_only=False, adopt_untracked=False, hidden=()):
    if operation not in ('open','back','return','list') or entry not in ('search','dialogs','either') or (entry=='either' and operation!='list'):raise ValueError('Invalid fixed operation')
    if type(unread_only) is not bool or (unread_only and operation!='open'):raise ValueError('Invalid unread filter')
    if type(needs_reply_only) is not bool or (needs_reply_only and operation!='open'):raise ValueError('Invalid reply filter')
    if type(adopt_untracked) is not bool or (adopt_untracked and operation!='open'):raise ValueError('Invalid adoption filter')
    if type(hidden) not in (list,tuple) or (hidden and operation!='open'):raise ValueError('Invalid hidden peers')
    allowed=targets(allowed);expected=identity(expected) if expected is not None else None;hidden=hidden_peers(hidden)
    if (operation=='back')!=(expected is not None) or (operation!='open' and allowed):raise ValueError('Invalid operation binding')
    s=route.FUNCTION
    s=replace_once(s,'function probeUIKitRoot() {','function probeUIKitRoot() {\n const operation='+json.dumps(operation)+',entryScreen='+json.dumps(entry)+',allowedTargets='+json.dumps(allowed)+',expectedIdentity='+json.dumps(expected)+',unreadOnly='+json.dumps(unread_only)+',needsReplyOnly='+json.dumps(needs_reply_only)+',adoptUntracked='+json.dumps(adopt_untracked)+',hiddenPeers=new Set('+json.dumps([x['account']+':'+x['peer'] for x in hidden])+');')
    s=replace_once(s,' function prepareNavigation(',PREPARE+'\n function prepareNavigation(')
    s=replace_once(s,'prepareDialogRoute(f,setup.navigation,getClass);','prepareDialogRoute(f,setup.navigation,getClass);prepareDialogBrowser(f,setup.navigation,getClass);')
    s=replace_once(s,'r.navigation=emptyNavigation();','r.navigation=emptyNavigation();'+'''Object.assign(r.navigation,{phase:'entry',entry_verified:false,list_verified:false,chat_verified:false,destination_verified:false,action_attempted:false,action_completed:false,selection_verified:false,exhausted:false,private_identity:null,metadata_checkpoint:'not-checked',selection_checkpoint:'not-checked',rows_scanned:0,scan_batches:0,read_rows_skipped:0,back_budget_retries:0,observation_budget_retries:0,entry_read_budget_retries:0,entry_binding_waits:0,entry_search_recovered:false,unread_filter_applied:false,unread_verified:false,reply_filter_applied:false,reply_needed_verified:false,waiting_rows_skipped:0,handled_rows_skipped:0,profile_closed:false,selected_message:null});
 for(const k of ['search_verified','dialogs_verified','return_verified','open_attempted','open_completed','back_attempted','back_completed'])delete r.navigation[k];''')
    s=replace_once(s,'"il2cpp_type_get_object"]','"il2cpp_type_get_object","il2cpp_class_get_parent"]')
    s=replace_once(s,"Object.assign(f,{classType:","Object.assign(f,{classParent:bind('class_get_parent','pointer',['pointer']),classType:")
    s=replace_once(s,'   let m=entry.m;',"   if(entry.dialogChecked&&!dialogSignature(f,entry,entry.m))fail('signature-mismatch');\n   let m=entry.m;")
    s=replace_once(s,'   if(entry.arity===1)',"   if(entry.dialogChecked&&!dialogSignature(f,entry,m))fail('signature-mismatch');\n   if(entry.arity===1&&!entry.dialogChecked)")
    # The baseline forbids ref returns. Only the exact typed CoreList indexer
    # opts into runtime_invoke's already-tested ref-to-reference normalization.
    s=replace_once(s,"||f.byref(f.returnType(m)))fail('signature-mismatch');", "||!!f.byref(f.returnType(m))!==!!entry.byref)fail('signature-mismatch');")
    s=replace_once(s,"   if(klass.equals(s.messageTab))", "   if(klass.equals(s.chatController))return 'chat';\n   if(klass.equals(s.profileQueue))return 'profile';\n   if(klass.equals(s.messageTab))")
    s=replace_once(s,"if(k==='search'||k==='dialogs'){", "if(k==='search'||k==='dialogs'||k==='chat'||k==='profile'){")
    s=s.replace("n.phase==='search'?'wrong-screen'", "n.phase==='entry'?'wrong-screen'")
    s=replace_once(s,'  try {\n   const root=call',UTILS+'  try {\n   const root=call')
    s=replace_once(s,'   resolve(root);',
        "   if((operation==='return'||operation==='open'||operation==='list')&&(!state.tabs||state.tabs.isNull()))scope(()=>resolve(root));")
    s=replace_once(s,'const current=resolve(candidate);if(current.isNull())return;',
                   'const current=scope(()=>resolve(candidate),true);if(current.isNull())return;')

    start=s.index("   if(n.phase==='search'&&k!=='search')")
    end=s.index('\n  } catch(e)',start)
    s=s[:start]+TICK+s[end:]
    # A slow frame AFTER the one verified back handler may be retried only as
    # observation. wait-back has no action calls and is never reset to entry.
    # Keep the baseline 100 ms/frame, total call/frame/time limits and cleanup.
    s=replace_once(s, "} catch(e){n.error=", """} catch(e){
   if(e==='frame-budget'&&n.phase==='entry'&&!n.action_attempted&&!n.action_completed&&
      !n.selection_verified&&state.stop===null&&!fixedCancellationRequested&&
      !n.cleanup_failed&&n.entry_read_budget_retries<3){
    resetDestination();n.entry_read_budget_retries++;return;
   }
   if(e==='frame-budget'&&(['wait-list','wait-chat','wait-search'].includes(n.phase)||(n.phase==='wait-back'&&n.profile_closed))&&
      n.entry_verified&&n.action_attempted&&n.action_completed&&state.stop===null&&
      !fixedCancellationRequested&&!n.cleanup_failed&&n.observation_budget_retries<3){
    resetDestination();n.observation_budget_retries++;return;
   }
   if(e==='frame-budget'&&operation==='list'&&entryScreen==='either'&&n.phase==='wait-back'&&
      state.startupReturnIdentity&&n.entry_verified&&n.action_attempted&&n.action_completed&&
      !n.chat_verified&&n.private_identity===null&&state.stop===null&&
      !fixedCancellationRequested&&!n.cleanup_failed&&n.back_budget_retries<3){
    resetDestination();n.back_budget_retries++;return;
   }
   if(e==='frame-budget'&&operation==='back'&&n.phase==='wait-back'&&
      n.entry_verified&&n.chat_verified&&n.action_attempted&&n.action_completed&&
      same(n.private_identity,expectedIdentity)&&state.stop===null&&
      !fixedCancellationRequested&&!n.cleanup_failed&&n.back_budget_retries<"""+str(MAX_BACK_BUDGET_RETRIES)+"""){
    resetDestination();n.back_budget_retries++;return;
   }
   n.error=""")
    s=s.replace('checkView(current)', 'scope(()=>checkView(current))')
    s=s.replace('resolve(candidate).equals(current)', 'scope(()=>resolve(candidate).equals(current))')
    s=replace_once(s,"['card','origin','tabs']", "['card','origin','tabs','selectedChat','selectedUser','destination']")
    s=replace_once(s,json.dumps(sorted(nav.ERRORS)),json.dumps(sorted(ERRORS)))
    return s


def validate(value,operation, *, allowed=(), expected=None, unread_only=False, needs_reply_only=False, adopt_untracked=False, hidden=()):
    if operation not in ('open','back','return','list'):raise ValueError('Invalid fixed operation')
    if type(unread_only) is not bool or (unread_only and operation!='open'):raise ValueError('Invalid unread filter')
    if type(needs_reply_only) is not bool or (needs_reply_only and operation!='open'):raise ValueError('Invalid reply filter')
    if type(adopt_untracked) is not bool or (adopt_untracked and operation!='open'):raise ValueError('Invalid adoption filter')
    if type(hidden) not in (list,tuple) or (hidden and operation!='open'):raise ValueError('Invalid hidden peers')
    allowed=targets(allowed);expected=identity(expected) if expected is not None else None;hidden=hidden_peers(hidden)
    if (operation=='back')!=(expected is not None) or (operation!='open' and allowed):raise ValueError('Invalid operation binding')
    if not isinstance(value,dict) or not isinstance(value.get('navigation'),dict):raise ValueError('Missing dialog evidence')
    n=value['navigation']
    if set(n)!=EXTRAS or n['phase'] not in PHASES or n['error'] not in ERRORS:raise ValueError('Invalid dialog evidence')
    if any(type(n[k]) is not bool for k in FLAGS) or n['ui_text_read']:raise ValueError('Invalid flags')
    if n['metadata_checkpoint'] not in CHECKPOINTS or n['selection_checkpoint'] not in SELECTION:raise ValueError('Invalid checkpoint')
    for k,limit in [('rows_scanned',128),('scan_batches',180),('read_rows_skipped',128),('waiting_rows_skipped',128),('handled_rows_skipped',128),('back_budget_retries',MAX_BACK_BUDGET_RETRIES),('observation_budget_retries',MAX_OBSERVATION_BUDGET_RETRIES),('entry_read_budget_retries',MAX_ENTRY_READ_BUDGET_RETRIES),('entry_binding_waits',MAX_ENTRY_BINDING_WAITS)]:
        if type(n[k]) is not int or not 0<=n[k]<=limit:raise ValueError('Invalid scan bounds')
    # v1.3.90: the selected row's last message id, reported only when the
    # needs-reply filter actually selected a row. It is a positive id string
    # exactly like an uploaded seen_ids entry - never a body, sender or name.
    if n['selected_message'] is not None:
        if not needs_reply_only or not n['reply_needed_verified'] or not isinstance(n['selected_message'],str) \
                or not re.fullmatch(r'[1-9][0-9]{0,18}', n['selected_message']):
            raise ValueError('Invalid selected message')
    # Startup chat binding waits exist only in the list/either recovery path:
    # they precede the one verified Back on a successfully bound chat, or end
    # as the same identity-not-bound stop when the wait is exhausted.
    if n['entry_binding_waits'] and operation!='list':
        raise ValueError('Invalid startup binding wait')
    if n['observation_budget_retries'] and (n['phase'] not in ('wait-list','wait-chat','wait-search','wait-back','scan','done')
            or not n['entry_verified'] or not n['action_completed']
            or (n['phase']=='wait-back' and not n['profile_closed'])):
        raise ValueError('Invalid observation recovery evidence')
    # A stuck profile card may be closed once by the fixed list/back flows:
    # the bounded Esc press after a chat Back or at list recovery. A completed
    # action ladder is always required; a verified destination list is only
    # reachable on the success paths, which already demand list_verified.
    if n['profile_closed'] and (operation not in ('list','back') or not n['entry_verified']
            or not n['action_attempted'] or not n['action_completed']):
        raise ValueError('Invalid profile recovery evidence')
    if n['entry_search_recovered'] and (operation!='open' or not n['entry_verified'] or not n['action_attempted']):
        raise ValueError('Invalid search reentry evidence')
    if n['back_budget_retries']:
        bound_back=operation=='back' and n['chat_verified'] and n['private_identity'] is not None
        startup_back=operation=='list' and not n['chat_verified'] and n['private_identity'] is None and n['selection_checkpoint']=='not-checked'
        if not (bound_back or startup_back) or n['phase'] not in ('wait-back','done') or not n['entry_verified'] or not n['action_completed']:
            raise ValueError('Invalid back recovery evidence')
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
        # v1.3.84: an adoption-mode open intentionally selects a row OUTSIDE the
        # uploaded journal targets (an operator-led dialog). The native scan
        # still proves the row needs a reply; the host routes it to the
        # read-only structure probe before anything is sent. Every other
        # operation keeps the strict tracked-binding contract.
        if operation=='open' and not adopt_untracked and not any(x['account']==private['account'] and x['peer']==private['peer'] and (int(x['chat'])<=0 or x['chat']==private['chat']) for x in allowed):raise ValueError('Untracked private binding')
        # v1.3.88: a hidden peer must NEVER leave the native scan as an opened
        # dialog - the scan refuses it in permitted(), so evidence of an open
        # hidden peer is a broken contract, never a usable result.
        if operation=='open' and any((x['account']=='*' or x['account']==private['account']) and x['peer']==private['peer'] for x in hidden):raise ValueError('Hidden dialog opened')
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
        return {'dialogs':'filters','chat':'filters','profile':'filters','messages-tab':'dv-container'}.get(k,k)
    for key in ('root_top_kind','last_presented_kind'):bn[key]=old(bn[key])
    if not isinstance(bn['controller_path'],list):raise ValueError('Invalid controller path')
    bn['controller_path']=[old(k) for k in bn['controller_path']]
    nav.validate(base,errors=ERRORS)
    from navigation_root_diagnostic import extract
    diagnostic={k:n[k] for k in ('stage','error','phase','metadata_checkpoint','selection_checkpoint','rows_scanned','scan_batches','action_attempted','action_completed','destination_verified','unread_filter_applied','unread_verified','read_rows_skipped','back_budget_retries','reply_filter_applied','reply_needed_verified','waiting_rows_skipped','handled_rows_skipped','selected_message','observation_budget_retries','entry_read_budget_retries','entry_binding_waits','entry_search_recovered','root_top_kind','last_presented_kind','controller_path')}
    diagnostic['root_probe']=extract(value)
    return dict(state=('exhausted' if n['exhausted'] else 'opened' if operation=='open' else 'returned' if operation=='back' else 'dialogs-ready' if operation=='list' else 'search-ready') if ready else 'stopped',identity=private,diagnostic=diagnostic)


# Targets are private data, never compiled JS. A fresh script accepts one upload
# and one root call; no persistent native session or identity cache is retained.
TARGET_BOOTSTRAP = r"""
let navigationTargets=null,navigationHidden=null,navigationStarted=false;
function prepareNavigationTargets(values){
 if(navigationTargets!==null||navigationStarted)throw new Error('targets-already-prepared');
 const positive=v=>typeof v==='string'&&/^[1-9][0-9]{0,18}$/.test(v)&&
  (v.length<19||v<='9223372036854775807');
 const chat=v=>v==='0'||positive(v)||(typeof v==='string'&&/^-[1-9][0-9]{0,18}$/.test(v)&&
  (v.length<20||v.slice(1)<='9223372036854775808'));
 if(!Array.isArray(values)||values.length>1000)throw new Error('invalid-targets');
 const seen=new Set(),checked=[];
 for(const x of values){
  if(x===null||typeof x!=='object'||Array.isArray(x))throw new Error('invalid-target');
  const keys=Object.keys(x).sort().join(',');
  if(keys!=='account,chat,peer'&&keys!=='account,chat,peer,seen_ids')throw new Error('invalid-target');
  if(!positive(x.account)||!positive(x.peer)||!chat(x.chat))throw new Error('invalid-target');
  const key=x.account+':'+x.peer;if(seen.has(key))throw new Error('duplicate-target');seen.add(key);
  const value={account:x.account,peer:x.peer,chat:x.chat};
  if(Object.prototype.hasOwnProperty.call(x,'seen_ids')){
   if(!Array.isArray(x.seen_ids)||x.seen_ids.length>128||x.seen_ids.some(v=>!positive(v))||
      new Set(x.seen_ids).size!==x.seen_ids.length)throw new Error('invalid-seen-ids');
   value.seen_ids=Object.freeze(x.seen_ids.slice());
  }
  checked.push(Object.freeze(value));
 }
 navigationTargets=Object.freeze(checked);return true;
}
function prepareNavigationHidden(values){
 if(navigationHidden!==null||navigationStarted)throw new Error('hidden-already-prepared');
 const positive=v=>typeof v==='string'&&/^[1-9][0-9]{0,18}$/.test(v)&&
  (v.length<19||v<='9223372036854775807');
 if(!Array.isArray(values)||values.length>2000)throw new Error('invalid-hidden');
 const seen=new Set(),checked=[];
 for(const x of values){
  if(x===null||typeof x!=='object'||Array.isArray(x))throw new Error('invalid-hidden');
  const keys=Object.keys(x).sort().join(',');
  if(keys!=='account,peer')throw new Error('invalid-hidden');
  if((x.account!=='*'&&!positive(x.account))||!positive(x.peer))throw new Error('invalid-hidden');
  const key=x.account+':'+x.peer;if(seen.has(key))throw new Error('duplicate-hidden');seen.add(key);
  checked.push(key);
 }
 navigationHidden=new Set(checked);return true;
}
"""


def prepared_source(source):
    source=replace_once(source,'allowedTargets=[]','allowedTargets=navigationTargets')
    source=replace_once(source,'hiddenPeers=new Set([])','hiddenPeers=navigationHidden')
    source=replace_once(source,'function probeUIKitRoot() {',"function probeUIKitRoot() {\n if(navigationTargets===null||navigationStarted)throw new Error('targets-not-ready');navigationStarted=true;")
    return TARGET_BOOTSTRAP+source


class PreparedNavigation:
    """Authored adapter: only an unloaded-script transport error may reconnect."""
    def __init__(self,source,allowed,validator,progress=None,hidden=()):
        self.source=prepared_source(source)
        self.allowed=targets(allowed)
        self.hidden=hidden_peers(hidden)
        self.validator=validator
        self.progress=progress

    def __call__(self,port,token,cancel,binding):
        from search_online import inspect
        return inspect(port,token,cancel,source_function=self.source,
                       validator=self.validator,navigation_targets=self.allowed,
                       navigation_hidden=self.hidden or None)

    def reconnecting(self,attempt):
        if self.progress is not None:
            self.progress(f'Восстанавливаю связь перед переходом • попытка {attempt}/2 • скрипт ещё не загружен')


def perform(operation,executable,folder,cancelled=lambda:False, *, allowed=(),expected=None,entry='search',unread_only=False, needs_reply_only=False, adopt_untracked=False, hidden=()):
    from one_chat_device import capture
    from search_online import inspect
    from startup_failure import checkpoint
    with checkpoint('navigation-source'):
        allowed=targets(allowed)
        if operation!='open' and (allowed or hidden):raise ValueError('Invalid operation binding')
        source=build(operation,allowed=(),expected=expected,entry=entry,unread_only=unread_only,needs_reply_only=needs_reply_only,adopt_untracked=adopt_untracked)
    def checked(result):
        try:
            return validate(result,operation,allowed=allowed,expected=expected,unread_only=unread_only,needs_reply_only=needs_reply_only,adopt_untracked=adopt_untracked,hidden=hidden)
        except Exception as error:
            # A rejected result never becomes a usable result. Preserve ONLY the
            # independently validated public diagnostic; discard all raw RPC data.
            from assistant_navigation_check import safe_diagnostic
            keys=('stage','error','phase','metadata_checkpoint','selection_checkpoint',
                  'rows_scanned','scan_batches','action_attempted','action_completed',
                  'destination_verified','unread_filter_applied','unread_verified',
                  'read_rows_skipped','back_budget_retries','reply_filter_applied',
                  'reply_needed_verified','waiting_rows_skipped','handled_rows_skipped','observation_budget_retries','entry_read_budget_retries','entry_binding_waits','entry_search_recovered','root_top_kind','last_presented_kind','controller_path')
            try:
                public=safe_diagnostic({k:result['navigation'][k] for k in keys})
            except Exception:
                pass
            else:
                error._dvk_navigation=public
            raise
    return capture(executable,folder,cancelled,inspector=PreparedNavigation(source,allowed,checked,hidden=hidden))
