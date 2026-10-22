"""Resolve exact IL2CPP exports in the loaded engine, including local Android namespaces.

No module loading, symbol scanning, guessed offsets or generic invocation.
"""
RESOLVER = r'''
function findIl2cppExport(name) {
 // Android's loader may keep libil2cpp outside the global symbol namespace.
 // When its named module is present, never borrow a same-named symbol elsewhere.
 const engine=Process.findModuleByName('libil2cpp.so');
 if(engine!==null)return engine.findExportByName(name);
 return Module.findGlobalExportByName(name);
}
'''

def with_module_exports(source):
    if 'Module.findGlobalExportByName(' not in source:
        raise ValueError('Missing fixed export lookup')
    return RESOLVER + source.replace('Module.findGlobalExportByName(', 'findIl2cppExport(')
