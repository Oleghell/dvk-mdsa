"""Strict validation of static APK indicators, never a runtime/UI-access claim."""
import re
from ui_model import UIError

KINDS={'unity_library','il2cpp_library','mono_library','il2cpp_metadata','managed_assembly'}
STATUSES={'scanned','unavailable','unreadable','limit_reached','not_scanned'}
ABI=re.compile(r'[a-zA-Z0-9_-]{1,32}\Z')
FIELDS={'unity_diagnostics_version','package','version_name','version_code','debuggable','test_only','device_supported_abis','archive_count','archives','entries_scanned','markers','complete','classification_scope','runtime_objects_access','sdk_integration_status','images_captured','actions_attempted','root_attempted','apk_modified','private_data_read'}

def validate(data):
    def fail():raise UIError('Invalid static Unity diagnostics; no action attempted')
    if not isinstance(data,dict) or set(data)!=FIELDS:fail()
    if type(data['unity_diagnostics_version']) is not int or data['unity_diagnostics_version']!=1 or data['package']!='drug.vokrug':fail()
    for k,v in [('classification_scope','installed_apk_entries_only'),('runtime_objects_access','not_tested'),('sdk_integration_status','not_assessed')]:
        if data[k]!=v:fail()
    for k in ('debuggable','test_only','complete','root_attempted','apk_modified','private_data_read'):
        if type(data[k]) is not bool:fail()
    if any(data[k] for k in ('root_attempted','apk_modified','private_data_read')):fail()
    for k in ('images_captured','actions_attempted'):
        if type(data[k]) is not int or data[k]!=0:fail()
    if not isinstance(data['version_name'],str) or len(data['version_name'])>128 or any(ord(c)<32 or 127<=ord(c)<=159 for c in data['version_name']):fail()
    if not isinstance(data['version_code'],str) or not re.fullmatch(r'0|[1-9][0-9]{0,18}',data['version_code']) or int(data['version_code'])>2**63-1:fail()
    abis=data['device_supported_abis']
    if not isinstance(abis,list) or not 1<=len(abis)<=16 or any(not isinstance(a,str) or not ABI.fullmatch(a) for a in abis) or len(set(abis))!=len(abis):fail()
    count=data['archive_count'];archives=data['archives'];entries=data['entries_scanned'];markers=data['markers']
    if type(count) is not int or not 1<=count<=10000 or type(entries) is not int or not 0<=entries<=150000:fail()
    if not isinstance(archives,list) or len(archives)!=min(count,33) or not isinstance(markers,list) or len(markers)>128:fail()
    total=0
    for i,a in enumerate(archives):
        if not isinstance(a,dict) or set(a)!={'index','role','status','entries_scanned'} or type(a['index']) is not int or a['index']!=i:fail()
        if a['role']!=('base' if i==0 else 'split') or not isinstance(a['status'],str) or a['status'] not in STATUSES:fail()
        n=a['entries_scanned']
        if type(n) is not int or not 0<=n<=150000:fail()
        total+=n
        if data['complete'] and a['status']!='scanned':fail()
    if total!=entries or data['complete'] and count>33:fail()
    kinds=set();observed=set();seen=set()
    for marker in markers:
        if not isinstance(marker,dict) or set(marker)!={'archive','kind','abi'}:fail()
        i=marker['archive'];kind=marker['kind'];abi=marker['abi']
        if type(i) is not int or not 0<=i<len(archives) or not isinstance(kind,str) or kind not in KINDS or not isinstance(abi,str):fail()
        if kind.endswith('_library'):
            if not ABI.fullmatch(abi):fail()
            observed.add(abi)
        elif abi!='':fail()
        key=(i,kind,abi)
        if key in seen or archives[i]['entries_scanned']==0:fail()
        seen.add(key);kinds.add(kind)
    mono='mono_library' in kinds;il2cpp='il2cpp_library' in kinds;metadata='il2cpp_metadata' in kinds
    if mono and (il2cpp or metadata):backend='mixed_indicators'
    elif il2cpp:backend='il2cpp_indicated'
    elif mono:backend='mono_indicated'
    elif metadata:backend='il2cpp_metadata_only'
    elif 'managed_assembly' in kinds:backend='managed_assemblies_only'
    elif 'unity_library' in kinds:backend='unity_backend_unknown'
    else:backend='not_identified' if data['complete'] else 'unknown_incomplete'
    return dict(data,backend_indication=backend,unity_indicated=bool(kinds&{'unity_library','il2cpp_library','il2cpp_metadata','managed_assembly'}),observed_engine_library_abis=sorted(observed),limitations='Static APK indicators only; no proof of loaded backend, process ABI, SDK availability or runtime object access')
