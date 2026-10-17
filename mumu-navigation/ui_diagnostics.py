"""Validate bounded read-only reports; never use diagnostic nodes for actions."""
from ui_model import UIError

def validate(data):
    def fail():raise UIError('Invalid expanded native diagnostics; no action attempted')
    if data.get('diagnostics_version')!=1 or data.get('package')!='drug.vokrug':fail()
    for k in ('complete','unity_surface','flags_restored_after_scan','identity_verified','empty_chat_verified'):
        if type(data.get(k)) is not bool:fail()
    if data['identity_verified'] or data['empty_chat_verified'] or not data['flags_restored_after_scan']:fail()
    for k in ('flags_requested','flags_applied','flags_original','window_count','foreign_windows_skipped','actionable_nodes','editable_nodes','images_captured','actions_attempted'):
        if type(data.get(k)) is not int or data[k]<0:fail()
    if data['images_captured'] or data['actions_attempted']:fail()
    nodes=data.get('nodes');windows=data.get('windows')
    if not isinstance(nodes,list) or not isinstance(windows,list) or len(nodes)>2000 or not 1<=len(windows)<=33 or len(windows)!=data['window_count']:fail()
    ids=set()
    for w in windows:
        if w.get('package')!='drug.vokrug' or type(w.get('window_id')) is not int or w['window_id'] in ids:fail()
        ids.add(w['window_id'])
    clicks=editors=0;unity=False
    for i,n in enumerate(nodes):
        if not isinstance(n,dict) or n.get('package')!='drug.vokrug' or n.get('index')!=i or n.get('window_id') not in ids:fail()
        parent=n.get('parent')
        if type(parent) is not int or not -1<=parent<i or parent>=0 and nodes[parent]['window_id']!=n['window_id']:fail()
        for k in ('password','visible','enabled','editable','action_click','action_set_text'):
            if type(n.get(k)) is not bool:fail()
        for k in ('resource_id','class_name','text','description'):
            if not isinstance(n.get(k),str) or len(n[k])>65536:fail()
        if n['password'] and (n['text'] or n['description']):fail()
        if type(n.get('child_count')) is not int or n['child_count']<0:fail()
        usable=n['visible'] and n['enabled'] and not n['password']
        clicks+=int(usable and n['action_click']);editors+=int(usable and n['editable'] and n['action_set_text'])
        unity|=n['resource_id'].endswith(':id/unitySurfaceView')
    if (clicks,editors,unity)!=(data['actionable_nodes'],data['editable_nodes'],data['unity_surface']):fail()
    if data['complete'] and (not nodes or data['flags_applied']&data['flags_requested']!=data['flags_requested']):fail()
    blocker='incomplete_scan' if not data['complete'] else 'unity_surface_without_exposed_controls' if unity and not clicks and not editors else 'not_determined'
    if data.get('blocker')!=blocker:fail()
    return data
