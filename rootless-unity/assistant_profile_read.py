"""Separate verified empty-history sampling, authorization and greeting frames.

Only the assistant's one-profile script is specialized. No host retry of a
profile/chat/send action and no budget increase. A pre-authorization read may
exit via the same pinned chat once, then require verified return before skip.
Legacy unknowns stay held.
"""
from uikit_profile_navigation import replace_once as replace
import cohort_pass
import chat_send_probe

PHASES = {'prepare-greeting', 'submit-greeting'}
DEFAULTS = dict(profile_read_budget_retries=0, greeting_frame_splits=0, profile_ready_waits=0)
SKIP_DEFAULTS = dict(profile_read_skipped=False, profile_read_skip_reason='none', profile_input_enabled=None)
SKIP_REASONS = {'chat-not-actual', 'history-loading', 'history-not-loaded', 'frame-budget', 'input-disabled'}
# A skip is not a successful history read and never an authorization. The next
# native frame must verify the pinned chat before Back; then verify search.
SKIP_GUARD = """n.phase==='check-chat'&&n.chat_open_completed&&n.chat_verified&&n.chat_identity_verified&&
    !n.send_attempted&&!n.send_handler_returned&&cohortPending===null&&cohortApproved===null"""
SKIP = """n.profile_read_skipped=true;n.profile_read_skip_reason=reason;
    state.sample=null;n.samples=0;n.message_count=null;n.history_status='not-ready';
    n.phase='close-chat';state.nextActionAt=Date.now();return;"""

CONTEXT = r'''
    if(k!=='chat'||!current.equals(target(state.chatController)))fail('identity-changed');
    const chat=target(state.chatModelPin),user=target(state.chatUserPin),cm=target(state.chatCMPin);
    if(chat.isNull()||user.isNull()||cm.isNull()||!user.equals(target(state.targetUser))||
     !call(s.chat,current).equals(chat)||!call(s.chatUser,current).equals(user)||
     !call(s.opponent,chat).equals(user)||!call(s.messages,chat).equals(cm))fail('identity-changed');
    if(!n.chat_identity_verified||n.samples!==2||n.history_status!=='empty'||n.message_count!==0||
     n.history_fully_loaded!==true||n.history_loading!==false||n.last_message_present!==false)fail('history-invalid');
    const integer=(entry,obj)=>{const box=call(entry,obj);if(box.isNull())fail('signature-mismatch');const p=f.unbox(box);if(p.isNull())fail('signature-mismatch');return p.readS32();};
    const field=call(s.all,cm);if(field.isNull()||!f.objectClass(field).equals(s.loadedClass))fail('screen-not-ready');own(field);
    if(!bool(s.dialog,chat)||!bool(s.actual,chat)||bool(s.draft,chat)!==n.model_draft||!bool(s.hasCM,chat)||
     !bool(s.input,chat)||bool(s.historyLoading,cm)||!bool(s.value,field)||integer(s.count,cm)!==0||
     !call(s.last,chat).isNull()||bool(s.presenting,current)||bool(s.dismissing,current)||!checkView(current))fail('screen-not-ready');
'''


# Input availability is read from the verified model, never screenshot text.
INPUT_GATE = """n.profile_input_enabled=bool(s.input,chat);
    if(!n.profile_input_enabled&&n.chat_open_completed&&n.chat_verified&&n.chat_identity_verified&&
     !n.send_attempted&&!n.send_handler_returned&&cohortPending===null&&cohortApproved===null){
     const reason='input-disabled';""" + SKIP + "}" 


def specialize(source):
    import json
    source = replace(source, 'r.navigation=emptyNavigation();',
                     'r.navigation=emptyNavigation();Object.assign(r.navigation,'+json.dumps(dict(DEFAULTS, **SKIP_DEFAULTS))+');')
    # Only an identity-verified, not-yet-authorized chat may wait for IsActual.
    # Each wait is a fresh full read, never a cached empty-history decision.
    source = replace(source,
        "if(state.waitSignature===signature&&Date.now()-state.waitAt>=1000)fail('history-not-ready');",
        """if(state.waitSignature===signature&&Date.now()-state.waitAt>=1000){
     if(reason==='chat-not-actual'&&n.phase==='check-chat'&&n.chat_verified&&n.chat_identity_verified&&
      !n.send_attempted&&!n.send_handler_returned&&cohortPending===null&&cohortApproved===null&&n.profile_ready_waits<4){
      n.profile_ready_waits++;
     }else if(['chat-not-actual','history-loading','history-not-loaded'].includes(reason)&&""" + SKIP_GUARD + ") {" + SKIP + """
     }else fail('history-not-ready');
    }""")
    source = replace(source,
        "save('chatUserPin',user);n.chat_identity_verified=true;",
        "save('chatUserPin',user);n.chat_identity_verified=true;\n" + INPUT_GATE)
    a = source.index("   if(first===0){", source.index("   if(n.phase==='check-chat')"))
    b = source.index("   if(n.phase==='search'){", a)
    send = chat_send_probe.SEND.replace("   if(first!==0)fail('chat-not-empty');", '')
    send = send.replace('greetingAttempted', 'batchSent.has(batchCandidateKey)')
    send = send.replace('batchSent.has(batchCandidateKey)=true;',
                        'n.greeting_variant=batchVariants[batchAttempts-1];batchSent.add(batchCandidateKey);')
    send = send.replace('n.app_actions_attempted=true;', '').replace('__GREETING__', 'batchGreetings[batchAttempts-1]')
    # The full two-sample read ends BEFORE reservation preparation. The final
    # gate still runs after durable ACK, on a fresh frame and the same pins.
    source = source[:a] + r'''
   if(first===0){n.greeting_frame_splits++;n.phase='prepare-greeting';state.nextActionAt=Date.now();return;}
   n.phase='close-chat';state.nextActionAt=Date.now()+1000;return;
   }
   if(n.phase==='prepare-greeting'){
''' + CONTEXT.replace("    if(!n.chat_identity_verified", INPUT_GATE + "\n    if(!n.chat_identity_verified") + cohort_pass.RESERVE + r'''
    n.phase='submit-greeting';state.nextActionAt=Date.now();return;
   }
   if(n.phase==='submit-greeting'){
''' + CONTEXT + cohort_pass.RESERVE.split('   if(cohortApproved!==reservationKey){', 1)[0] + "   if(cohortApproved!==reservationKey)fail('identity-changed');\n" + send + r'''
    n.phase='close-chat';state.nextActionAt=Date.now()+1000;return;
   }
''' + source[b:]
    # Recovery is exclusively a fresh read inside the already pinned chat.
    # Never retry after publishing pending authorization or after any send.
    anchor = '} catch(e){state.scanCellBusy=false;'
    source = replace(source, anchor, anchor + r'''
   if(e==='frame-budget'&&n.phase==='check-chat'&&n.chat_open_completed&&n.chat_verified&&
    !n.send_attempted&&!n.send_handler_returned&&cohortPending===null&&cohortApproved===null&&
    n.profile_read_budget_retries<4){
    n.profile_read_budget_retries++;state.sample=null;n.samples=0;n.message_count=null;
    n.history_status='unknown';state.waitSignature=null;state.nextActionAt=Date.now();return;
   }
   if(e==='frame-budget'&&n.profile_read_budget_retries===4&&''' + SKIP_GUARD + r''' ){
    const reason='frame-budget';''' + SKIP + r'''
   }
''')
    return source


def validate(n):
    if not set(DEFAULTS) <= set(n):
        raise ValueError('Missing profile read evidence')
    skip = {key: n.pop(key, default) for key, default in SKIP_DEFAULTS.items()}
    if type(skip['profile_read_skipped']) is not bool or skip['profile_read_skip_reason'] not in SKIP_REASONS | {'none'}:
        raise ValueError('Invalid profile read skip')
    enabled = skip['profile_input_enabled']
    if enabled is not None and type(enabled) is not bool:
        raise ValueError('Invalid verified input flag')
    if skip['profile_read_skip_reason'] == 'input-disabled' and enabled is not False:
        raise ValueError('Input skip without disabled model')
    skipped = skip['profile_read_skipped']
    if skipped != (skip['profile_read_skip_reason'] != 'none'):
        raise ValueError('Missing profile read skip reason')
    if skipped and (n.get('send_attempted') is not False or n.get('send_handler_returned') is not False or
        n.get('chat_verified') is not True or n.get('chat_identity_verified') is not True or
        n.get('history_status') != 'not-ready' or n.get('message_count') is not None or n.get('samples') != 0 or
        n.get('phase') not in {'close-chat','wait-chat-back','confirm-profile','wait-return','done'} or
        (n.get('stage') == 'navigation-ready' and
         (n.get('error') != 'none' or n.get('chat_return_verified') is not True or n.get('return_verified') is not True))):
        raise ValueError('Unverified profile skip')
    if skipped and skip['profile_read_skip_reason'] not in {'frame-budget','input-disabled'} and n.get('wait_reason') != skip['profile_read_skip_reason']:
        raise ValueError('Profile skip without read failure')
    values = {key: n.pop(key) for key in DEFAULTS}
    if skipped and (values['greeting_frame_splits'] != 0 and skip['profile_read_skip_reason'] != 'input-disabled' or
        skip['profile_read_skip_reason'] == 'chat-not-actual' and values['profile_ready_waits'] != 4 or
        skip['profile_read_skip_reason'] == 'frame-budget' and values['profile_read_budget_retries'] != 4):
        raise ValueError('Profile skip before bounded reads')
    for key, maximum in (('profile_read_budget_retries', 4), ('greeting_frame_splits', 1), ('profile_ready_waits', 4)):
        if type(values[key]) is not int or not 0 <= values[key] <= maximum:
            raise ValueError('Invalid profile read counter')
    if values['profile_ready_waits'] and not (n.get('chat_verified') and n.get('chat_identity_verified')):
        raise ValueError('Readiness wait without verified chat')
    if n.get('send_attempted') and values['greeting_frame_splits'] != 1:
        raise ValueError('Greeting submitted without split frame')
    if values['greeting_frame_splits'] and not skipped and (n.get('samples') != 2 or n.get('history_status') != 'empty'):
        raise ValueError('Greeting split without complete empty history')
    if n.get('phase') in PHASES:
        if values['greeting_frame_splits'] != 1 or (n.get('phase') == 'prepare-greeting' and n.get('send_attempted')):
            raise ValueError('Invalid greeting preparation')
        n['phase'] = 'check-chat'

    return skipped and n.get('stage') == 'navigation-ready'
