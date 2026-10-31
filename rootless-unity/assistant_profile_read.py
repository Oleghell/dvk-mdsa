"""Separate verified empty-history sampling, authorization and greeting frames.

Only the assistant's one-profile script is specialized. No host retry of a
profile/chat/send action and no budget increase. A pre-authorization read may
exit via the same pinned chat once, then require verified return before skip.
Legacy unknowns stay held.
"""
from uikit_profile_navigation import CHAT_OPEN_WAIT_LIMIT, replace_once as replace
import cohort_pass
import chat_send_probe

PHASES = {'prepare-greeting', 'submit-greeting'}
# v1.3.99 (twelve ports at once): the ACKed submit-greeting frame carries the
# whole re-verified context plus the send invocation inside ONE 100ms tick.
# Under a loaded multi-port MuMu host that tick regularly blows its budget at
# the send call - previously AFTER the latch, which recorded a never-invoked
# greeting as 'attempted-unknown' (claim held, chat parked open until
# recovery backed out, peer never greeted). The pre-latch guards in
# chat_send_probe.SEND now fail such a tick as NOT-invoked, and the send
# frame gets its OWN bounded retry budget (submit_frame_retries, 8 fresh
# frames) on top of the shared read budget, so the greeting lands on a later
# frame instead of dying with the whole cycle.
SUBMIT_FRAME_RETRY_LIMIT = 8
DEFAULTS = dict(profile_read_budget_retries=0, greeting_frame_splits=0, profile_ready_waits=0,
                submit_frame_retries=0)
SKIP_DEFAULTS = dict(profile_read_skipped=False, profile_read_skip_reason='none', profile_input_enabled=None)
SKIP_REASONS = {'chat-not-actual', 'history-loading', 'history-not-loaded', 'frame-budget', 'input-disabled',
                'chat-not-opened', 'submit-frame-budget'}
# A skip is not a successful history read and never an authorization. The next
# native frame must verify the pinned chat before Back; then verify search.
SKIP_GUARD = """n.phase==='check-chat'&&n.chat_open_completed&&n.chat_verified&&n.chat_identity_verified&&
    !n.send_attempted&&!n.send_handler_returned&&cohortPending===null&&cohortApproved===null"""
SKIP = """n.profile_read_skipped=true;n.profile_read_skip_reason=reason;
    state.sample=null;n.samples=0;n.message_count=null;n.history_status='not-ready';
    n.phase='close-chat';state.nextActionAt=Date.now();return;"""

# Reports 484/489 (v1.3.72, twelve ports started at once): while the host
# authorization waits out shared-pooler retries, the fixed 100ms re-pend made
# the native side re-run the full verified context about ten times a second,
# burning the whole 6000-call budget in ~20s and stopping a healthy cycle at
# call-limit in prepare-greeting. The waits now double up to 3200ms: the common
# fast approval is still picked up at the first 100ms re-check, and a slow
# approval costs a bounded number of fresh full re-verifications instead of the
# whole budget. The submit gate still re-verifies identity/history on a fresh
# frame after the durable ACK.
PEND_BACKOFF = ("cohortPending=reservation;"
    "state.cohortWaits=(state.cohortWaits||0)+1;"
    "state.nextActionAt=Date.now()+100*Math.pow(2,Math.min(state.cohortWaits-1,5));"
    "return;")

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
    # v1.3.92 (user report: «заходит в новую анкету, сидит там и не отписывает
    # приветствие»): OnMessageButton was invoked but the chat screen never
    # appeared - the old wait-chat phase re-verified the profile forever, so
    # the cycle parked ON THE OPEN ANKETA until the whole 90-second native
    # budget, stopped the pass and pushed the port into recovery rounds. The
    # wait is now counted: after CHAT_OPEN_WAIT_LIMIT one-second polls the
    # cycle records a verified 'chat-not-opened' skip and routes itself into
    # the existing confirm-profile close gate, which closes the anketa with
    # the same verified evidence used for every other skip. The pass then
    # continues on the next candidate instead of sitting silently.
    source = replace(source, """if(n.phase==='wait-chat'){
    if(k==='profile'){if(!current.equals(target(state.card))||!verifyProfile(current))fail('identity-changed');return;}""",
                    """if(n.phase==='wait-chat'){
    if(k==='profile'){
     if(!current.equals(target(state.card))||!verifyProfile(current))fail('identity-changed');
     if(n.chat_open_waits<""" + str(CHAT_OPEN_WAIT_LIMIT) + """){n.chat_open_waits++;state.nextActionAt=Date.now()+1000;return;}
     n.profile_read_skipped=true;n.profile_read_skip_reason='chat-not-opened';
     state.sample=null;n.samples=0;n.message_count=null;n.history_status='not-ready';
     n.phase='confirm-profile';state.nextActionAt=Date.now()+1000;return;
    }""")
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
    # The app can briefly show the SAME profile again while chat navigation
    # settles. Observe only; never call StartChat twice or accept a different ID.
    source = replace(source, "   if(n.phase==='check-chat'){\n    if(k!=='chat')fail('unexpected-screen');",
        """   if(n.phase==='check-chat'){
    if(k==='profile'&&current.equals(target(state.card))&&verifyProfile(current)&&
     n.chat_open_completed&&n.chat_verified&&!n.send_attempted&&cohortPending===null&&cohortApproved===null&&(state.chatTransitionWaits||0)<3){
     state.chatTransitionWaits=(state.chatTransitionWaits||0)+1;state.nextActionAt=Date.now()+100;return;
    }
    if(k!=='chat')fail('unexpected-screen');""")
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
''' + CONTEXT.replace("    if(!n.chat_identity_verified", INPUT_GATE + "\n    if(!n.chat_identity_verified") + cohort_pass.RESERVE.replace("cohortPending=reservation;state.nextActionAt=Date.now()+1000;return;", PEND_BACKOFF) + r'''
    n.phase='submit-greeting';state.nextActionAt=Date.now();return;
   }
   if(n.phase==='submit-greeting'){
''' + CONTEXT + cohort_pass.RESERVE.split('   if(cohortApproved!==reservationKey){', 1)[0] + "   if(cohortApproved!==reservationKey)fail('identity-changed');\n" + send + r'''
    n.phase='close-chat';state.nextActionAt=Date.now()+1000;return;
   }
''' + source[b:]
    # Recovery is exclusively a fresh read inside the already pinned chat.
    # Greeting checks can resume on a fresh frame, but never after any send.
    anchor = '} catch(e){state.scanCellBusy=false;'
    source = replace(source, anchor, anchor + r'''
   if(e==='frame-budget'&&['prepare-greeting','submit-greeting'].includes(n.phase)&&
    n.chat_open_completed&&n.chat_verified&&n.chat_identity_verified&&n.greeting_frame_splits===1&&
    !n.send_attempted&&!n.send_handler_returned&&n.profile_read_budget_retries<4){
    n.profile_read_budget_retries++;state.nextActionAt=Date.now();return;
   }
   if(e==='frame-budget'&&n.phase==='submit-greeting'&&cohortApproved!==null&&
    n.chat_open_completed&&n.chat_verified&&n.chat_identity_verified&&n.greeting_frame_splits===1&&
    !n.send_attempted&&!n.send_handler_returned&&n.submit_frame_retries<__SUBMIT_FRAME_RETRY_LIMIT__){
    // v1.3.99 (twelve ports at once): the ACKed greeting submit gets its own
    // bounded fresh-frame budget - the send itself must not starve because
    // the read phases already consumed the shared 4-retry budget under load.
    // Only a frame that never opened the send latch retries; the latch plus
    // the pre-latch guards in the SEND block keep every post-invoke failure
    // an unknown that is never replayed.
    n.submit_frame_retries++;state.nextActionAt=Date.now();return;
   }
   if(e==='frame-budget'&&n.phase==='submit-greeting'&&cohortApproved!==null&&
    n.chat_open_completed&&n.chat_verified&&n.chat_identity_verified&&n.greeting_frame_splits===1&&
    !n.send_attempted&&!n.send_handler_returned&&n.submit_frame_retries===__SUBMIT_FRAME_RETRY_LIMIT__){
    // v1.3.99 (twelve ports at once): even the dedicated fresh frames could
    // not fit the ACKed send - the host is saturated. The chat is closed with
    // the same verified evidence every other skip uses (no open-dialog park,
    // no recovery round) and the pass continues; the host releases the
    // committed claim (assistant_pass) so another port can still greet the
    // peer instead of a 24-hour claimed-but-never-greeted shield.
    const reason='submit-frame-budget';''' + SKIP + r'''
   }
   if(e==='frame-budget'&&n.phase==='check-chat'&&n.chat_open_completed&&n.chat_verified&&
    !n.send_attempted&&!n.send_handler_returned&&cohortPending===null&&cohortApproved===null&&
    n.profile_read_budget_retries<4){
    n.profile_read_budget_retries++;state.sample=null;n.samples=0;n.message_count=null;
    n.history_status='unknown';state.waitSignature=null;state.nextActionAt=Date.now();return;
   }
   if(e==='frame-budget'&&['wait-profile','confirm-profile'].includes(n.phase)&&
    n.open_completed&&!n.close_attempted&&!n.chat_open_attempted&&
    !n.send_attempted&&!n.send_handler_returned&&n.profile_read_budget_retries<4){
    // Reports 9104352d snapshots 626/628/631/633 (v1.3.99): a slow observation
    // tick between the opened anketa and its content/friends read stopped the
    // whole profile cycle (profile-check-stopped, profile_read_budget_retries=0)
    // and parked the port in recovery rounds. The wait-profile/confirm-profile
    // tick is pure observation: the open already completed and the close
    // latch (!n.close_attempted) guarantees no uncertain mutating cancel is
    // ever retried - the same bounded budget the check-chat phase uses.
    n.profile_read_budget_retries++;state.nextActionAt=Date.now();return;
   }
   if(e==='frame-budget'&&n.profile_read_budget_retries===4&&''' + SKIP_GUARD + r''' ){
    const reason='frame-budget';''' + SKIP + r'''
   }
''')
    source = source.replace('__SUBMIT_FRAME_RETRY_LIMIT__', str(SUBMIT_FRAME_RETRY_LIMIT))
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
    chat_open_skip = skipped and skip['profile_read_skip_reason'] == 'chat-not-opened'
    if chat_open_skip:
        # The chat open was attempted and counted to its bound, the screen
        # stayed on the profile, and the anketa itself is what gets closed and
        # returned - so the chat-side evidence is exactly the inverse of the
        # read-skip forms above.
        if (n.get('send_attempted') is not False or n.get('send_handler_returned') is not False or
            n.get('chat_open_attempted') is not True or n.get('chat_open_completed') is not True or
            n.get('chat_verified') is not False or n.get('chat_identity_verified') is not False or
            n.get('chat_back_attempted') is not False or n.get('chat_back_completed') is not False or
            n.get('chat_return_verified') is not False or n.get('chat_return_route') != 'not-checked' or
            n.get('chat_open_waits') != CHAT_OPEN_WAIT_LIMIT or
            n.get('friends_eligible') is not True or
            n.get('history_status') != 'not-ready' or n.get('message_count') is not None or n.get('samples') != 0 or
            n.get('phase') not in {'confirm-profile', 'wait-return', 'done'} or
            (n.get('stage') == 'navigation-ready' and
             (n.get('error') != 'none' or n.get('return_verified') is not True or n.get('close_completed') is not True))):
            raise ValueError('Unverified chat-open skip')
    elif skipped and (n.get('send_attempted') is not False or n.get('send_handler_returned') is not False or
        n.get('chat_verified') is not True or n.get('chat_identity_verified') is not True or
        n.get('history_status') != 'not-ready' or n.get('message_count') is not None or n.get('samples') != 0 or
        n.get('phase') not in {'close-chat','wait-chat-back','confirm-profile','wait-return','done'} or
        (n.get('stage') == 'navigation-ready' and
         (n.get('error') != 'none' or n.get('chat_return_verified') is not True or n.get('return_verified') is not True))):
        raise ValueError('Unverified profile skip')
    if skipped and skip['profile_read_skip_reason'] not in {'frame-budget','input-disabled','chat-not-opened','submit-frame-budget'} and n.get('wait_reason') != skip['profile_read_skip_reason']:
        raise ValueError('Profile skip without read failure')
    values = {key: n.pop(key) for key in DEFAULTS}
    if skipped and (values['greeting_frame_splits'] != 0 and skip['profile_read_skip_reason'] not in {'input-disabled','submit-frame-budget'} or
        skip['profile_read_skip_reason'] == 'chat-not-actual' and values['profile_ready_waits'] != 4 or
        skip['profile_read_skip_reason'] == 'frame-budget' and values['profile_read_budget_retries'] != 4 or
        skip['profile_read_skip_reason'] == 'submit-frame-budget' and (values['submit_frame_retries'] != SUBMIT_FRAME_RETRY_LIMIT or values['greeting_frame_splits'] != 1)):
        raise ValueError('Profile skip before bounded reads')
    for key, maximum in (('profile_read_budget_retries', 4), ('greeting_frame_splits', 1), ('profile_ready_waits', 4),
                         ('submit_frame_retries', SUBMIT_FRAME_RETRY_LIMIT)):
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

    # v1.3.92: the caller needs to know WHICH verified skip form this is - the
    # unready-chat read skip keeps the chat-side evidence contract, while the
    # chat-not-opened skip proves the chat never appeared at all.
    return (skipped and not chat_open_skip and n.get('stage') == 'navigation-ready',
            chat_open_skip and n.get('stage') == 'navigation-ready')
