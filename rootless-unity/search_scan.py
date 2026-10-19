"""Cooperative, read-only search scanning. Hard 100ms frame limit unchanged.

Only one new cell is fully inspected per callback. Any yield occurs before the
selection's permanent handles transfer and before OnUserSelected. No actions retry.
"""
from uikit_profile_navigation import replace_once as replace

def specialize(source):
    source=replace(source,"const selected=scoped(()=>{\n     n.selection_counts.rows++;", "const selected=scoped(()=>{\n     if(!state.scanRowCounted){n.selection_counts.rows++;state.scanRowCounted=true;}")
    source=replace(source,"if(state.selectionRow===0){if(n.selection_counts.passes>=3)","n.scan_slices++;if(state.selectionRow===0&&!state.scanPassActive){state.scanPassActive=true;if(n.selection_counts.passes>=3)")
    source=replace(source,"seen=new Set();let visited=0;", "seen=new Set();let visited=0,cellOrdinal=0;")
    source=replace(source,"if(f.objectClass(item.view).equals(s.cell)){\n       const candidate", "if(f.objectClass(item.view).equals(s.cell)){\n       if(cellOrdinal++<state.scanCell)continue;\n       const candidate")
    source=replace(source,"n.selection_counts.cells++;const cell=item.view;", "state.scanCellBusy=true;if(!state.scanCellCounted){n.selection_counts.cells++;state.scanCellCounted=true;}const cell=item.view;")
    source=replace(source,"if(candidate!==null)return escaping(candidate);\n       continue;", "state.scanCellBusy=false;if(candidate!==null)return escaping(candidate);\n       state.scanCell++;state.scanCellCounted=false;state.scanRowPending=true;return null;")
    source=replace(source,"if(selected!==null)return escaping(selected);\n    state.selectionRow=i+1;", "if(selected!==null)return escaping(selected);\n    if(state.scanRowPending){state.scanRowPending=false;return null;}\n    state.scanCell=0;state.scanCellCounted=false;state.scanRowCounted=false;state.selectionRow=i+1;")
    source=replace(source,"if(state.selectionRow>=count)state.selectionRow=0;", "if(state.selectionRow>=count){state.selectionRow=0;state.scanPassActive=false;state.scanCell=0;state.scanCellCounted=false;state.scanRowCounted=false;}")
    source=replace(source,"if(Date.now()>deadline)fail('frame-budget');", "if(Date.now()>deadline)fail('frame-budget');\n   if(Date.now()>deadline-35&&n.phase==='search'&&!n.open_attempted&&state.targetUser.isNull()&&state.origin.isNull()&&!state.scanCellBusy)fail('scan-yield');")
    source=replace(source,"} catch(e){if(e==='selection-changed'", """} catch(e){state.scanCellBusy=false;
   if((e==='scan-yield'||e==='frame-budget')&&n.phase==='search'&&!n.open_attempted&&state.targetUser.isNull()&&state.origin.isNull()&&n.scan_yields<8){n.scan_yields++;state.nextActionAt=Date.now()+1000;return;}
   if(e==='scan-yield')e='frame-budget';
   if(e==='selection-changed'""")
    source=replace(source,"selectionRow:0,nextActionAt:0,stop:null", "selectionRow:0,scanCell:0,scanPassActive:false,scanRowCounted:false,scanCellCounted:false,scanRowPending:false,scanCellBusy:false,nextActionAt:0,stop:null")
    source=source.replace("state.selectionRow=0;return null;", "state.selectionRow=0;state.scanPassActive=false;state.scanCell=0;state.scanCellCounted=false;state.scanRowCounted=false;return null;")
    return source
