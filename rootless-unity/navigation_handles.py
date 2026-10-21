"""Bound temporary traversals without increasing the 64-live-handle limit."""
from uikit_profile_navigation import replace_once

SCOPE=r'''
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
'''


def scoped_traversals(source):
    source=replace_once(source,'  try {\n   const root=call',SCOPE+'  try {\n   const root=call')
    source=replace_once(source,'const current=resolve(candidate);if(current.isNull())return;',
                        'const current=scope(()=>resolve(candidate),true);if(current.isNull())return;')
    source=source.replace('checkView(current)','scope(()=>checkView(current))')
    return source.replace('resolve(candidate).equals(current)','scope(()=>resolve(candidate).equals(current))')
