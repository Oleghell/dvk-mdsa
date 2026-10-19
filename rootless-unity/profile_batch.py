"""At most ten visible, unique profiles. No messages or automatic scrolling.

User.get_Id(): Int64 is confirmed in the user's 0.3.10 definition report.
Identity keys live only in this script instance and never enter its results.
"""
import uikit_profile_navigation as single

VERSION='0.3.22'
LIMIT=10

def build():
    source=single.FUNCTION
    replace=single.replace_once
    source=replace(source,"  r.navigation.metadata_checkpoint='ready';return s;", "  if(s.friendCount===null)throw new Error('signature');\n  s.batchId=checked(s.user,'get_Id',10);\n  r.navigation.metadata_checkpoint='ready';return s;")
    source=replace(source,"if(bool(s.selfUser,user)){n.selection_counts.self_user++;return null;}", "if(bool(s.selfUser,user)){n.selection_counts.self_user++;return null;}\n        const identity=longInteger(s.batchId,user);if(identity.compare(0)<=0)fail('selection-changed');\n        const identityKey=identity.toString();if(batchSeen.has(identityKey))return null;")
    source=replace(source,"n.selection_status='selected';return escaping({entry,user,avatar});", "batchCandidateKey=identityKey;\n        n.selection_status='selected';return escaping({entry,user,avatar});")
    source=replace(source,'    state.targetUser=own(selected.user);', "    const identityKey=longInteger(s.batchId,selected.user).toString();\n    if(identityKey!==batchCandidateKey||batchSeen.has(identityKey)||batchSeen.size>=10)fail('selection-changed');\n    state.targetUser=own(selected.user);")
    source=replace(source,'    n.open_attempted=true;call(s.open,current,args([selected.entry,promotion,selected.avatar]));', "    batchSeen.add(identityKey);\n    n.open_attempted=true;call(s.open,current,args([selected.entry,promotion,selected.avatar]));")
    return "let batchSeen=new Set(),batchCandidateKey=null,batchAttempts=0,batchActive=false,batchHalted=false;\n"+source+'''\nasync function probeBatchProfile(){
 if(batchActive||batchHalted||batchAttempts>=10)throw new Error('batch-closed');
 batchActive=true;batchAttempts++;
 try{
  const value=await probeUIKitRoot();
  if(!value.navigation||value.navigation.stage!=='navigation-ready'||value.navigation.friends_status!=='read')batchHalted=true;
  return value;
 }catch(_){batchHalted=true;throw new Error('batch-stopped');}
 finally{batchActive=false;batchCandidateKey=null;}
}
'''

FUNCTION=build()
validate=single.validate


def run(root,cancelled=lambda:False,progress=lambda text:None):
    """The host also enforces the limit; an unsafe/unknown result always stops."""
    out={'limit':LIMIT,'status':'batch-stopped','reason':'not-started','attempts':0,
         'visited':0,'checked':0,'eligible':0,'skipped':0,'unknown':0,'errors':0,
         'profile_may_remain_open':False,'messages_sent':0,
         'unique_scope':'current-run','identity_keys_recorded':False,'items':[]}
    for number in range(1,LIMIT+1):
        if cancelled():out.update(status='batch-cancelled',reason='cancelled');break
        progress(f'Анкета {number}/{LIMIT}…')
        out['attempts']+=1
        try:value=validate(root())
        except Exception:
            out.update(reason='probe-failed',errors=1,profile_may_remain_open=True);break
        n=value['navigation']
        item={'number':number,'stage':n['stage'],'error':n['error'],
              'opened':n['open_attempted'],'returned':n['return_verified'],
              'friends_status':n['friends_status'],'friends_count':n['friends_count'],
              'friends_eligible':n['friends_eligible']}
        out['items'].append(item)
        out['profile_may_remain_open']=n['open_attempted'] and not n['return_verified']
        if n['stage']!='navigation-ready':
            if n['error']=='selection-unavailable' and not n['open_attempted']:
                out.update(status='batch-exhausted',reason='visible-exhausted')
            elif n['error']=='cancelled':out.update(status='batch-cancelled',reason='cancelled')
            else:out.update(reason=n['error'] if n['error']!='none' else 'preflight-failed',errors=1)
            break
        out['visited']+=1
        if n['friends_status']!='read':
            out['unknown']+=1;out.update(reason='count-unavailable',errors=1);break
        out['checked']+=1
        out['eligible' if n['friends_eligible'] else 'skipped']+=1
    else:out.update(status='batch-completed',reason='limit-reached')
    return out
