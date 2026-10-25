"""Skip a globally greeted or terminally blocked EMPTY chat via checked native Back.
No cancellation, fake history, false successful-send flags or handler retries.
"""
from uikit_profile_navigation import replace_once

def specialize(source):
    source=replace_once(source,'let cohortPending=null,cohortApproved=null;',
        'let cohortPending=null,cohortApproved=null,cohortRejected=null;')
    source=replace_once(source,'function cohortAcknowledge(value){',"""function cohortAcknowledge(value){
 if(value!==null&&value.skip===true){
  const {skip,...reservation}=value;
  if(cohortPending===null||JSON.stringify(reservation)!==JSON.stringify(cohortPending))return false;
  cohortRejected=JSON.stringify(cohortPending);cohortPending=null;return true;
 }
""")
    source=replace_once(source,'   if(cohortApproved!==reservationKey){',"""   if(cohortRejected===reservationKey){
    n.shared_peer_skipped=true;n.phase='close-chat';state.nextActionAt=Date.now();return;
   }
   if(cohortApproved!==reservationKey){""")
    source=replace_once(source,'r.navigation=emptyNavigation();',
        'r.navigation=emptyNavigation();r.navigation.shared_peer_skipped=false;')
    return source

def skip(script,pending,state):
    # State is set BEFORE RPC: an uncertain acknowledgement never authorizes a send.
    state['shared_peer_skipped']=True
    if script.exports_sync.cohortack(dict(pending,skip=True)) is not True:
        raise RuntimeError('Shared skip acknowledgement failed')
