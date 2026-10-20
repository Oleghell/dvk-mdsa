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

VERSION = '0.3.32'
MAX_MESSAGES = 20
MAX_TEXT = 2048
STATE_FIELDS = {'read_checkpoint','wait_reason','model_actual','model_draft','model_has_cm','cm_present','loaded_field_present','metadata_checkpoint','loaded_value_method_found','loaded_value_return_kind','loaded_value_byref','loaded_value_owner_verified','loaded_value_owner_inherited','loaded_value_owner_scope','loaded_value_static','loaded_value_abstract','loaded_value_arity','history_status','message_count','history_fully_loaded','history_loading','last_message_present','samples','sample_interval_ms','chat_identity_verified','app_actions_attempted','messages_sent'}
ERRORS = state.ERRORS | {'identity-not-bound', 'snapshot-too-large', 'message-invalid', 'snapshot-changing', 'nonpositive-message-id', 'nonpositive-message-sender-id', 'nonpositive-message-chat-id'}


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
   const id64=(entry,obj,label)=>{
    n.scalar_checkpoint=label;n.scalar_state='not-read';
    const box=call(entry,obj);if(box.isNull()){n.scalar_state='missing-box';fail('signature-mismatch');}
    const p=f.unbox(box);if(p.isNull()){n.scalar_state='missing-unbox';fail('signature-mismatch');}
    const value=p.readS64(),sign=value.compare(0);n.scalar_state=sign===0?'zero':sign<0?'negative':'positive';
    if(sign<=0)fail(label.startsWith('message-')?'nonpositive-'+label:'identity-not-bound');
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
   if(first>20)fail('snapshot-too-large');
   const messages=[],seenIds=new Set();let totalText=0;
   const releaseOne=h=>{f.release(h);n.handles_released++;held.splice(held.indexOf(h),1);};
   for(let i=0;i<first;i++){
    n.message_slot=i;
    const index=Memory.alloc(4);index.writeS32(i);const args=Memory.alloc(8);args.writePointer(index);
    const message=call(s.messageItem,cm,args);if(message.isNull()||!f.assignable(s.message,f.objectClass(message)))fail('message-invalid');
    const mh=own(message);n.message_kind=f.assignable(s.textMessage,f.objectClass(message))?'text':'non-text';
    const mine=bool(s.messageMine,message);n.message_direction=mine?'own':'not-own';
    const id=id64(s.messageId,message,'message-id'),sender=id64(s.messageSender,message,'message-sender-id'),chatId=id64(s.messageChat,message,'message-chat-id');
    if(seenIds.has(id)||chatId!==who.chat||![who.account,who.peer].includes(sender)||mine!==(sender===who.account))fail('message-invalid');seenIds.add(id);
    let text=null;
    if(f.assignable(s.textMessage,f.objectClass(message))){
     const value=call(s.messageText,message);if(value.isNull()||!f.objectClass(value).equals(s.stringClass))fail('message-invalid');const sh=own(value);
     const length=f.stringLength(value);if(length<0||length>2048||(totalText+=length)>16384)fail('snapshot-too-large');
     const chars=f.stringChars(value);if(chars.isNull()&&length!==0)fail('message-invalid');
     text=length===0?'':chars.readUtf16String(length);if(text===null||text.includes('\u0000'))fail('message-invalid');releaseOne(sh);
    }
    messages.push({id,sender,text});releaseOne(mh);
   }
   verifyWho();
'''


def build(expected=None):
    expected = identity(expected) if expected is not None else None
    # Use one stable key order on both sides; IDs are literal validated decimals.
    expected = {k: expected[k] for k in ('account', 'peer', 'chat')} if expected else None
    source = state.FUNCTION
    source = replace_once(source, "n.metadata_checkpoint='ready';return s;", "n.metadata_checkpoint='ready';return prepareOneChat(f,s,getClass);")
    source = PREPARE + source
    source = replace_once(source, 'function probeUIKitRoot() {', 'function probeUIKitRoot() {\n const expectedIdentity=' + json.dumps(expected) + ';')
    # The index argument helper originally supported only the modal collection.
    source = replace_once(source, "if(!f.classFromType(f.returnType(m)).equals(s.vc))fail('signature-mismatch');", "if(!f.classFromType(f.returnType(m)).equals(entry.result||s.vc))fail('signature-mismatch');")
    source = replace_once(source, "messages_sent:0};}", "messages_sent:0,private_result:null,scalar_checkpoint:'not-read',scalar_state:'not-read',identity_checkpoint:'not-checked',message_slot:-1,message_kind:'not-read',message_direction:'not-read'};}")
    source = replace_once(source, "save('origin',current);save('card',chat);save('user',user);n.chat_identity_verified=true;", "save('origin',current);save('card',chat);save('user',user);n.chat_identity_verified=true;" + BIND)
    source = replace_once(source, "n.read_checkpoint='recheck';", COLLECT + "\n   n.read_checkpoint='recheck';")
    source = replace_once(source, "const sample={count:first,last:!lastMessage.isNull(),draft:n.model_draft};", "verifyWho();\n   const sample={count:first,last:!lastMessage.isNull(),draft:n.model_draft,identity:who,messages};")
    source = replace_once(source, "state.sample.draft!==sample.draft", "state.sample.draft!==sample.draft||JSON.stringify(state.sample)!==JSON.stringify(sample)")
    source = replace_once(source, "n.read_checkpoint='complete';n.samples=2;", "n.private_result={identity:who,messages};n.read_checkpoint='complete';n.samples=2;")
    source = replace_once(source, "if(n.stage!=='navigation-ready'){n.history_status=", "if(n.stage!=='navigation-ready'){n.private_result=null;n.history_status=")
    source = replace_once(source, json.dumps(sorted(state.ERRORS)), json.dumps(sorted(ERRORS)))
    source = replace_once(source, "classParent:bind('class_get_parent','pointer',['pointer'])", "classParent:bind('class_get_parent','pointer',['pointer']),stringLength:bind('string_length','int',['pointer']),stringChars:bind('string_chars','pointer',['pointer'])")
    source = replace_once(source, json.dumps(__import__('uikit_root').APIS + nav.APIS + ['il2cpp_class_get_parent']), json.dumps(__import__('uikit_root').APIS + nav.APIS + ['il2cpp_class_get_parent', 'il2cpp_string_length', 'il2cpp_string_chars']))
    return source


def private_snapshot(value, expected=None):
    """Validate private RPC data in memory; caller must never dump this object."""
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
        state.validate(result)
        return None
    if not isinstance(private, dict) or set(private) != {'identity', 'messages'}:
        raise ValueError('Invalid private result')
    who = identity(private['identity'])
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
        state.validate(result)
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
        if sum(len(m['text'] or '') for m in messages) > 16384:
            raise ValueError('Too much text')
    return private


def _nav_fields():
    return {'cleanup_failed','search_verified','filters_verified','return_verified','open_attempted',
            'open_completed','cancel_attempted','cancel_completed','ui_text_read','stage','phase','error',
            'frames','managed_calls','handles_acquired','handles_released','root_top_kind','last_presented_kind',
            'controller_path','action_backend','readiness_check','readiness','view_parent_depth'}
