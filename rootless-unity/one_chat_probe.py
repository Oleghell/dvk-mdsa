"""Fixed read-only observer for one explicitly bound, manually opened test chat.

Identity-only binding never reads bodies. Snapshot order is NOT interpreted as
chronological. No navigation, sending, enrollment, Telegram or arbitrary RPC.
"""
import copy
import json
import re

import chat_state_probe as state
import uikit_navigation as nav
from uikit_profile_navigation import replace_once

VERSION = '0.3.35'
from chat_limits import MAX_MESSAGES, MAX_TEXT, MAX_TOTAL_TEXT, READ_MAX_CALLS
STATE_FIELDS = {'read_checkpoint','wait_reason','model_actual','model_draft','model_has_cm','cm_present','loaded_field_present','metadata_checkpoint','loaded_value_method_found','loaded_value_return_kind','loaded_value_byref','loaded_value_owner_verified','loaded_value_owner_inherited','loaded_value_owner_scope','loaded_value_static','loaded_value_abstract','loaded_value_arity','history_status','message_count','history_fully_loaded','history_loading','last_message_present','samples','sample_interval_ms','chat_identity_verified','app_actions_attempted','messages_sent'}
ERRORS = state.ERRORS | {'identity-not-bound', 'snapshot-too-large', 'message-invalid', 'snapshot-changing', 'nonpositive-message-id', 'nonpositive-message-sender-id', 'nonpositive-message-chat-id', 'local-own-message-unanchored'}


def identity(value):
    if not isinstance(value, dict) or set(value) != {'account', 'peer', 'chat'}:
        raise ValueError('Invalid test identity')
    for v in value.values():
        if not isinstance(v, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', v) or int(v) > 2**63-1:
            raise ValueError('Invalid test identity')
    if value['account'] == value['peer']:
        raise ValueError('Self dialog')
    return dict(value)


DIAGNOSTIC_FIELDS = {'scalar_checkpoint', 'scalar_state', 'identity_checkpoint', 'message_slot', 'message_kind', 'message_direction'}
SCALAR_CHECKPOINTS = {'not-read','account-id','peer-id','chat-id','message-id','message-sender-id','message-chat-id'}
SCALAR_STATES = {'not-read','positive','zero','negative','missing-box','missing-unbox'}
IDENTITY_CHECKPOINTS = {'not-checked','initial-ids','distinct-accounts','actual-server-chat','saved-binding','recheck'}


def diagnostic(value):
    out = {k: value[k] for k in DIAGNOSTIC_FIELDS}
    if (out['scalar_checkpoint'] not in SCALAR_CHECKPOINTS or out['scalar_state'] not in SCALAR_STATES
            or out['identity_checkpoint'] not in IDENTITY_CHECKPOINTS
            or out['message_kind'] not in {'not-read','text','non-text'}
            or out['message_direction'] not in {'not-read','own','not-own'}
            or type(out['message_slot']) is not int or not -1 <= out['message_slot'] < MAX_MESSAGES):
        raise ValueError('Invalid scalar diagnostic')
    if out['scalar_checkpoint'] == 'not-read' and out['scalar_state'] != 'not-read':
        raise ValueError('Scalar result without a read')
    return out


PREPARE = r'''
 function prepareOneChat(f,s,getClass){
  const manager=getClass('DV.Messages.dll','DV.Messages','MessagesManager');
  s.textMessage=getClass('DV.Messages.dll','DV.Messages','TextMessage');
  if(manager.isNull()||s.textMessage.isNull()||!f.assignable(s.message,s.textMessage))throw new Error('metadata');
  const check=(klass,label,kind,arity=0,result=null)=>{
   const m=f.method(klass,Memory.allocUtf8String(label),arity),bits=Memory.alloc(4);bits.writeU32(0);
   if(m.isNull()||f.arity(m)!==arity||(f.flags(m,bits)&(16|1024))!==0||f.typeKind(f.returnType(m))!==kind||f.byref(f.returnType(m)))throw new Error('signature');
   const owner=f.methodClass(m);let cursor=klass,found=false;const seen=new Set();
   for(let i=0;i<10&&!cursor.isNull();i++){const key=cursor.toString();if(seen.has(key))throw new Error('hierarchy');seen.add(key);if(cursor.equals(owner)){found=true;break;}cursor=f.classParent(cursor);}
   if(!found||!f.assignable(owner,klass))throw new Error('signature');
   if(result&&!f.classFromType(f.returnType(m)).equals(result))throw new Error('signature');
   if(arity===1){const p=f.param(m,0);if(p.isNull()||f.typeKind(p)!==8||f.byref(p))throw new Error('signature');}
   return {m,klass,kind,arity,result};
  };
  s.chatManager=check(s.chatModel,'get_MessagesManager',18,0,manager);
  s.accountId=check(manager,'get_CurrentUserId',10);s.peerId=check(s.user,'get_Id',10);
  s.chatId=check(s.chatModel,'get_Id',10);s.messageId=check(s.message,'get_Id',10);
  s.messageSender=check(s.message,'get_SenderId',10);s.messageChat=check(s.message,'get_ChatId',10);
  s.messageMine=check(s.message,'get_IsMine',2);s.messageText=check(s.textMessage,'get_Text',14);
  s.stringClass=f.classFromType(f.returnType(s.messageText.m));
  if(s.stringClass.isNull())throw new Error('signature');
  let list=s.cm;const seen=new Set();
  for(let i=0;i<10&&!list.isNull();i++){
   const key=list.toString();if(seen.has(key))throw new Error('hierarchy');seen.add(key);
   const m=f.method(list,Memory.allocUtf8String('get_Item'),1);
   if(!m.isNull()){s.messageItem=check(list,'get_Item',18,1,s.message);break;}list=f.classParent(list);
  }
  if(!s.messageItem)throw new Error('signature');return s;
 }
'''
BIND = r'''
   const id64=(entry,obj,label,allowLocalChat=false)=>{
    n.scalar_checkpoint=label;n.scalar_state='not-read';
    const box=call(entry,obj);if(box.isNull()){n.scalar_state='missing-box';fail('signature-mismatch');}
    const p=f.unbox(box);if(p.isNull()){n.scalar_state='missing-unbox';fail('signature-mismatch');}
    const value=p.readS64(),sign=value.compare(0);n.scalar_state=sign===0?'zero':sign<0?'negative':'positive';
    if(sign<=0&&!(sign<0&&allowLocalChat&&label==='message-chat-id'))fail(label.startsWith('message-')?'nonpositive-'+label:'identity-not-bound');
    return value.toString();
   };
   n.identity_checkpoint='initial-ids';
   const manager=call(s.chatManager,chat);if(manager.isNull())fail('identity-not-bound');own(manager);
   const who={account:id64(s.accountId,manager,'account-id'),peer:id64(s.peerId,user,'peer-id'),chat:id64(s.chatId,chat,'chat-id')};
   n.identity_checkpoint='distinct-accounts';if(who.account===who.peer)fail('identity-not-bound');
   n.identity_checkpoint='actual-server-chat';if(!bool(s.actual,chat)||bool(s.draft,chat))fail('identity-not-bound');
   n.identity_checkpoint='saved-binding';
   if(expectedIdentity!==null&&JSON.stringify(who)!==JSON.stringify(expectedIdentity))fail('identity-not-bound');
   const verifyWho=()=>{
    n.identity_checkpoint='recheck';
    if(!call(s.chat,current).equals(chat)||!call(s.chatUser,current).equals(user)||!call(s.opponent,chat).equals(user)||
       !call(s.chatManager,chat).equals(manager)||id64(s.accountId,manager,'account-id')!==who.account||
       id64(s.peerId,user,'peer-id')!==who.peer||id64(s.chatId,chat,'chat-id')!==who.chat||!bool(s.actual,chat)||bool(s.draft,chat))fail('identity-changed');
   };
   verifyWho();
   if(expectedIdentity===null){
    if(!checkView(current)||!resolve(candidate).equals(current))fail('identity-changed');verifyWho();
    n.private_result={identity:who,messages:null};n.phase='done';n.stage='navigation-ready';return;
   }
'''
COLLECT = r'''
   // Only exact bound IDs reach this point. No collection-order assumption.
   if(first>__MAX_MESSAGES__)fail('snapshot-too-large');
   const messages=[],seenIds=new Set();let totalText=0;
   const headers=[],messageBindings=[];let localOwn=0,peerAnchors=0;
   const releaseOne=h=>{f.release(h);n.handles_released++;held.splice(held.indexOf(h),1);};
   const messageAt=i=>{
    const index=Memory.alloc(4);index.writeS32(i);const args=Memory.alloc(Process.pointerSize);args.writePointer(index);
    const message=call(s.messageItem,cm,args);
    if(message.isNull()||!f.assignable(s.message,f.objectClass(message)))fail('message-invalid');
    return message;
   };
   const messageHeader=message=>{
    n.message_kind=f.assignable(s.textMessage,f.objectClass(message))?'text':'non-text';
    const mine=bool(s.messageMine,message);n.message_direction=mine?'own':'not-own';
    const id=id64(s.messageId,message,'message-id'),sender=id64(s.messageSender,message,'message-sender-id');
    // A negative per-message ChatId is not the actual dialog ID. Accept it only
    // for our own message in this exact CM, with an independent positive peer
    // anchor below. Zero, foreign positive IDs and negative incoming IDs STOP.
    const chatId=id64(s.messageChat,message,'message-chat-id',mine&&sender===who.account);
    if(![who.account,who.peer].includes(sender)||mine!==(sender===who.account)||
       (!chatId.startsWith('-')&&chatId!==who.chat))fail('message-invalid');
    return {id,sender,chatId,mine};
   };
   // Resume only private value data between frames, never unrooted objects.
   // Validate ALL headers before any body; two complete samples still gate send.
   if(loading||!all||first!==second){state.historyChunk=null;invalidate(loading?'history-loading':!all?'history-not-loaded':'changing-count');return;}
   const startChunk=()=>({identity:JSON.stringify(who),count:first,phase:'headers',headers:[],messages:[],totalText:0,localOwn:0,peerAnchors:0});
   if(!state.historyChunk)state.historyChunk=startChunk();
   const chunk=state.historyChunk;
   if(chunk.identity!==JSON.stringify(who))fail('identity-changed');
   if(chunk.count!==first){state.historyChunk=null;invalidate('changing-count');return;}
   const end=Math.min(first,(chunk.phase==='headers'?chunk.headers.length:chunk.messages.length)+4);
   if(chunk.phase==='headers'){
    const start=chunk.headers.length;
    for(let i=start;i<end;i++){
     if(i>start&&Date.now()>deadline-30)break;
     n.message_slot=i;const message=messageAt(i),handle=own(message),bits=messageHeader(message);
     if(chunk.headers.some(row=>row.bits.id===bits.id))fail('message-invalid');
     if(bits.chatId.startsWith('-'))chunk.localOwn++;
     else if(bits.sender===who.peer&&!bits.mine&&bits.chatId===who.chat)chunk.peerAnchors++;
     chunk.headers.push({pointer:message.toString(),bits});releaseOne(handle);
    }
    if(chunk.headers.length<first){verifyWho();return;}
    if(chunk.localOwn>0&&chunk.peerAnchors===0)fail('local-own-message-unanchored');
    chunk.phase='bodies';if(first>0){verifyWho();return;}
   }else if(chunk.phase==='bodies'){
    const start=chunk.messages.length;
    for(let i=start;i<end;i++){
     if(i>start&&Date.now()>deadline-30)break;
     n.message_slot=i;const row=chunk.headers[i],message=messageAt(i),handle=own(message);
     if(message.toString()!==row.pointer||JSON.stringify(messageHeader(message))!==JSON.stringify(row.bits))fail('message-invalid');
     const {id,sender}=row.bits;let text=null;
     if(f.assignable(s.textMessage,f.objectClass(message))){
      const value=call(s.messageText,message);if(value.isNull()||!f.objectClass(value).equals(s.stringClass))fail('message-invalid');const sh=own(value);
      const length=f.stringLength(value);if(length<0||length>__MAX_TEXT__||(chunk.totalText+=length)>__MAX_TOTAL_TEXT__)fail('snapshot-too-large');
      const chars=f.stringChars(value);if(chars.isNull()&&length!==0)fail('message-invalid');
      text=length===0?'':chars.readUtf16String(length);if(text===null||text.includes('\u0000'))fail('message-invalid');releaseOne(sh);
     }
     chunk.messages.push({id,sender,text});releaseOne(handle);
    }
    if(chunk.messages.length===first)chunk.phase='complete';
    verifyWho();return;
   }
   messages.push(...chunk.messages);messageBindings.push(...chunk.headers.map(row=>row.bits));
   state.historyChunk=null;verifyWho();

'''


def build(expected=None, *, read_name=False, scoped_traversal=False, read_latest=False, read_input=False):
    if type(read_input) is not bool or read_input and expected is None:
        raise ValueError("Input state requires a bound dialog")
    if type(read_latest) is not bool or read_latest and expected is None:
        raise ValueError("Latest message requires a bound dialog")
    if read_name and expected is None:
        raise ValueError('Name requires an authorized bound dialog')
    expected = identity(expected) if expected is not None else None
    # Use one stable key order on both sides; IDs are literal validated decimals.
    expected = {k: expected[k] for k in ('account', 'peer', 'chat')} if expected else None
    source = state.FUNCTION
    source = replace_once(source, 'sample:null,waitSignature:null', 'sample:null,historyChunk:null,waitSignature:null')
    source = replace_once(source, "n.wait_reason=reason;n.history_status='not-ready';", "state.historyChunk=null;n.wait_reason=reason;n.history_status='not-ready';")
    source = replace_once(source, "n.metadata_checkpoint='ready';return s;", "n.metadata_checkpoint='ready';return prepareOneChat(f,s,getClass);")
    source = PREPARE + source
    if read_name:
        source = replace_once(source, "  if(!s.messageItem)throw new Error('signature');return s;",
            "  s.peerName=check(s.user,'get_Name',14);if(!f.classFromType(f.returnType(s.peerName.m)).equals(s.stringClass))throw new Error('signature');\n  if(!s.messageItem)throw new Error('signature');return s;")
    source = replace_once(source, 'function probeUIKitRoot() {', 'function probeUIKitRoot() {\n const expectedIdentity=' + json.dumps(expected) + ';')
    # The index argument helper originally supported only the modal collection.
    source = replace_once(source, "if(!f.classFromType(f.returnType(m)).equals(s.vc))fail('signature-mismatch');", "if(!f.classFromType(f.returnType(m)).equals(entry.result||s.vc))fail('signature-mismatch');")
    source = replace_once(source, "messages_sent:0};}", "messages_sent:0,private_result:null,scalar_checkpoint:'not-read',scalar_state:'not-read',identity_checkpoint:'not-checked',message_slot:-1,message_kind:'not-read',message_direction:'not-read'};}")
    source = replace_once(source, "save('origin',current);save('card',chat);save('user',user);n.chat_identity_verified=true;", "save('origin',current);save('card',chat);save('user',user);n.chat_identity_verified=true;" + BIND)
    source = replace_once(source, "n.read_checkpoint='recheck';", COLLECT.replace('__MAX_MESSAGES__',str(MAX_MESSAGES)).replace('__MAX_TEXT__',str(MAX_TEXT)).replace('__MAX_TOTAL_TEXT__',str(MAX_TOTAL_TEXT)) + "\n   n.read_checkpoint='recheck';")
    source = replace_once(source, "const sample={count:first,last:!lastMessage.isNull(),draft:n.model_draft};", "verifyWho();\n   const sample={count:first,last:!lastMessage.isNull(),draft:n.model_draft,identity:who,messages,messageBindings};")
    source = replace_once(source, "state.sample.draft!==sample.draft", "state.sample.draft!==sample.draft||JSON.stringify(state.sample)!==JSON.stringify(sample)")
    source = replace_once(source, "n.read_checkpoint='complete';n.samples=2;", "n.private_result={identity:who,messages};n.read_checkpoint='complete';n.samples=2;")
    source = replace_once(source, "if(n.stage!=='navigation-ready'){n.history_status=", "if(n.stage!=='navigation-ready'){n.private_result=null;n.history_status=")
    source = replace_once(source, json.dumps(sorted(state.ERRORS)), json.dumps(sorted(ERRORS)))
    source = replace_once(source, "classParent:bind('class_get_parent','pointer',['pointer'])", "classParent:bind('class_get_parent','pointer',['pointer']),stringLength:bind('string_length','int',['pointer']),stringChars:bind('string_chars','pointer',['pointer'])")
    source = replace_once(source, json.dumps(__import__('uikit_root').APIS + nav.APIS + ['il2cpp_class_get_parent']), json.dumps(__import__('uikit_root').APIS + nav.APIS + ['il2cpp_class_get_parent', 'il2cpp_string_length', 'il2cpp_string_chars']))
    if read_name:
        # Read only the bound user's display name, after identity/body checks.
        name_read = r"""
   const display=call(s.peerName,user);if(display.isNull()||!f.objectClass(display).equals(s.stringClass))fail('message-invalid');
   const displayHandle=own(display),displayLength=f.stringLength(display);
   if(displayLength<1||displayLength>128)fail('message-invalid');
   const displayChars=f.stringChars(display);if(displayChars.isNull())fail('message-invalid');
   const peerName=displayChars.readUtf16String(displayLength);
   if(peerName===null||!peerName.trim()||/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/.test(peerName))fail('message-invalid');
   releaseOne(displayHandle);verifyWho();
"""
        source = replace_once(source, "   n.read_checkpoint='recheck';", name_read + "   n.read_checkpoint='recheck';")
        source = replace_once(source, 'draft:n.model_draft,identity:who,messages,messageBindings};', 'draft:n.model_draft,identity:who,messages,peer_name:peerName};')
        source = replace_once(source, 'n.private_result={identity:who,messages};', 'n.private_result={identity:who,messages,peer_name:peerName};')
    if read_latest:
        # Chat.LastMessage is an independent semantic marker, not list/ID order.
        # It must be the EXACT same object/header in this complete bound sample.
        latest_read = r"""
   let latestId=null;
   if(!lastMessage.isNull()){
    const latestRow=chunk.headers.find(row=>row.pointer===lastMessage.toString());
    // A separate server-model object is NOT proof about this CM. Keep ordinary
    // history readable, but do not adopt any legacy stage without the proof.
    if(latestRow){
     const latestBits=messageHeader(lastMessage);
     if(JSON.stringify(latestRow.bits)!==JSON.stringify(latestBits))fail('message-invalid');
     latestId=latestBits.id;
    }
   }
"""
        source=replace_once(source,'   const sample={count:first,',latest_read+'   const sample={latest_message_id:latestId,count:first,')
        fields='identity:who,messages'+(',peer_name:peerName' if read_name else '')
        source=replace_once(source,'n.private_result={'+fields+'};','n.private_result={'+fields+',latest_message_id:latestId};')
    if read_input:
        source=replace_once(source,"  if(!s.messageItem)throw new Error('signature');return s;",
            "  s.inputEnabled=check(s.chatModel,'get_IsInputEnabled',2);\n  if(!s.messageItem)throw new Error('signature');return s;")
        source=replace_once(source,'   const sample={',
            "   const inputEnabled=bool(s.inputEnabled,chat);verifyWho();\n   const sample={input_enabled:inputEnabled,")
        fields='identity:who,messages'+(',peer_name:peerName' if read_name else '')+(',latest_message_id:latestId' if read_latest else '')
        source=replace_once(source,'n.private_result={'+fields+'};','n.private_result={'+fields+',input_enabled:inputEnabled};')
    source=source.replace('n.managed_calls>=6000' ,f'n.managed_calls>={READ_MAX_CALLS}')
    if scoped_traversal:
        from navigation_handles import scoped_traversals
        source=scoped_traversals(source)
    return source


def private_snapshot(value, expected=None, *, read_name=False, read_latest=False, read_input=False):
    """Validate private RPC data in memory; caller must never dump this object."""
    if type(read_input) is not bool or read_input and expected is None:
        raise ValueError("Input state requires a bound dialog")
    if type(read_latest) is not bool or read_latest and expected is None:
        raise ValueError("Latest message requires a bound dialog")
    expected = identity(expected) if expected is not None else None
    result = copy.deepcopy(value)
    n = result.get('navigation', {})
    if not isinstance(n, dict) or 'private_result' not in n:
        raise ValueError('Missing test result')
    if set(n) != _nav_fields() | STATE_FIELDS | DIAGNOSTIC_FIELDS | {'private_result'}:
        raise ValueError('Unexpected test fields')
    diagnostic(n)
    for key in DIAGNOSTIC_FIELDS:
        n.pop(key)
    private = n.pop('private_result')
    error = n.get('error')
    if error not in ERRORS:
        raise ValueError('Unexpected stop reason')
    if error not in state.ERRORS:
        n['error'] = 'history-invalid'
    if n.get('stage') != 'navigation-ready':
        if private is not None:
            raise ValueError('Private data on failed read')
        state.validate(result,max_calls=READ_MAX_CALLS)
        return None
    fields = {'identity', 'messages', 'peer_name'} if read_name else {'identity', 'messages'}
    if read_latest: fields |= {'latest_message_id'}
    if read_input: fields |= {'input_enabled'}
    if read_name and expected is None:
        raise ValueError('Name requires an authorized dialog')
    if not isinstance(private, dict) or set(private) != fields:
        raise ValueError('Invalid private result')
    if read_input and type(private['input_enabled']) is not bool:
        raise ValueError('Invalid input state')
    who = identity(private['identity'])
    if read_name:
        from shared_contact import display_name
        display_name(private['peer_name'])
    if expected is not None and who != expected:
        raise ValueError('Different test dialog')
    if expected is None:
        if (n.get('app_actions_attempted') is not False or type(n.get('messages_sent')) is not int or n['messages_sent'] != 0
                or n.get('history_status') != 'unknown' or n.get('message_count') is not None or n.get('samples') != 0
                or n.get('read_checkpoint') != 'identity' or n.get('metadata_checkpoint') != 'ready'):
            raise ValueError('Binding must not act or read history')
        if private['messages'] is not None or not n.get('chat_identity_verified'):
            raise ValueError('Binding must not read messages')
        # Strip chat-specific schema and reuse the common frame/lifetime validator.
        extras = set(n) - set(_nav_fields())
        for key in extras:
            n.pop(key)
        for key in ('root_top_kind', 'last_presented_kind'):
            if n[key] == 'chat':
                n[key] = 'filters'
        n['controller_path'] = ['filters' if k == 'chat' else k for k in n['controller_path']]
        n['action_backend'] = 'semantic-controller-handlers'
        for key in ('search_verified', 'filters_verified', 'return_verified', 'open_attempted', 'open_completed', 'cancel_attempted', 'cancel_completed'):
            if n[key] is not False:
                raise ValueError('Unexpected action')
            n[key] = True  # Common validator's success chain, not actual actions.
        nav.validate(result)
    else:
        state.validate(result,max_calls=READ_MAX_CALLS)
        messages = private['messages']
        if not isinstance(messages, list) or len(messages) != n['message_count'] or len(messages) > MAX_MESSAGES:
            raise ValueError('Invalid history size')
        seen = set()
        for m in messages:
            if not isinstance(m, dict) or set(m) != {'id', 'sender', 'text'}:
                raise ValueError('Invalid message')
            identity({'account': who['account'], 'peer': who['peer'], 'chat': m['id']})
            if m['id'] in seen or m['sender'] not in (who['account'], who['peer']):
                raise ValueError('Invalid message identity')
            seen.add(m['id'])
            if m['text'] is not None and (not isinstance(m['text'], str) or len(m['text']) > MAX_TEXT or '\x00' in m['text']):
                raise ValueError('Invalid message body')
        if sum(len(m['text'] or '') for m in messages) > MAX_TOTAL_TEXT:
            raise ValueError('Too much text')
    if read_latest:
        latest=private['latest_message_id']
        if latest is not None and (not isinstance(latest,str) or latest not in seen):
            raise ValueError('Latest message is not in verified history')
        if latest is not None and n['last_message_present'] is not True:
            raise ValueError('Latest marker does not match verified history')
    return private


def _nav_fields():
    return {'cleanup_failed','search_verified','filters_verified','return_verified','open_attempted',
            'open_completed','cancel_attempted','cancel_completed','ui_text_read','stage','phase','error',
            'frames','managed_calls','handles_acquired','handles_released','root_top_kind','last_presented_kind',
            'controller_path','action_backend','readiness_check','readiness','view_parent_depth'}
