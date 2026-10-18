"""Read-only loader evidence for NativeBridge; no function calls or UI-object reads."""
MODULES=['libfrida-gadget.so','libunity.so','libil2cpp.so','libmain.so']
EXPORTS=['il2cpp_domain_get','il2cpp_domain_get_assemblies','il2cpp_class_from_name','il2cpp_thread_attach']
# Only this exact proc path may be opened. Raw mappings never leave the target script.
EVIDENCE_FUNCTION = r'''
function moduleEvidence() {
  const names = ['libfrida-gadget.so','libunity.so','libil2cpp.so','libmain.so'];
  const ranges = {};
  for (const n of names) ranges[n] = 0;
  const result = {maps_available:false, maps_complete:false, map_line_count:0,
    map_limit_reached:false, mapped_ranges:ranges, apk_mappings_present:false,
    global_export_api_available:typeof Module.findGlobalExportByName === 'function',
    global_exports:{}, global_export_errors:0};
  let f = null;
  try {
    f = new File('/proc/self/maps','r');
    result.maps_available = true;
    let bytes = 0;
    for (let i = 0; i < 20000; i++) {
      const line = f.readLine();
      if (line === null || line === '') {result.maps_complete = true;break;}
      bytes += line.length;
      if (line.length > 8192 || bytes > 4 * 1024 * 1024) {result.map_limit_reached = true;break;}
      result.map_line_count++;
      // Only compare fixed file basenames, never return pointers or arbitrary pathname text.
      const cleaned = line.replace(/ \(deleted\)$/, '');
      for (const n of names) {
        if (cleaned.endsWith('/' + n) || cleaned.endsWith('!/' + n)) ranges[n]++;
      }
      if (/\.apk$/.test(cleaned)) result.apk_mappings_present = true;
      if (i === 19999) result.map_limit_reached = true;
    }
  } catch (_) {
    result.maps_complete = false;
  } finally {
    if (f !== null) {try {f.close();} catch (_) {}}
  }
  for (const name of ['il2cpp_domain_get','il2cpp_domain_get_assemblies','il2cpp_class_from_name','il2cpp_thread_attach']) {
    result.global_exports[name] = false;
    if (result.global_export_api_available) {
      try {result.global_exports[name] = Module.findGlobalExportByName(name) !== null;}
      catch (_) {result.global_export_errors++;}
    }
  }
  return result;
}
'''


def validate_evidence(value):
    expected={'maps_available','maps_complete','map_line_count','map_limit_reached','mapped_ranges',
              'apk_mappings_present','global_export_api_available','global_exports','global_export_errors'}
    if not isinstance(value,dict) or set(value) != expected:raise ValueError('Invalid evidence fields')
    for key in ('maps_available','maps_complete','map_limit_reached','apk_mappings_present','global_export_api_available'):
        if type(value[key]) is not bool:raise ValueError('Invalid evidence flag')
    for key,maximum in (('map_line_count',20000),('global_export_errors',4)):
        if type(value[key]) is not int or not 0 <= value[key] <= maximum:raise ValueError('Invalid evidence count')
    for field,allowed,is_bool in (('mapped_ranges',MODULES,False),('global_exports',EXPORTS,True)):
        result=value[field]
        if not isinstance(result,dict) or set(result)!=set(allowed):raise ValueError('Invalid evidence map')
        for item in result.values():
            if is_bool:
                if type(item) is not bool:raise ValueError('Invalid export flag')
            elif type(item) is not int or not 0 <= item <= 20000:raise ValueError('Invalid range count')
    if value['maps_complete'] and (not value['maps_available'] or value['map_limit_reached']):
        raise ValueError('Inconsistent maps completeness')
    return value


def classify_evidence(enumerated, evidence):
    validate_evidence(evidence)
    if enumerated['libunity.so'] and enumerated['libil2cpp.so']:return 'modules-ready'
    ranges=evidence['mapped_ranges']
    if ranges['libunity.so']>0 and ranges['libil2cpp.so']>0:return 'engine-mapped-not-fully-enumerated'
    if any(evidence['global_exports'].values()):return 'il2cpp-global-export-visible'
    if not evidence['maps_available']:return 'module-evidence-unavailable'
    if not evidence['maps_complete']:return 'module-evidence-incomplete'
    return 'engine-not-confirmed'
