"""One fixed greeting in the currently visible, twice-verified empty dialog."""
import copy,json
import chat_state_probe as state
from greetings import GREETINGS,get_greeting,choose_index
from uikit_profile_navigation import replace_once
VERSION='0.3.27'
GREETING=GREETINGS[0]
ERRORS=state.ERRORS|{'chat-not-empty','input-disabled','send-already-attempted'}
SEND_SETUP=r"""
  const send=f.method(s.filters,Memory.allocUtf8String('DV.Messages.BottomBarView.IDelegate.OnSendText'),1),bits=Memory.alloc(4);bits.writeU32(0);
  if(send.isNull()||f.arity(send)!==1||(f.flags(send,bits)&(16|1024))||!f.methodClass(send).equals(s.filters)||f.typeKind(f.returnType(send))!==1||f.byref(f.returnType(send)))throw new Error('signature');
  const param=f.param(send,0);if(param.isNull()||f.typeKind(param)!==14||f.byref(param))throw new Error('signature');
  s.send={m:send,klass:s.filters,kind:1,arity:1};s.input=checked(s.chatModel,'get_IsInputEnabled',2);
  if(greetingAttempted)throw new Error('signature');
"""
SEND=r"""
   if(first!==0)fail('chat-not-empty');
   if(greetingAttempted)fail('send-already-attempted');
   if(!bool(s.input,chat))fail('input-disabled');
   const text=f.newString(Memory.allocUtf8String(__GREETING__));if(text.isNull())fail('unexpected-object');own(text);
   const args=Memory.alloc(Process.pointerSize);args.writePointer(text);
   // Revalidate the same target after allocation. No routing, draft editing or navigation.
   if(!resolve(candidate).equals(current)||!call(s.chat,current).equals(chat)||!call(s.chatUser,current).equals(user)||!call(s.messages,chat).equals(cm))fail('identity-changed');
   if(!bool(s.actual,chat)||bool(s.draft,chat)!==n.model_draft||!bool(s.hasCM,chat)||!bool(s.input,chat)||bool(s.historyLoading,cm)||!bool(s.value,field)||integer(s.count,cm)!==0||!call(s.last,chat).isNull()||!checkView(current))fail('screen-not-ready');
   // Reports 9104352d (v1.3.99, twelve ports at once): the frame-budget check
   // inside call() fired AFTER the send latch, so one slow 100ms tick at the
   // invocation turned a never-invoked greeting into 'attempted-unknown' -
   // the chat sat open until recovery backed out of it, the claim stayed
   // held for its whole window and the peer never received the greeting.
   // The reply path already orders its guards BEFORE its latch
   // (one_chat_send); the greeting now mirrors that doctrine: an exhausted
   // tick or a pending stop fails as NOT-invoked, so the bounded greeting
   // frame retry takes a fresh frame instead of dying as an unknown send.
   // (The reversed comparison is deliberate: search_scan pins the exact
   // call()-inner spelling to a single occurrence in the composed source.)
   if(deadline<Date.now())fail('frame-budget');
   if(state.stop!==null)fail(state.stop);
   if(fixedCancellationRequested)fail('cancelled');
   // Latch immediately before the invocation itself: an exception, a
   // cancellation or a lost response after this point never cause a retry.
   greetingAttempted=true;n.send_attempted=true;n.app_actions_attempted=true;n.messages_sent=null;
   call(s.send,current,args);n.send_handler_returned=true;
"""
def build(greeting_index=0):
    greeting=get_greeting(greeting_index)
    s=state.FUNCTION
    s=replace_once(s,"  n.metadata_checkpoint='ready';return s;",SEND_SETUP+"  n.metadata_checkpoint='ready';return s;")
    s=replace_once(s,'app_actions_attempted:false,messages_sent:0','app_actions_attempted:false,messages_sent:0,send_attempted:false,send_handler_returned:false,greeting_variant:'+str(greeting_index))
    s=replace_once(s,"action_backend:'read-only-chat-state'","action_backend:'one-greeting-handler'")
    s=replace_once(s,'if(entry.arity===1){',"if(entry.arity===1&&entry.kind!==1){")
    s=replace_once(s,'   const flags2=Memory.alloc(4);',"   if(entry.arity===1&&entry.kind===1){const p=f.param(m,0);if(p.isNull()||f.typeKind(p)!==14||f.byref(p))fail('signature-mismatch');}\n   const flags2=Memory.alloc(4);")
    s=replace_once(s,"   n.read_checkpoint='complete';n.samples=2;",SEND.replace('__GREETING__',json.dumps(greeting))+"   n.read_checkpoint='complete';n.samples=2;")
    s=replace_once(s,"classParent:bind('class_get_parent','pointer',['pointer'])","classParent:bind('class_get_parent','pointer',['pointer']),newString:bind('string_new','pointer',['pointer'])")
    # Extend the checked export inventory; do not introduce a generic execution RPC.
    s=replace_once(s,'"il2cpp_class_get_parent"]','"il2cpp_class_get_parent", "il2cpp_string_new"]')
    s=replace_once(s,json.dumps(sorted(state.ERRORS)),json.dumps(sorted(ERRORS)))
    return 'let greetingAttempted=false;\n'+s
def build_random():
    return build(choose_index())

FUNCTION=build()
def validate(value):
    v=copy.deepcopy(value);n=v.get('navigation',{})
    get_greeting(n.pop('greeting_variant',None))
    attempted=n.pop('send_attempted',None);returned=n.pop('send_handler_returned',None)
    if type(attempted) is not bool or type(returned) is not bool or (returned and not attempted):raise ValueError('Invalid send state')
    if n.get('action_backend')!='one-greeting-handler' or n.get('app_actions_attempted') is not attempted:raise ValueError('Invalid send backend')
    if (attempted and n.get('messages_sent') is not None) or (not attempted and (type(n.get('messages_sent')) is not int or n['messages_sent']!=0)):raise ValueError('Delivery is not confirmed')
    if n.get('stage')=='navigation-ready' and (not returned or n.get('history_status')!='empty'):raise ValueError('Unverified submission')
    if n.get('error') not in ERRORS:raise ValueError('Invalid send stop')
    if n['error'] not in state.ERRORS:n['error']='screen-not-ready'
    n.update(action_backend='read-only-chat-state',app_actions_attempted=False,messages_sent=0)
    state.validate(v)
    return value

def send_once(adb,folder,progress=lambda text:None,cancelled=lambda:False):
    from diagnose_device import diagnose,TestError
    lock=folder/'.dvk-one-greeting.lock'
    try:
        with lock.open('x',encoding='utf-8') as f:f.write('One greeting attempt reserved. Delivery may be unknown. Do not retry blindly.\n');f.flush();__import__('os').fsync(f.fileno())
    except FileExistsError:raise TestError('Повтор заблокирован: проверь чат вручную. Файл .dvk-one-greeting.lock сохранён.')
    result,path=diagnose(adb,folder,progress,cancelled,chat_send_probe=True)
    n=result.get('gadget',{}).get('uikit_root',{}).get('navigation',{})
    # Only a complete validated response explicitly ruling out invocation releases the reservation.
    if n.get('send_attempted') is False:lock.unlink(missing_ok=True)
    return result,path
