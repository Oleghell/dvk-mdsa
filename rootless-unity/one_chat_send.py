"""One validated short reply in the exact bound dialog.

Caller commits authorization before submission. Default retains the manual
test question; automatic callers may use templates or validated AI drafts.
No arbitrary text, navigation, typing imitation or retries.
"""
from chat_limits import MAX_MESSAGES, MAX_TEXT, MAX_TOTAL_TEXT

import copy
import json
from one_chat_preview import QUESTION
import one_chat_probe as reader
from uikit_profile_navigation import replace_once

ERRORS = reader.ERRORS | {'submission-already-attempted', 'submission-snapshot-changed', 'input-disabled'}
FLAGS = {'submission_attempted', 'submission_returned'}


def checked(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {'identity', 'messages'}:
        raise ValueError('Invalid submission snapshot')
    who = reader.identity(snapshot['identity'])
    messages = snapshot['messages']
    if not isinstance(messages, list) or not 1 <= len(messages) < MAX_MESSAGES:
        raise ValueError('No room for one test reply')
    seen = set()
    for m in messages:
        if not isinstance(m, dict) or set(m) != {'id','sender','text'}:
            raise ValueError('Invalid submission message')
        reader.identity(dict(account=who['account'], peer=who['peer'], chat=m['id']))
        if m['id'] in seen or m['sender'] not in {who['account'],who['peer']}:
            raise ValueError('Invalid submission identity')
        seen.add(m['id'])
        if m['text'] is not None and (not isinstance(m['text'],str) or len(m['text'])>MAX_TEXT or '\0' in m['text']):
            raise ValueError('Invalid submission text')
    if sum(len(m['text'] or '') for m in messages)>MAX_TOTAL_TEXT:
        raise ValueError('Too much submission text')
    return copy.deepcopy(snapshot)


def checked_reply(text):
    """Same structural gate as the AI draft; never permit arbitrary native text.

    Exact stage/hash authorization remains the caller's durable responsibility.
    This adapter independently checks the final text before any device access.
    """
    from conversation_engine import QUESTIONS, CONTACT_TEXT
    from assistant_contact_clarify import TEXT as CLARIFY_TEXT
    from assistant_contact_followup import TEXT as FOLLOWUP_TEXT
    from groq_reply import decision, GroqError
    if isinstance(text, str) and text in (*QUESTIONS, CONTACT_TEXT, CLARIFY_TEXT, FOLLOWUP_TEXT):
        return text
    for kind in ('question', 'contact', 'clarify', 'followup'):
        try:
            return decision(dict(decision='reply', text=text), kind)['text']
        except GroqError:
            pass
    raise ValueError('Unsupported automatic reply')


def build(before, *, text=QUESTION):
    text = checked_reply(text)
    before = checked(before)
    source = reader.build(before['identity'])
    setup = r'''
  const sm=f.method(s.filters,Memory.allocUtf8String('DV.Messages.BottomBarView.IDelegate.OnSendText'),1),sb=Memory.alloc(4);sb.writeU32(0);
  if(sm.isNull()||f.arity(sm)!==1||(f.flags(sm,sb)&(16|1024))||!f.methodClass(sm).equals(s.filters)||f.typeKind(f.returnType(sm))!==1||f.byref(f.returnType(sm)))throw new Error('signature');
  const sp=f.param(sm,0);if(sp.isNull()||f.typeKind(sp)!==14||f.byref(sp)||!f.classFromType(sp).equals(s.stringClass))throw new Error('signature');
  s.submit={m:sm,klass:s.filters,kind:1,arity:1};s.input=check(s.chatModel,'get_IsInputEnabled',2);
'''
    source = replace_once(source, "  if(!s.messageItem)throw new Error('signature');return s;", setup + "  if(!s.messageItem)throw new Error('signature');return s;")
    source = replace_once(source, 'if(entry.arity===1){', 'if(entry.arity===1&&entry.kind!==1){')
    source = replace_once(source, '   const flags2=Memory.alloc(4);', "   if(entry.arity===1&&entry.kind===1){const p=f.param(m,0);if(p.isNull()||f.typeKind(p)!==14||f.byref(p)||!f.classFromType(p).equals(s.stringClass))fail('signature-mismatch');}\n   const flags2=Memory.alloc(4);")
    source = replace_once(source, "messages_sent:0,private_result:null", "messages_sent:0,submission_attempted:false,submission_returned:false,private_result:null")
    source = replace_once(source, 'n.private_result={identity:who,messages};n.read_checkpoint=\'complete\';n.samples=2;', r'''
   const canonical=xs=>JSON.stringify(xs.map(m=>({id:m.id,sender:m.sender,text:m.text})).sort((a,b)=>a.id<b.id?-1:a.id>b.id?1:0));
   // Lexical sorting is equality only, NOT chronology. No changed dialog/history may submit.
   if(canonical(messages)!==canonical(__BEFORE__))fail('submission-snapshot-changed');
   if(oneSubmissionAttempted)fail('submission-already-attempted');
   if(!bool(s.input,chat))fail('input-disabled');
   const text=f.newString(Memory.allocUtf8String(__QUESTION__));if(text.isNull())fail('unexpected-object');own(text);
   const args=Memory.alloc(Process.pointerSize);args.writePointer(text);
   verifyWho();
   if(!resolve(candidate).equals(current)||!checkView(current)||!call(s.messages,chat).equals(cm)||bool(s.historyLoading,cm)||!bool(s.value,field)||integer(s.count,cm)!==first||!bool(s.input,chat))fail('screen-not-ready');
   // Durable host reservation precedes this entire script. Native latch precedes invocation.
   call(s.submit,current,args);n.submission_returned=true;
   n.private_result={identity:who,messages};n.read_checkpoint='complete';n.samples=2;
'''.replace('__BEFORE__', json.dumps(before['messages'])).replace('__QUESTION__', json.dumps(text)))
    source = replace_once(source, "stringChars:bind('string_chars','pointer',['pointer'])", "stringChars:bind('string_chars','pointer',['pointer']),newString:bind('string_new','pointer',['pointer'])")
    source = replace_once(source, '"il2cpp_string_chars"]', '"il2cpp_string_chars", "il2cpp_string_new"]')
    source = replace_once(source, json.dumps(sorted(reader.ERRORS)), json.dumps(sorted(ERRORS)))
    # call() still has deadline, receiver and signature checks. Mark an
    # attempt only AFTER these checks, immediately before the native invoke.
    source = replace_once(source, '   const out=f.invoke(m,receiver,params,ex);',
        "   if(entry===s.submit&&Date.now()>deadline)fail('frame-budget');if(entry===s.submit&&(state.stop!==null||fixedCancellationRequested))fail('cancelled');\n   if(entry===s.submit){if(oneSubmissionAttempted)fail('submission-already-attempted');oneSubmissionAttempted=true;n.submission_attempted=true;n.app_actions_attempted=true;n.messages_sent=null;}\n   const out=f.invoke(m,receiver,params,ex);")
    return 'let oneSubmissionAttempted=false;\n' + source


def validate(value, before):
    before = checked(before)
    result = copy.deepcopy(value)
    n = result.get('navigation', {})
    attempted = n.pop('submission_attempted', None)
    returned = n.pop('submission_returned', None)
    if type(attempted) is not bool or type(returned) is not bool or (returned and not attempted):
        raise ValueError('Invalid submission flags')
    if n.get('app_actions_attempted') is not attempted or (attempted and n.get('messages_sent') is not None):
        raise ValueError('Invalid submission state')
    if not attempted and (type(n.get('messages_sent')) is not int or n['messages_sent'] != 0):
        raise ValueError('Invalid no-submission state')
    if n.get('stage') == 'navigation-ready' and not returned:
        raise ValueError('Incomplete submission')
    if n.get('error') not in ERRORS:
        raise ValueError('Invalid submission error')
    if n['error'] not in reader.ERRORS:
        n['error'] = 'screen-not-ready'
    n.update(app_actions_attempted=False,messages_sent=0)
    private = reader.private_snapshot(result, before['identity'])
    if private is not None:
        canonical=lambda xs:sorted(xs,key=lambda m:m['id'])
        if canonical(private['messages']) != canonical(before['messages']):
            raise ValueError('Submission history changed')
    return dict(attempted=attempted, handler_returned=returned)


def checked_diagnostic(value):
    from uikit_root import STAGES
    from chat_state_probe import CHECKPOINTS,READ_STEPS,WAIT_REASONS
    keys=reader.DIAGNOSTIC_FIELDS|{'root_stage','navigation_stage','navigation_error','metadata_checkpoint','read_checkpoint','wait_reason'}
    if not isinstance(value,dict) or set(value)!=keys:
        raise ValueError('Invalid submission diagnostic fields')
    reader.diagnostic(value)
    if (value['root_stage'] not in STAGES or value['navigation_stage'] not in {'not-attempted','navigation-ready','navigation-stopped','cleanup-failed'}
        or value['navigation_error'] not in ERRORS or value['metadata_checkpoint'] not in CHECKPOINTS
        or value['read_checkpoint'] not in READ_STEPS or value['wait_reason'] not in WAIT_REASONS):
        raise ValueError('Invalid submission diagnostic enum')
    return dict(value)


def diagnostic(value):
    n=value['navigation']
    return checked_diagnostic(dict(root_stage=value['stage'],navigation_stage=n['stage'],navigation_error=n['error'],
        metadata_checkpoint=n['metadata_checkpoint'],read_checkpoint=n['read_checkpoint'],wait_reason=n['wait_reason'],**reader.diagnostic(n)))


def input_disabled_before_submission(result):
    """Only a fully validated native no-attempt result proves this call unsent.

    This never changes any older reservation or permits retrying a send.
    """
    if (not isinstance(result,dict) or result.get('attempted') is not False
            or result.get('handler_returned') is not False):return False
    try:
        n=checked_diagnostic(result.get('native_check'))
    except (ValueError,KeyError,TypeError):return False
    return (n['root_stage']=='root-ready' and n['navigation_error']=='input-disabled'
        and n['navigation_stage']=='navigation-stopped'
        and n['metadata_checkpoint']=='ready' and n['read_checkpoint']=='sample'
        and n['identity_checkpoint']=='recheck' and n['scalar_checkpoint']=='chat-id'
        and n['scalar_state']=='positive' and n['wait_reason']=='none')


PREFLIGHT_RETRY_ERRORS={'send-setup-unavailable','frame-budget','call-limit','frame-limit','transition-timeout','history-not-ready','screen-not-ready'}

def no_submission_proof(result):
    """Closed, validated native result, never exception text or missing flags.

    A second root() can report submission-already-attempted with false flags;
    it is deliberately excluded, so it cannot erase an earlier invocation.
    """
    if not isinstance(result,dict) or result.get('attempted') is not False or result.get('handler_returned') is not False:return None
    try:n=checked_diagnostic(result.get('native_check'))
    except (ValueError,KeyError,TypeError):return None
    if (n['root_stage']!='root-ready' or n['navigation_stage']!='navigation-stopped'
        or n['metadata_checkpoint']!='ready'
        or n['navigation_error'] not in PREFLIGHT_RETRY_ERRORS|{'submission-snapshot-changed'}):return None
    return n['navigation_error']
