"""Bounded search/profile/chat/send/back cycle. Fixed UI handlers, no generic RPC."""
import copy,json
import profile_batch as profiles
import uikit_profile_navigation as single
import chat_state_probe as chat
import chat_send_probe as sender
from greetings import choose_index,get_greeting
VERSION='0.3.24'
LIMIT=10
ERRORS=single.base.ERRORS|chat.ERRORS|{'selection-limit','selection-changed','selection-unavailable','input-disabled','send-already-attempted'}
DEFAULTS={
 'scan_yields':0,'scan_slices':0,'chat_metadata_checkpoint':'base','read_checkpoint':'not-checked','wait_reason':'not-checked',
 'loaded_value_method_found':None,'loaded_value_return_kind':None,'loaded_value_byref':None,
 'loaded_value_owner_verified':None,'loaded_value_owner_inherited':None,'loaded_value_owner_scope':None,
 'loaded_value_static':None,'loaded_value_abstract':None,'loaded_value_arity':None,
 'model_actual':None,'model_draft':None,'model_has_cm':None,'cm_present':None,'loaded_field_present':None,
 'history_status':'unknown','message_count':None,'history_fully_loaded':None,'history_loading':None,
 'last_message_present':None,'samples':0,'sample_interval_ms':1000,'chat_identity_verified':False,
 'chat_open_attempted':False,'chat_open_completed':False,'chat_verified':False,
 'chat_back_attempted':False,'chat_back_completed':False,'chat_return_verified':False,'chat_return_route':'not-checked',
 'send_attempted':False,'send_handler_returned':False,'messages_sent':0,'greeting_variant':None}
BOOLS={k for k,v in DEFAULTS.items() if type(v) is bool}
NULL_BOOLS={'loaded_value_method_found','loaded_value_byref','loaded_value_owner_verified','loaded_value_owner_inherited','loaded_value_owner_scope','loaded_value_static','loaded_value_abstract','model_actual','model_draft','model_has_cm','cm_present','loaded_field_present','history_fully_loaded','history_loading','last_message_present'}
PHASES={'open-chat','wait-chat','check-chat','close-chat','wait-chat-back'}
SETUP=r'''
  s.filters=getClass('DV.Messages.dll','DV.Messages','MessagesViewController');
  s.overlay=getClass('DV.Profile.dll','DV.Profiles','ProfileOverlayView');
  if(s.filters.isNull()||s.overlay.isNull())throw new Error('metadata');
  s.overlayField=f.field(s.profile,Memory.allocUtf8String('m_OverlayView'));
  if(s.overlayField.isNull()||!f.fieldOwner(s.overlayField).equals(s.profile)||(f.fieldFlags(s.overlayField)&16))throw new Error('signature');
  const ft=f.fieldType(s.overlayField);if(ft.isNull()||f.typeKind(ft)!==18||f.byref(ft)||!f.classFromType(ft).equals(s.overlay))throw new Error('signature');
  prepareChat(f,s,getClass);
  s.overlayModel=checked(s.overlay,'get_Profile',18,s.profileModel);
  s.startChat=checked(s.overlay,'OnMessageButton',1);
  s.chatBack=checked(s.filters,'DV.Messages.BottomBarView.IDelegate.OnBackButton',1);
  s.send=checked(s.filters,'DV.Messages.BottomBarView.IDelegate.OnSendText',1,null,[{kind:14}]);
  s.input=checked(s.chatModel,'get_IsInputEnabled',2);
'''
PHASE_CODE=r'''
   if(n.phase==='open-chat'){
    if(k!=='profile'||!current.equals(target(state.card))||!verifyProfile(current))fail('identity-changed');
    const model=call(s.contentProfile,target(state.content));if(model.isNull())fail('screen-not-ready');own(model);
    if(!bool(s.friendActual,model)||longInteger(s.friendCount,model).compare(50)>=0)fail('screen-not-ready');
    const out=Memory.alloc(Process.pointerSize);out.writePointer(ptr(0));f.fieldValue(current,s.overlayField,out);
    const overlay=out.readPointer();if(overlay.isNull())fail('screen-not-ready');own(overlay);
    const attached=()=>{let v=overlay;const seen=new Set();for(let i=0;i<32&&!v.isNull();i++){const key=v.toString();if(seen.has(key))fail('view-parent-cycle');seen.add(key);if(v.equals(window))return true;v=call(s.parent,v);if(!v.isNull())own(v);}return false;};
    if(!f.objectClass(overlay).equals(s.overlay)||bool(s.hidden,overlay)||!bool(s.interactive,overlay)||!attached()||!call(s.overlayModel,overlay).equals(model)||!verifyProfile(current))fail('identity-changed');
    n.chat_open_attempted=true;call(s.startChat,overlay);n.chat_open_completed=true;
    n.phase='wait-chat';state.nextActionAt=Date.now()+1000;return;
   }
   if(n.phase==='wait-chat'){
    if(k==='profile'){if(!current.equals(target(state.card))||!verifyProfile(current))fail('identity-changed');return;}
    if(k!=='chat')fail('unexpected-screen');
    const user=call(s.chatUser,current);if(!user.equals(target(state.targetUser)))fail('identity-changed');
    n.chat_verified=true;n.phase='check-chat';state.nextActionAt=Date.now()+1000;return;
   }
   if(n.phase==='close-chat'){
    if(k!=='chat'||!current.equals(target(state.chatController))||!call(s.chatUser,current).equals(target(state.targetUser))||!call(s.chat,current).equals(target(state.chatModelPin)))fail('identity-changed');
    n.chat_back_attempted=true;call(s.chatBack,current);n.chat_back_completed=true;
    n.phase='wait-chat-back';state.nextActionAt=Date.now()+1000;return;
   }
   if(n.phase==='wait-chat-back'){
    if(k==='chat'){if(!current.equals(target(state.chatController)))fail('identity-changed');return;}
    if(k==='search'){
     if(!current.equals(target(state.origin)))fail('identity-changed');
     n.chat_return_route='search';n.chat_return_verified=true;n.return_verified=true;n.phase='done';n.stage='navigation-ready';return;
    }
    if(k!=='profile'||!current.equals(target(state.card))||!verifyProfile(current))fail('identity-changed');
    n.chat_return_route='profile';n.chat_return_verified=true;n.phase='confirm-profile';state.nextActionAt=Date.now()+1000;return;
   }
   if(n.phase==='check-chat'){
    if(k!=='chat')fail('unexpected-screen');
__READ__
   }
'''

def build(variants=None):
    variants=[0]*LIMIT if variants is None else list(variants)
    if len(variants)!=LIMIT:raise ValueError('Exactly ten bounded greeting choices are required')
    for i in variants:get_greeting(i)
    replace=single.replace_once
    from search_scan import specialize
    s=profiles.FUNCTION
    # Reuse exact semantic profile selection and its in-memory uniqueness set.
    s=replace(s,' function prepareProfile(',chat.EXTRA.replace('n.metadata_checkpoint','n.chat_metadata_checkpoint')+'\n function prepareProfile(')
    s=replace(s,"  if(s.friendCount===null)throw new Error('signature');",SETUP+"  if(s.friendCount===null)throw new Error('signature');")
    init='Object.assign(r.navigation,'+json.dumps(DEFAULTS,separators=(',',':'))+');'
    s=replace(s,'r.navigation=emptyNavigation();','r.navigation=emptyNavigation();'+init)
    s=replace(s,"if(klass.equals(s.search))return 'search';", "if(klass.equals(s.filters))return 'chat';if(klass.equals(s.search))return 'search';")
    s=replace(s,"if(k==='search'||k==='profile'){","if(k==='search'||k==='profile'||k==='chat'){")
    s=replace(s,"!['search','profile'].includes(k)","!['search','profile','chat'].includes(k)")
    s=replace(s,"    n.close_attempted=true;", "    if(n.friends_status!=='read')fail('screen-not-ready');\n    if(n.friends_eligible&&!n.chat_open_attempted){n.phase='open-chat';state.nextActionAt=Date.now()+1000;return;}\n    n.close_attempted=true;")
    read=chat.READ
    read=replace(read,"   if(!f.objectClass(user).equals(s.user))fail('unexpected-object');","   if(!f.objectClass(user).equals(s.user)||!user.equals(target(state.targetUser)))fail('identity-changed');")
    for old,new in [('origin','chatController'),('card','chatModelPin'),('user','chatUserPin'),('cm','chatCMPin')]:
        read=read.replace("save('"+old+"',","save('"+new+"',")
    ending="   n.read_checkpoint='complete';n.samples=2;n.message_count=first;n.history_status=first===0?'empty':'not-empty';n.phase='done';n.stage='navigation-ready';"
    send=sender.SEND.replace("   if(first!==0)fail('chat-not-empty');",'')
    send=send.replace('greetingAttempted','batchSent.has(batchCandidateKey)')
    send=send.replace('batchSent.has(batchCandidateKey)=true;', 'batchSent.add(batchCandidateKey);')
    send=send.replace('n.app_actions_attempted=true;','')
    send=send.replace('__GREETING__','batchGreetings[batchAttempts-1]')
    send=send.replace("batchSent.add(batchCandidateKey);", "n.greeting_variant=batchVariants[batchAttempts-1];batchSent.add(batchCandidateKey);")
    read=replace(read,ending,"   n.read_checkpoint='complete';n.samples=2;n.message_count=first;n.history_status=first===0?'empty':'not-empty';\n   if(first===0){\n"+send+"   }\n   n.phase='close-chat';state.nextActionAt=Date.now()+1000;return;")
    phases=PHASE_CODE.replace('__READ__',read)
    s=replace(s,"   if(n.phase==='search'){\n    n.search_verified=true;",phases+"   if(n.phase==='search'){\n    n.search_verified=true;")
    s=replace(s,"['content','targetUser','card','origin']","['chatCMPin','chatUserPin','chatModelPin','chatController','content','targetUser','card','origin']")
    s=replace(s,'content:ptr(0),targetUser:ptr(0),selectionRow:0,nextActionAt:0,stop:null', 'content:ptr(0),targetUser:ptr(0),chatCMPin:ptr(0),chatUserPin:ptr(0),chatModelPin:ptr(0),chatController:ptr(0),sample:null,waitSignature:null,waitAt:0,selectionRow:0,nextActionAt:0,stop:null')
    apis=single.ROOT_APIS+single.base.APIS+single.EXTRA_APIS
    extra=['il2cpp_class_get_parent','il2cpp_string_new','il2cpp_class_get_field_from_name','il2cpp_field_get_type','il2cpp_field_get_flags','il2cpp_field_get_parent','il2cpp_field_get_value']
    s=replace(s,json.dumps(apis),json.dumps(apis+extra))
    old="declaring:bind('class_get_declaring_type','pointer',['pointer'])"
    more=",classParent:bind('class_get_parent','pointer',['pointer']),newString:bind('string_new','pointer',['pointer']),field:bind('class_get_field_from_name','pointer',['pointer','pointer']),fieldType:bind('field_get_type','pointer',['pointer']),fieldFlags:bind('field_get_flags','uint32',['pointer']),fieldOwner:bind('field_get_parent','pointer',['pointer']),fieldValue:bind('field_get_value','void',['pointer','pointer','pointer'])"
    s=replace(s,old,old+more)
    s=replace(s,"'DV.Profile.dll','UIKit.Unity.dll'", "'DV.Profile.dll','DV.Messages.dll','UIKit.Unity.dll'")
    olderrors=json.dumps(sorted(single.base.ERRORS|{'selection-limit','selection-changed','selection-unavailable'}))
    # The profile specialization may retain the base error list, augmented by its own builder.
    if olderrors not in s:olderrors=json.dumps(sorted(single.base.ERRORS))
    s=replace(s,olderrors,json.dumps(sorted(ERRORS)))
    s=specialize(s)
    return 'const batchVariants='+json.dumps(variants)+';const batchGreetings='+json.dumps([get_greeting(i) for i in variants])+';const batchSent=new Set();\n'+s

def build_random():return build([choose_index() for _ in range(LIMIT)])
FUNCTION=build()

def validate(value):
    v=copy.deepcopy(value)
    if not isinstance(v,dict) or not isinstance(v.get('navigation'),dict):raise ValueError('Missing automatic navigation')
    n=v['navigation']
    if not set(DEFAULTS)<=set(n):raise ValueError('Missing chat cycle fields')
    x={k:n.pop(k) for k in DEFAULTS}
    for k in BOOLS:
        if type(x[k]) is not bool:raise ValueError('Invalid chat action flag')
    for k in NULL_BOOLS:
        if x[k] is not None and type(x[k]) is not bool:raise ValueError('Invalid chat state flag')
    if x['chat_metadata_checkpoint'] not in chat.CHECKPOINTS or x['read_checkpoint'] not in chat.READ_STEPS or x['wait_reason'] not in chat.WAIT_REASONS:raise ValueError('Invalid chat checkpoint')
    if any(type(x[k]) is not int or not 0<=x[k]<=180 for k in ('scan_yields','scan_slices')) or x['scan_yields']>8:raise ValueError('Invalid cooperative scan counters')
    if type(x['samples']) is not int or not 0<=x['samples']<=2 or type(x['sample_interval_ms']) is not int or x['sample_interval_ms']!=1000:raise ValueError('Invalid history samples')
    if x['history_status'] not in {'unknown','not-ready','checking','empty','not-empty'}:raise ValueError('Invalid history state')
    for k in ('loaded_value_arity','loaded_value_return_kind'):
        if x[k] is not None and (type(x[k]) is not int or not 0<=x[k]<=255):raise ValueError('Invalid metadata diagnostic')
    chain=['chat_open_attempted','chat_open_completed','chat_verified','chat_identity_verified','chat_back_attempted','chat_back_completed','chat_return_verified']
    for a,b in zip(chain,chain[1:]):
        if x[b] and not x[a]:raise ValueError('Chat action out of order')
    if x['chat_open_attempted'] and n.get('friends_eligible') is not True:raise ValueError('Chat without eligible profile')
    route=x['chat_return_route']
    if route not in {'not-checked','profile','search'} or (route!='not-checked')!=x['chat_return_verified']:raise ValueError('Invalid chat return route')
    if route=='search':
        if n.get('phase')!='done' or n.get('stage')!='navigation-ready' or not n.get('return_verified') or n.get('close_attempted') or n.get('close_completed') or n.get('controller_path',[])[-1:]!=['search']:raise ValueError('Unverified direct search return')
        # Only the validation copy adapts the legacy close-before-return invariant.
        # The actual report retains close_attempted=False/close_completed=False.
        n['close_attempted']=True;n['close_completed']=True

    if x['send_handler_returned'] and not x['send_attempted']:raise ValueError('Submission without invocation')
    if x['send_attempted']:
        get_greeting(x['greeting_variant'])
        if x['messages_sent'] is not None or not x['chat_identity_verified'] or n.get('friends_eligible') is not True:raise ValueError('Unverified send')
    elif x['greeting_variant'] is not None or type(x['messages_sent']) is not int or x['messages_sent']!=0:raise ValueError('False submission state')
    classified=x['history_status'] in ('empty','not-empty')
    if classified:
        count=x['message_count']
        if type(count) is not int or not 0<=count<=1000000 or (count==0)!=(x['history_status']=='empty'):raise ValueError('Invalid chat count')
        if x['chat_metadata_checkpoint']!='ready' or x['read_checkpoint']!='complete' or x['wait_reason']!='none' or type(x['loaded_value_owner_inherited']) is not bool or x['samples']!=2 or not x['chat_identity_verified'] or x['history_fully_loaded'] is not True or x['history_loading'] is not False or x['model_actual'] is not True or type(x['model_draft']) is not bool or any(x[k] is not True for k in ('model_has_cm','cm_present','loaded_field_present','loaded_value_method_found','loaded_value_owner_verified','loaded_value_owner_scope')) or x['loaded_value_return_kind']!=2 or x['loaded_value_byref'] is not False or x['loaded_value_static'] is not False or x['loaded_value_abstract'] is not False or x['loaded_value_arity']!=0:raise ValueError('Unverified history classification')
        if count==0 and x['last_message_present'] is not False:raise ValueError('Contradictory empty history')
    elif x['message_count'] is not None:raise ValueError('Unknown count must remain unknown')
    if x['send_attempted'] and (not classified or x['history_status']!='empty'):raise ValueError('Send without stable empty history')
    if n.get('stage')=='navigation-ready':
        if n.get('friends_eligible'):
            if not x['chat_return_verified'] or not classified:raise ValueError('Unfinished chat cycle')
            if x['history_status']=='empty' and not x['send_handler_returned']:raise ValueError('Empty cycle did not submit')
        elif x['chat_open_attempted']:raise ValueError('Skipped profile opened chat')
    if n.get('phase') in PHASES:n['phase']='confirm-profile'
    for k in ('root_top_kind','last_presented_kind'):
        if n.get(k)=='chat':n[k]='profile'
    if isinstance(n.get('controller_path'),list):n['controller_path']=['profile' if k=='chat' else k for k in n['controller_path']]
    if n.get('error') not in ERRORS:raise ValueError('Unknown cycle error')
    if n['error'] not in single.base.ERRORS and n['error'] not in {'selection-limit','selection-changed','selection-unavailable'}:n['error']='screen-not-ready'
    single.validate(v)
    return value

def run(root,cancelled=lambda:False,progress=lambda text:None):
    out={'limit':LIMIT,'status':'batch-stopped','reason':'not-started','attempts':0,'visited':0,'checked':0,'eligible':0,'skipped':0,'unknown':0,'errors':0,'chats_checked':0,'not_empty':0,'send_attempts':0,'handlers_returned':0,'delivery_confirmed':False,'profile_may_remain_open':False,'messages_sent':0,'unique_scope':'current-run','identity_keys_recorded':False,'items':[]}
    for number in range(1,LIMIT+1):
        if cancelled():out.update(status='batch-cancelled',reason='cancelled');break
        out['attempts']+=1;progress(f'Автопроход {number}/{LIMIT}…')
        try:value=validate(root())
        except Exception:out.update(reason='probe-failed',errors=1,profile_may_remain_open=True,messages_sent=None,send_attempts=None,handlers_returned=None);break
        n=value['navigation'];item={k:n[k] for k in ('stage','error','scan_yields','scan_slices','friends_status','friends_count','friends_eligible','chat_open_attempted','chat_return_verified','chat_return_route','history_status','message_count','send_attempted','send_handler_returned','greeting_variant')};item.update(number=number,opened=n['open_attempted'],returned=n['return_verified']);out['items'].append(item)
        out['profile_may_remain_open']=n['open_attempted'] and not n['return_verified']
        out['send_attempts']+=int(n['send_attempted']);out['handlers_returned']+=int(n['send_handler_returned'])
        if n['send_attempted']:out['messages_sent']=None
        if n['history_status'] in ('empty','not-empty'):out['chats_checked']+=1
        if n['history_status']=='not-empty':out['not_empty']+=1
        if n['profile_verified']:out['visited']+=1
        if n['friends_status']=='read':out['checked']+=1;out['eligible' if n['friends_eligible'] else 'skipped']+=1
        if n['stage']!='navigation-ready':
            if n['error']=='selection-unavailable' and not n['open_attempted']:out.update(status='batch-exhausted',reason='visible-exhausted')
            elif n['error']=='cancelled':out.update(status='batch-cancelled',reason='cancelled')
            else:out.update(reason=n['error'] if n['error']!='none' else 'metadata-not-ready',errors=1)
            break
    else:out.update(status='batch-completed',reason='limit-reached')
    return out

def start(adb,folder,progress=lambda text:None,cancelled=lambda:False):
    from diagnose_device import diagnose,TestError
    lock=folder/'.dvk-ten-profile-pass.lock'
    try:
        with lock.open('x',encoding='utf-8') as f:f.write('One bounded automatic pass reserved. Do not resume blindly.\n');f.flush();__import__('os').fsync(f.fileno())
    except FileExistsError:raise TestError('Автопроход уже запускался. Повтор заблокирован; проверь прошлый отчёт и чат.')
    result,path=diagnose(adb,folder,progress,cancelled,automatic_probe=True)
    b=result.get('gadget',{}).get('batch')
    if b is not None and b.get('send_attempts')==0 and b.get('messages_sent')==0 and b.get('reason')!='probe-failed':lock.unlink(missing_ok=True)
    return result,path
