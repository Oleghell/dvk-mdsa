"""Cooperative, read-only search scanning. Hard 100ms frame limit unchanged.

Only one new cell is fully inspected per callback. Any yield occurs before the
selection's permanent handles transfer and before OnUserSelected. No actions retry.
"""
from uikit_profile_navigation import replace_once as replace

def specialize(source):
    source=replace(source,"const selected=scoped(()=>{\n     n.selection_counts.rows++;", "const selected=scoped(()=>{\n     const scanRowFirst=!state.scanRowCounted;if(scanRowFirst){n.selection_counts.rows++;state.scanRowCounted=true;}")
    source=replace(source,"if(state.selectionRow===0){if(n.selection_counts.passes>=3)","n.scan_slices++;if(state.selectionRow===0&&!state.scanPassActive){state.scanPassActive=true;if(n.selection_counts.passes>=3)")
    source=replace(source,"seen=new Set();let visited=0;", "seen=new Set();let visited=0,cellOrdinal=0;")
    source=replace(source,"if(f.objectClass(item.view).equals(s.cell)){\n       const candidate", "if(f.objectClass(item.view).equals(s.cell)){\n       if(cellOrdinal++<state.scanCell)continue;\n       const candidate")
    # Reports 480-483 (v1.3.71, dropmefiles WHm3): `cells` and `rows` are counted
    # once per unique cell/row (scanCellCounted/scanRowCounted), but every skip
    # and avatar counter re-incremented on EACH re-inspection of the same cell.
    # Re-inspection is not limited to the two selection-changed retries the
    # 1.3.71 validator tolerance covers: a frame-budget thrown mid-cell (during
    # its managed calls) is retried through scan_yields up to EIGHT times, so a
    # single noninteractive avatar could legally reach cells+8 and still stopped
    # the whole pass as 'Inconsistent avatar counts'. Counters describe unique
    # observations, not re-examinations: every per-cell counter now increments
    # only on the first look at that cell, exactly like `cells` itself.
    source=replace(source,"n.selection_counts.cells++;const cell=item.view;", "state.scanCellBusy=true;const scanFirst=!state.scanCellCounted;state.scanRepeatLook=!scanFirst;if(scanFirst){n.selection_counts.cells++;state.scanCellCounted=true;}const cell=item.view;")
    source=replace(source,"if(!attached(cell,row)){n.selection_counts.cell_unready++;return null;}", "if(!attached(cell,row)){if(scanFirst)n.selection_counts.cell_unready++;return null;}")
    source=replace(source,"const entry=call(s.cellEntry,cell);if(entry.isNull()){n.selection_counts.entry_missing++;return null;}", "const entry=call(s.cellEntry,cell);if(entry.isNull()){if(scanFirst)n.selection_counts.entry_missing++;return null;}")
    source=replace(source,"if(promoted(record,entry)){n.selection_counts.promoted++;return null;}", "if(promoted(record,entry)){if(scanFirst)n.selection_counts.promoted++;return null;}")
    source=replace(source,"const user=call(s.entryUser,entry);if(user.isNull()){n.selection_counts.user_missing++;return null;}", "const user=call(s.entryUser,entry);if(user.isNull()){if(scanFirst)n.selection_counts.user_missing++;return null;}")
    source=replace(source,"if(bool(s.selfUser,user)){n.selection_counts.self_user++;return null;}", "if(bool(s.selfUser,user)){if(scanFirst)n.selection_counts.self_user++;return null;}")
    source=replace(source,"const avatar=call(s.cellAvatar,cell);if(avatar.isNull()){n.selection_counts.avatar_missing++;return null;}", "const avatar=call(s.cellAvatar,cell);if(avatar.isNull()){if(scanFirst)n.selection_counts.avatar_missing++;return null;}")
    source=replace(source,"if(!attached(avatar,cell,false)){n.selection_counts.avatar_unready++;return null;}", "if(!attached(avatar,cell,false)){if(scanFirst)n.selection_counts.avatar_unready++;return null;}")
    # The avatar hidden/noninteractive counters live inside the shared attached()
    # helper; only the avatar check passes needsInteraction=false, and the
    # repeat-look flag is (re)set at the top of every cell inspection.
    source=replace(source,"if(bool(s.hidden,view)){if(!needsInteraction)n.selection_counts.avatar_hidden++;return false;}", "if(bool(s.hidden,view)){if(!needsInteraction&&!state.scanRepeatLook)n.selection_counts.avatar_hidden++;return false;}")
    source=replace(source,"const interactive=bool(s.interactive,view);if(!interactive){if(needsInteraction)return false;n.selection_counts.avatar_noninteractive++;}", "const interactive=bool(s.interactive,view);if(!interactive){if(needsInteraction)return false;if(!state.scanRepeatLook)n.selection_counts.avatar_noninteractive++;}")
    # Row-level skip counters follow the same rule as `rows` itself: a row
    # re-entered after a mid-row exception must not count its unready/binding
    # skip twice while `rows` stays counted once.
    source=replace(source,"if(!attached(row,table)){n.selection_counts.row_unready++;return null;}", "if(!attached(row,table)){if(scanRowFirst)n.selection_counts.row_unready++;return null;}")
    source=replace(source,"const record=call(s.rowItems[ri],row);if(record.isNull()){n.selection_counts.binding_missing++;return null;}", "const record=call(s.rowItems[ri],row);if(record.isNull()){if(scanRowFirst)n.selection_counts.binding_missing++;return null;}")
    source=replace(source,"if(candidate!==null)return escaping(candidate);\n       continue;", "state.scanCellBusy=false;if(candidate!==null)return escaping(candidate);\n       state.scanCell++;state.scanCellCounted=false;state.scanRowPending=true;return null;")
    source=replace(source,"if(selected!==null)return escaping(selected);\n    state.selectionRow=i+1;", "if(selected!==null)return escaping(selected);\n    if(state.scanRowPending){state.scanRowPending=false;return null;}\n    state.scanCell=0;state.scanCellCounted=false;state.scanRowCounted=false;state.selectionRow=i+1;")
    source=replace(source,"if(state.selectionRow>=count)state.selectionRow=0;", "if(state.selectionRow>=count){state.selectionRow=0;state.scanPassActive=false;state.scanCell=0;state.scanCellCounted=false;state.scanRowCounted=false;}")
    source=replace(source,"if(Date.now()>deadline)fail('frame-budget');", "if(Date.now()>deadline)fail('frame-budget');\n   if(Date.now()>deadline-35&&n.phase==='search'&&!n.open_attempted&&state.targetUser.isNull()&&state.origin.isNull()&&!state.scanCellBusy)fail('scan-yield');")
    source=replace(source,"} catch(e){if(e==='selection-changed'", """} catch(e){state.scanCellBusy=false;
   if((e==='scan-yield'||e==='frame-budget')&&n.phase==='search'&&!n.open_attempted&&state.targetUser.isNull()&&state.origin.isNull()&&n.scan_yields<8){n.scan_yields++;state.nextActionAt=Date.now()+1000;return;}
   if(e==='scan-yield')e='frame-budget';
   if(e==='selection-changed'""")
    source=replace(source,"selectionRow:0,nextActionAt:0,stop:null", "selectionRow:0,scanCell:0,scanPassActive:false,scanRowCounted:false,scanCellCounted:false,scanRowPending:false,scanCellBusy:false,scanRepeatLook:false,nextActionAt:0,stop:null")
    source=source.replace("state.selectionRow=0;return null;", "state.selectionRow=0;state.scanPassActive=false;state.scanCell=0;state.scanCellCounted=false;state.scanRowCounted=false;return null;")
    return source
